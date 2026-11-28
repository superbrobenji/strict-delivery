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
import errno
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
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, watched, within

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


CHILD_SECS = 120  # every child process and git call of a test is bounded: a hang fails the test by name


def bounded(label, fn, secs=CHILD_SECS):
    """``fn()`` under a time limit: a call that has not returned after ``secs`` seconds fails the test with ``label``
    in the message, so a hung git call never blocks the shard (F7)."""
    try:
        kind, value = watched(fn, secs)
    except AssertionError:
        raise AssertionError("%s did not finish within %d s (a git call or the script hung)" % (label, secs)) from None
    if kind == "err":
        raise value
    return value


def run_child(args, cwd, env=None, secs=CHILD_SECS):
    """``(code, stdout bytes, stderr bytes)`` of ``python3 scripts/release.py <args>`` as a child process of the running
    interpreter; ``env`` adds names (a value of ``None`` removes the name); PYTHONIOENCODING and PYTHONINTMAXSTRDIGITS
    are never inherited."""
    full = dict((k, v) for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONINTMAXSTRDIGITS"))
    for k, v in (env or {}).items():
        if v is None:
            full.pop(k, None)
        else:
            full[k] = v
    try:
        p = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=cwd, env=full, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=secs)
    except subprocess.TimeoutExpired:
        raise AssertionError("the release script child did not finish within %d s" % secs) from None
    return p.returncode, p.stdout, p.stderr


def printout(old, new, branch, base, date="2026-12-01"):
    """The whole stdout of a successful run, typed by hand from the plan (names that shlex.quote leaves as they are)."""
    paths = [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "CLAUDE.md", ".gitignore",
             ".strict-delivery/config.yml", "CHANGELOG.md"]
    tag = "v" + new
    return ("release: %s -> %s (%s)\nchanged:\n" % (old, new, date) + "".join("  %s\n" % p for p in paths)
            + "next commands (this script ran none of them):\n"
            + "  git add -- " + " ".join(paths) + "\n"
            + "  git commit -m 'release: %s'\n" % tag
            + "  git push -u origin %s\n" % branch
            + "  open a pull request into %s and merge it\n" % base
            + "  after the merge is read back from the host, on the merge commit: "
              "git tag -a %s -m 'strict-delivery %s' <merge commit>\n" % (tag, new)
            + "  only on the owner's word: git push origin %s\n" % tag)


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

    def refused(self, *args, root="default", repo=None, want=(), unwanted=(), exact=None):
        """Run, assert exit 1 with every ``want`` text in stderr, nothing on stdout and no file changed; the stderr.
        ``exact``: the whole reason (R2-F5), typed by hand; stderr is then ``release: <exact>\\n`` and nothing else."""
        repo = repo or self.repo
        before = snapshot(self.work)
        head = git(repo, "rev-parse", "HEAD")
        code, out, err = self.run_release(*args, root=repo if root == "default" else root)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        if exact is not None:
            self.assertEqual(err, "release: %s\n" % exact)
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
                self.refused(new, "--date", DATE, repo=repo,
                             exact="the version %s is not greater than the current version %s" % (new, current))

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
        self.refused("0.1.0", "--date", DATE, exact="the version 0.1.0 is not greater than the current version 0.1.0")
        self.commit()
        self.refused("0.1.0", "--date", DATE, exact="the version 0.1.0 is not greater than the current version 0.1.0")

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
        code, _out, err = run_child(["0.1.0", "--date", DATE, "--root", self.repo], self.work)
        self.assertEqual((code, err), (0, b""))
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[2]), "0.1.0")
        code, _out, err = run_child(["0.1", "--root", self.repo], self.work)
        self.assertEqual(code, 1)
        self.assertIn(b"MAJOR.MINOR.PATCH", err)


# --------------------------------------------------------------------------- S: the sites

class SiteRows(ReleaseCase):
    def test_disagreeing_sites_refused(self):  # S2
        for odd in SITES:
            with self.subTest(odd=odd):
                repo = self.fresh(versions={odd: "0.0.1"})
                self.refused("0.1.0", "--date", DATE, repo=repo, exact=(
                    "the sites disagree on the current version (most hold 0.0.0): %s holds 0.0.1" % odd))

    def test_two_disagreeing_sites_both_listed(self):  # S2
        repo = self.fresh(versions={MARKET: "0.0.1", CONFIG: "0.0.2"})
        self.refused("0.1.0", repo=repo, exact="the sites disagree on the current version (most hold 0.0.0): "
                     ".claude-plugin/marketplace.json holds 0.0.1; .strict-delivery/config.yml holds 0.0.2")

    def test_disagreeing_with_the_new_version_still_refused(self):  # S2
        repo = self.fresh(versions={IGNORE: "0.1.0"})
        self.refused("0.1.0", repo=repo,
                     exact="the sites disagree on the current version (most hold 0.0.0): .gitignore holds 0.1.0")

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
                self.refused("0.1.0", repo=repo,
                             exact='%s: the text "version": "0.0.0" matches 2 times, not exactly once' % rel)

    def test_json_key_repeated_refused(self):  # S3, F4: refused at the parse now, before the text count
        text = (PLUGIN_JSON % "0.0.0").replace('  "license"', '  "version": "0.0.0",\n  "license"')
        repo = self.fresh(texts={PLUGIN: text})
        err = self.refused("0.1.0", repo=repo)
        self.assertEqual(err, 'release: .claude-plugin/plugin.json: repeated key "version"\n')

    @staticmethod
    def repeated(rel, key, label):
        """``(text, hand-typed what)``: the site file ``rel`` (version 0.0.0) with ``key`` repeated as ``label`` says."""
        base = (PLUGIN_JSON if rel == PLUGIN else MARKET_JSON) % "0.0.0"
        entry = rel == MARKET  # the strict-delivery entry of the marketplace, else the top level of plugin.json
        pad = "      " if entry else "  "
        ver = pad + '"version": "0.0.0",\n'
        if label == "version, equal values":
            return base.replace(ver, ver + ver, 1)
        if label == "version, different values":
            return base.replace(ver, ver + pad + '"version": "0.0.1",\n', 1)
        name = pad + '"name": "strict-delivery",\n'
        if label == "name, strict-delivery then another":
            return base.replace(name, name + pad + '"name": "other",\n', 1)
        if label == "name, another then strict-delivery":
            return base.replace(name, pad + '"name": "other",\n' + name, 1)
        if label == "nested object":
            return base.replace('"name": "Someone"\n', '"name": "Someone",\n    "name": "Someone"\n', 1)
        if label == "top level":
            top = '  "license": "MIT",\n' if rel == PLUGIN else '  "owner": {\n'
            return base.replace(top, '  "marker": 1,\n  "marker": 2,\n' + top, 1)
        raise AssertionError(label)

    def test_json_repeated_key_refused(self):  # F4 (F-20261126-8meb): any key twice in any one object
        members = (("version, equal values", "version"), ("version, different values", "version"),
                   ("name, strict-delivery then another", "name"), ("name, another then strict-delivery", "name"),
                   ("nested object", "name"), ("top level", "marker"))
        for rel in (PLUGIN, MARKET):
            for label, key in members:
                with self.subTest(rel=rel, member=label):
                    text = self.repeated(rel, key, label)
                    self.assertNotEqual(text, (PLUGIN_JSON if rel == PLUGIN else MARKET_JSON) % "0.0.0")
                    repo = self.fresh(texts={rel: text})
                    err = self.refused("0.1.0", "--date", DATE, repo=repo)
                    self.assertEqual(err, 'release: %s: repeated key "%s"\n' % (rel, key))

    def test_json_same_key_in_different_objects_accepted(self):  # F4 invariant: only one object's repeat is refused
        text = (PLUGIN_JSON % "0.0.0").replace('"name": "Someone"', '"name": "strict-delivery"')
        repo = self.fresh(texts={PLUGIN: text})
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))

    def test_json_number_is_never_a_version(self):  # F3 invariant: an integer where a version string belongs
        for rel, text in ((PLUGIN, '{"version": 1}\n'),
                          (MARKET, '{"plugins": [{"name": "strict-delivery", "version": 100}]}\n')):
            with self.subTest(rel=rel):
                repo = self.fresh(texts={rel: text})
                err = self.refused("0.1.0", repo=repo)
                self.assertEqual(err, "release: %s: version is missing or not a string\n" % rel)

    @staticmethod
    def with_literal(rel, where, literal):
        """The site file ``rel`` (version 0.0.0) holding the JSON number text ``literal`` at ``where``."""
        base = (PLUGIN_JSON if rel == PLUGIN else MARKET_JSON) % "0.0.0"
        if where == "top level":
            anchor = '  "license": "MIT",\n' if rel == PLUGIN else '  "owner": {\n'
            return base.replace(anchor, '  "build": %s,\n' % literal + anchor, 1)
        if where == "nested":
            if rel == PLUGIN:
                return base.replace('"name": "Someone"\n', '"name": "Someone",\n    "build": %s\n' % literal, 1)
            return base.replace('      "source": "./",\n', '      "source": "./",\n      "build": %s,\n' % literal, 1)
        anchor = '  "dependencies": [\n' if rel == PLUGIN else '  "allowCrossMarketplaceDependenciesOn": [\n'
        return base.replace(anchor, anchor + "    %s,\n" % literal, 1)

    def huge_cases(self):
        """(label, literal, accepted): the digit counts of the member list; the sign is not counted."""
        one = "1" + "0" * 4299
        two = "1" + "0" * 4300
        return (("4300 digits", one, True), ("4301 digits", two, False),
                ("negative, 4300 digits", "-" + one, True), ("negative, 4301 digits", "-" + two, False))

    def check_huge(self, rel, where, label, literal, accepted):
        text = self.with_literal(rel, where, literal)
        self.assertIn(literal, text)
        repo = self.fresh(texts={rel: text})
        if accepted:
            code, out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(get(repo, rel), text.encode("utf-8").replace(b'"version": "0.0.0"', b'"version": "0.1.0"'))
        else:
            err = self.refused("0.1.0", "--date", DATE, repo=repo)
            self.assertEqual(err, "release: %s: holds an integer of more than 4300 digits\n" % rel)

    def test_json_huge_integer_in_process(self):  # F3 (F-20261126-yr5b): the same verdict under every int limit
        for limit in INT_LIMITS:
            for rel in (PLUGIN, MARKET):
                for where in ("top level", "nested", "array element"):
                    for label, literal, accepted in self.huge_cases():
                        if limit is not None and where == "array element":
                            continue
                        with self.subTest(limit=limit, rel=rel, where=where, member=label):
                            with int_limit(limit):
                                self.check_huge(rel, where, label, literal, accepted)

    def test_json_huge_integer_in_a_child_process(self):  # F3: PYTHONINTMAXSTRDIGITS 640, 0 and unset (also on 3.9)
        for env in (None, "640", "0"):
            for rel, where, (_label, literal, accepted) in [(r, w, c) for r in (PLUGIN, MARKET)
                                                           for w in ("top level", "nested") for c in self.huge_cases()]:
                    with self.subTest(env=env, rel=rel, where=where, digits=len(literal), accepted=accepted):
                        text = self.with_literal(rel, where, literal)
                        repo = self.fresh(texts={rel: text})
                        before = snapshot(self.work)
                        code, out, err = run_child(["0.1.0", "--date", DATE, "--root", repo], self.work,
                                                   {"PYTHONINTMAXSTRDIGITS": env} if env is not None else {})
                        if accepted:
                            self.assertEqual((code, err), (0, b""))
                            self.assertEqual(get(repo, rel), text.encode("utf-8").replace(
                                b'"version": "0.0.0"', b'"version": "0.1.0"'))
                        else:
                            self.assertEqual((code, out), (1, b""))
                            self.assertEqual(err, ("release: %s: holds an integer of more than 4300 digits\n" % rel).encode())
                            self.assertEqual(snapshot(self.work), before)

    def test_json_integer_band_under_a_lowered_limit(self):  # R2-F2 (F-20261128-hri6): 641-4300 digits accepted, 4301 refused
        # Controller decision (round 2): the accepted band stays, as gates/lib/plugin.py's own parser keeps integer text:
        # "4300 digits accepted, more refused; the same on both interpreters and every PYTHONINTMAXSTRDIGITS value".
        for digits, accepted in ((641, True), (999, True), (4300, True), (4301, False)):
            for rel in (PLUGIN, MARKET):
                with self.subTest(rel=rel, digits=digits):
                    literal = "1" + "0" * (digits - 1)
                    text = self.with_literal(rel, "top level", literal)
                    repo = self.fresh(texts={rel: text})
                    before = snapshot(self.work)
                    code, out, err = run_child(["0.1.0", "--date", DATE, "--root", repo], self.work,
                                               {"PYTHONINTMAXSTRDIGITS": "640"})
                    if accepted:
                        self.assertEqual((code, err), (0, b""))
                        self.assertEqual(get(repo, rel), text.encode("utf-8").replace(
                            b'"version": "0.0.0"', b'"version": "0.1.0"'))
                    else:
                        self.assertEqual((code, out), (1, b""))
                        self.assertEqual(err, ("release: %s: holds an integer of more than 4300 digits\n" % rel).encode())
                        self.assertEqual(snapshot(self.work), before)

    def test_json_non_finite_numbers_refused(self):  # R2-U1 (F-20261128-qmay): as gates/lib/plugin.py refuses them
        for rel in (PLUGIN, MARKET):
            for where in ("top level", "nested", "array element"):
                for literal in ("NaN", "Infinity", "-Infinity", "1e400", "-1e400"):
                    with self.subTest(rel=rel, where=where, literal=literal):
                        text = self.with_literal(rel, where, literal)
                        self.assertIn(literal, text)
                        repo = self.fresh(texts={rel: text})
                        self.refused("0.1.0", "--date", DATE, repo=repo, exact="%s: holds a non-finite number" % rel)

    def test_json_finite_numbers_accepted(self):  # R2-U1 invariant: a float that is finite is still accepted
        for literal in ("1.5", "-1.5", "1e308", "-1e308", "1e-400", "0.0", "1E2"):
            for rel in (PLUGIN, MARKET):
                with self.subTest(rel=rel, literal=literal):
                    text = self.with_literal(rel, "top level", literal)
                    repo = self.fresh(texts={rel: text})
                    code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(get(repo, rel), text.encode("utf-8").replace(
                        b'"version": "0.0.0"', b'"version": "0.1.0"'))

    def test_json_pattern_nowhere_refused(self):  # S4
        for rel, base in ((PLUGIN, PLUGIN_JSON), (MARKET, MARKET_JSON)):
            for variant in ('"version":"%s"', '"version" : "%s"', '"version":  "%s"'):
                with self.subTest(rel=rel, variant=variant):
                    repo = self.fresh(texts={rel: (base % "0.0.0").replace('"version": "0.0.0"', variant % "0.0.0")})
                    self.refused("0.1.0", repo=repo,
                                 exact='%s: the text "version": "0.0.0" matches 0 times, not exactly once' % rel)

    def test_json_without_a_version_refused(self):  # S4
        repo = self.fresh(texts={PLUGIN: (PLUGIN_JSON % "0.0.0").replace('  "version": "0.0.0",\n', "")})
        self.refused("0.1.0", repo=repo, exact=".claude-plugin/plugin.json: version is missing or not a string")

    def test_json_wrong_shapes_refused(self):  # S4
        top, mk = ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"
        one = "needs exactly one plugins entry named strict-delivery, found "
        cases = [(PLUGIN, "[]\n", top + ": the top level must be an object"),
                 (PLUGIN, "{not json}\n", top + ": is not valid JSON"),
                 (PLUGIN, '{"version": 1}\n', top + ": version is missing or not a string"),
                 (PLUGIN, '{"version": "0.0"}\n', top + ": version '0.0' is not of the form MAJOR.MINOR.PATCH"),
                 (MARKET, '{"plugins": {}}\n', mk + ": plugins must be a list"),
                 (MARKET, '{"plugins": []}\n', mk + ": " + one + "0"),
                 (MARKET, '{"plugins": [{"name": "other", "version": "0.0.0"}]}\n', mk + ": " + one + "0"),
                 (MARKET, '{"plugins": [{"name": "strict-delivery", "version": "0.0.0"}, {"name": "strict-delivery", '
                          '"version": "0.0.0"}]}\n', mk + ": " + one + "2")]
        for rel, text, reason in cases:
            with self.subTest(rel=rel, text=text):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo, exact=reason)

    def test_json_deeply_nested_refused(self):  # S4 invariant of the parse: RecursionError is a refusal, not a crash
        for rel in (PLUGIN, MARKET):
            with self.subTest(rel=rel):
                repo = self.fresh(texts={rel: '{"a": ' * 20000 + "1" + "}" * 20000 + "\n"})
                err = self.refused("0.1.0", repo=repo)
                self.assertEqual(err, "release: %s: is not valid JSON\n" % rel)

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
        self.refused("0.1.0", repo=repo,
                     exact=".claude-plugin/plugin.json: the version text is not that of the strict-delivery object")

    def test_missing_site_refused(self):  # S5
        for rel in SITES + [CHANGELOG]:
            with self.subTest(rel=rel):
                repo = self.fresh()
                git(repo, "rm", "-q", "--", rel)
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, exact="%s: is missing" % rel)

    def test_changelog_missing_refused(self):  # C1
        repo = self.fresh(changelog=None)
        self.refused("0.1.0", repo=repo, exact="CHANGELOG.md: is missing")

    def test_missing_block_refused(self):  # S6
        for rel, text in ((CLAUDE, CLAUDE_HEAD), (IGNORE, IGNORE_HEAD)):
            with self.subTest(rel=rel):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo,
                             exact="%s: holds no strict-delivery managed block; run /strict-delivery:init" % rel)

    def test_malformed_or_foreign_block_refused(self):  # S6, R2-F5 (F-20261128-er8d): each member's whole reason
        for rel, text, reason in (
                (CLAUDE, claude_text("0.0.0").replace("<!-- strict-delivery:end -->\n", ""),
                 "CLAUDE.md: block: no end marker"),
                (IGNORE, ignore_text("0.0.0") + ignore_text("0.0.0"), ".gitignore: block: more than one begin marker"),
                (CLAUDE, claude_text("0.0.0").replace("claude-block/1", "gitignore-block/1"),
                 "CLAUDE.md: its block is gitignore-block, not claude-block; run /strict-delivery:upgrade"),
                (CLAUDE, claude_text("0.0.0").replace("\n", "\r\n"), "CLAUDE.md: block: begin marker malformed: line 5")):
            with self.subTest(rel=rel, reason=reason):
                repo = self.fresh(texts={rel: text})
                self.refused("0.1.0", repo=repo, exact=reason)

    def test_config_version_line_must_be_exact(self):  # S2
        for text in ('schema: config/2\nframework_version: "0.0.0" # pinned\nprofile: strict\n',
                     "schema: config/2\nframework_version: 0.0.0\nprofile: strict\n",
                     "schema: config/2\nframework_version: '0.0.0'\nprofile: strict\n",
                     'schema: config/2\nframework_version: "0.0.0"\nframework_version: "0.0.0"\nprofile: strict\n',
                     'schema: config/2\nprofile: strict\n', 'schema: config/2\nframework_version: ""\nprofile: strict\n'):
            with self.subTest(text=text):
                repo = self.fresh(texts={CONFIG: text})
                self.refused("0.1.0", repo=repo, want=(CONFIG,))

    def test_config_version_refusal_reasons(self):  # F1 (F-20261126-3pka): the exact reason of each member
        exact = 'framework_version line is not of the exact form framework_version: "<version>"'
        # (label, config text, reason as printed today; who gives it: the script's _config_old, or its _agree)
        members = (
            ("duplicate lines (the script's check)",
             'schema: config/2\nframework_version: "0.0.0"\nframework_version: "0.0.0"\nprofile: strict\n',
             ".strict-delivery/config.yml: needs exactly one framework_version line, found 2"),
            ("trailing comment (the script's check)",
             'schema: config/2\nframework_version: "0.0.0" # pinned\nprofile: strict\n',
             ".strict-delivery/config.yml: the " + exact),
            ("unquoted (the script's check)", "schema: config/2\nframework_version: 0.0.0\nprofile: strict\n",
             ".strict-delivery/config.yml: the " + exact),
            ("single-quoted (the script's check)", "schema: config/2\nframework_version: '0.0.0'\nprofile: strict\n",
             ".strict-delivery/config.yml: the " + exact),
            ("missing line (the script's check)", "schema: config/2\nprofile: strict\n",
             ".strict-delivery/config.yml: needs exactly one framework_version line, found 0"),
            ("empty value (the script's _agree: the quoted empty text is a version that differs)",
             'schema: config/2\nframework_version: ""\nprofile: strict\n',
             "the sites disagree on the current version (most hold 0.0.0): .strict-delivery/config.yml holds "))
        for label, text, reason in members:
            with self.subTest(member=label):
                repo = self.fresh(texts={CONFIG: text})
                err = self.refused("0.1.0", "--date", DATE, repo=repo)
                self.assertEqual(err, "release: " + reason + "\n")

    def test_invalid_config_refused(self):
        repo = self.fresh(texts={CONFIG: CONFIG_YML % "0.0.0" + "unknown_key: 1\n"})
        self.refused("0.1.0", repo=repo, exact=".strict-delivery/config.yml: unknown key 'unknown_key'")

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
        self.refused("0.1.0", repo=repo, exact="CHANGELOG.md: has no '## Unreleased' heading")

    def test_empty_unreleased_refused(self):  # C3
        for text in ("# Changelog\n\n## Unreleased\n\n## 0.0.0 - 2026-01-01\n\n- first\n",
                     "# Changelog\n\n## Unreleased\n## 0.0.0\n- first\n",
                     "# Changelog\n\n## Unreleased\n", "# Changelog\n\n## Unreleased", "# Changelog\n\n## Unreleased\n\n\n  \n",
                     "# Changelog\n\n## Unreleased\n\n# Other\n\n- x\n"):
            with self.subTest(text=text):
                repo = self.fresh(changelog=text)
                self.refused("0.1.0", repo=repo, exact="CHANGELOG.md: the section under '## Unreleased' is empty")

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
        self.refused("0.1.0", repo=repo, exact="CHANGELOG.md: has 2 '## Unreleased' headings, not one")

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
                        self.refused("0.1.0", repo=repo, exact="CHANGELOG.md: line %d, %s, is not exactly '## Unreleased'"
                                     % (number, "'" + line.replace("\t", "\\t") + "'"))

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
                self.refused("0.1.0", repo=repo,
                             exact="CHANGELOG.md: holds a carriage return (CR); only LF line ends are read")

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
                paths = {"untracked": "stray.txt", "modified": "README.md", "staged": "new.txt", "deleted": "README.md",
                         "nested": "deep/er/stray.txt"}  # typed by hand: what git lists for each member
                self.refused("0.1.0", "--date", DATE, repo=repo, exact="the tree is not clean: " + paths[name])

    def test_dirty_site_file_refused(self):  # T2
        put(self.repo, PLUGIN, PLUGIN_JSON % "0.0.0" + "\n")
        self.refused("0.1.0", repo=self.repo, exact="the tree is not clean: .claude-plugin/plugin.json")

    def test_on_base_branch_refused(self):  # T3
        git(self.repo, "checkout", "-q", "main")
        self.refused("0.1.0", repo=self.repo,
                     exact="the current branch 'main' is the base branch 'main'; check out a release branch")

    def test_non_default_base_branch(self):  # T3
        repo = self.fresh(base="develop", branch="develop")
        self.refused("0.1.0", repo=repo, exact="the current branch 'develop' is the base branch 'develop'; "
                     "check out a release branch")
        repo = self.fresh(base="develop", branch="main")
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))
        repo = self.fresh(base="develop", branch="release-test")
        self.assertEqual(self.run_release("0.1.0", "--date", DATE, root=repo)[0], 0)

    def test_detached_refused(self):  # T4
        git(self.repo, "checkout", "-q", "--detach")
        self.refused("0.1.0", repo=self.repo, exact="HEAD is detached; check out a release branch")

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
        self.assertEqual(out, printout("0.0.0", "0.1.0", "release-test", "main"))
        # F6 (HM2): a version other than 0.1.0 prints its own tag and push lines
        code, out, err = self.run_release("0.2.0", "--date", DATE, root=self.fresh())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, printout("0.0.0", "0.2.0", "release-test", "main"))
        self.assertIn("git commit -m 'release: v0.2.0'\n", out)
        self.assertIn("git tag -a v0.2.0 -m 'strict-delivery 0.2.0' <merge commit>\n", out)
        self.assertIn("git push origin v0.2.0\n", out)
        self.assertNotIn("v0.1.0", out)

    def test_branch_names_printable_ascii_refused(self):  # F5 (F-20261126-n924): refused before any write
        shown = "holds a character outside printable ASCII (U+0020-U+007E)"
        members = (("non-ASCII branch", {"branch": "rél"}, "the current branch 'r\\xe9l' " + shown),
                   ("non-ASCII base_branch", {"base": '"café"'}, "base_branch 'caf\\xe9' " + shown),
                   ("control character in base_branch", {"base": '"a\\tb"'}, "base_branch 'a\\tb' " + shown),
                   ("control character (newline) in base_branch", {"base": '"a\\nb"'}, "base_branch 'a\\nb' " + shown))
        for label, kw, reason in members:
            for encoding in ("ascii", "utf-8"):
                with self.subTest(member=label, PYTHONIOENCODING=encoding):
                    repo = self.fresh(**kw)
                    before = snapshot(self.work)
                    head = git(repo, "rev-parse", "HEAD")
                    code, out, err = run_child(["0.1.0", "--date", DATE, "--root", repo], self.work,
                                               {"PYTHONIOENCODING": encoding})
                    self.assertEqual((code, out), (1, b""))
                    self.assertEqual(err, ("release: " + reason + "\n").encode("ascii"))
                    self.assertEqual(snapshot(self.work), before)
                    self.assertEqual(git(repo, "rev-parse", "HEAD"), head)

    def test_branch_names_printable_ascii_refused_in_process(self):  # F5: the same verdict through release.main
        for kw in ({"branch": "rél"}, {"base": '"café"'}, {"base": '"a\\tb"'}):
            with self.subTest(kw=kw):
                repo = self.fresh(**kw)
                err = self.refused("0.1.0", "--date", DATE, repo=repo, want=("printable ASCII",))
                err.encode("ascii")  # the reason is ASCII even though the name is not (whole text: the child test)

    def test_branch_names_printable_ascii_success_under_ascii_stdout(self):  # F5: the full printout, whatever the stdout
        for encoding in ("ascii", "utf-8"):
            with self.subTest(PYTHONIOENCODING=encoding):
                repo = self.fresh(branch="feature/rel-0.1_x", base='"develop"')
                code, out, err = run_child(["0.1.0", "--date", DATE, "--root", repo], self.work,
                                           {"PYTHONIOENCODING": encoding})
                self.assertEqual((code, err), (0, b""))
                self.assertEqual(out.decode("ascii"), printout("0.0.0", "0.1.0", "feature/rel-0.1_x", "develop"))

    def test_refusal_order_after_base(self):  # R2-F6 (F-20261128-5m9s): the order of _run's refusals after `base`
        # a dirty tree, or branch == base, is named before the printable-ASCII refusal of a branch name; the reason is the
        # one each refusal gave before the ASCII check existed (typed by hand)
        dirty = "the tree is not clean: stray.txt"
        members = (
            ("dirty tree, non-ASCII branch", {"branch": "rél"}, True, dirty),
            ("dirty tree, non-ASCII base_branch", {"base": '"café"'}, True, dirty),
            ("branch == base, non-ASCII name", {"base": '"café"', "branch": "café"}, False,
             "the current branch 'caf\\xe9' is the base branch 'caf\\xe9'; check out a release branch"))
        for label, kw, make_dirty, reason in members:
            with self.subTest(member=label):
                repo = self.fresh(**kw)
                if make_dirty:
                    put(repo, "stray.txt", "x\n")
                self.refused("0.1.0", "--date", DATE, repo=repo, exact=reason)

    def test_branch_names_printable_ascii_bounds_accepted(self):  # F5 invariant: U+0020 and U+007E are printable
        repo = self.fresh(branch="release-test", base='"a ~b"')
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
        self.assertEqual((code, err), (0, ""))


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
                    self.refused("0.1.0", "--date", DATE, repo=repo, exact="%s: is a symbolic link" % rel)

    def test_dangling_symlink_site_refused(self):  # H1
        git(self.repo, "rm", "-q", "--", CONFIG)
        os.makedirs(os.path.join(self.repo, ".strict-delivery"), exist_ok=True)
        os.symlink(os.path.join(self.work, "nowhere"), os.path.join(self.repo, *CONFIG.split("/")))
        self.commit()
        self.refused("0.1.0", exact=".strict-delivery/config.yml: is a symbolic link")

    def test_directory_site_refused(self):  # H2
        for rel in self.targets():
            with self.subTest(rel=rel):
                repo = self.fresh()
                git(repo, "rm", "-q", "--", rel)
                put(repo, rel + "/inner.txt", "x\n")
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, exact="%s: is a directory" % rel)

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
                first = ".claude-plugin/plugin.json" if parent == ".claude-plugin" else ".strict-delivery/config.yml"
                self.refused("0.1.0", "--date", DATE, repo=repo,
                             exact="%s: a parent is a symbolic link or not a directory" % first)

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
        self.refused("0.1.0", root=sub, exact="--root must be the repository top level")
        self.refused("0.1.0", root=os.path.join(sub, "file.txt"), want=("--root",))
        self.refused("0.1.0", root=os.path.join(self.repo, "missing"), want=("--root",))

    def test_root_symlink_to_the_top_level_accepted(self):  # H5
        link = os.path.join(self.work, "link")
        os.symlink(self.repo, link)
        code, _o, err = self.run_release("0.1.0", "--date", DATE, root=link)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(site_version(self.repo, release.RELEASE_SITES[0]), "0.1.0")

    def test_toplevel_not_utf8_refused(self):  # R2-F1 (F-20261128-k733) G1r: a toplevel with byte 0xff, on any file system
        real = gitinfo._run

        def fake(root, name, args, *a, **kw):
            if args == ["rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(args, 0, b"/x/r\xff\n", b"")
            return real(root, name, args, *a, **kw)
        before = snapshot(self.work)
        with mock.patch.object(gitinfo, "_run", fake):
            code, out, err = self.run_release("0.1.0", "--date", DATE)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "release: --root: git rev-parse --show-toplevel gave output that is not valid UTF-8\n")
        self.assertEqual(snapshot(self.work), before)

    def test_non_utf8_refused(self):  # H6
        for rel in self.targets():
            with self.subTest(rel=rel):
                repo = self.fresh()
                put(repo, rel, get(repo, rel) + b"\xff\xfe broken\n")
                self.commit(repo)
                self.refused("0.1.0", "--date", DATE, repo=repo, exact="%s: is not valid UTF-8" % rel)

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

    @staticmethod
    def g1_pairs(excludes):
        """The config pairs G1 sets. No test starts git's built-in file-system monitor daemon (owner direction
        2026-11-22, main PR #34, guard ``test_no_test_file_starts_the_daemon`` of tests/test_githooks.py): the
        ``core.fsmonitor`` pair carries a false value only; a true value, in any form (-c, GIT_CONFIG_COUNT, a config
        file), would make any plain git call of this test start the daemon, which has hung the shard. The script's own
        git calls pass ``-c core.fsmonitor=false`` (gitinfo.FSMONITOR_OFF)."""
        return [("status.showUntrackedFiles", "no"), ("status.showUntrackedFiles", "normal"),
                ("core.excludesFile", excludes), ("core.fsmonitor", "false"), ("status.relativePaths", "false"),
                ("core.quotePath", "false"), ("color.status", "always"), ("diff.ignoreSubmodules", "all"),
                ("core.untrackedCache", "true"), ("status.renames", "copies"), ("status.short", "true")]

    def test_generated_git_environments_agree(self):  # G1, F7: every git and release call is bounded
        rng = random.Random(20261126)
        decoy = os.path.join(self.work, "decoy")
        os.makedirs(decoy)
        bounded("G1 git init", lambda: git(decoy, "init", "-q", "-b", "main"))
        excludes = os.path.join(self.tmp, "excludes")
        with open(excludes, "w", encoding="utf-8") as fh:
            fh.write("stray.txt\n")
        variants = {}
        for name in ("clean", "dirty", "base"):
            repo = bounded("G1 fixture " + name, self.fresh)
            if name == "dirty":
                put(repo, "stray.txt", "x\n")
            if name == "base":
                bounded("G1 git checkout", lambda: git(repo, "checkout", "-q", "main"))
            variants[name] = repo
        expected = {}
        for name, repo in variants.items():
            self.guard(repo)
            code, _o, err = bounded("G1 release run " + name,
                                    lambda: self.call(["0.1.0", "--date", DATE, "--root", repo]))
            expected[name] = (code, err)
            if code == 0:
                bounded("G1 git reset", lambda: git(repo, "reset", "-q", "--hard"))
        self.assertEqual(expected["clean"], (0, ""))
        self.assertEqual(expected["dirty"][0], 1)
        self.assertEqual(expected["base"][0], 1)
        pairs = self.g1_pairs(excludes)
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
                code, _o, err = bounded("G1 release run (case %d, %s)" % (i, name),
                                        lambda: self.call(["0.1.0", "--date", DATE, "--root", repo]))
                if name == "dirty":
                    # git's own answer, with the case's config and without the names gitinfo clears: is the untracked
                    # file ignored by the user's rules (a finding: gitinfo.dirty_paths then calls the tree clean)?
                    probe = dict((k, v) for k, v in os.environ.items() if k not in gitinfo.CLEARED_ENV)
                    try:
                        hidden = subprocess.run(["git", "-C", repo, "check-ignore", "-q", "--", "stray.txt"], env=probe,
                                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL, timeout=CHILD_SECS).returncode == 0
                    except subprocess.TimeoutExpired:
                        raise AssertionError("G1 git check-ignore (case %d) did not finish within %d s" % (i, CHILD_SECS)) from None
            if code == 0:
                bounded("G1 git reset (case %d)" % i, lambda: git(repo, "reset", "-q", "--hard"))
            if hidden:
                hidden_cases.append((i, code))
            elif (code, err) != expected[name]:
                differing.append((i, name, sorted(env), code, err))
        self.assertEqual(differing, [])
        # Finding (reported, not fixed here): when the user's ignore rules (core.excludesFile) hide the untracked
        # file, gitinfo.dirty_paths lists nothing and the script, like every gate that asks it, calls the tree clean.
        self.assertGreater(len(hidden_cases), 0)
        self.assertEqual([c for _i, c in hidden_cases if c != 0], [])

    def test_generated_environments_start_no_fsmonitor_daemon(self):  # F7: G1's pairs never turn the daemon on
        ipc = "fsmonitor--daemon.ipc"
        off = ("false", "no", "off", "0")
        for key, value in self.g1_pairs("/nowhere"):
            if key.lower() == "core.fsmonitor":
                self.assertIn(value, off)  # a true value would start the daemon on the first plain git call
        for form in ("GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL file", "repository config"):
            for value in off:
                with self.subTest(form=form, value=value):
                    repo = bounded("fixture", self.fresh)
                    env = {}
                    if form == "GIT_CONFIG_COUNT":
                        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": value}
                    elif form == "GIT_CONFIG_GLOBAL file":
                        env = {"GIT_CONFIG_GLOBAL": os.path.join(self.tmp, "gitconfig-fsm-" + value)}
                        with open(env["GIT_CONFIG_GLOBAL"], "w", encoding="utf-8") as fh:
                            fh.write("[core]\n\tfsmonitor = " + value + "\n")
                    else:
                        bounded("git config", lambda: git(repo, "config", "core.fsmonitor", value))
                    self.guard(repo)
                    with mock.patch.dict(os.environ, env):
                        code, _o, err = bounded("release run", lambda: self.call(["0.1.0", "--date", DATE, "--root", repo]))
                    self.assertEqual((code, err), (0, ""))
                    self.assertFalse(os.path.exists(os.path.join(repo, ".git", ipc)))


# --------------------------------------------------------------------------- F2: the write side

def expected_new(rel, old):
    """The bytes a target holds after ``0.0.0 -> 0.1.0`` on 2026-12-01, by a hand-written rule."""
    if rel == CHANGELOG:
        return old.replace(b"## Unreleased\n", b"## Unreleased\n\n## 0.1.0 - 2026-12-01\n", 1)
    assert old.count(b"0.0.0") == 1, rel
    return old.replace(b"0.0.0", b"0.1.0")


def outside_of(snap, repo, work):
    """The entries of ``snapshot(work)`` that are not the repository ``repo`` or inside it."""
    name = os.path.relpath(repo, work)
    return dict((k, v) for k, v in snap.items() if k != name and not k.startswith(name + os.sep))


class WriteSideRows(ReleaseCase):
    """F2 (F-20261126-eh2g): the write of every RELEASE_SITES file and CHANGELOG.md, through ``release.main``, with an
    in-process wrapper around ``managed._write`` that changes the state just before the real write."""
    TARGETS = SITES + [CHANGELOG]

    def hooked(self, target, before):
        real = managed._write
        calls = []

        def wrapped(root, rel, text):
            if (rel == target or target is None) and not calls:
                calls.append(rel)
                before(root, rel)
            return real(root, rel, text)
        return calls, mock.patch.object(managed, "_write", wrapped)

    def test_write_side_target_turned_into_a_link_is_replaced_not_followed(self):  # F2: inside and outside the root
        for rel in self.TARGETS:
            for where in ("inside", "outside"):
                with self.subTest(rel=rel, where=where):
                    repo = self.fresh()
                    old = get(repo, rel)
                    dest = os.path.join(repo if where == "inside" else self.work, "link-dest-%d" % self.n)

                    def before(root, r, dest=dest):
                        data = get(root, r)
                        with open(dest, "wb") as fh:
                            fh.write(data)
                        os.unlink(os.path.join(root, *r.split("/")))
                        os.symlink(dest, os.path.join(root, *r.split("/")))
                    calls, patch = self.hooked(rel, before)
                    snap = snapshot(self.work)
                    with patch:
                        code, out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                    self.assertEqual(calls, [rel])  # the wrapper ran: the write went through managed._write
                    self.assertEqual((code, err), (0, ""))
                    self.assertFalse(os.path.islink(os.path.join(repo, *rel.split("/"))))
                    self.assertEqual(get(repo, rel), expected_new(rel, old))
                    self.assertEqual(get(os.path.dirname(dest), os.path.basename(dest)), old)  # no byte through the link
                    if where == "outside":
                        after = snapshot(self.work)
                        self.assertEqual(outside_of(after, repo, self.work),
                                         dict(outside_of(snap, repo, self.work), **{os.path.basename(dest): old}))

    def test_write_side_parent_swapped_for_a_link(self):  # F2: refused, nothing goes through the link
        written = {".claude-plugin": "nothing written",
                   ".strict-delivery": "written before it: .claude-plugin/plugin.json, .claude-plugin/marketplace.json, "
                                       "CLAUDE.md, .gitignore"}
        first = {".claude-plugin": PLUGIN, ".strict-delivery": CONFIG}
        for parent in (".claude-plugin", ".strict-delivery"):
            for where in ("inside", "outside"):
                with self.subTest(parent=parent, where=where):
                    repo = self.fresh()
                    dest = os.path.join(repo if where == "inside" else self.work, "moved-%d" % self.n)
                    kept = dict((n, get(repo, parent + "/" + n)) for n in os.listdir(os.path.join(repo, parent)))

                    def before(root, r, parent=parent, dest=dest):
                        os.rename(os.path.join(root, parent), dest)
                        os.symlink(dest, os.path.join(root, parent))
                    calls, patch = self.hooked(first[parent], before)
                    with patch:
                        code, out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                    self.assertEqual(calls, [first[parent]])
                    self.assertEqual((code, out), (1, ""))
                    self.assertEqual(err, "release: %s: a parent is a symbolic link or not a directory; %s\n"
                                     % (first[parent], written[parent]))
                    self.assertTrue(os.path.islink(os.path.join(repo, parent)))
                    self.assertEqual(dict((n, get(dest, n)) for n in os.listdir(dest)), kept)  # the link target kept

    def test_write_side_failed_replace_keeps_the_old_file(self):  # F2: atomic: the old file intact, no temporary left
        for i, rel in enumerate(self.TARGETS):
            with self.subTest(rel=rel):
                repo = self.fresh()
                old = dict((t, get(repo, t)) for t in self.TARGETS)
                real = os.replace

                def failing(src, dst, *a, **kw):
                    if dst == os.path.basename(rel) and kw.get("dst_dir_fd") is not None:
                        raise OSError(errno.EIO, os.strerror(errno.EIO))
                    return real(src, dst, *a, **kw)
                with mock.patch.object(os, "replace", failing):
                    code, out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                tail = "written before it: " + ", ".join(self.TARGETS[:i]) if i else "nothing written"
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err, "release: %s: cannot be written (Input/output error); %s\n" % (rel, tail))
                self.assertEqual(get(repo, rel), old[rel])
                self.assertEqual([k for k in snapshot(self.work) if ".sd-managed-" in k], [])  # no temporary file
                for j, t in enumerate(self.TARGETS):
                    self.assertEqual(get(repo, t), expected_new(t, old[t]) if j < i else old[t], t)

    def test_root_swapped_before_a_later_write_refused(self):  # R2-F3 (F-20261128-wvga) G3r: before each write, not only the first
        for state in ("symlink-dir-out", "symlink-top", "absent", "regular"):
            with self.subTest(state=state):
                repo = self.fresh()
                out_dir = os.path.join(self.work, "outside-%d" % self.n)
                os.mkdir(out_dir)
                put(out_dir, "sentinel", "outside the root\n")
                outside = snapshot(out_dir)
                old = dict((t, get(repo, t)) for t in self.TARGETS)
                hold = os.path.join(self.work, "moved-%d" % self.n)
                real, reads = release._read, {}

                def swapping(root, rel):
                    text = real(root, rel)
                    reads[rel] = reads.get(rel, 0) + 1
                    if rel == MARKET and reads[rel] == 3:  # the read just before the write of the second site
                        os.rename(root, hold)
                        if state == "symlink-dir-out":
                            os.symlink(out_dir, root)
                        elif state == "symlink-top":
                            os.symlink(hold, root)
                        elif state == "regular":
                            put(os.path.dirname(root), os.path.basename(root), "a file\n")
                    return text
                with mock.patch.object(release, "_read", swapping):
                    code, out, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err, "release: --root: %s changed during the run; written before it: %s\n"
                                 % (repo, PLUGIN))
                self.assertEqual(snapshot(out_dir), outside)  # no byte outside the root
                self.assertEqual(get(hold, PLUGIN), expected_new(PLUGIN, old[PLUGIN]))  # written before the swap
                for rel in self.TARGETS[1:]:
                    self.assertEqual(get(hold, rel), old[rel], rel)  # the rest untouched

    def test_unchanged_root_is_written(self):  # R2-F3 invariant: an unchanged root, or a link to the top level, writes
        for via_link in (False, True):
            with self.subTest(via_link=via_link):
                repo = self.fresh()
                root = repo
                if via_link:
                    root = os.path.join(self.work, "rootlink-%d" % self.n)
                    os.symlink(repo, root)
                old = dict((t, get(repo, t)) for t in self.TARGETS)
                code, _o, err = self.run_release("0.1.0", "--date", DATE, root=root)
                self.assertEqual((code, err), (0, ""))
                for rel in self.TARGETS:
                    self.assertEqual(get(repo, rel), expected_new(rel, old[rel]), rel)

    def test_write_side_mode_kept(self):  # F2: 0644, 0600, 0755 (and a mix) survive the write
        for label, modes in (("0644", [0o644] * 6), ("0600", [0o600] * 6), ("0755", [0o755] * 6),
                             ("mixed", [0o644, 0o600, 0o755, 0o640, 0o700, 0o664])):
            with self.subTest(modes=label):
                repo = self.fresh()
                for rel, mode in zip(self.TARGETS, modes):
                    os.chmod(os.path.join(repo, *rel.split("/")), mode)
                self.commit(repo)
                code, _o, err = self.run_release("0.1.0", "--date", DATE, root=repo)
                self.assertEqual((code, err), (0, ""))
                for rel, mode in zip(self.TARGETS, modes):
                    self.assertEqual(stat.S_IMODE(os.lstat(os.path.join(repo, *rel.split("/"))).st_mode), mode, rel)
                    self.assertEqual(get(repo, rel).count(b"0.1.0"), 1, rel)


# --------------------------------------------------------------------------- PM: the generated path matrix
# (owner 2026-11-26 21:10, stream-common :69). Path role x file state x moment; the cells are listed by ``pm_cells``,
# the exit code of each is typed by hand in ``pm_expected`` (None: the rule settles no verdict, reported as a decision).

PM_FILES = SITES + [CHANGELOG]
PM_PARENTS = (".claude-plugin", ".strict-delivery")
PM_FILE_STATES = ("regular", "absent", "directory", "symlink-in", "symlink-out", "fifo")
PM_PARENT_STATES = ("directory", "absent", "regular", "symlink-dir-in", "symlink-dir-out", "symlink-file-in",
                    "symlink-file-out", "fifo")
PM_ROOT_STATES = ("directory", "absent", "regular", "symlink-top", "symlink-dir-out", "symlink-file", "fifo",
                  "name-0xff")


def pm_cells():
    """Every (role, name, state, moment) cell: the six files, the two parents and the root, each state, each moment."""
    out = []
    for moment in ("check", "between"):
        for rel in PM_FILES:
            out += [("file", rel, st, moment) for st in PM_FILE_STATES]
        for parent in PM_PARENTS:
            out += [("parent", parent, st, moment) for st in PM_PARENT_STATES]
        out += [("root", "", st, moment) for st in PM_ROOT_STATES if not (st == "name-0xff" and moment == "between")]
    return out


def pm_expected(role, name, state, moment):
    """The exit code of a cell, typed by hand from the table rows H1-H5 (at the check) and decision 7 of the build report
    (between check and use: the run refuses or reports naming the path; a file replaced at the write is replaced, not
    followed). None: no verdict is settled by the rule."""
    if moment == "check":
        if role == "file":
            return 0 if state == "regular" else 1
        if role == "parent":
            return 0 if state == "directory" else 1
        # name-0xff: the script refuses a toplevel that git prints with a byte that is not UTF-8 (R2-F1, strict decode)
        return 0 if state in ("directory", "symlink-top") else 1
    if role == "file":
        return 1 if state == "directory" else 0  # os.replace of a file over a directory fails; over a link, FIFO or nothing it works
    if role == "parent":
        if state == "directory":
            return 0
        if state == "absent":
            return 1 if name == ".claude-plugin" else 0  # the second file of .claude-plugin finds it missing
        return 1
    # root: swapped after the last comparison, before a write: any change of identity is refused (R2-F3); only the
    # unchanged directory is accepted. A root swapped for a link to the moved repository (symlink-top) is refused too.
    return 0 if state == "directory" else 1


class PathMatrix(ReleaseCase):
    seq = 0

    def place(self, path, state, files):
        """Make ``path`` (nothing there now) the ``state``; ``files`` is {name: bytes} of the directory that was there, or
        {"": bytes} of the file. Returns {path: bytes} of every file a link now leads to (they must stay as they are)."""
        guards = {}
        PathMatrix.seq += 1
        home = self.cell_repo if state.endswith("-in") else self.cell_out
        dest = os.path.join(home, "dest-%d" % PathMatrix.seq)
        if state == "absent":
            pass
        elif state == "regular":
            with open(path, "wb") as fh:
                fh.write(b"not what was here\n")
        elif state == "directory":
            os.mkdir(path)
            with open(os.path.join(path, "inner.txt"), "wb") as fh:
                fh.write(b"x\n")
        elif state in ("symlink-in", "symlink-out", "symlink-file-in", "symlink-file-out"):
            data = files.get("", b"a file\n")
            with open(dest, "wb") as fh:
                fh.write(data)
            guards[dest] = data
            os.symlink(dest, path)
        elif state in ("symlink-dir-in", "symlink-dir-out"):
            os.mkdir(dest)
            for name, data in files.items():
                with open(os.path.join(dest, name), "wb") as fh:
                    fh.write(data)
                guards[os.path.join(dest, name)] = data
            os.symlink(dest, path)
        elif state == "fifo":
            os.mkfifo(path)
        else:
            raise AssertionError(state)
        return guards

    def cell(self, role, name, state, moment):
        """Run one cell; returns the notes the report lists (``untestable`` or ``observed``)."""
        repo = self.fresh()
        out_dir = os.path.join(self.work, "outside-%d" % self.n)
        os.mkdir(out_dir)
        with open(os.path.join(out_dir, "sentinel"), "wb") as fh:
            fh.write(b"outside the root\n")
        self.cell_repo, self.cell_out = repo, out_dir
        old = dict((t, get(repo, t)) for t in PM_FILES)
        guards, ctx = {}, {"final": repo, "calls": []}
        root_arg, note = repo, None
        want_token = {"file": name, "parent": name, "root": "--root"}[role]
        if moment == "between":
            want_token = name if role != "root" else "--root"
        normal = state == {"file": "regular", "parent": "directory", "root": "directory"}[role]  # nothing to change
        if moment == "check" and not normal:
            if role == "file":
                git(repo, "rm", "-q", "--", name)
                os.makedirs(os.path.dirname(os.path.join(repo, *name.split("/"))), exist_ok=True)  # git rm drops an empty parent
                guards.update(self.place(os.path.join(repo, *name.split("/")), state, {"": old[name]}))
            elif role == "parent":
                kept = dict((n, get(repo, name + "/" + n)) for n in os.listdir(os.path.join(repo, name)))
                git(repo, "rm", "-q", "-r", "--", name)
                guards.update(self.place(os.path.join(repo, name), state, kept))
            else:
                stray = os.path.join(self.work, "stray-%d" % self.n)
                if state == "absent":
                    root_arg = os.path.join(self.work, "nope-%d" % self.n)
                elif state in ("regular", "symlink-file", "fifo"):
                    guards.update(self.place(stray, "regular" if state != "fifo" else "fifo", {}))
                    root_arg = stray
                    if state == "symlink-file":
                        root_arg = os.path.join(self.work, "rootlink-%d" % self.n)
                        os.symlink(stray, root_arg)
                elif state == "symlink-top":
                    root_arg = os.path.join(self.work, "rootlink-%d" % self.n)
                    os.symlink(repo, root_arg)
                elif state == "symlink-dir-out":
                    root_arg = os.path.join(self.work, "rootlink-%d" % self.n)
                    os.symlink(out_dir, root_arg)
                elif state == "name-0xff":
                    root_arg = os.path.join(self.work, "r\udcff")  # the byte 0xff, as os.fsdecode spells it
                    try:
                        build(root_arg)
                        ctx["final"] = root_arg
                    except OSError as e:
                        if e.errno != errno.EILSEQ:
                            raise
                        note = "untestable: this file system refuses the name (EILSEQ); the refused-absent variant ran"
                else:
                    raise AssertionError(state)
            if role != "root" and state != "fifo":
                self.commit(repo)
        want = pm_expected(role, name, state, moment)
        if moment == "between" and not normal:
            hold = os.path.join(self.work, "moved-%d" % self.n)

            def before(root, rel):
                if role == "file":
                    path = os.path.join(root, *name.split("/"))
                    data = get(root, name)
                    os.unlink(path)
                    guards.update(self.place(path, state, {"": data}))
                elif role == "parent":
                    kept = dict((n, get(root, name + "/" + n)) for n in os.listdir(os.path.join(root, name)))
                    os.rename(os.path.join(root, name), hold)
                    guards.update(self.place(os.path.join(root, name), state, kept))
                else:
                    os.rename(root, hold)
                    if state == "symlink-top":
                        os.symlink(hold, root)
                        ctx["final"] = hold
                    elif state == "symlink-dir-out":
                        os.symlink(out_dir, root)
                    elif state == "symlink-file":
                        guards.update(self.place(hold + "-file", "regular", {}))
                        os.symlink(hold + "-file", root)
                    else:
                        guards.update(self.place(root, state, {}))
                ctx["calls"].append(rel)
                ctx["out"] = snapshot(out_dir)
            if role == "root":
                # R2-F3: the root is swapped after the last comparison read of the first file and before the write (the
                # read just before the write of the first site, as test_swap_during_the_writes_reported counts it)
                real_read, reads = release._read, {}

                def swapping(root, rel):
                    text = real_read(root, rel)
                    reads[rel] = reads.get(rel, 0) + 1
                    if rel == PLUGIN and reads[rel] == 3:
                        before(root, rel)
                    return text
                patch = mock.patch.object(release, "_read", swapping)
            else:
                real = managed._write

                def wrapped(root, rel, text):
                    hit = (rel == name) if role == "file" else rel.startswith(name + "/")
                    if hit and not ctx["calls"]:
                        before(root, rel)
                    return real(root, rel, text)
                patch = mock.patch.object(managed, "_write", wrapped)
        else:
            patch = contextlib.nullcontext()
        ctx.setdefault("out", snapshot(out_dir))
        snap = snapshot(self.work) if moment == "check" else None
        self.guard(root_arg)
        with patch:
            code, out, err = bounded("path matrix cell %r" % ((role, name, state, moment),),
                                     lambda: self.call(["0.1.0", "--date", DATE, "--root", root_arg]), 60)
        if moment == "between" and not normal:
            self.assertEqual(len(ctx["calls"]), 1, "the wrapper ran once, just before the write")
        if want is None:
            self.assertIn(code, (0, 1))
            return "observed exit %d (verdict not settled by the rule)" % code
        self.assertEqual(code, want, err)
        if code == 0:
            self.assertEqual(err, "")
            for rel in PM_FILES:
                path = os.path.join(ctx["final"], *rel.split("/"))
                self.assertTrue(stat.S_ISREG(os.lstat(path).st_mode), rel)
                self.assertEqual(get(ctx["final"], rel), expected_new(rel, old[rel]), rel)
        else:
            self.assertEqual(out, "")
            self.assertIn(want_token, err)
            if role == "root" and moment == "between":  # R2-F3: nothing was written, so the reason says so
                self.assertEqual(err, "release: --root: %s changed during the run; nothing written\n" % root_arg)
            if role == "root" and state == "name-0xff" and ctx["final"] != repo:  # R2-F1: the name could be created
                self.assertEqual(err, "release: --root: git rev-parse --show-toplevel gave output that is not "
                                      "valid UTF-8\n")
            if moment == "check":
                self.assertEqual(snapshot(self.work), snap)
        for dest, data in guards.items():
            self.assertEqual(get(os.path.dirname(dest), os.path.basename(dest)), data, "a byte went through a link")
        self.assertEqual(snapshot(out_dir), ctx["out"], "a byte outside the root changed")
        return note

    def test_generated_path_matrix(self):  # PM: every cell of pm_cells, in the order a fixed seed shuffles them to
        cells = pm_cells()
        self.assertEqual(len(cells), len(set(cells)))
        random.Random(20261128).shuffle(cells)
        notes = {}
        for cell in cells:
            with self.subTest(cell=cell):
                note = self.cell(*cell)
                if note:
                    notes[cell] = note
        # no cell is left open now; the one this file system may not hold (the 0xff name on APFS) is named, never silently passed
        self.assertLessEqual(set(notes), {("root", "", "name-0xff", "check")})


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


E2E_SECS = {"clone": 300, "git": 120, "release": 120, "run_all": 2400, "doctor": 600}  # seconds per E2E call


def e2e_run(label, cmd, cwd, secs):
    """The completed child of ``cmd`` (stdout and stderr together), or a failure naming ``label`` after ``secs``."""
    try:
        return subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=secs)
    except subprocess.TimeoutExpired:
        raise AssertionError("e2e %s did not finish within %d s" % (label, secs)) from None


def e2e_body(tc, source):
    """This checkout cloned into a temporary directory with its working files, the script run, then ``run_all`` and
    ``doctor`` on the result: both exit 0."""
    clone = os.path.join(tc.work, "e2e")
    # mw3y class (round 2): every call is bounded and a hang fails by name: the git calls through ``bounded``, the three
    # subprocess calls (the release run, ``run_all``, ``doctor``) through ``e2e_run``
    bounded("e2e git clone", lambda: git(tc.work, "clone", "-q", source, clone), E2E_SECS["clone"])
    bounded("e2e git config", lambda: git(clone, "config", "user.email", "fixture@example.invalid"), E2E_SECS["git"])
    bounded("e2e git config", lambda: git(clone, "config", "user.name", "Fixture"), E2E_SECS["git"])
    bounded("e2e git config", lambda: git(clone, "config", "commit.gpgsign", "false"), E2E_SECS["git"])
    names = bounded("e2e git ls-files", lambda: git(source, "ls-files", "-z", "--cached", "--others",
                                                    "--exclude-standard"), E2E_SECS["git"]).split("\0")
    for rel in names:
        src = os.path.join(source, rel)
        if rel == "" or not os.path.isfile(src):
            continue
        to = os.path.join(clone, rel)
        os.makedirs(os.path.dirname(to), exist_ok=True)
        with open(src, "rb") as fh, open(to, "wb") as out:
            out.write(fh.read())
    bounded("e2e commit", lambda: commit_all(clone, "working files"), E2E_SECS["git"])
    bounded("e2e git checkout", lambda: git(clone, "checkout", "-q", "-b", "release-e2e"), E2E_SECS["git"])
    run = [sys.executable, os.path.join(clone, "scripts", "release.py"), "0.1.0", "--date", DATE, "--root", clone]
    p = e2e_run("release run", run, clone, E2E_SECS["release"])
    tc.assertEqual(p.returncode, 0, p.stdout)
    for label, cmd in (("run_all", [sys.executable, "-m", "gates", "run_all", "--root", clone]),
                       ("doctor", [sys.executable, "-m", "gates", "doctor", "--root", clone])):
        p = e2e_run(label, cmd, clone, E2E_SECS[label])
        tc.assertEqual(p.returncode, 0, p.stdout)


class EndToEnd(ReleaseCase):
    def test_run_all_and_doctor_agree_after_bump(self):  # E2E (row E2E; decision: dependency skip, reason below)
        e2e_or_skip(self, ROOT, e2e_body)

    def test_e2e_calls_are_bounded(self):  # mw3y class, G8r: the clone, the release run and run_all/doctor carry a time bound
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        funcs = dict((n.name, n) for n in tree.body if isinstance(n, ast.FunctionDef))
        parents = {}
        for node in ast.walk(funcs["e2e_body"]):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def name_of(call):
            f = call.func
            return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""

        def inside_bounded(node):
            while node in parents:
                node = parents[node]
                if isinstance(node, ast.Call) and name_of(node) == "bounded":
                    return True
            return False
        seen = set()
        for node in ast.walk(funcs["e2e_body"]):
            if isinstance(node, ast.Call):
                name = name_of(node)
                seen.add(name)
                self.assertNotEqual(name, "run", "e2e_body calls subprocess.run directly (use e2e_run)")
                if name in ("git", "commit_all"):
                    self.assertTrue(inside_bounded(node), "an unbounded %s call at line %d" % (name, node.lineno))
        self.assertLessEqual({"bounded", "e2e_run"}, seen)
        self.assertEqual(sum(1 for n in ast.walk(funcs["e2e_body"]) if isinstance(n, ast.Call) and name_of(n) == "e2e_run"), 2)
        runs = [n for n in ast.walk(funcs["e2e_run"]) if isinstance(n, ast.Call) and name_of(n) == "run"]
        self.assertEqual(len(runs), 1)
        self.assertIn("timeout", [k.arg for k in runs[0].keywords])
        # the bound fails by name: a child that outlives it fails the test with the label
        with self.assertRaises(AssertionError) as cm:
            e2e_run("probe sleeper", [sys.executable, "-c", "import time; time.sleep(30)"], self.work, 1)
        self.assertEqual(str(cm.exception), "e2e probe sleeper did not finish within 1 s")
        p = e2e_run("probe echo", [sys.executable, "-c", "print('ok')"], self.work, 60)
        self.assertEqual((p.returncode, p.stdout), (0, b"ok\n"))

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
        self.refused("0.1.0", repo=repo, exact="CLAUDE.md: holds no strict-delivery managed block; run /strict-delivery:init")


if __name__ == "__main__":
    unittest.main()
