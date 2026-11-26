"""Task 6R.2: ``scripts/release.py`` and ``CHANGELOG.md`` (input-domain table 6R.2-input-domain.md; row ids A, S, C, T, D,
N, H, P, X, G, CR, SB, DS and E2E are those of the table).

Every test runs ``release.main`` (or the script as a child process) on a fixture repository built under the test's own
mkdtemp sandbox: sites at version ``0.0.0``, branch ``release-test``, base branch ``main``. Expected values are
literals written by hand; ``site_version`` reads each site with its own regular expression, never through the script.
SB: ``ReleaseCase.run_release`` refuses (as a test error, before any call) every ``--root`` and every path a test
hands it that is not inside the test's own sandbox ``self.tmp``, or that is the sandbox itself, TMPDIR, $HOME or the
repository under test, so a refusal that fails to refuse can only ever write inside the sandbox."""
import ast
import builtins
import contextlib
import datetime
import importlib.util
import io
import json
import os
import random
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from gates.lib import config, gitinfo, managed, templates
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, within

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "release.py")
_spec = importlib.util.spec_from_file_location("release_script_under_test", SCRIPT)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

SITES = [rel for rel, _kind in release.RELEASE_SITES]
SITE_PATHS = set(SITES)
PLUGIN, MARKET, CLAUDE, IGNORE, CONFIG = SITES
CHANGELOG = "CHANGELOG.md"
DATE = "2026-12-01"
E2E_REASON = "4d.3 doctor and Rq-4-5 adoption not on this branch"

PLUGIN_JSON = ('{\n  "name": "strict-delivery",\n  "version": "%s",\n  "description": "A plugin.",\n'
               '  "author": {\n    "name": "Someone"\n  },\n  "license": "MIT",\n'
               '  "dependencies": [\n    {\n      "name": "other",\n      "marketplace": "m"\n    }\n  ]\n}\n')
MARKET_JSON = ('{\n  "name": "strict-delivery",\n  "owner": {\n    "name": "Someone"\n  },\n  "plugins": [\n    {\n'
               '      "name": "strict-delivery",\n      "source": "./",\n      "version": "%s",\n'
               '      "description": "A plugin."\n    }\n  ],\n  "allowCrossMarketplaceDependenciesOn": [\n    "m"\n  ]\n}\n')
CONFIG_YML = 'schema: config/2\nframework_version: "%s"\nprofile: strict\n'
CHANGELOG_TEXT = ("# Changelog\n\nSemver.\n\n## Unreleased\n\n- a note\n- another note\n\n"
                  "## 0.0.0 - 2026-01-01\n\n- first\n")
CLAUDE_HEAD = "# Project\n\nHand-written notes.\n\n"
IGNORE_HEAD = "node_modules/\n*.log\n"
CLAUDE_BEGIN = "<!-- strict-delivery:begin schema=claude-block/1 version=%s -->"
IGNORE_BEGIN = "# strict-delivery:begin schema=gitignore-block/1 version=%s"


class Sub(str):
    pass


class ListSub(list):
    pass


def claude_body():
    return templates.claude_block_body({"paths": config.DEFAULTS["paths"]})


def ignore_body():
    return templates.gitignore_block_body({"paths": config.DEFAULTS["paths"]})


def claude_text(version, head=CLAUDE_HEAD, body=None):
    return managed.put_block(head, managed.HTML, "claude-block", version, claude_body() if body is None else body)


def ignore_text(version, head=IGNORE_HEAD, body=None):
    return managed.put_block(head, managed.HASH, "gitignore-block", version, ignore_body() if body is None else body)


def site_texts(versions, base=None):
    """The five site files at the given versions (a dict path -> version, default 0.0.0)."""
    v = dict((s, "0.0.0") for s in SITES)
    v.update(versions or {})
    cfg = CONFIG_YML % v[CONFIG] + ("base_branch: %s\n" % base if base else "")
    return {PLUGIN: PLUGIN_JSON % v[PLUGIN], MARKET: MARKET_JSON % v[MARKET], CLAUDE: claude_text(v[CLAUDE]),
            IGNORE: ignore_text(v[IGNORE]), CONFIG: cfg}


def build(repo, versions=None, base=None, branch="release-test", changelog=CHANGELOG_TEXT, texts=None):
    """A repository at ``repo`` holding the five sites, a changelog and a README, committed on ``branch``."""
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "maintenance.auto", "false")
    git(repo, "config", "gc.auto", "0")
    files = site_texts(versions, base)
    files.update(texts or {})
    if changelog is not None:
        files[CHANGELOG] = changelog
    files["README.md"] = "readme\n"
    for rel, text in files.items():
        put(repo, rel, text)
    commit_all(repo, "fixture")
    if branch != "main":
        git(repo, "checkout", "-q", "-b", branch)
    return repo


def put(repo, rel, text):
    path = os.path.join(repo, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = text if type(text) is bytes else text.encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)


def get(repo, rel):
    with open(os.path.join(repo, *rel.split("/")), "rb") as fh:
        return fh.read()


def snapshot(root):
    """Every file and link under ``root`` outside .git: path -> bytes, or ('link', target), or 'dir'."""
    out = {}
    for d, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            full = os.path.join(d, name)
            rel = os.path.relpath(full, root)
            if os.path.islink(full):
                out[rel] = ("link", os.readlink(full))
            elif os.path.isdir(full):
                out[rel] = "dir"
            elif stat.S_ISREG(os.lstat(full).st_mode):
                out[rel] = get(root, rel)
            else:
                out[rel] = "special"
    return out


def site_version(repo, site):
    """The version a site holds, read by a hand-written pattern."""
    rel = site[0]
    text = get(repo, rel).decode("utf-8")
    if rel == PLUGIN:
        return json.loads(text)["version"]
    if rel == MARKET:
        return json.loads(text)["plugins"][0]["version"]
    if rel in (CLAUDE, IGNORE):
        return re.search(r"^(?:<!-- |# )strict-delivery:begin schema=\S+ version=(\S+?)(?: -->)?$", text, re.M).group(1)
    return re.search(r'^framework_version: "([^"]*)"$', text, re.M).group(1)


class ReleaseCase(GitIsolatedTestCase):
    """A sandbox ``self.tmp`` (mkdtemp, with HOME inside it) and a default fixture repository ``self.repo``."""

    def setUp(self):
        super().setUp()
        self.n = 0
        self.repo = self.fresh()

    def fresh(self, **kw):
        self.n += 1
        return build(os.path.join(self.work, "r%d" % self.n), **kw)

    def guard(self, path):
        """SB: ``path`` lies inside the sandbox and is none of the places a failed guard must not reach."""
        real = os.path.realpath(path)
        for name, bad in (("the sandbox itself", self.tmp), ("TMPDIR", tempfile.gettempdir()),
                          ("$HOME", os.environ.get("HOME", "")), ("the repository under test", ROOT), ("/tmp", "/tmp")):
            if bad and real == os.path.realpath(bad):
                raise AssertionError("test guard: %s is %s" % (path, name))
        if not real.startswith(self.tmp + os.sep):
            raise AssertionError("test guard: %s is outside the sandbox %s" % (path, self.tmp))

    def run_release(self, *args, root="default"):
        """``(code, stdout, stderr)`` of ``release.main(list(args) + ['--root', root])``; the default root is self.repo."""
        argv = list(args)
        if root == "default":
            root = self.repo
        if root is not None:
            self.guard(root)
            argv += ["--root", root]
        return self.call(argv)

    def call(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release.main(argv)
        return code, out.getvalue(), err.getvalue()

    def refused(self, *args, root="default", repo=None, want=(), unwanted=()):
        """Run, assert exit 1 with every ``want`` text in stderr, nothing on stdout and no file changed; the stderr."""
        repo = repo or self.repo
        before = snapshot(self.work)
        head = git(repo, "rev-parse", "HEAD")
        code, out, err = self.run_release(*args, root=repo if root == "default" else root)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        for text in want:
            self.assertIn(text, err)
        for text in unwanted:
            self.assertNotIn(text, err)
        self.assertEqual(snapshot(self.work), before)
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
        return err

    def commit(self, repo=None, msg="change"):
        commit_all(repo or self.repo, msg)

    def changed(self, repo=None):
        return set(git(repo or self.repo, "diff", "--name-only", "HEAD").split("\n")) - {""}

    def replace(self, rel, text, repo=None):
        put(repo or self.repo, rel, text)
        self.commit(repo)


# --------------------------------------------------------------------------- A: the version argument and S1

class VersionRows(ReleaseCase):
    def test_bumps_every_site_and_nothing_else(self):  # A1, S1, T1
        old = snapshot(self.repo)
        code, out, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.changed(), SITE_PATHS | {CHANGELOG})
        for site in release.RELEASE_SITES:
            self.assertEqual(site_version(self.repo, site), "0.1.0", site)
        self.assertEqual(sorted(k for k in snapshot(self.repo) if snapshot(self.repo)[k] != old.get(k)),
                         sorted(SITE_PATHS | {CHANGELOG}))

    def test_sites_are_the_five_of_the_ruling(self):
        self.assertEqual(SITES, [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "CLAUDE.md",
                                 ".gitignore", ".strict-delivery/config.yml"])

    def test_bytes_outside_versions_unchanged(self):  # S1, H6
        old = snapshot(self.repo)
        self.assertEqual(self.run_release("0.1.0", "--date", DATE)[0], 0)
        new = snapshot(self.repo)
        for rel in SITES:
            self.assertEqual(old[rel].count(b"0.0.0"), 1, rel)
            self.assertEqual(new[rel], old[rel].replace(b"0.0.0", b"0.1.0"), rel)
        self.assertEqual(new[CHANGELOG], old[CHANGELOG].replace(
            b"## Unreleased\n", b"## Unreleased\n\n## 0.1.0 - 2026-12-01\n", 1))
        self.assertEqual(new["README.md"], old["README.md"])

    def test_bytes_outside_versions_unchanged_with_bom_and_non_ascii(self):  # H6
        bom = "\ufeff"
        texts = {PLUGIN: bom + (PLUGIN_JSON % "0.0.0").replace("A plugin.", "Ein Plugin: \u00e9\u4e2d"),
                 MARKET: (MARKET_JSON % "0.0.0").replace("A plugin.", "caf\u00e9 \U0001F600"),
                 CLAUDE: bom + claude_text("0.0.0", head="# Projekt \u00fc\n\n"),
                 CHANGELOG: bom + CHANGELOG_TEXT.replace("- a note", "- a note \u00e9\u00e8")}
        repo = self.fresh(texts=texts)
        old = snapshot(repo)
        code, _out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))
        new = snapshot(repo)
        for rel in (PLUGIN, MARKET, CLAUDE):
            self.assertEqual(new[rel], old[rel].replace(b"0.0.0", b"0.1.0"), rel)
        self.assertEqual(new[CHANGELOG], old[CHANGELOG].replace(
            b"## Unreleased\n", b"## Unreleased\n\n## 0.1.0 - 2026-12-01\n", 1))
        self.assertTrue(new[PLUGIN].startswith(bom.encode("utf-8")))

    def test_accepted_versions(self):  # A1, A2
        for version in ("0.1.0", "1.0.0", "0.0.1", "10.20.30", "123456789.0.0"):
            with self.subTest(version=version):
                repo = self.fresh()
                code, _o, err = self.run_release(version, "--date", DATE, root=repo)
                self.assertEqual((code, err), (0, ""))
                self.assertTrue(all(site_version(repo, s) == version for s in release.RELEASE_SITES))

    def test_bad_version_refused(self):  # A3
        for bad in ("0.1", "0.1.0.1", "v0.1.0", "01.0.0", "0.01.0", "0.1.00", "0.1.0-rc1", "", "1.0", "1", "0.1.0\n",
                    " 0.1.0", "0.1.0 ", "0..0", "a.b.c", "0.1.0+build", "00.0.1"):
            with self.subTest(version=bad):
                err = self.refused(bad, "--date", DATE, want=("MAJOR.MINOR.PATCH",))
                self.assertNotIn("0.0.0\n", err)

    def test_not_greater_refused(self):  # A4, A5
        for current, new in (("0.0.0", "0.0.0"), ("0.0.1", "0.0.0"), ("0.0.1", "0.0.1"), ("0.10.0", "0.9.0"),
                             ("0.10.0", "0.10.0"), ("1.0.0", "0.9.9"), ("1.0.0", "0.99.99"), ("1.2.3", "1.2.2"),
                             ("1.2.3", "1.1.9"), ("2.0.0", "1.99.99")):
            with self.subTest(current=current, new=new):
                repo = self.fresh(versions=dict((s, current) for s in SITES))
                self.refused(new, "--date", DATE, repo=repo, want=("not greater",))

    def test_higher_each_position(self):  # A6
        for current, new in (("0.0.0", "0.0.1"), ("0.0.0", "0.1.0"), ("0.0.0", "1.0.0"), ("0.9.0", "0.10.0"),
                             ("0.0.9", "0.0.10"), ("9.0.0", "10.0.0"), ("0.5.5", "1.0.0"), ("1.2.3", "1.2.4"),
                             ("1.2.3", "1.3.0"), ("1.2.3", "2.0.0"), ("1.9.9", "1.10.0"), ("0.0.0", "99.99.99")):
            with self.subTest(current=current, new=new):
                repo = self.fresh(versions=dict((s, current) for s in SITES))
                code, _o, err = self.run_release(new, "--date", DATE, root=repo)
                self.assertEqual((code, err), (0, ""))
                self.assertTrue(all(site_version(repo, s) == new for s in release.RELEASE_SITES))

    def test_second_run_with_the_same_version_refused(self):  # A4
        self.assertEqual(self.run_release("0.1.0", "--date", DATE)[0], 0)
        self.refused("0.1.0", "--date", DATE, want=("not greater",))
        self.commit()
        self.refused("0.1.0", "--date", DATE, want=("not greater",))

    def test_usage_refused(self):
        for argv in ([], ["--date", DATE], ["0.1.0", "0.2.0"], ["0.1.0", "--bogus"], ["0.1.0", "--date"],
                     ["0.1.0", "--root"], ["0.1.0", "--date", DATE, "--date", DATE], ["0.1.0", "--root", "a", "--root", "a"],
                     ["0.1.0", "--date=2026-12-01"], ["-1.0.0"], ["0.1.0", "-x"]):
            with self.subTest(argv=argv):
                before = snapshot(self.work)
                code, out, err = self.call(argv + ["--root", self.repo] if "--root" not in argv else argv)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("release:", err)
                self.assertEqual(snapshot(self.work), before)

    def test_default_root_is_the_repository_of_the_script(self):
        self.assertEqual(release._REPO, ROOT)
        with mock.patch.object(release, "_REPO", self.repo):
            code, _o, err = self.call(["0.1.0", "--date", DATE])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[0]), "0.1.0")

    def test_runs_as_a_script(self):
        p = subprocess.run([sys.executable, SCRIPT, "0.1.0", "--date", DATE, "--root", self.repo], cwd=self.work,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[2]), "0.1.0")
        p = subprocess.run([sys.executable, SCRIPT, "0.1", "--root", self.repo], cwd=self.work,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"MAJOR.MINOR.PATCH", p.stderr)


# --------------------------------------------------------------------------- S: the sites

class SiteRows(ReleaseCase):
    def test_disagreeing_sites_refused(self):  # S2
        for odd in SITES:
            with self.subTest(odd=odd):
                repo = self.fresh(versions={odd: "0.0.1"})
                err = self.refused("0.1.0", "--date", DATE, repo=repo, want=(odd, "disagree"),
                                   unwanted=[s for s in SITES if s != odd])
                self.assertIn("0.0.1", err)

    def test_two_disagreeing_sites_both_listed(self):  # S2
        repo = self.fresh(versions={MARKET: "0.0.1", CONFIG: "0.0.2"})
        self.refused("0.1.0", repo=repo, want=(MARKET, CONFIG, "disagree"), unwanted=(PLUGIN, CLAUDE, IGNORE))

    def test_disagreeing_with_the_new_version_still_refused(self):  # S2
        repo = self.fresh(versions={IGNORE: "0.1.0"})
        self.refused("0.1.0", repo=repo, want=(IGNORE, "disagree"))

    def test_json_pattern_twice_refused(self):  # S3
        twice = {
            PLUGIN: (PLUGIN_JSON % "0.0.0").replace('"name": "other",', '"name": "other",\n      "version": "0.0.0",'),
            MARKET: (MARKET_JSON % "0.0.0").replace('"description": "A plugin."\n    }',
                                                    '"description": "A plugin.",\n      "metadata": {"version": "0.0.0"}\n    }'),
        }
        for rel, text in twice.items():
            with self.subTest(rel=rel):
                repo = self.fresh(texts={rel: text})
                self.assertEqual(text.count('"version": "0.0.0"'), 2)
                self.refused("0.1.0", repo=repo, want=(rel, "matches 2 times"))

    def test_json_key_repeated_refused(self):  # S3
        text = (PLUGIN_JSON % "0.0.0").replace('  "license"', '  "version": "0.0.0",\n  "license"')
        repo = self.fresh(texts={PLUGIN: text})
        self.refused("0.1.0", repo=repo, want=(PLUGIN, "matches 2 times"))

    def test_json_pattern_nowhere_refused(self):  # S4
        for rel, base in ((PLUGIN, PLUGIN_JSON), (MARKET, MARKET_JSON)):
            for variant in ('"version":"%s"', '"version" : "%s"', '"version":  "%s"'):
                with self.subTest(rel=rel, variant=variant):
                    repo = self.fresh(texts={rel: (base % "0.0.0").replace('"version": "0.0.0"', variant % "0.0.0")})
                    self.refused("0.1.0", repo=repo, want=(rel, "matches 0 times"))

    def test_json_without_a_version_refused(self):  # S4
        repo = self.fresh(texts={PLUGIN: (PLUGIN_JSON % "0.0.0").replace('  "version": "0.0.0",\n', "")})
        self.refused("0.1.0", repo=repo, want=(PLUGIN, "version"))

    def test_json_wrong_shapes_refused(self):  # S4
        cases = [(PLUGIN, "[]\n"), (PLUGIN, "{not json}\n"), (PLUGIN, '{"version": 1}\n'),
                 (PLUGIN, '{"version": "0.0"}\n'),
                 (MARKET, '{"plugins": {}}\n'), (MARKET, '{"plugins": []}\n'),
                 (MARKET, '{"plugins": [{"name": "other", "version": "0.0.0"}]}\n'),
                 (MARKET, '{"plugins": [{"name": "strict-delivery", "version": "0.0.0"}, {"name": "strict-delivery", '
                          '"version": "0.0.0"}]}\n')]
        for rel, text in cases:
            with self.subTest(rel=rel, text=text):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo, want=(rel,))

    def test_marketplace_edits_the_strict_delivery_entry(self):  # S1
        text = (MARKET_JSON % "0.0.0").replace('"plugins": [', '"plugins": [\n    {"name": "other", "version": "7.7.7"},')
        repo = self.fresh(texts={MARKET: text})
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))
        data = json.loads(get(repo, MARKET).decode("utf-8"))
        self.assertEqual([(p["name"], p["version"]) for p in data["plugins"]],
                         [("other", "7.7.7"), ("strict-delivery", "0.1.0")])

    def test_json_edit_must_land_in_the_right_object(self):  # S3: the one exact text is in another object
        text = ('{\n  "name": "strict-delivery",\n  "version":"0.0.0",\n  "dependencies": [{"name": "x", '
                '"version": "0.0.0"}]\n}\n')
        repo = self.fresh(texts={PLUGIN: text})
        err = self.refused("0.1.0", repo=repo, want=(PLUGIN,))
        self.assertIn("is not that of", err)

    def test_missing_site_refused(self):  # S5
        for rel in SITES + [CHANGELOG]:
            with self.subTest(rel=rel):
                repo = self.fresh()
                git(repo, "rm", "-q", "--", rel)
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, want=(rel, "missing"))

    def test_changelog_missing_refused(self):  # C1
        repo = self.fresh(changelog=None)
        self.refused("0.1.0", repo=repo, want=(CHANGELOG, "missing"))

    def test_missing_block_refused(self):  # S6
        for rel, text in ((CLAUDE, CLAUDE_HEAD), (IGNORE, IGNORE_HEAD)):
            with self.subTest(rel=rel):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo, want=(rel, "init"))

    def test_malformed_or_foreign_block_refused(self):  # S6
        for rel, text in ((CLAUDE, claude_text("0.0.0").replace("<!-- strict-delivery:end -->\n", "")),
                          (IGNORE, ignore_text("0.0.0") + ignore_text("0.0.0")),
                          (CLAUDE, claude_text("0.0.0").replace("claude-block/1", "gitignore-block/1")),
                          (CLAUDE, claude_text("0.0.0").replace("\n", "\r\n"))):
            with self.subTest(rel=rel, text=text[:60]):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo, want=(rel,))

    def test_config_version_line_must_be_exact(self):  # S2
        for text in ('schema: config/2\nframework_version: "0.0.0" # pinned\nprofile: strict\n',
                     "schema: config/2\nframework_version: 0.0.0\nprofile: strict\n",
                     "schema: config/2\nframework_version: '0.0.0'\nprofile: strict\n",
                     'schema: config/2\nframework_version: "0.0.0"\nframework_version: "0.0.0"\nprofile: strict\n',
                     'schema: config/2\nprofile: strict\n', 'schema: config/2\nframework_version: ""\nprofile: strict\n'):
            with self.subTest(text=text):
                repo = self.fresh(texts={CONFIG: text})
                self.refused("0.1.0", repo=repo, want=(CONFIG,))

    def test_invalid_config_refused(self):
        repo = self.fresh(texts={CONFIG: CONFIG_YML % "0.0.0" + "unknown_key: 1\n"})
        self.refused("0.1.0", repo=repo, want=("unknown_key",))

    def test_crlf_preserved(self):  # S7
        for rel, base in ((PLUGIN, PLUGIN_JSON), (MARKET, MARKET_JSON)):
            with self.subTest(rel=rel):
                text = (base % "0.0.0").replace("\n", "\r\n")
                repo = self.fresh(texts={rel: text})
                code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(get(repo, rel), text.replace("0.0.0", "0.1.0").encode("utf-8"))
                self.assertEqual(get(repo, rel).count(b"\r\n"), text.count("\r\n"))

    def test_block_marker_as_init(self):  # S8
        code, _o, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(get(self.repo, CLAUDE).decode("utf-8"),
                         managed.put_block(CLAUDE_HEAD, managed.HTML, "claude-block", "0.1.0", claude_body()))
        self.assertEqual(get(self.repo, IGNORE).decode("utf-8"),
                         managed.put_block(IGNORE_HEAD, managed.HASH, "gitignore-block", "0.1.0", ignore_body()))
        self.assertIn("\n" + CLAUDE_BEGIN % "0.1.0" + "\n", get(self.repo, CLAUDE).decode("utf-8"))
        self.assertIn("\n" + IGNORE_BEGIN % "0.1.0" + "\n", get(self.repo, IGNORE).decode("utf-8"))
        self.assertEqual(managed.find_block(get(self.repo, CLAUDE).decode("utf-8"), managed.HTML).version, "0.1.0")

    def test_block_body_and_text_around_it_kept(self):  # S8
        head, tail = "# Mine\n\nbefore\n", "\nafter the block\nmore\n"
        body = "A hand-edited line.\nAnother.\n"
        text = claude_text("0.0.0", head=head, body=body) + tail
        repo = self.fresh(texts={CLAUDE: text})
        self.assertEqual(self.run_release("0.1.0", "--date", DATE, root=repo)[0], 0)
        self.assertEqual(get(repo, CLAUDE).decode("utf-8"), text.replace("version=0.0.0", "version=0.1.0"))


# --------------------------------------------------------------------------- C: CHANGELOG.md

class ChangelogRows(ReleaseCase):
    def test_no_unreleased_refused(self):  # C2
        repo = self.fresh(changelog="# Changelog\n\n## 0.0.0 - 2026-01-01\n\n- first\n")
        self.refused("0.1.0", repo=repo, want=("Unreleased",))

    def test_empty_unreleased_refused(self):  # C3
        for text in ("# Changelog\n\n## Unreleased\n\n## 0.0.0 - 2026-01-01\n\n- first\n",
                     "# Changelog\n\n## Unreleased\n## 0.0.0\n- first\n",
                     "# Changelog\n\n## Unreleased\n", "# Changelog\n\n## Unreleased", "# Changelog\n\n## Unreleased\n\n\n  \n",
                     "# Changelog\n\n## Unreleased\n\n# Other\n\n- x\n"):
            with self.subTest(text=text):
                repo = self.fresh(changelog=text)
                self.refused("0.1.0", repo=repo, want=("Unreleased", "empty"))

    def test_unreleased_last_section(self):  # C4
        for text in ("# Changelog\n\n## 0.0.0 - 2026-01-01\n\n- first\n\n## Unreleased\n\n- note\n",
                     "# Changelog\n\n## Unreleased\n\n- note", "## Unreleased\n- note\n",
                     "# Changelog\n\n## Unreleased\n\n### Added\n\n- x\n\n## 0.0.0\n"):
            with self.subTest(text=text):
                repo = self.fresh(changelog=text)
                code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                self.assertEqual((code, err), (0, ""))
                want = text.replace("## Unreleased\n", "## Unreleased\n\n## 0.1.0 - 2026-12-01\n", 1) \
                    if text.count("## Unreleased\n") else text.replace("## Unreleased", "## Unreleased\n\n## 0.1.0 - 2026-12-01", 1)
                self.assertEqual(get(repo, CHANGELOG).decode("utf-8"), want)

    def test_two_unreleased_refused(self):  # C5
        repo = self.fresh(changelog=CHANGELOG_TEXT + "\n## Unreleased\n\n- again\n")
        self.refused("0.1.0", repo=repo, want=("Unreleased", "2"))

    def test_changelog_rolled(self):  # C6, D1
        self.assertEqual(self.run_release("0.1.0", "--date", DATE)[0], 0)
        text = get(self.repo, CHANGELOG).decode("utf-8")
        self.assertIn("## Unreleased\n\n## 0.1.0 - 2026-12-01\n", text)
        self.assertEqual(text, "# Changelog\n\nSemver.\n\n## Unreleased\n\n## 0.1.0 - 2026-12-01\n\n- a note\n- another note\n\n"
                               "## 0.0.0 - 2026-01-01\n\n- first\n")

    def test_near_miss_refused_with_the_line_number(self):
        near = ["### Unreleased", "##  Unreleased", "## unreleased", "## Unreleased ", "## Unreleased (next)", "# Unreleased",
                "## UNRELEASED", "##Unreleased", "#unreleased", "### UnReleased", "## Unreleased:", "## Unreleasedx",
                "#  Unreleased", "## Unreleased\t"]
        for line in near:
            for pos in (0, 1):
                with self.subTest(line=line, pos=pos):
                    lines = ["# Changelog", "", "## Unreleased", "", "- note", ""]
                    lines.insert(1 if pos == 0 else 5, line)
                    # the near-miss line sits at line 2 (pos 0) or line 6 (pos 1); with the exact heading present or not
                    for doc in ("\n".join(lines) + "\n", "\n".join(l for l in lines if l != "## Unreleased") + "\n"):
                        repo = self.fresh(changelog=doc)
                        number = doc.split("\n").index(line) + 1
                        self.refused("0.1.0", repo=repo, want=(CHANGELOG, "line %d" % number))

    def test_lines_that_are_not_near_misses_are_ignored(self):
        for line in ("- unreleased things", "text ## unreleased", "unreleased", " ## unreleased", "## Released", "## 0.0.0"):
            with self.subTest(line=line):
                repo = self.fresh(changelog=CHANGELOG_TEXT + "\n" + line + "\n")
                self.assertEqual(self.run_release("0.1.0", "--date", DATE, root=repo)[0], 0)

    def test_changelog_cr_refused(self):  # CR
        for text in (CHANGELOG_TEXT.replace("\n", "\r\n"), CHANGELOG_TEXT.replace("- a note", "- a note\rmore"),
                     CHANGELOG_TEXT + "\r", "\r" + CHANGELOG_TEXT):
            with self.subTest(text=text[:40]):
                repo = self.fresh(changelog=text)
                self.refused("0.1.0", repo=repo, want=(CHANGELOG, "CR"))

    def test_shipped_changelog_shape(self):  # C7
        with open(os.path.join(ROOT, CHANGELOG), "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8")
        self.assertNotIn("\r", text)
        lines = text.split("\n")
        self.assertEqual(lines[0], "# Changelog")
        self.assertEqual(lines.count("## Unreleased"), 1)
        head, _sep, section = text.partition("\n## Unreleased\n")
        self.assertRegex(head, r"semantic versioning")
        self.assertRegex(head, r"Before 1\.0 a breaking change is allowed, and it comes with a migration")
        areas = ["Gates", "Tools", "Schemas and migrations", "Init, doctor and upgrade", "The plugin",
                 "Programs and streams", "Profiles"]
        bullets = [ln for ln in section.split("\n") if ln.startswith("- ")]
        self.assertEqual([b[2:b.index(":")] for b in bullets], areas)
        self.assertEqual([ln for ln in section.split("\n") if ln.strip() and not ln.startswith("- ")], [])
        self.assertNotRegex(text, r"\b(F|DEC|C|R)-[0-9]{8}-")
        self.assertNotRegex(text, r"\b(F|DEC|C|R)-20[0-9]{2}")
        self.assertNotRegex(text, r"(^|[^A-Za-z0-9_])@[A-Za-z0-9]")
        self.assertNotRegex(text.lower(), r"lap[- ]?timer|superbrobenji|swanepoel|benji|github\.com")
        self.assertEqual(text.count("## "), 1)
        # the shipped file can be released: the script accepts it as the changelog of a repository
        repo = self.fresh(changelog=text)
        self.assertEqual(self.run_release("0.1.0", "--date", DATE, root=repo)[0], 0)


# --------------------------------------------------------------------------- T, D, N

class TreeBranchDateRows(ReleaseCase):
    def test_dirty_tree_refused(self):  # T2
        def untracked(r):
            put(r, "stray.txt", "x\n")

        def modified(r):
            put(r, "README.md", "changed\n")

        def staged(r):
            put(r, "new.txt", "x\n")
            git(r, "add", "new.txt")

        def deleted(r):
            git(r, "rm", "-q", "--", "README.md")

        def nested_untracked(r):
            put(r, "deep/er/stray.txt", "x\n")
        for name, make in (("untracked", untracked), ("modified", modified), ("staged", staged), ("deleted", deleted),
                           ("nested", nested_untracked)):
            with self.subTest(case=name):
                repo = self.fresh()
                make(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, want=("not clean",))

    def test_dirty_site_file_refused(self):  # T2
        put(self.repo, PLUGIN, PLUGIN_JSON % "0.0.0" + "\n")
        self.refused("0.1.0", repo=self.repo, want=("not clean", PLUGIN))

    def test_on_base_branch_refused(self):  # T3
        git(self.repo, "checkout", "-q", "main")
        self.refused("0.1.0", repo=self.repo, want=("main",))

    def test_non_default_base_branch(self):  # T3
        repo = self.fresh(base="develop", branch="develop")
        self.refused("0.1.0", repo=repo, want=("develop",))
        repo = self.fresh(base="develop", branch="main")
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))
        repo = self.fresh(base="develop", branch="release-test")
        self.assertEqual(self.run_release("0.1.0", "--date", DATE, root=repo)[0], 0)

    def test_detached_refused(self):  # T4
        git(self.repo, "checkout", "-q", "--detach")
        self.refused("0.1.0", repo=self.repo, want=("detached",))

    def test_bad_date_refused(self):  # D2, P2
        for bad in ("2026-02-30", "2026-1-01", "20261201", "2026-13-01", "2026-12-1", "2027-02-29", "0000-01-01",
                    "2026-12-01 ", "", "2026-12-01\n", " 2026-12-01", "26-12-01", "2026-00-10", "2026-12-00",
                    "2026/12/01", "\u0662\u0660\u0662\u0666-\u0661\u0662-\u0660\u0661", "2026-12-0\u0661",
                    "\uff12\uff10\uff12\uff16-12-01"):
            with self.subTest(date=bad):
                self.refused("0.1.0", "--date", bad, want=("--date",))

    def test_valid_dates(self):  # D1
        for good in ("2026-12-01", "2028-02-29", "1999-01-31", "9999-12-31"):
            with self.subTest(date=good):
                repo = self.fresh()
                self.assertEqual(self.run_release("0.1.0", "--date", good, root=repo)[0], 0)
                self.assertIn("## 0.1.0 - %s\n" % good, get(repo, CHANGELOG).decode("utf-8"))

    def test_default_date_utc(self):  # D3
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is not available")
        old = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.pop("TZ", None) if old is None else os.environ.__setitem__("TZ", old),
                                 time.tzset()))
        for tz in ("Pacific/Kiritimati", "Etc/GMT+12", "UTC"):
            with self.subTest(tz=tz):
                os.environ["TZ"] = tz
                time.tzset()
                repo = self.fresh()
                before = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                code, _o, err = self.run_release("0.1.0", root=repo)
                after = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                self.assertEqual((code, err), (0, ""))
                m = re.search(r"^## 0\.1\.0 - ([0-9-]+)$", get(repo, CHANGELOG).decode("utf-8"), re.M)
                self.assertIn(m.group(1), (before, after))

    def test_never_commits_or_tags(self):  # N1
        head = git(self.repo, "rev-parse", "HEAD")
        refs = git(self.repo, "for-each-ref")
        code, _o, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.repo, "for-each-ref"), refs)
        self.assertEqual(git(self.repo, "tag"), "")
        self.assertEqual(git(self.repo, "stash", "list"), "")
        self.assertEqual(git(self.repo, "remote"), "")
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only"), "")
        self.assertEqual(self.changed(), SITE_PATHS | {CHANGELOG})

    def test_prints_next_commands(self):  # N1
        code, out, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual((code, err), (0, ""))
        for rel in sorted(SITE_PATHS | {CHANGELOG}):
            self.assertIn("  " + rel + "\n", out)
        self.assertIn("git add -- " + " ".join(SITES + [CHANGELOG]) + "\n", out)
        self.assertIn("git commit -m 'release: v0.1.0'\n", out)
        self.assertIn("git push -u origin release-test\n", out)
        self.assertIn("git tag -a v0.1.0 -m 'strict-delivery 0.1.0' <merge commit>\n", out)
        self.assertIn("git push origin v0.1.0\n", out)
        self.assertIn("pull request into main", out)
        self.assertEqual(git(self.repo, "tag"), "")


# --------------------------------------------------------------------------- H, P, X, G

class HardeningRows(ReleaseCase):
    def targets(self):
        return SITES + [CHANGELOG]

    def test_symlink_site_refused(self):  # H1
        for rel in self.targets():
            for where in ("inside", "outside"):
                with self.subTest(rel=rel, where=where):
                    repo = self.fresh()
                    data = get(repo, rel)
                    git(repo, "rm", "-q", "--", rel)
                    os.makedirs(os.path.dirname(os.path.join(repo, *rel.split("/"))), exist_ok=True)
                    if where == "inside":
                        target = os.path.join(repo, "target-copy")
                    else:
                        target = os.path.join(self.work, "outside-%d" % self.n)
                    with open(target, "wb") as fh:
                        fh.write(data)
                    os.symlink(target, os.path.join(repo, *rel.split("/")))
                    self.commit(repo)
                    self.refused("0.1.0", "--date", DATE, repo=repo, want=(rel, "symbolic link"))

    def test_dangling_symlink_site_refused(self):  # H1
        git(self.repo, "rm", "-q", "--", CONFIG)
        os.makedirs(os.path.join(self.repo, ".strict-delivery"), exist_ok=True)
        os.symlink(os.path.join(self.work, "nowhere"), os.path.join(self.repo, *CONFIG.split("/")))
        self.commit()
        self.refused("0.1.0", want=(CONFIG, "symbolic link"))

    def test_directory_site_refused(self):  # H2
        for rel in self.targets():
            with self.subTest(rel=rel):
                repo = self.fresh()
                git(repo, "rm", "-q", "--", rel)
                put(repo, rel + "/inner.txt", "x\n")
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, want=(rel, "directory"))

    def test_fifo_site_refused(self):  # H3
        for rel in self.targets():
            with self.subTest(rel=rel):
                repo = self.fresh()
                git(repo, "rm", "-q", "--", rel)
                os.makedirs(os.path.dirname(os.path.join(repo, *rel.split("/"))), exist_ok=True)
                os.mkfifo(os.path.join(repo, *rel.split("/")))
                before = snapshot(self.work)
                self.guard(repo)
                code, out, err = within(lambda: self.call(["0.1.0", "--date", DATE, "--root", repo]), 20)
                self.assertEqual(code, 1, err)
                self.assertIn(rel, err)
                self.assertIn("not a regular file", err)
                self.assertEqual(snapshot(self.work), before)

    def test_parent_symlink_refused(self):  # H4
        for parent in (".claude-plugin", ".strict-delivery"):
            with self.subTest(parent=parent):
                repo = self.fresh()
                other = os.path.join(self.work, "other-%d" % self.n)
                os.makedirs(other)
                for name in os.listdir(os.path.join(repo, parent)):
                    with open(os.path.join(other, name), "wb") as fh:
                        fh.write(get(repo, parent + "/" + name))
                git(repo, "rm", "-q", "-r", "--", parent)
                os.symlink(other, os.path.join(repo, parent))
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, want=(parent + "/", "symbolic link or not a directory"))

    def test_swap_between_read_and_write_detected(self):  # H4
        real = release._read
        calls = {}

        def swapping(root, rel):
            text = real(root, rel)
            calls[rel] = calls.get(rel, 0) + 1
            if rel == PLUGIN and calls[rel] == 2:  # the first read of the comparison pass, after the tree check
                with open(os.path.join(root, *MARKET.split("/")), "ab") as fh:
                    fh.write(b" ")
            return text
        before = snapshot(self.repo)
        with mock.patch.object(release, "_read", swapping):
            code, out, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual(code, 1)
        self.assertIn(MARKET, err)
        self.assertIn("changed after it was read", err)
        self.assertIn("nothing written", err)
        after = snapshot(self.repo)
        self.assertEqual(after.pop(MARKET), before[MARKET] + b" ")
        before.pop(MARKET)
        self.assertEqual(after, before)

    def test_swap_during_the_writes_reported(self):  # H4
        real = release._read
        calls = {}

        def swapping(root, rel):
            text = real(root, rel)
            calls[rel] = calls.get(rel, 0) + 1
            if rel == PLUGIN and calls[rel] == 3:  # the read just before the write of the first site
                with open(os.path.join(root, *MARKET.split("/")), "ab") as fh:
                    fh.write(b" ")
            return text
        before = snapshot(self.repo)
        with mock.patch.object(release, "_read", swapping):
            code, out, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual(code, 1)
        self.assertIn(MARKET, err)
        self.assertIn("written before it: " + PLUGIN, err)
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[0]), "0.1.0")
        self.assertEqual(get(self.repo, MARKET), before[MARKET] + b" ")
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[2]), "0.0.0")

    def test_site_turned_into_a_link_during_the_run_refused(self):  # H4
        real = release._read
        calls = {}

        def swapping(root, rel):
            text = real(root, rel)
            calls[rel] = calls.get(rel, 0) + 1
            if rel == PLUGIN and calls[rel] == 3:
                path = os.path.join(root, *MARKET.split("/"))
                os.rename(path, path + ".moved")
                os.symlink(path + ".moved", path)
            return text
        with mock.patch.object(release, "_read", swapping):
            code, _o, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual(code, 1)
        self.assertIn(MARKET, err)
        self.assertIn("symbolic link", err)
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[0]), "0.1.0")
        self.assertEqual(get(self.repo, MARKET + ".moved"), (MARKET_JSON % "0.0.0").encode("utf-8"))

    def test_root_not_toplevel_refused(self):  # H5
        sub = os.path.join(self.repo, "sub")
        os.makedirs(sub)
        put(self.repo, "sub/file.txt", "x\n")
        put(sub, "extra.txt", "y\n")
        self.commit()
        self.refused("0.1.0", root=sub, want=("top level",))
        self.refused("0.1.0", root=os.path.join(sub, "file.txt"), want=("--root",))
        self.refused("0.1.0", root=os.path.join(self.repo, "missing"), want=("--root",))

    def test_root_symlink_to_the_top_level_accepted(self):  # H5
        link = os.path.join(self.work, "link")
        os.symlink(self.repo, link)
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=link)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[0]), "0.1.0")

    def test_non_utf8_refused(self):  # H6
        for rel in self.targets():
            with self.subTest(rel=rel):
                repo = self.fresh()
                put(repo, rel, get(repo, rel) + b"\xff\xfe broken\n")
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, want=(rel, "UTF-8"))

    def test_outside_root_refused(self):  # H7
        plain = os.path.join(self.work, "plain")
        os.makedirs(plain)
        for rel, text in site_texts(None).items():
            put(plain, rel, text)
        put(plain, CHANGELOG, CHANGELOG_TEXT)
        before = snapshot(self.work)
        for root in (plain, os.path.join(self.work, "missing-dir")):
            with self.subTest(root=root):
                code, out, err = self.run_release("0.1.0", "--date", DATE, root=root)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("--root", err)
                self.assertEqual(snapshot(self.work), before)
        for root in ("", "bad\x00root"):
            with self.subTest(root=root):
                code, out, err = self.call(["0.1.0", "--root", root])
                self.assertEqual((code, out), (1, ""))
                self.assertIn("--root", err)
                self.assertEqual(snapshot(self.work), before)

    def test_huge_component(self):  # P1
        big = ["1" + "0" * 4299, "1" + "0" * 4300, "1" + "0" * 9, "1234567890"]
        for limit in INT_LIMITS:
            for digits in big:
                for form in ("%s.0.0", "0.%s.0", "0.0.%s"):
                    with self.subTest(limit=limit, digits=len(digits), form=form):
                        with int_limit(limit):
                            self.refused(form % digits, "--date", DATE, want=("digits",))
        with int_limit(640 if 640 in INT_LIMITS else None):
            repo = self.fresh(versions=dict((s, "1" + "0" * 4300 + ".0.0") for s in SITES))
            self.refused("0.1.0", repo=repo, want=("digits",))
            repo = self.fresh(versions=dict((s, "1" + "0" * 4300 + ".0.0") for s in SITES))
            self.refused("9.9.9", repo=repo, want=("digits",))

    def test_non_ascii_digits_refused(self):  # P2
        for bad in ("\u0660.\u0661.\u0660", "\uff10.\uff11.\uff10", "\u00b2.0.0", "0.\u0967.0", "0.1.\u0e50", "\u2467.0.0",
                    "1.0.0\u0660", "\u0661.0.0"):
            with self.subTest(version=bad):
                self.refused(bad, "--date", DATE, want=("MAJOR.MINOR.PATCH",))

    def test_base_exception_propagates(self):  # P3
        excs = [KeyboardInterrupt(), SystemExit(3), GeneratorExit()]
        if sys.version_info >= (3, 11):
            excs.append(builtins.BaseExceptionGroup("group", [KeyboardInterrupt()]))
        else:
            self.assertFalse(hasattr(builtins, "BaseExceptionGroup"))
        for exc in excs:
            for name in ("put_block", "find_block"):
                with self.subTest(exc=type(exc).__name__, name=name):
                    repo = self.fresh()
                    before = snapshot(self.work)
                    with mock.patch.object(managed, name, side_effect=exc):
                        with self.assertRaises(type(exc)):
                            self.call(["0.1.0", "--date", DATE, "--root", repo])
                    self.assertEqual(snapshot(self.work), before)

    def test_ordinary_exceptions_are_not_swallowed_as_refusals(self):  # P3
        with mock.patch.object(managed, "put_block", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.call(["0.1.0", "--date", DATE, "--root", self.repo])

    def test_main_takes_exact_types(self):  # X1
        good = ["0.1.0", "--date", DATE, "--root", self.repo]
        self.guard(self.repo)
        bad = [("list subclass", ListSub(good), "ListSub"), ("tuple", tuple(good), "tuple"), ("None", None, "NoneType"),
               ("str", "0.1.0", "str"), ("dict", {}, "dict"), ("int", 1, "int"),
               ("str subclass item", ["0.1.0", Sub("--date"), DATE, "--root", self.repo], "Sub"),
               ("str subclass value", ["0.1.0", "--date", DATE, "--root", Sub(self.repo)], "Sub"),
               ("bytes item", [b"0.1.0", "--root", self.repo], "bytes"), ("None item", ["0.1.0", None], "NoneType"),
               ("int item", [1], "int"), ("nested list item", [["0.1.0"]], "list")]
        before = snapshot(self.work)
        for name, value, typename in bad:
            with self.subTest(case=name):
                with mock.patch.object(release, "_read", side_effect=AssertionError("read before the type check")):
                    with mock.patch.object(release.gitinfo, "toplevel", side_effect=AssertionError("git before the check")):
                        out, err = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            with self.assertRaises(TypeError) as cm:
                                release.main(value)
                self.assertIn("argv", str(cm.exception))
                self.assertIn(typename, str(cm.exception))
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
                self.assertEqual(snapshot(self.work), before)
        code, _o, err = self.call(list(good))
        self.assertEqual((code, err), (0, ""))

    def test_public_functions_take_exact_types(self):  # X2
        with open(SCRIPT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        public = {n.name: [a.arg for a in n.args.args] for n in tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
        self.assertEqual(public, {"main": ["argv"]})  # a new public function needs its row here
        exact = {("main", "argv"): ["0.1.0", "--root", self.repo]}
        subclass = {("main", "argv"): ListSub(exact[("main", "argv")])}
        for (fn, param), value in exact.items():
            for name, bad in (("subclass", subclass[(fn, param)]), ("None", None), ("unrelated", 5)):
                with self.subTest(function=fn, parameter=param, value=name):
                    with mock.patch.object(release, "_read", side_effect=AssertionError("work before the type check")):
                        with self.assertRaises(TypeError) as cm:
                            getattr(release, fn)(bad)
                    self.assertIn(param, str(cm.exception))
        self.assertEqual(self.call(list(exact[("main", "argv")]) + ["--date", "2026-02-30"])[0], 1)

    def test_generated_git_environments_agree(self):  # G1
        rng = random.Random(20261126)
        decoy = os.path.join(self.work, "decoy")
        os.makedirs(decoy)
        git(decoy, "init", "-q", "-b", "main")
        excludes = os.path.join(self.tmp, "excludes")
        with open(excludes, "w", encoding="utf-8") as fh:
            fh.write("stray.txt\n")
        variants = {}
        for name in ("clean", "dirty", "base"):
            repo = self.fresh()
            if name == "dirty":
                put(repo, "stray.txt", "x\n")
            if name == "base":
                git(repo, "checkout", "-q", "main")
            variants[name] = repo
        expected = {}
        for name, repo in variants.items():
            code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
            expected[name] = (code, err)
            if code == 0:
                git(repo, "reset", "-q", "--hard")
        self.assertEqual(expected["clean"], (0, ""))
        self.assertEqual(expected["dirty"][0], 1)
        self.assertEqual(expected["base"][0], 1)
        pairs = [("status.showUntrackedFiles", "no"), ("status.showUntrackedFiles", "normal"), ("core.excludesFile", excludes),
                 ("core.fsmonitor", "true"), ("status.relativePaths", "false"), ("core.quotePath", "false"),
                 ("color.status", "always"), ("diff.ignoreSubmodules", "all"), ("core.untrackedCache", "true"),
                 ("status.renames", "copies"), ("status.short", "true")]
        names = ("clean", "dirty", "base")
        differing = []
        hidden_cases = []
        for i in range(120):
            env = {}
            if rng.random() < 0.4:
                env["GIT_DIR"] = os.path.join(decoy, ".git")
            if rng.random() < 0.4:
                env["GIT_WORK_TREE"] = decoy
            if rng.random() < 0.3:
                env["GIT_COMMON_DIR"] = os.path.join(decoy, ".git")
            if rng.random() < 0.3:
                env["GIT_CEILING_DIRECTORIES"] = self.work
            if rng.random() < 0.6:
                chosen = rng.sample(pairs, rng.randint(1, 3))
                env["GIT_CONFIG_COUNT"] = str(len(chosen))
                for k, (key, value) in enumerate(chosen):
                    env["GIT_CONFIG_KEY_%d" % k] = key
                    env["GIT_CONFIG_VALUE_%d" % k] = value
            if rng.random() < 0.5:
                gpath = os.path.join(self.tmp, "gitconfig-%d" % i)
                chosen = rng.sample(pairs[:6], rng.randint(1, 2))
                with open(gpath, "w", encoding="utf-8") as fh:
                    for key, value in chosen:
                        section, _dot, var = key.partition(".")
                        fh.write("[%s]\n\t%s = %s\n" % (section, var, value))
                env["GIT_CONFIG_GLOBAL"] = gpath
            if rng.random() < 0.5:
                env["GIT_CONFIG_NOSYSTEM"] = "1"
            name = names[i % 3]
            repo = variants[name]
            self.guard(repo)
            hidden = False
            with mock.patch.dict(os.environ, env):
                code, _o, err = self.call(["0.1.0", "--date", DATE, "--root", repo])
                if name == "dirty":
                    # git's own answer, with the case's config and without the names gitinfo clears: is the untracked
                    # file ignored by the user's rules (a finding: gitinfo.dirty_paths then calls the tree clean)?
                    probe = dict((k, v) for k, v in os.environ.items() if k not in gitinfo.CLEARED_ENV)
                    hidden = subprocess.run(["git", "-C", repo, "check-ignore", "-q", "--", "stray.txt"], env=probe,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL).returncode == 0
            if code == 0:
                git(repo, "reset", "-q", "--hard")
            if hidden:
                hidden_cases.append((i, code))
            elif (code, err) != expected[name]:
                differing.append((i, name, sorted(env), code, err))
        self.assertEqual(differing, [])
        # Finding (reported, not fixed here): when the user's ignore rules (core.excludesFile) hide the untracked
        # file, gitinfo.dirty_paths lists nothing and the script, like every gate that asks it, calls the tree clean.
        self.assertGreater(len(hidden_cases), 0)
        self.assertEqual([c for _i, c in hidden_cases if c != 0], [])


# --------------------------------------------------------------------------- G2: generated changelogs

class GeneratedChangelogs(ReleaseCase):
    POOL = ["# Changelog", "", "", "## 0.0.0 - 2026-01-01", "## 0.0.1", "### Added", "- note", "- another note", "text",
            "  ", "### Unreleased", "##  Unreleased", "## unreleased", "## Unreleased ", "## Unreleased (next)",
            "# Unreleased", "## UNRELEASED", "#unreleased", "## Unreleasedx", "- ## Unreleased", "unreleased",
            "- unreleased things", "# Other", "#", "## ", "##Unreleased", "text ## unreleased"]

    PLAIN = ["# Changelog", "", "## 0.0.0 - 2026-01-01", "## 0.0.1", "# Other", "text", "  ", "- unreleased things"]
    SECTION = ["", "- note", "- another note", "### Added", "text", "  ", "", "- note"]

    @staticmethod
    def oracle(doc):
        """(accepted, rolled text or None) by a hand-written reading of the decision."""
        lines = doc.split("\n")
        exact = [i for i, ln in enumerate(lines) if ln == "## Unreleased"]
        for ln in lines:
            low = ln.lower()
            stripped = low.lstrip("#")
            if low.startswith("#") and stripped.lstrip(" ").startswith("unreleased") and ln != "## Unreleased":
                return False, None
        if len(exact) != 1:
            return False, None
        i = exact[0]
        j = i + 1
        body = []
        while j < len(lines) and not lines[j].startswith("## ") and not lines[j].startswith("# "):
            body.append(lines[j])
            j += 1
        if all(b.strip() == "" for b in body):
            return False, None
        rolled = lines[:i] + ["## Unreleased", "", "## 0.1.0 - 2026-12-01"] + lines[i + 1:]
        return True, "\n".join(rolled)

    def test_generated_changelogs(self):  # G2
        rng = random.Random(20261126)
        repo = self.repo
        seen = {True: 0, False: 0}
        for i in range(220):
            lines = [rng.choice(self.PLAIN) for _ in range(rng.randint(0, 5))]
            for _ in range(rng.choice((0, 1, 1, 1, 1, 1, 1, 2))):
                lines.append("## Unreleased")
                lines += [rng.choice(self.SECTION) for _ in range(rng.randint(0, 4))]
                lines += [rng.choice(self.PLAIN) for _ in range(rng.randint(0, 3))]
            if rng.random() < 0.3:  # a near-miss line or another odd line somewhere
                lines.insert(rng.randint(0, len(lines)), rng.choice(self.POOL))
            doc = "\n".join(lines) + rng.choice(("", "\n"))
            ok, rolled = self.oracle(doc)
            seen[ok] += 1
            put(repo, CHANGELOG, doc)
            self.commit(repo)
            before = snapshot(self.work)
            code, out, err = self.run_release("0.1.0", "--date", DATE)
            with self.subTest(i=i, doc=doc):
                if ok:
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(get(repo, CHANGELOG).decode("utf-8"), rolled)
                else:
                    self.assertEqual(code, 1)
                    self.assertTrue("Unreleased" in err or re.search(r"line [0-9]+", err), err)
                    self.assertEqual(snapshot(self.work), before)
            if code == 0:
                git(repo, "reset", "-q", "--hard")
        self.assertGreater(seen[True], 50)
        self.assertGreater(seen[False], 50)


# --------------------------------------------------------------------------- E2E and DS

def e2e_skip_reason(root):
    """The reason the E2E body cannot run on the checkout ``root``, or None: no doctor module (Task 4d.3), or the
    CLAUDE.md of the checkout holds no managed block (the adoption, Rq-4-5)."""
    if not os.path.isfile(os.path.join(root, "gates", "tools", "doctor.py")):
        return E2E_REASON
    try:
        with open(os.path.join(root, "CLAUDE.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return E2E_REASON
    if "<!-- strict-delivery:begin" not in text:
        return E2E_REASON
    return None


def e2e_or_skip(tc, root, body):
    reason = e2e_skip_reason(root)
    if reason is not None:
        tc.skipTest(reason)
    body(tc, root)


def e2e_body(tc, source):
    """This checkout cloned into a temporary directory with its working files, the script run, then ``run_all`` and
    ``doctor`` on the result: both exit 0."""
    clone = os.path.join(tc.work, "e2e")
    git(tc.work, "clone", "-q", source, clone)
    git(clone, "config", "user.email", "fixture@example.invalid")
    git(clone, "config", "user.name", "Fixture")
    git(clone, "config", "commit.gpgsign", "false")
    names = git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    for rel in names:
        src = os.path.join(source, rel)
        if rel == "" or not os.path.isfile(src):
            continue
        to = os.path.join(clone, rel)
        os.makedirs(os.path.dirname(to), exist_ok=True)
        with open(src, "rb") as fh, open(to, "wb") as out:
            out.write(fh.read())
    commit_all(clone, "working files")
    git(clone, "checkout", "-q", "-b", "release-e2e")
    run = [sys.executable, os.path.join(clone, "scripts", "release.py"), "0.1.0", "--date", DATE, "--root", clone]
    p = subprocess.run(run, cwd=clone, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tc.assertEqual(p.returncode, 0, p.stdout)
    for cmd in ([sys.executable, "-m", "gates", "run_all", "--root", clone],
                [sys.executable, "-m", "gates", "doctor", "--root", clone]):
        p = subprocess.run(cmd, cwd=clone, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        tc.assertEqual(p.returncode, 0, p.stdout)


class EndToEnd(ReleaseCase):
    def test_run_all_and_doctor_agree_after_bump(self):  # E2E (row E2E; decision: dependency skip, reason below)
        e2e_or_skip(self, ROOT, e2e_body)

    def test_e2e_skip_condition(self):  # DS
        def fixture(name, doctor, block):
            root = os.path.join(self.work, name)
            os.makedirs(os.path.join(root, "gates", "tools"))
            if doctor:
                put(root, "gates/tools/doctor.py", "# doctor\n")
            put(root, "CLAUDE.md", "# Notes\n" + (CLAUDE_BEGIN % "0.0.0" + "\nx\n<!-- strict-delivery:end -->\n" if block else ""))
            return root
        for name, doctor, block in (("none", False, False), ("no-block", True, False), ("no-doctor", False, True)):
            with self.subTest(case=name):
                root = fixture(name, doctor, block)
                calls = []
                with self.assertRaises(unittest.SkipTest) as cm:
                    e2e_or_skip(self, root, lambda tc, r: calls.append(r))
                self.assertEqual(str(cm.exception), E2E_REASON)
                self.assertEqual(calls, [])
        root = fixture("both", True, True)
        calls = []
        e2e_or_skip(self, root, lambda tc, r: calls.append(r))
        self.assertEqual(calls, [root])
        self.assertEqual(E2E_REASON, "4d.3 doctor and Rq-4-5 adoption not on this branch")
        missing = os.path.join(self.work, "no-claude")
        os.makedirs(missing)
        self.assertEqual(e2e_skip_reason(missing), E2E_REASON)

    def test_this_repository_is_refused_with_the_missing_block_reason(self):  # S6 on the real files, read only
        if e2e_skip_reason(ROOT) is None:
            self.skipTest("this checkout holds the managed blocks")
        with open(os.path.join(ROOT, "CLAUDE.md"), "rb") as fh:
            self.assertNotIn(b"strict-delivery:begin", fh.read())
        repo = self.fresh(texts={CLAUDE: CLAUDE_HEAD})
        self.refused("0.1.0", repo=repo, want=(CLAUDE, "init"))


if __name__ == "__main__":
    unittest.main()
