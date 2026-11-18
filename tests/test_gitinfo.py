"""Tests for the git helpers (gates.lib.gitinfo), on real repositories built with plain git."""
import hashlib
import os
import shutil
import subprocess
import unittest
from unittest import mock

from gates.lib import gitinfo
from gates.lib.result import GateError, GitNotFound
from tests.helpers import (E128, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo,
                           root_forms)

INVALID_UTF8 = b"ok \xff\xfe bad\n"


def git_in(root, args, data):
    """Run git with data on stdin; return stripped stdout."""
    p = subprocess.run(["git", "-C", root] + args, input=data, stdout=subprocess.PIPE, check=True)
    return p.stdout.decode("ascii").strip()


def spy_runs():
    """Patch subprocess.run in gitinfo to record (argv, env) of each call and still run it."""
    calls = []
    real = subprocess.run

    def spy(argv, *a, **kw):
        calls.append((list(argv), dict(kw.get("env") or {})))
        return real(argv, *a, **kw)
    return calls, mock.patch.object(gitinfo.subprocess, "run", spy)


class Fixture(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.files = {
            "a.txt": b"alpha\n",
            "crlf.txt": b"a\r\nb",
            "empty.txt": b"",
            "dir/x.txt": b"x\n",
            "dir/sub/y.txt": b"y\n",
            "bin/run": b"#!/bin/sh\n",
            "sp ace/f g.txt": b"s\n",
            "é/ü.txt": b"u\n",
            "-lead.txt": b"lead\n",
            "co:lon.txt": b"colon\n",
            "nl\nname.txt": b"nl\n",
            "gl*ob/f.txt": b"g\n",
            "glxob/h.txt": b"h\n",
            "bad.bin": INVALID_UTF8,
            ":(top)tm.txt": b"magic\n",
            ":(top)md/f.txt": b"md\n",
        }
        for rel, data in self.files.items():
            p = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(p) or self.root, exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
        os.chmod(os.path.join(self.root, "bin/run"), 0o755)
        os.symlink("a.txt", os.path.join(self.root, "link"))
        os.symlink("../a.txt", os.path.join(self.root, "dir", "lnk"))
        self.sha_a = commit_all(self.root, "files")
        git(self.root, "update-index", "--add", "--cacheinfo",
            "160000,%s,subm" % self.sha_a)
        self.head = commit_all(self.root, "gitlink")
        self.config_sha = git(self.root, "rev-parse", "HEAD~2")


class MakeRepoTest(GitIsolatedTestCase):
    def test_make_repo_branch_is_main(self):  # F5, even with init.defaultBranch=master configured
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "init.defaultBranch",
               "GIT_CONFIG_VALUE_0": "master"}
        with mock.patch.dict(os.environ, env):
            root = make_repo(self.work)
            self.assertEqual(git(root, "symbolic-ref", "HEAD"), "refs/heads/main")
            probe = os.path.join(self.tmp, "probe")
            os.mkdir(probe)
            git(probe, "init", "-q")
            self.assertEqual(git(probe, "symbolic-ref", "HEAD"), "refs/heads/master")

    def test_make_repo_identity_and_email(self):
        root = make_repo(self.work)
        self.assertEqual(git(root, "config", "user.email"), "fixture@example.invalid")
        self.assertEqual(git(root, "log", "-1", "--format=%an <%ae> %aI"),
                         "Fixture Author <author@example.invalid> 2026-01-01T00:00:00Z")


class _Probe(GitIsolatedTestCase):
    def runTest(self):
        pass


class FixtureEnvIsolationTest(GitIsolatedTestCase):
    """F-1a-ver-1: a git variable set in the parent environment before setUp does not reach fixture git."""

    def test_parent_git_env_does_not_reach_fixture_git(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        with open(os.path.join(other, "other.txt"), "w") as fh:
            fh.write("other\n")
        other_head = commit_all(other, "other")
        other_git = os.path.join(other, ".git")
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        hostile = {
            "GIT_DIR": other_git,
            "GIT_WORK_TREE": other,
            "GIT_COMMON_DIR": other_git,
            "GIT_OBJECT_DIRECTORY": empty,
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.join(other_git, "objects"),
            "GIT_NAMESPACE": "zz",
            "GIT_CEILING_DIRECTORIES": self.tmp,
            "GIT_INDEX_FILE": os.path.join(self.tmp, "missing-index"),
        }
        for name, value in hostile.items():
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: value}):
                probe = _Probe()
                probe.setUp()
                try:
                    root = make_repo(probe.work)
                    head = git(root, "rev-parse", "HEAD")
                    dot = os.path.join(root, ".git")
                    with open(os.path.join(dot, "refs", "heads", "main")) as fh:
                        self.assertEqual(fh.read().strip(), head)  # GIT_DIR, GIT_COMMON_DIR
                    self.assertTrue(os.path.isfile(os.path.join(dot, "objects", head[:2], head[2:])))
                    self.assertTrue(os.path.isfile(os.path.join(dot, "index")))  # GIT_INDEX_FILE
                    self.assertEqual(git(root, "ls-files"), ".strict-delivery/config.yml")  # GIT_WORK_TREE
                    self.assertEqual(git(root, "cat-file", "-t", other_head, check=False), "")
                    clone = os.path.join(probe.tmp, "clone")
                    git(probe.tmp, "clone", "-q", "--depth", "1", "--no-local", "--branch", "main",
                        "file://" + root, clone)  # GIT_NAMESPACE
                    self.assertEqual(git(clone, "rev-parse", "HEAD"), head)
                    sub = os.path.join(root, ".strict-delivery")
                    self.assertEqual(git(sub, "rev-parse", "HEAD"), head)
                    self.assertFalse(name in os.environ, name)  # GIT_CEILING_DIRECTORIES: no fixture effect
                finally:
                    probe.doCleanups()
                with open(os.path.join(other_git, "refs", "heads", "main")) as fh:
                    self.assertEqual(fh.read().strip(), other_head)


class RootKindsTest(Fixture):
    def test_repo_and_subdir_work(self):  # G1
        sub = os.path.join(self.root, "dir")
        self.assertEqual(gitinfo.head_sha(self.root), self.head)
        self.assertEqual(gitinfo.toplevel(sub), self.root)  # toplevel is the one function that accepts a subdirectory
        for fn in (gitinfo.head_sha, lambda r: gitinfo.commit_exists(r, self.head)):  # Q-1bfin-2 (a)
            with self.assertRaises(GateError) as e:
                fn(sub)
            self.assertEqual(str(e.exception), TOP)

    def test_path_functions_refuse_non_toplevel_root(self):  # F-1a-fin-1, Q-1a-fin-1
        sub = os.path.join(self.root, "dir")
        for name, fn in (("blob_exists", lambda r: gitinfo.blob_exists(r, self.head, "dir/x.txt")),
                         ("show", lambda r: gitinfo.show(r, "HEAD", "dir/x.txt")),
                         ("ls_tree", lambda r: gitinfo.ls_tree(r, "HEAD", "dir")),
                         ("tracked_files", gitinfo.tracked_files)):
            with self.subTest(fn=name):
                with self.assertRaises(GateError) as e:
                    fn(sub)
                self.assertIn("git rev-parse --show-toplevel", str(e.exception))
                self.assertIn("top level", str(e.exception))
                self.assertNotIn(self.root, str(e.exception))
                fn(self.root)  # the top level itself is accepted

    def test_toplevel_spellings_by_samefile(self):  # Q-1a-rr-1
        self.assertEqual(gitinfo.show(self.root + "/", "HEAD", "dir/x.txt"), "x\n")
        self.assertEqual(gitinfo.show(self.root + "/dir/..", "HEAD", "dir/x.txt"), "x\n")
        swapped = self.root.swapcase()
        if not os.path.exists(swapped) or not os.path.samefile(swapped, self.root):
            self.skipTest("the test filesystem is case-sensitive")
        self.assertEqual(gitinfo.ls_tree(swapped, "HEAD", "dir"), ["dir/x.txt"])

    def test_samefile_oserror_refuses_root(self):  # F-1a-rr2-1
        with mock.patch("gates.lib.gitinfo.os.path.samefile", side_effect=OSError("boom")):
            with self.assertRaises(GateError) as e:
                gitinfo.show(self.root, "HEAD", "dir/x.txt")
        self.assertIn("top level", str(e.exception))

    def test_missing_root_is_gate_error_not_oserror(self):  # Q-1a-rr-1
        missing = os.path.join(self.tmp, "no-such-dir")
        for fn in (lambda: gitinfo.show(missing, "HEAD", "a"), lambda: gitinfo.ls_tree(missing, "HEAD", "a"),
                   lambda: gitinfo.blob_exists(missing, "HEAD", "a"), lambda: gitinfo.tracked_files(missing)):
            with self.assertRaises(GateError):
                fn()

    def test_symlinked_alias_of_toplevel_is_accepted(self):  # Q-1a-fin-1
        alias = os.path.join(self.tmp, "alias")
        os.symlink(self.root, alias)
        self.assertEqual(gitinfo.show(alias, "HEAD", "dir/x.txt"), "x\n")
        self.assertEqual(gitinfo.ls_tree(alias, "HEAD", "dir"), ["dir/x.txt"])
        self.assertTrue(gitinfo.blob_exists(alias, self.head, "dir/x.txt"))
        self.assertEqual(gitinfo.tracked_files(alias), gitinfo.tracked_files(self.root))

    def test_non_normalised_paths_refused_per_function(self):  # F-1a-fin-2, Q-1a-fin-2
        forms = [".", "./a", "a/.", "a//b", "dir/", "/dir", "dir//x.txt", "dir/./x.txt", "..", "dir/../x.txt",
                 "./", "//", "/"]
        for form in forms:
            for name, fn in (("blob_exists", lambda f: gitinfo.blob_exists(self.root, "HEAD", f)),
                             ("show", lambda f: gitinfo.show(self.root, "HEAD", f)),
                             ("ls_tree", lambda f: gitinfo.ls_tree(self.root, "HEAD", f))):
                with self.subTest(fn=name, form=form):
                    with self.assertRaises(GateError) as e:
                        fn(form)
                    self.assertNotIn(self.root, str(e.exception))
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir"), ["dir/x.txt"])  # normalised twin accepted

    def test_plain_missing_and_file_roots_are_gate_errors(self):
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        afile = os.path.join(self.tmp, "afile")
        open(afile, "w").close()
        missing = os.path.join(self.tmp, "missing")
        calls = {
            "head_sha": lambda r: gitinfo.head_sha(r),
            "commit_exists": lambda r: gitinfo.commit_exists(r, "0" * 40),
            "blob_exists": lambda r: gitinfo.blob_exists(r, "0" * 40, "a"),
            "tracked_files": lambda r: gitinfo.tracked_files(r),
            "show": lambda r: gitinfo.show(r, "HEAD", "a"),
            "ls_tree": lambda r: gitinfo.ls_tree(r, "HEAD", "a"),
            "merge_base": lambda r: gitinfo.merge_base(r, "HEAD", "HEAD"),
        }
        for kind, root in (("plain", plain), ("missing", missing), ("file", afile)):
            for name, fn in calls.items():
                with self.subTest(root=kind, fn=name):
                    with self.assertRaises(GateError) as e:
                        fn(root)
                    self.assertIn("git ", str(e.exception))
                    self.assertNotIn(root, str(e.exception))
        for root in (plain, missing, afile):  # user_email too (Q-1bfin-2 (a)): no longer the global email or None
            with self.subTest(root=root, fn="user_email"):
                with self.assertRaises(GateError) as e:
                    gitinfo.user_email(root)
                self.assertEqual(str(e.exception), E128)

    def test_git_not_installed_is_gate_error(self):
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "nowhere")}):
            with self.assertRaises(GateError) as e:
                gitinfo.head_sha(self.root)
        self.assertEqual(str(e.exception), "git not found on PATH; install git")  # owner Q-1a2r-6


class HeadTest(GitIsolatedTestCase):
    def test_no_commits(self):  # G2
        root = os.path.join(self.work, "empty")
        os.mkdir(root)
        git(root, "init", "-q", "-b", "main")
        with self.assertRaises(GateError):
            gitinfo.head_sha(root)
        self.assertFalse(gitinfo.commit_exists(root, "0" * 40))
        self.assertFalse(gitinfo.blob_exists(root, "HEAD", "a"))
        self.assertEqual(gitinfo.tracked_files(root), frozenset())
        with self.assertRaises(GateError):
            gitinfo.show(root, "HEAD", "a")


class CommitExistsTest(Fixture):
    def test_head_and_commit_exists(self):  # G3
        self.assertEqual(gitinfo.head_sha(self.root), git(self.root, "rev-parse", "HEAD"))
        self.assertIs(gitinfo.commit_exists(self.root, gitinfo.head_sha(self.root)), True)
        self.assertIs(gitinfo.commit_exists(self.root, "0" * 40), False)

    def test_ref_forms(self):
        git(self.root, "branch", "feature")
        git(self.root, "tag", "light")
        git(self.root, "tag", "-a", "-m", "annotated", "ann")
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        blob = git(self.root, "rev-parse", "HEAD:a.txt")
        cases = [
            (self.head, True),
            (self.head[:7], True),
            ("main", True), ("feature", True), ("light", True), ("ann", True), ("HEAD", True),
            (tree, False), (blob, False), ("0" * 40, False), ("nonexistent", False), ("", False),
        ]
        for value, want in cases:
            with self.subTest(value=value):
                self.assertIs(gitinfo.commit_exists(self.root, value), want)

    def test_ambiguous_short_sha_is_false(self):  # owner Q-1a2-3
        seen = {}
        i = 0
        while True:
            data = b"amb%d\n" % i
            h = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            if h[:4] in seen:
                pair = (seen[h[:4]], data)
                break
            seen[h[:4]] = data
            i += 1
        for data in pair:
            p = subprocess.run(["git", "-C", self.root, "hash-object", "-w", "--stdin"],
                               input=data, stdout=subprocess.PIPE, check=True)
        prefix = h[:4]
        bad = subprocess.run(["git", "-C", self.root, "rev-parse", "--verify", "-q", prefix],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(bad.returncode, 0)  # git itself calls it ambiguous
        self.assertIs(gitinfo.commit_exists(self.root, prefix), False)

    def _blob_with_prefix(self, prefix):
        """Write a blob whose sha starts with prefix (lowercase hex); return its sha."""
        i = 0
        while True:
            data = b"cb%d\n" % i
            if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest().startswith(prefix):
                return git_in(self.root, ["hash-object", "-w", "--stdin"], data)
            i += 1

    def _ambiguous_commit_prefix(self):
        """A 4-char prefix of a commit, holding at least two letters, shared with a blob; return (prefix, sha)."""
        sha = git(self.root, "rev-parse", "HEAD")
        n = 0
        while sum(c in "abcdef" for c in sha[:4]) < 2:
            n += 1
            sha = commit_all(self.root, "letters %d" % n)
        self._blob_with_prefix(sha[:4])
        return sha[:4], sha

    def test_prefix_shared_by_commit_and_blob_is_false(self):  # owner Q-1a2r-2, F-1a2r-4
        prefix, sha = self._ambiguous_commit_prefix()
        self.assertEqual(subprocess.run(["git", "-C", self.root, "cat-file", "-e", prefix + "^{commit}"]
                                        ).returncode, 0)  # plain git picks the commit
        letters = [i for i, c in enumerate(prefix) if c in "abcdef"]
        mixed = "".join(c.upper() if i == letters[0] else c for i, c in enumerate(prefix))
        self.assertNotIn(mixed, (mixed.lower(), mixed.upper()))  # truly mixed case
        for value in (prefix, prefix.upper(), mixed):  # an ambiguous prefix in every letter case
            with self.subTest(value=value):
                self.assertIs(gitinfo.commit_exists(self.root, value), False)
        for value in (sha, sha.upper(), sha[:12], sha[:12].upper(), mixed + sha[4:12]):  # unique: True
            with self.subTest(value=value):
                self.assertIs(gitinfo.commit_exists(self.root, value), True)
        git(self.root, "config", "core.disambiguate", "commit")  # repo config does not lift the rule
        self.assertEqual(git(self.root, "rev-parse", "--verify", mixed), sha)  # plain git now picks the commit
        for value in (prefix, prefix.upper(), mixed):  # in any letter case
            with self.subTest(config="commit", value=value):
                self.assertIs(gitinfo.commit_exists(self.root, value), False)
        self.assertEqual(git(self.root, "rev-parse", "--verify", prefix + "^{}"), sha)  # not a bare prefix:
        self.assertIs(gitinfo.commit_exists(self.root, prefix + "^{}"), True)  # git's verdict, config included

    def test_hex_named_ref_resolves_as_a_ref(self):  # G3, F-1a2r-3: a ref name wins over a prefix
        prefix, sha = self._ambiguous_commit_prefix()
        other = git(self.root, "rev-parse", "HEAD~1")
        blob = self._blob_with_prefix(other[:4])
        name = other[:4]
        self.assertIs(gitinfo.commit_exists(self.root, name), False)  # a pure prefix: ambiguous
        layouts = [  # (refs created, all pointing at sha)
            ["refs/tags/%s"], ["refs/heads/%s"], ["refs/%s"], ["refs/remotes/%s"], ["refs/remotes/%s/HEAD"],
            ["refs/tags/%s", "refs/heads/%s"],  # git warns "refname is ambiguous", picks the tag
            ["refs/heads/%s", "refs/remotes/%s/HEAD"],
        ]
        for layout in layouts:
            with self.subTest(layout=layout):
                for ref in layout:
                    git(self.root, "update-ref", ref % name, sha)
                self.assertEqual(git(self.root, "rev-parse", "--verify", name + "^{commit}"), sha)
                self.assertIs(gitinfo.commit_exists(self.root, name), True)
                for ref in layout:
                    git(self.root, "update-ref", "-d", ref % name)
                self.assertIs(gitinfo.commit_exists(self.root, name), False)
        peel = ["rev-parse", "--verify", "--quiet", name + "^{commit}"]
        git(self.root, "update-ref", "refs/tags/%s" % name, blob)  # a ref to a blob: git's verdict
        self.assertEqual(git(self.root, *peel, check=False), "")
        self.assertIs(gitinfo.commit_exists(self.root, name), False)
        git(self.root, "update-ref", "refs/heads/%s" % name, sha)  # tag outranks branch: still the blob
        self.assertEqual(git(self.root, *peel, check=False), "")
        self.assertIs(gitinfo.commit_exists(self.root, name), False)
        git(self.root, "update-ref", "-d", "refs/tags/%s" % name)
        self.assertEqual(git(self.root, *peel), sha)
        self.assertIs(gitinfo.commit_exists(self.root, name), True)
        git(self.root, "update-ref", "-d", "refs/heads/%s" % name)
        self.assertIs(gitinfo.commit_exists(self.root, name), False)
        with open(os.path.join(self.root, ".git", name), "w") as fh:  # first rule: $GIT_DIR/<name>
            fh.write(sha + "\n")
        self.assertEqual(git(self.root, *peel), sha)
        self.assertIs(gitinfo.commit_exists(self.root, name), True)

    def test_revision_expressions_resolve_as_git_does(self):  # G3, F-1a2r-3
        prefix, sha = self._ambiguous_commit_prefix()
        git(self.root, "tag", "-a", "-m", "t", "ttree", "HEAD^{tree}")
        for value, want in (("HEAD~1", True), ("HEAD^{tree}", False), (prefix + "~0", True),
                            (prefix + "^{commit}", True), (prefix + "^0", True), (prefix.upper() + "~0", True),
                            (prefix, False), ("HEAD:a.txt", False), ("ttree", False),
                            ("main@{0}", True), ("x" + prefix, False)):
            with self.subTest(value=value):
                self.assertIs(gitinfo.commit_exists(self.root, value), want)

    def test_dash_value_is_never_passed_to_git(self):
        calls, patch = spy_runs()
        with patch:
            self.assertIs(gitinfo.commit_exists(self.root, "-x"), False)
            self.assertIs(gitinfo.commit_exists(self.root, "--help"), False)
            self.assertIs(gitinfo.blob_exists(self.root, "-r", "a.txt"), False)
            with self.assertRaises(GateError):
                gitinfo.show(self.root, "-r", "HEAD")
            with self.assertRaises(GateError):
                gitinfo.ls_tree(self.root, "-r", "HEAD")
            with self.assertRaises(GateError):
                gitinfo.merge_base(self.root, "-x", "HEAD")
            with self.assertRaises(GateError):
                gitinfo.merge_base(self.root, "HEAD", "-x")
        self.assertTrue(calls)  # the repo checks ran, so the spy saw real calls
        for argv, _ in calls:
            for a in argv:
                self.assertFalse(a in ("-r", "--help") or a.startswith("-x"), argv)

    def test_dash_ref_is_refused_not_just_failed(self):
        with self.assertRaises(GateError) as e:
            gitinfo.show(self.root, "-r", "HEAD")
        self.assertIn("ref", str(e.exception))
        with self.assertRaises(GateError) as e:
            gitinfo.merge_base(self.root, "HEAD", "-x")
        self.assertIn("ref", str(e.exception))

    def test_caret_value_is_refused_like_dash(self):  # F-1a-ver-2, owner Q-1a-ver-2 (a)
        values = ("^main", "^HEAD", "^" + self.head, "^" + self.head[:7], "^", "^^main", "^-x")
        calls, patch = spy_runs()
        with patch:
            for v in values:
                with self.subTest(fn="commit_exists", value=v):
                    self.assertIs(gitinfo.commit_exists(self.root, v), False)
                with self.subTest(fn="blob_exists", value=v):
                    self.assertIs(gitinfo.blob_exists(self.root, v, "a.txt"), False)
                for name, fn in (("show", lambda r: gitinfo.show(self.root, r, "a.txt")),
                                 ("ls_tree", lambda r: gitinfo.ls_tree(self.root, r, "dir")),
                                 ("merge_base a", lambda r: gitinfo.merge_base(self.root, r, "HEAD")),
                                 ("merge_base b", lambda r: gitinfo.merge_base(self.root, "HEAD", r))):
                    with self.subTest(fn=name, value=v):
                        with self.assertRaises(GateError) as e:
                            fn(v)
                        self.assertEqual(str(e.exception), "ref must not start with '^'")
        self.assertTrue(calls)
        for argv, _ in calls:
            self.assertFalse(any(a.startswith("^") for a in argv), argv)
        # a '^' after the first character is still a revision suffix, resolved as git does
        self.assertIs(gitinfo.commit_exists(self.root, "HEAD^0"), True)
        self.assertEqual(gitinfo.merge_base(self.root, "HEAD^0", "main"), self.head)
        self.assertEqual(gitinfo.show(self.root, "HEAD^0", "a.txt"), "alpha\n")


ROOT, SUB, ERR = "root", "sub", "GateError"  # ls_tree verdicts: the HEAD root listing, ['x.txt'], GateError
TXT = "alpha\n"


class RevisionFormsTest(Fixture):
    """Every gitrevisions form for the ref/sha argument of commit_exists, blob_exists, show, ls_tree (G3, G4,
    G6, G7, round 5): each value pinned to the verdict the code gives, or refused (over-long hex, F-1a2r-5)."""

    def setUp(self):
        super().setUp()
        r = self.root
        git(r, "branch", "feature", "HEAD~1")
        git(r, "config", "branch.main.remote", ".")
        git(r, "config", "branch.main.merge", "refs/heads/feature")
        git(r, "update-ref", "ORIG_HEAD", "HEAD~1")
        with open(os.path.join(r, ".git", "FETCH_HEAD"), "w") as fh:
            fh.write(self.head + "\t\tbranch 'main' of x\n")
        self.listing = gitinfo.ls_tree(r, "HEAD", "")
        self.assertIn("a.txt", self.listing)

    def verdicts(self, value, path="a.txt", directory=""):
        def guard(fn):
            try:
                return fn()
            except GateError:
                return ERR
        ls = guard(lambda: gitinfo.ls_tree(self.root, value, directory))
        ls = ROOT if ls == self.listing else SUB if ls == ["x.txt"] else ls
        return (gitinfo.commit_exists(self.root, value), gitinfo.blob_exists(self.root, value, path),
                guard(lambda: gitinfo.show(self.root, value, path)), ls)

    def git_names_commit(self, value):
        """Oracle from the git CLI: the value resolves (rev-parse --verify) and its object peels to a commit."""
        p = subprocess.run(["git", "-C", self.root, "rev-parse", "--verify", "--quiet", "--end-of-options", value],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            return False
        oid = p.stdout.decode("ascii").strip()
        return subprocess.run(["git", "-C", self.root, "cat-file", "-e", oid + "^{commit}"],
                              stderr=subprocess.PIPE).returncode == 0

    def test_revision_forms(self):
        H = self.head
        ok = (True, True, TXT, ROOT)
        absent = (False, False, ERR, ERR)
        old = (True, False, None, [])  # a commit older than a.txt (the config commit)
        cases = [
            (H, ok), (H.upper(), ok), (H[:7], ok), (H[:7].upper(), ok), (H[:7].upper()[:3] + H[3:7], ok),
            ("HEAD", ok), ("FETCH_HEAD", ok), ("ORIG_HEAD", ok), ("@", ok), ("@{u}", ok), ("@{upstream}", ok),
            ("main", ok), ("heads/main", ok), ("refs/heads/main", ok), ("feature", ok),
            ("main@{0}", ok), ("main@{1}", ok), ("@{1}", ok), ("main@{2026-01-02}", ok),
            ("main@{2025-01-01}", old),  # before the reflog: git takes the oldest entry
            ("@{-1}", absent),  # no branch was checked out before
            ("HEAD~1", ok), ("HEAD^", ok), ("HEAD^^", old), ("HEAD~1^1", old), ("HEAD^2", absent),
            ("HEAD^{commit}", ok), ("HEAD^{}", ok), ("HEAD^{tree}", (False, True, TXT, ROOT)),
            ("HEAD^{/fixture}", old), ("HEAD^{/nomatch}", absent),
            (":/files", ok), (":/nomatch", absent),  # :/text names a commit
            ("HEAD:dir", (False, False, None, SUB)),  # <rev>:<path> naming a tree is a tree-ish
            ("HEAD:a.txt", absent), (":0:a.txt", absent), (":1:a.txt", absent), (":a.txt", absent),  # blobs
            ("HEAD~1..HEAD", absent), ("HEAD...feature", absent), ("HEAD^@", absent), ("HEAD^!", absent),
            ("", absent), (" ", absent), ("HEAD ", absent), (" HEAD", absent), ("\tHEAD", absent),
            ("HEAD\n", absent), ("nonexistent", absent), ("0" * 40, absent),
        ]
        for value, want in cases:
            with self.subTest(value=value):
                self.assertEqual(self.verdicts(value), want)
                self.assertIs(gitinfo.commit_exists(self.root, value), self.git_names_commit(value))

    def test_overlong_hex_is_refused(self):  # F-1a2r-5: spec ids are 7-40 hex digits
        H = self.head
        refused = (False, False, ERR, ERR)
        for value in (H + "0", H + "0" * 24, H.upper() + "0", H + "0~0", H + "0^{tree}", H + "0:dir",
                      "HEAD:" + "a" * 41, H + "0" * 25, H + "1", "0" * 41, "a" * 41):
            with self.subTest(value=value):
                self.assertEqual(self.verdicts(value), refused)
        self.assertTrue(self.git_names_commit(H + "0"))  # git itself would resolve it
        self.assertTrue(self.git_names_commit(H + "0~0"))
        tag = "t" + "a" * 41
        git(self.root, "tag", tag)  # a ref name holding 41 hex digits in a row is refused too
        self.assertTrue(self.git_names_commit(tag))
        self.assertEqual(self.verdicts(tag), refused)
        for fn in (lambda: gitinfo.show(self.root, H + "0", "a.txt"), lambda: gitinfo.ls_tree(self.root, H + "0", "")):
            with self.assertRaises(GateError) as e:
                fn()
            self.assertIn("40 hex digits", str(e.exception))
        self.assertEqual(self.verdicts(H), (True, True, TXT, ROOT))  # 40 digits still accepted
        calls, patch = spy_runs()
        with patch:
            gitinfo.commit_exists(self.root, H + "0")
            gitinfo.blob_exists(self.root, H + "0", "a.txt")
        self.assertFalse([argv for argv, _ in calls if any(H + "0" in a for a in argv)])  # git never sees it

    def test_path_forms(self):  # G4, G6, G7: the path argument (dir for ls_tree)
        absolute = os.path.join(self.root, "a.txt")
        cases = [  # path: (blob_exists, show, ls_tree with the path as directory)
            ("a.txt", (True, TXT, [])), ("/a.txt", (ERR, ERR, ERR)), (absolute, (ERR, ERR, ERR)),
            ("../a.txt", (ERR, ERR, ERR)), ("dir/../a.txt", (ERR, ERR, ERR)), ("./a.txt", (ERR, ERR, ERR)),
            ("a.txt/", (ERR, ERR, ERR)), ("dir", (False, None, ["dir/x.txt"])), ("dir/", (ERR, ERR, ERR)),
            (".", (ERR, ERR, ERR)), ("a/.", (ERR, ERR, ERR)), ("./a", (ERR, ERR, ERR)), ("/", (ERR, ERR, ERR)),
            ("dir//x.txt", (ERR, ERR, ERR)), ("dir/./x.txt", (ERR, ERR, ERR)),  # Q-1a-fin-2
            ("gl*ob/f.txt", (True, "g\n", [])), ("gl?ob/f.txt", (False, None, [])),
            ("co:lon.txt", (True, "colon\n", [])), (":(top)tm.txt", (True, "magic\n", [])),
            ("é/ü.txt", (True, "u\n", [])), ("nl\nname.txt", (True, "nl\n", [])), ("-lead.txt", (True, "lead\n", [])),
            ("", (False, ERR, self.listing)), (" a.txt", (False, None, [])), ("a.txt ", (False, None, [])),
            ("A.TXT", (False, None, [])), ("a\0b", (ERR, ERR, ERR)),
        ]
        for path, want in cases:
            with self.subTest(path=path):
                got = []
                for fn in (lambda: gitinfo.blob_exists(self.root, "HEAD", path),
                           lambda: gitinfo.show(self.root, "HEAD", path),
                           lambda: gitinfo.ls_tree(self.root, "HEAD", path)):
                    try:
                        got.append(fn())
                    except GateError:
                        got.append(ERR)
                self.assertEqual(tuple(got), want)


class BlobExistsTest(Fixture):
    def test_blob_exists_only_for_blobs(self):  # G4
        h = self.head
        yes = ["a.txt", "dir/x.txt", "dir/sub/y.txt", "bin/run", "empty.txt", "sp ace/f g.txt",
               "é/ü.txt", "-lead.txt", "co:lon.txt", "nl\nname.txt", "gl*ob/f.txt", ":(top)tm.txt", ":(top)md/f.txt"]
        no = ["dir", "nope", "link", "dir/lnk", "subm", "gl*", "gl?ob/f.txt", "", "dir/x.tx", "gl*ob"]
        for p in yes:
            with self.subTest(path=p, want=True):
                self.assertIs(gitinfo.blob_exists(self.root, h, p), True)
        for p in no:
            with self.subTest(path=p, want=False):
                self.assertIs(gitinfo.blob_exists(self.root, h, p), False)

    def test_blob_exists_ref_forms(self):
        self.assertIs(gitinfo.blob_exists(self.root, "HEAD", "a.txt"), True)
        self.assertIs(gitinfo.blob_exists(self.root, self.head[:7], "a.txt"), True)
        self.assertIs(gitinfo.blob_exists(self.root, "0" * 40, "a.txt"), False)
        self.assertIs(gitinfo.blob_exists(self.root, "nonexistent", "a.txt"), False)
        self.assertIs(gitinfo.blob_exists(self.root, self.config_sha, "a.txt"), False)
        self.assertIs(gitinfo.blob_exists(self.root, self.config_sha, ".strict-delivery/config.yml"), True)

    def test_tree_path_and_missing_path(self):
        head = gitinfo.head_sha(self.root)
        self.assertIs(gitinfo.blob_exists(self.root, head, "dir"), False)
        self.assertIs(gitinfo.blob_exists(self.root, head, "nope"), False)


class TrackedFilesTest(Fixture):
    def test_modes_100644_and_100755_only(self):  # G5
        want = frozenset([
            ".strict-delivery/config.yml", "a.txt", "crlf.txt", "empty.txt", "dir/x.txt",
            "dir/sub/y.txt", "bin/run", "sp ace/f g.txt", "é/ü.txt", "-lead.txt",
            "co:lon.txt", "nl\nname.txt", "gl*ob/f.txt", "glxob/h.txt", "bad.bin", ":(top)tm.txt",
            ":(top)md/f.txt"])
        got = gitinfo.tracked_files(self.root)
        self.assertIsInstance(got, frozenset)
        self.assertEqual(got, want)  # no link, dir/lnk, subm

    def test_untracked_file_not_in_tracked(self):
        with open(os.path.join(self.root, "new.txt"), "w") as fh:
            fh.write("n")
        self.assertNotIn("new.txt", gitinfo.tracked_files(self.root))
        git(self.root, "add", "new.txt")
        self.assertIn("new.txt", gitinfo.tracked_files(self.root))

    def test_git_index_file_is_honoured(self):  # owner Q-1a2r-5
        alt = os.path.join(self.tmp, "alt-index")
        shutil.copy(os.path.join(self.root, ".git", "index"), alt)
        with open(os.path.join(self.root, "new.txt"), "w") as fh:
            fh.write("n")
        git(self.root, "add", "new.txt", env={"GIT_INDEX_FILE": alt})
        self.assertNotIn("new.txt", gitinfo.tracked_files(self.root))
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            self.assertIn("new.txt", gitinfo.tracked_files(self.root))

    def test_index_not_head(self):
        git(self.root, "rm", "-q", "--cached", "a.txt")
        self.assertNotIn("a.txt", gitinfo.tracked_files(self.root))


class ShowTest(Fixture):
    def test_present_file_text(self):  # G6
        self.assertEqual(gitinfo.show(self.root, "HEAD", "a.txt"), "alpha\n")
        self.assertEqual(gitinfo.show(self.root, self.head, "crlf.txt"), "a\r\nb")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "empty.txt"), "")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "é/ü.txt"), "u\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "-lead.txt"), "lead\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "co:lon.txt"), "colon\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "sp ace/f g.txt"), "s\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "nl\nname.txt"), "nl\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", "bin/run"), "#!/bin/sh\n")
        self.assertEqual(gitinfo.show(self.root, "HEAD", ":(top)tm.txt"), "magic\n")  # no pathspec magic

    def test_show_absent_path_is_none(self):
        self.assertIsNone(gitinfo.show(self.root, "HEAD", "nope"))
        self.assertIsNone(gitinfo.show(self.root, self.config_sha, "a.txt"))
        self.assertIsNone(gitinfo.show(self.root, "HEAD", "gl*"))

    def test_directory_symlink_gitlink_are_none(self):  # owner Q-1a2-5, Q-1a2r-1
        for p in ("dir", "link", "dir/lnk", "subm"):
            with self.subTest(path=p):
                self.assertIsNone(gitinfo.show(self.root, "HEAD", p))

    def test_nonexistent_ref_is_gate_error(self):
        for ref in ("nonexistent", "0" * 40, ""):
            with self.subTest(ref=ref):
                with self.assertRaises(GateError) as e:
                    gitinfo.show(self.root, ref, "a.txt")
                self.assertIn("git ls-tree", str(e.exception))
                self.assertNotIn(self.root, str(e.exception))

    def test_invalid_utf8_names_the_path(self):  # owner Q-1a2-5
        with self.assertRaises(GateError) as e:
            gitinfo.show(self.root, "HEAD", "bad.bin")
        self.assertIn("bad.bin", str(e.exception))
        self.assertIn("UTF-8", str(e.exception))


class LsTreeTest(Fixture):
    def test_regular_files_directly_in_directory(self):  # G7
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir"), ["dir/x.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir/sub"), ["dir/sub/y.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "bin"), ["bin/run"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "sp ace"), ["sp ace/f g.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "é"), ["é/ü.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, self.head[:7], "dir"), ["dir/x.txt"])

    def test_glob_characters_are_literal(self):
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "gl*ob"), ["gl*ob/f.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", ":(top)md"), [":(top)md/f.txt"])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "gl?ob"), [])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "gl*"), [])

    def test_absent_dir_and_file_are_empty(self):
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "nope"), [])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "a.txt"), [])
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "subm"), [])
        self.assertEqual(gitinfo.ls_tree(self.root, self.config_sha, "dir"), [])

    def test_dotdot_segment_is_gate_error(self):  # owner Q-1a2r-1
        for d in ("dir/../bin", "..", "../x", "a/..", "dir/..", "dir/../"):
            with self.subTest(directory=d):
                with self.assertRaises(GateError) as e:
                    gitinfo.ls_tree(self.root, "HEAD", d)
                self.assertIn("..", str(e.exception))
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "..x"), [])  # only a whole '..' segment

    def test_repo_root_directory(self):
        top = gitinfo.ls_tree(self.root, "HEAD", "")
        self.assertEqual(sorted(top), sorted(
            ["a.txt", "crlf.txt", "empty.txt", "-lead.txt", "co:lon.txt", "nl\nname.txt", "bad.bin",
             ":(top)tm.txt"]))

    def test_nonexistent_ref_is_gate_error(self):
        for ref in ("nonexistent", "0" * 40, ""):
            with self.subTest(ref=ref):
                with self.assertRaises(GateError):
                    gitinfo.ls_tree(self.root, ref, "dir")


class OddNamesTest(Fixture):
    def test_nul_in_an_argument_is_gate_error(self):
        for fn in (lambda: gitinfo.show(self.root, "HEAD", "a\0b"),
                   lambda: gitinfo.ls_tree(self.root, "HEAD", "a\0b"),
                   lambda: gitinfo.merge_base(self.root, "HEAD", "a\0b")):
            with self.assertRaises(GateError) as e:
                fn()
            self.assertIn("git ", str(e.exception))
        with self.assertRaises(GateError):
            gitinfo.blob_exists(self.root, "HEAD", "a\0b")
        with self.assertRaises(GateError):
            gitinfo.commit_exists(self.root, "a\0b")

    def test_non_utf8_path_in_the_tree_is_gate_error(self):
        blob = git(self.root, "rev-parse", "HEAD:a.txt")
        git(self.root, "update-index", "--add", "--cacheinfo", "100644,%s,bad\udcffname" % blob)
        git(self.root, "commit", "-q", "-m", "bad name")  # no add -A: the file is not in the work tree
        with self.assertRaises(GateError) as e:
            gitinfo.tracked_files(self.root)
        self.assertIn("UTF-8", str(e.exception))
        with self.assertRaises(GateError) as e:
            gitinfo.ls_tree(self.root, "HEAD", "")
        self.assertIn("UTF-8", str(e.exception))
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir"), ["dir/x.txt"])


class MergeBaseTest(Fixture):
    def test_related(self):  # G8
        git(self.root, "branch", "side")
        git(self.root, "checkout", "-q", "side")
        side = commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "main")
        main = commit_all(self.root, "main2")
        self.assertNotEqual(side, main)
        self.assertEqual(gitinfo.merge_base(self.root, "main", "side"), self.head)
        self.assertEqual(gitinfo.merge_base(self.root, side, main), self.head)

    def test_unrelated_histories_and_bad_refs(self):
        git(self.root, "checkout", "-q", "--orphan", "other")
        git(self.root, "rm", "-rf", "-q", ".")
        commit_all(self.root, "orphan")
        git(self.root, "checkout", "-q", "main")
        for a, b in (("main", "other"), ("main", "nonexistent"), ("nonexistent", "main"), ("", "main")):
            with self.subTest(a=a, b=b):
                with self.assertRaises(GateError) as e:
                    gitinfo.merge_base(self.root, a, b)
                self.assertIn("git merge-base", str(e.exception))

    def test_overlong_hex_is_refused(self):  # F-1a2r-5 widened by the owner (round 6)
        H = git(self.root, "rev-parse", "HEAD")
        self.assertEqual(git(self.root, "merge-base", H + "0", "HEAD"), H)  # git itself would accept it
        self.assertEqual(gitinfo.merge_base(self.root, H, "HEAD"), H)  # 40 digits still accepted
        calls, patch = spy_runs()
        with patch:
            for a, b in ((H + "0", "HEAD"), ("HEAD", H + "0"), (H.upper() + "0" * 24, "HEAD"),
                         ("HEAD", H + "0~0"), ("a" * 41, "HEAD")):
                with self.subTest(a=a, b=b):
                    with self.assertRaises(GateError) as e:
                        gitinfo.merge_base(self.root, a, b)
                    self.assertEqual(str(e.exception), "ref must not hold more than 40 hex digits in a row")
        self.assertEqual([argv for argv, _ in calls if "merge-base" in argv], [])  # git never ran merge-base


class IsAncestorTest(Fixture):
    """Task 2c.3 table rows A1-A6: ``gitinfo.is_ancestor``."""

    def two(self):
        first = commit_all(self.root, "one")
        second = commit_all(self.root, "two")
        return first, second

    def test_is_ancestor(self):  # A1
        first, second = self.two()
        self.assertTrue(gitinfo.is_ancestor(self.root, first, second))
        self.assertFalse(gitinfo.is_ancestor(self.root, second, first))

    def test_is_ancestor_cases(self):  # A2-A5
        first, second = self.two()
        self.assertTrue(gitinfo.is_ancestor(self.root, second, second))            # A2: a commit is its own ancestor
        git(self.root, "checkout", "-q", "--orphan", "other")
        git(self.root, "rm", "-rf", "-q", ".")
        orphan = commit_all(self.root, "orphan")
        git(self.root, "checkout", "-q", "main")
        self.assertFalse(gitinfo.is_ancestor(self.root, orphan, second))           # A3: unrelated histories
        self.assertFalse(gitinfo.is_ancestor(self.root, second, orphan))
        failed = "git merge-base --is-ancestor failed (exit 128)"
        for a, b in (("0" * 40, second), (second, "0" * 40), ("nonexistent", second), ("", second)):
            with self.subTest(a=a, b=b):                                           # A4: exit 128 is an error, never False
                with self.assertRaises(GateError) as e:
                    gitinfo.is_ancestor(self.root, a, b)
                self.assertEqual(str(e.exception), failed)
        check_root_forms(self, root_forms(self.tmp, self.root),
                         {"is_ancestor": lambda r: gitinfo.is_ancestor(r, "HEAD", "HEAD")})   # A4 roots
        calls, patch = spy_runs()
        with patch:                                                                # A5: refused before git runs
            for a, b, text in (("-x", second, "ref must not start with '-'"), (second, "^HEAD",
                                                                                  "ref must not start with '^'"),
                               ("a" * 41, second, "ref must not hold more than 40 hex digits in a row"),
                               (second, "a" * 41, "ref must not hold more than 40 hex digits in a row")):
                with self.subTest(a=a, b=b):
                    with self.assertRaises(GateError) as e:
                        gitinfo.is_ancestor(self.root, a, b)
                    self.assertEqual(str(e.exception), text)
        self.assertEqual([argv for argv, _ in calls if "--is-ancestor" in argv], [])

    def test_is_ancestor_invocation(self):  # A6: the pinned call
        first, second = self.two()
        calls, patch = spy_runs()
        with patch:
            gitinfo.is_ancestor(self.root, first, second)
        argv, env = [c for c in calls if "--is-ancestor" in c[0]][0]
        self.assertEqual(argv[argv.index("merge-base"):], ["merge-base", "--is-ancestor", first, second])
        self.assertEqual(env["LC_ALL"], "C")
        for name in gitinfo.CLEARED_ENV:
            self.assertNotIn(name, env)


class UserEmailTest(GitIsolatedTestCase):
    def repo(self):
        root = os.path.join(self.work, "r")
        os.mkdir(root)
        git(root, "init", "-q", "-b", "main")
        return root

    def test_set_and_stripped(self):  # G9
        root = self.repo()
        git(root, "config", "user.email", "me@example.invalid")
        self.assertEqual(gitinfo.user_email(root), "me@example.invalid")
        git(root, "config", "user.email", "  me@example.invalid ")
        self.assertEqual(gitinfo.user_email(root), "me@example.invalid")

    def test_user_email_unset_is_none(self):
        self.assertIsNone(gitinfo.user_email(self.repo()))

    def test_empty_and_blank_are_none(self):  # owner Q-1a2-7
        root = self.repo()
        for value in ("", "   "):
            with self.subTest(value=value):
                git(root, "config", "user.email", value)
                self.assertIsNone(gitinfo.user_email(root))

    def test_global_email_is_ignored_in_isolated_env(self):
        root = self.repo()
        with open(os.path.join(os.environ["HOME"], ".gitconfig"), "w") as fh:
            fh.write("[user]\n\temail = global@example.invalid\n")
        self.assertIsNone(gitinfo.user_email(root))


class EnvAndFlagsTest(Fixture):
    def test_locale_forced_and_git_env_cleared(self):  # G10
        calls, patch = spy_runs()
        env = {"LC_ALL": "de_DE.UTF-8", "GIT_DIR": "/nonexistent/x", "GIT_WORK_TREE": "/nonexistent/y"}
        with mock.patch.dict(os.environ, env), patch:
            gitinfo.head_sha(self.root)
            gitinfo.commit_exists(self.root, "HEAD")
            gitinfo.tracked_files(self.root)
            gitinfo.user_email(self.root)
        self.assertTrue(calls)
        for argv, e in calls:
            self.assertEqual(e.get("LC_ALL"), "C", argv)
            self.assertNotIn("GIT_DIR", e)
            self.assertNotIn("GIT_WORK_TREE", e)
            self.assertEqual(argv[0], "git")

    def test_caller_git_dir_does_not_redirect(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        git(other, "commit", "-q", "--allow-empty", "-m", "different")
        other_head = git(other, "rev-parse", "HEAD")
        self.assertNotEqual(other_head, self.head)
        env = {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(gitinfo.head_sha(self.root), self.head)
            self.assertIn("a.txt", gitinfo.tracked_files(self.root))
            self.assertEqual(gitinfo.show(self.root, "HEAD", "a.txt"), "alpha\n")

    def _other_repo(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        git(other, "commit", "-q", "--allow-empty", "-m", "different")
        other_head = git(other, "rev-parse", "HEAD")
        self.assertEqual(git(self.root, "cat-file", "-t", other_head, check=False), "")
        return other, other_head

    def test_repository_env_names_cleared(self):  # G10, F-1a-ver-3, owner Q-1a-ver-3 (a)
        other, _ = self._other_repo()
        names = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
        env = {n: os.path.join(other, ".git") for n in names}
        env["GIT_INDEX_FILE"] = os.path.join(self.root, ".git", "index")
        calls, patch = spy_runs()
        with mock.patch.dict(os.environ, env), patch:
            gitinfo.head_sha(self.root)
            gitinfo.commit_exists(self.root, "HEAD")
            gitinfo.blob_exists(self.root, "HEAD", "a.txt")
            gitinfo.tracked_files(self.root)
            gitinfo.show(self.root, "HEAD", "a.txt")
            gitinfo.ls_tree(self.root, "HEAD", "dir")
            gitinfo.merge_base(self.root, "HEAD", "main")
            gitinfo.user_email(self.root)
        self.assertTrue(calls)
        for argv, e in calls:
            for n in names:
                self.assertNotIn(n, e, argv)
            self.assertEqual(e.get("GIT_INDEX_FILE"), env["GIT_INDEX_FILE"], argv)  # owner Q-1a2r-5

    def test_each_repository_env_name_does_not_redirect(self):  # G10, F-1a-ver-3: one row per name
        other, other_head = self._other_repo()
        other_git = os.path.join(other, ".git")
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        sub = os.path.join(self.root, "dir")

        def answers():
            return (gitinfo.commit_exists(self.root, other_head), gitinfo.commit_exists(self.root, self.head),
                    gitinfo.head_sha(self.root), gitinfo.toplevel(sub) == self.root,
                    gitinfo.merge_base(self.root, "HEAD", "main"), gitinfo.ls_tree(self.root, "HEAD", "dir"),
                    gitinfo.show(self.root, "HEAD", "a.txt"), "a.txt" in gitinfo.tracked_files(self.root))
        want = (False, True, self.head, True, self.head, ["dir/x.txt"], "alpha\n", True)
        self.assertEqual(answers(), want)
        rows = (
            ("GIT_DIR", other_git),
            ("GIT_WORK_TREE", other),
            ("GIT_COMMON_DIR", other_git),
            ("GIT_OBJECT_DIRECTORY", os.path.join(other_git, "objects")),
            ("GIT_OBJECT_DIRECTORY", empty),
            ("GIT_ALTERNATE_OBJECT_DIRECTORIES", os.path.join(other_git, "objects")),
            ("GIT_NAMESPACE", "zz"),
            ("GIT_CEILING_DIRECTORIES", self.root),
        )
        for name, value in rows:
            with self.subTest(name=name, value=value), mock.patch.dict(os.environ, {name: value}):
                try:
                    got = answers()
                except GateError as e:
                    got = "GateError: %s" % e
                self.assertEqual(got, want)

    def test_every_user_path_follows_double_dash(self):
        calls, patch = spy_runs()
        with patch:
            gitinfo.blob_exists(self.root, "HEAD", "-lead.txt")
            gitinfo.show(self.root, "HEAD", "-lead.txt")
            gitinfo.ls_tree(self.root, "HEAD", "-lead")
        seen = 0
        for argv, _ in calls:
            if "ls-tree" in argv and any("-lead" in a for a in argv):
                seen += 1
                i = argv.index("--")
                self.assertTrue(all("-lead" in a for a in argv[i + 1:]), argv)
                self.assertFalse(any("-lead" in a for a in argv[:i]), argv)
        self.assertEqual(seen, 3)

    def test_argument_lists_not_shell_strings(self):
        calls, patch = spy_runs()
        with patch:
            gitinfo.show(self.root, "HEAD", "a.txt; echo hi")
            gitinfo.head_sha(self.root)
        self.assertTrue(all(isinstance(argv, list) and all(isinstance(a, str) for a in argv)
                            for argv, _ in calls))



class RootGuardTest(Fixture):
    """Q-1bfin-2 (a): head_sha, commit_exists, merge_base and user_email refuse a root that is not the top level,
    before any other work (task 1c0.1, T1-T15, O1-O3)."""

    def calls(self):
        return {
            "head_sha": gitinfo.head_sha,
            "commit_exists": lambda r: gitinfo.commit_exists(r, self.head),
            "merge_base": lambda r: gitinfo.merge_base(r, "HEAD", "HEAD"),
            "user_email": gitinfo.user_email,
        }

    def test_subdirectory_root_refused_everywhere(self):  # T1-T12, T15
        check_root_forms(self, root_forms(self.tmp, self.root), self.calls())

    def test_symlinked_top_level_accepted_with_the_same_answers(self):  # T3
        link = os.path.join(self.tmp, "alias")
        os.symlink(self.root, link)
        for spelling in (link, link + "/", self.root + "/"):
            with self.subTest(root=spelling):
                self.assertEqual(gitinfo.head_sha(spelling), self.head)
                self.assertTrue(gitinfo.commit_exists(spelling, self.head))
                self.assertEqual(gitinfo.merge_base(spelling, "HEAD", "HEAD"), self.head)
                self.assertEqual(gitinfo.user_email(spelling), "fixture@example.invalid")

    def test_linked_worktree_top_level_accepted(self):  # T9
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        self.assertEqual(gitinfo.head_sha(wt), self.head)
        self.assertEqual(gitinfo.user_email(wt), "fixture@example.invalid")

    def test_unborn_repository_passes_the_root_check(self):  # T13
        unborn = os.path.join(self.tmp, "unborn")
        os.mkdir(unborn)
        git(unborn, "init", "-q", "-b", "main")
        with self.assertRaises(GateError) as e:
            gitinfo.head_sha(unborn)
        self.assertEqual(str(e.exception), "git rev-parse HEAD failed (exit 128)")
        self.assertIsNone(gitinfo.user_email(unborn))
        self.assertIs(gitinfo.commit_exists(unborn, "0" * 40), False)

    def test_git_not_on_path_is_git_not_found_from_every_function(self):  # T14
        for name, fn in self.calls().items():
            with self.subTest(fn=name), mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "nowhere")}):
                with self.assertRaises(GitNotFound) as e:
                    fn(self.root)
                self.assertEqual(str(e.exception), "git not found on PATH; install git")

    def test_root_check_comes_before_ref_and_sha_checks(self):  # O1, O2, O3
        sub = os.path.join(self.root, "dir")
        for sha in ("-x", "^x", "a" * 41):
            with self.subTest(sha=sha):
                with self.assertRaises(GateError) as e:
                    gitinfo.commit_exists(sub, sha)
                self.assertEqual(str(e.exception), TOP)
                self.assertIs(gitinfo.commit_exists(self.root, sha), False)
        with self.assertRaises(GateError) as e:
            gitinfo.merge_base(sub, "-x", "HEAD")
        self.assertEqual(str(e.exception), TOP)
        with self.assertRaises(GateError) as e:
            gitinfo.merge_base(self.root, "-x", "HEAD")
        self.assertEqual(str(e.exception), "ref must not start with '-'")
        for fn in (gitinfo.show, gitinfo.ls_tree):  # unchanged: the ref check still precedes the root check
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(GateError) as e:
                    fn(sub, "-x", "dir")
                self.assertEqual(str(e.exception), "ref must not start with '-'")


# ======================================================================== Task P1.3: current_branch, dirty_paths,
# upstream_sha, remotes (table rows CB1-CB9, DP1-DP16, UP1-UP8, RM1-RM6; decisions D-Q6, D-Q7, D-Q8, D-Q12, D-Q14)

def plain_git(root, *args, check=True):
    """The plain git command line, bytes out (the independent oracle of the tests below)."""
    p = subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and p.returncode != 0:
        raise AssertionError(p.stderr)
    return p


def porcelain_oracle(root):
    """Three lines written in the test: ``git status --porcelain=v1 -z`` entries, one path each (no renames)."""
    out = plain_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=no", "--no-renames").stdout
    return [e[3:].decode("utf-8") for e in out.split(b"\0") if e]


class P13Case(GitIsolatedTestCase):
    """A ``make_repo`` fixture whose config pins the Global Constraints :33 settings (colour always, abbrev 7)."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        git(self.root, "config", "color.ui", "always")
        git(self.root, "config", "color.diff", "always")
        git(self.root, "config", "color.status", "always")
        git(self.root, "config", "core.abbrev", "7")

    def put(self, rel, data=b"x\n", root=None):
        path = os.path.join(root or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def bare_remote(self, name="origin"):
        bare = os.path.join(self.tmp, name + ".git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", bare)
        git(self.root, "remote", "add", name, bare)
        return bare

    def linked(self, name="w", branch=None):
        path = os.path.join(self.tmp, name)
        if branch:
            git(self.root, "worktree", "add", "-q", "-b", branch, path)
        else:
            git(self.root, "worktree", "add", "-q", "--detach", path)
        return path


class CurrentBranch(P13Case):
    def test_current_branch_names(self):  # CB1
        for name in ("block/p1.3", "feat-x", "b" * 200, "café", "7up", "main"):
            with self.subTest(name=name[:20]):
                git(self.root, "checkout", "-q", "-B", name)
                self.assertEqual(gitinfo.current_branch(self.root), name)
                self.assertEqual(plain_git(self.root, "symbolic-ref", "--short", "HEAD").stdout.decode().strip(), name)

    def test_current_branch_detached_is_none(self):  # CB2
        git(self.root, "checkout", "-q", "--detach")
        self.assertIsNone(gitinfo.current_branch(self.root))

    def test_current_branch_unborn(self):  # CB3
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "trunk")
        self.assertEqual(gitinfo.current_branch(fresh), "trunk")
        with self.assertRaises(GateError):
            gitinfo.head_sha(fresh)

    def test_current_branch_tag_of_same_name(self):  # CB4, D-Q6
        git(self.root, "checkout", "-q", "-b", "feat")
        git(self.root, "tag", "feat")
        self.assertEqual(plain_git(self.root, "symbolic-ref", "--short", "HEAD").stdout.decode().strip(), "heads/feat")
        self.assertEqual(gitinfo.current_branch(self.root), "feat")

    def test_current_branch_linked_worktree(self):  # CB5
        w = self.linked("sib", "sibbr")
        self.assertEqual(gitinfo.current_branch(w), "sibbr")
        self.assertEqual(gitinfo.current_branch(self.root), "main")

    def test_current_branch_root_forms(self):  # CB6
        check_root_forms(self, root_forms(self.tmp, self.root), {"current_branch": gitinfo.current_branch})

    def test_current_branch_ignores_user_config(self):  # CB7
        git(self.root, "config", "init.defaultBranch", "other")
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "nowhere"), "GIT_INDEX_FILE": "idx"}):
            self.assertEqual(gitinfo.current_branch(self.root), "main")
        calls, patch = spy_runs()
        with patch:
            gitinfo.current_branch(self.root)
        sym = [a for a, _ in calls if "symbolic-ref" in a]
        self.assertEqual(len(sym), 1)
        self.assertEqual(sym[0][-3:], ["symbolic-ref", "--quiet", "HEAD"])
        self.assertEqual(sym[0][:3], ["git", "-C", self.root])

    def test_current_branch_root_types(self):  # CB8, D-Q14
        class S(str):
            pass
        for bad in (None, b".", 5, S(self.root), ""):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(GateError) as e:
                    gitinfo.current_branch(bad)
                self.assertEqual(str(e.exception), "root must be a string")

    def test_current_branch_unicode_same_on_both(self):  # CB9
        for name in ("uࡰx", "e\U0001fae8"):
            git(self.root, "checkout", "-q", "-B", name)
            self.assertEqual(gitinfo.current_branch(self.root), name)

    def test_current_branch_target_outside_heads_is_refused(self):  # D-Q6 fail closed
        real = gitinfo._run

        def fake(root, name, args, **kw):
            p = real(root, name, args, **kw)
            if name == "symbolic-ref":
                p.stdout = b"refs/remotes/origin/main\n"
            return p
        with mock.patch.object(gitinfo, "_run", fake):
            with self.assertRaises(GateError) as e:
                gitinfo.current_branch(self.root)
        self.assertEqual(str(e.exception), "git symbolic-ref: HEAD does not name a branch under refs/heads/")


class DirtyPaths(P13Case):
    def test_dirty_paths_clean(self):  # DP1
        self.assertEqual(gitinfo.dirty_paths(self.root), [])

    def test_dirty_paths_each_kind(self):  # DP2
        self.put("a.txt")
        self.put("b.txt")
        self.put("c.txt")
        self.put("d.txt")
        commit_all(self.root, "base")
        self.put("a.txt", b"changed\n")
        git(self.root, "add", "a.txt")  # staged modify
        self.put("b.txt", b"changed\n")  # unstaged modify
        os.remove(os.path.join(self.root, "c.txt"))  # deleted, unstaged
        git(self.root, "rm", "-q", "d.txt")  # staged delete
        self.put("u.txt")
        git(self.root, "add", "u.txt")  # staged add
        self.put("n/x y.txt")  # untracked, in a new directory
        got = gitinfo.dirty_paths(self.root)
        self.assertEqual(got, ["a.txt", "b.txt", "c.txt", "d.txt", "u.txt", "n/x y.txt"])  # tracked entries, then untracked
        self.assertEqual(got, porcelain_oracle(self.root))

    def test_dirty_paths_mm_listed_once(self):  # DP3
        self.put("a.txt")
        commit_all(self.root, "base")
        self.put("a.txt", b"one\n")
        git(self.root, "add", "a.txt")
        self.put("a.txt", b"two\n")
        self.assertEqual(gitinfo.dirty_paths(self.root), ["a.txt"])

    def test_dirty_paths_rename_entries(self):  # DP4, Q7 (a), V4
        self.put("a.txt", b"some longer content so the rename is detected\n" * 3)
        commit_all(self.root, "base")
        git(self.root, "mv", "a.txt", "a2.txt")
        want = ["a.txt", "a2.txt"]
        self.assertEqual(sorted(gitinfo.dirty_paths(self.root)), want)
        for value in ("false", "true"):
            git(self.root, "config", "status.renames", value)
            self.assertEqual(sorted(gitinfo.dirty_paths(self.root)), want, value)
        git(self.root, "config", "status.renames", "copies")
        self.assertEqual(sorted(gitinfo.dirty_paths(self.root)), want)
        self.assertEqual(len(gitinfo.dirty_paths(self.root)), 2)

    def test_dirty_paths_ignored_passes(self):  # DP5
        self.put(".gitignore", b"*.log\n")
        commit_all(self.root, "ignore")
        self.put("x.log")
        self.assertEqual(gitinfo.dirty_paths(self.root), [])
        self.put(".git/info/exclude", b"*.tmp\n")
        self.put("y.tmp")
        self.assertEqual(gitinfo.dirty_paths(self.root), [])

    def test_dirty_paths_odd_names(self):  # DP6
        names = ["sp ace.txt", "nl\nname.txt", "café.txt", 'q"uote.txt', "-lead.txt", "t\tab.txt", "back\\slash.txt"]
        for n in names:
            self.put(n)
        self.assertEqual(sorted(gitinfo.dirty_paths(self.root)), sorted(names))
        self.assertEqual(gitinfo.dirty_paths(self.root), porcelain_oracle(self.root))

    def test_dirty_paths_invalid_utf8_name_is_a_gate_error(self):  # DP6
        try:
            with open(os.path.join(os.fsencode(self.root), b"bad\xff.txt"), "wb") as fh:
                fh.write(b"x")
        except OSError:
            self.skipTest("this file system refuses a byte name that is not UTF-8")
        with self.assertRaises(GateError) as e:
            gitinfo.dirty_paths(self.root)
        self.assertEqual(str(e.exception), "git status --porcelain gave output that is not valid UTF-8")

    def test_dirty_paths_untracked_kinds(self):  # DP7
        os.mkdir(os.path.join(self.root, "emptydir"))
        os.symlink("a.txt", os.path.join(self.root, "lnk"))
        inner = os.path.join(self.root, "inner")
        os.mkdir(inner)
        git(inner, "init", "-q", "-b", "main")
        self.put("inner/f.txt")
        os.mkfifo(os.path.join(self.root, "fifo"))
        got = gitinfo.dirty_paths(self.root)
        self.assertNotIn("emptydir", got)
        self.assertEqual(got, porcelain_oracle(self.root))
        self.assertIn("lnk", got)
        self.assertIn("inner/", got)

    def test_dirty_paths_unmerged(self):  # DP8
        self.put("f.txt", b"base\n")
        commit_all(self.root, "base")
        git(self.root, "checkout", "-q", "-b", "side")
        self.put("f.txt", b"side\n")
        commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "main")
        self.put("f.txt", b"main\n")
        commit_all(self.root, "main")
        git(self.root, "merge", "side", check=False)
        self.assertEqual(gitinfo.dirty_paths(self.root), ["f.txt"])

    def test_dirty_paths_ignores_other_worktrees(self):  # DP9, plan :2593
        w = self.linked("other", "ob")
        self.put("x", root=w)
        self.assertEqual(gitinfo.dirty_paths(self.root), [])
        self.assertEqual(gitinfo.dirty_paths(w), ["x"])
        self.put("m", root=self.root)
        self.assertEqual(gitinfo.dirty_paths(self.root), ["m"])
        self.assertEqual(gitinfo.dirty_paths(w), ["x"])

    def test_dirty_paths_inherits_git_index_file(self):  # DP10
        self.put("a.txt", b"one\n")
        commit_all(self.root, "base")
        alt = os.path.join(self.tmp, "alt-index")
        shutil.copy(os.path.join(self.root, ".git", "index"), alt)
        self.put("scratch", b"different\n")
        h = plain_git(self.root, "hash-object", "-w", "scratch").stdout.decode().strip()
        os.remove(os.path.join(self.root, "scratch"))
        env = dict(os.environ, GIT_INDEX_FILE=alt)
        subprocess.run(["git", "-C", self.root, "update-index", "--cacheinfo", "100644,%s,a.txt" % h], env=env, check=True)
        self.assertEqual(gitinfo.dirty_paths(self.root), [])
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            self.assertEqual(gitinfo.dirty_paths(self.root), ["a.txt"])

    def test_dirty_paths_ignores_user_config(self):  # DP11, Global Constraints :33
        self.put("u.txt")
        for key, value in (("status.showUntrackedFiles", "no"), ("status.short", "true"), ("status.branch", "true"),
                           ("core.quotePath", "true"), ("color.status", "always"), ("core.abbrev", "7")):
            git(self.root, "config", key, value)
        self.assertEqual(gitinfo.dirty_paths(self.root), ["u.txt"])

    def test_dirty_paths_call_form(self):  # Global Constraints :33
        calls, patch = spy_runs()
        with patch:
            gitinfo.dirty_paths(self.root)
        st = [(a, e) for a, e in calls if "status" in a]
        self.assertEqual(len(st), 1)
        argv, env = st[0]
        self.assertEqual(argv, ["git", "-c", "core.fsmonitor=false", "-C", self.root, "status", "--porcelain=v1", "-z",
                                "--untracked-files=all", "--ignored=no", "--no-renames", "--ignore-submodules=none"])
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")

    def test_dirty_paths_does_not_write_the_index(self):  # DP12, D-Q8
        self.put("a.txt")
        commit_all(self.root, "base")
        os.utime(os.path.join(self.root, "a.txt"), (1, 1))  # stat-dirty, content equal
        idx = os.path.join(self.root, ".git", "index")
        with open(idx, "rb") as fh:
            before = fh.read()
        self.assertEqual(gitinfo.dirty_paths(self.root), [])
        with open(idx, "rb") as fh:
            self.assertEqual(fh.read(), before)
        plain_git(self.root, "status", "--porcelain=v1")  # the plain call does rewrite it (why the variable is set)
        with open(idx, "rb") as fh:
            self.assertNotEqual(fh.read(), before)

    def test_dirty_paths_root_forms(self):  # DP13
        check_root_forms(self, root_forms(self.tmp, self.root), {"dirty_paths": gitinfo.dirty_paths})

    def test_dirty_paths_root_types(self):  # D-Q14
        for bad in (None, b".", 5, ""):
            with self.assertRaises(GateError) as e:
                gitinfo.dirty_paths(bad)
            self.assertEqual(str(e.exception), "root must be a string")

    def test_dirty_paths_submodule(self):  # DP14, Q7b
        sub = os.path.join(self.tmp, "subsrc")
        os.mkdir(sub)
        git(sub, "init", "-q", "-b", "main")
        git(sub, "config", "user.email", "f@example.invalid")
        git(sub, "config", "user.name", "F")
        self.put("s.txt", root=sub)
        commit_all(sub, "s")
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "mod")
        commit_all(self.root, "add submodule")
        self.assertEqual(gitinfo.dirty_paths(self.root), [])
        self.put("mod/untracked.txt")
        git(self.root, "config", "diff.ignoreSubmodules", "all")
        git(self.root, "config", "submodule.mod.ignore", "all")
        self.assertEqual(gitinfo.dirty_paths(self.root), ["mod"])

    def test_dirty_paths_same_on_both(self):  # DP15, V1, V2
        names = ["uࡰ.txt", "e\U0001fae8.txt"]
        for n in names:
            self.put(n)
        digits = "9" * 255  # the longest name; a 4301-digit path exceeds PATH_MAX (1024) on macOS, so none is built
        self.put(digits)
        got = gitinfo.dirty_paths(self.root)
        self.assertEqual(sorted(got), sorted(names + [digits]))

    def test_dirty_paths_many_paths(self):  # DP16 (3000 files; the call count is what the row pins)
        for i in range(3000):
            self.put("many/f%04d" % i, b"")
        calls, patch = spy_runs()
        with patch:
            got = gitinfo.dirty_paths(self.root)
        self.assertEqual(len(got), 3000)
        self.assertEqual(len([a for a, _ in calls if "status" in a]), 1)


class UpstreamAndRemotes(P13Case):
    def setUp(self):
        super().setUp()
        self.bare = self.bare_remote()

    def push(self):
        git(self.root, "push", "-q", "-u", "origin", "main")

    def test_upstream_sha_none(self):  # UP1
        self.assertIsNone(gitinfo.upstream_sha(self.root))

    def test_upstream_sha_values(self):  # UP2
        self.push()
        pushed = git(self.root, "rev-parse", "HEAD")
        self.assertEqual(gitinfo.upstream_sha(self.root), pushed)
        self.assertEqual(len(gitinfo.upstream_sha(self.root)), 40)
        self.put("a.txt")
        local = commit_all(self.root, "local")
        self.assertEqual(gitinfo.upstream_sha(self.root), pushed)  # behind
        git(self.root, "reset", "-q", "--hard", pushed)
        other = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", self.bare, other)
        git(other, "config", "user.email", "f@example.invalid")
        git(other, "config", "user.name", "F")
        self.put("from-clone", root=other)
        remote_new = commit_all(other, "clone")
        git(other, "push", "-q", "origin", "HEAD:main")
        git(self.root, "fetch", "-q")
        self.assertEqual(gitinfo.upstream_sha(self.root), remote_new)  # ahead
        self.put("b.txt")
        commit_all(self.root, "diverge")
        self.assertEqual(gitinfo.upstream_sha(self.root), remote_new)  # diverged
        self.assertNotEqual(local, remote_new)

    def test_upstream_sha_gone(self):  # UP3
        git(self.root, "checkout", "-q", "-b", "b")
        git(self.root, "push", "-q", "-u", "origin", "b")
        self.assertIsNotNone(gitinfo.upstream_sha(self.root))
        git(self.root, "push", "-q", "origin", ":b")  # git drops the local tracking ref with it
        git(self.root, "fetch", "-q", "--prune")
        self.assertIsNone(gitinfo.upstream_sha(self.root))

    def test_upstream_sha_local_upstream(self):  # UP4
        git(self.root, "checkout", "-q", "-b", "loc")
        git(self.root, "branch", "--set-upstream-to=main")
        self.assertEqual(gitinfo.upstream_sha(self.root), git(self.root, "rev-parse", "main"))

    def test_upstream_sha_follows_configuration_not_name(self):  # UP5
        self.push()
        git(self.root, "checkout", "-q", "-b", "newfeat", "origin/main")
        self.put("n.txt")
        commit_all(self.root, "n")
        git(self.root, "push", "-q", "origin", "newfeat:newfeat")
        self.assertEqual(gitinfo.upstream_sha(self.root), git(self.root, "rev-parse", "origin/main"))
        self.assertNotEqual(gitinfo.upstream_sha(self.root), git(self.root, "rev-parse", "HEAD"))
        git(self.root, "branch", "--set-upstream-to=origin/newfeat")
        self.assertEqual(gitinfo.upstream_sha(self.root), git(self.root, "rev-parse", "HEAD"))

    def test_upstream_sha_detached(self):  # UP6
        self.push()
        git(self.root, "checkout", "-q", "--detach")
        self.assertIsNone(gitinfo.upstream_sha(self.root))

    def test_upstream_sha_odd_names(self):  # UP7
        git(self.root, "checkout", "-q", "-b", "a/b/c")
        git(self.root, "remote", "add", "weird/name", self.bare)
        git(self.root, "push", "-q", "-u", "weird/name", "a/b/c")
        self.assertEqual(gitinfo.upstream_sha(self.root), git(self.root, "rev-parse", "HEAD"))

    def test_upstream_sha_ignores_abbrev_and_color(self):  # UP8
        self.push()
        self.assertRegex(gitinfo.upstream_sha(self.root), r"\A[0-9a-f]{40}\Z")

    def test_upstream_sha_root_forms_and_types(self):
        check_root_forms(self, root_forms(self.tmp, self.root), {"upstream_sha": gitinfo.upstream_sha})
        for bad in (None, 5, b".", ""):
            with self.assertRaises(GateError):
                gitinfo.upstream_sha(bad)

    def test_remotes_none(self):  # RM1
        fresh = os.path.join(self.tmp, "norem")
        os.mkdir(fresh)
        make_repo(fresh)
        self.assertEqual(gitinfo.remotes(fresh), [])

    def test_remotes_names(self):  # RM2
        git(self.root, "remote", "add", "fork", self.bare)
        self.assertEqual(gitinfo.remotes(self.root), ["fork", "origin"])
        self.assertEqual(gitinfo.remotes(self.root), plain_git(self.root, "remote").stdout.decode().split())

    def test_remotes_without_url(self):  # RM3, D-Q12
        git(self.root, "config", "remote.noloc.fetch", "+refs/heads/*:refs/remotes/noloc/*")
        self.assertEqual(gitinfo.remotes(self.root), ["noloc", "origin"])

    def test_remotes_odd_names(self):  # RM4
        git(self.root, "remote", "add", "weird/name", self.bare)
        git(self.root, "remote", "add", "café", self.bare)
        self.assertEqual(sorted(gitinfo.remotes(self.root)), sorted(["origin", "weird/name", "café"]))

    def test_remotes_root_forms(self):  # RM5
        check_root_forms(self, root_forms(self.tmp, self.root), {"remotes": gitinfo.remotes})
        with self.assertRaises(GateError):
            gitinfo.remotes(None)

    def test_remotes_returns_list(self):  # RM6
        got = gitinfo.remotes(self.root)
        self.assertIs(type(got), list)
        self.assertTrue(all(type(x) is str for x in got))



# ======================================================================== Task P2.1 part i: local_branches,
# changed_paths, rev_list, parents, main_worktree (table rows LB1-LB15, CP1-CP21, RL1-RL15, PA1-PA13, WT7-WT9;
# decisions D-A13, D-A13b, D-A14, D-A15, D-A16, D-A23, D-A25)

class _Sub(str):
    pass


HEX40 = "0123456789abcdef0123456789abcdef01234567"
ABSENT40 = "89abcdef0123456789abcdef0123456789abcdef"


def stub_run(name_prefix, stdout):
    """Patch gitinfo._run so that the call whose name starts with ``name_prefix`` returns ``stdout``; every other
    call runs for real."""
    real = gitinfo._run

    def fake(root, name, args, *a, **kw):
        if name.startswith(name_prefix):
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")
        return real(root, name, args, *a, **kw)
    return mock.patch.object(gitinfo, "_run", fake)


class P21Case(P13Case):
    """P13Case's repository (colour always, abbrev 7) plus the merge fixture MR of the table: A, then C on branch
    ``side`` (committed before B), B on main (renames x to y, deletes z, adds ``sp ace.txt`` and ``nl\\nname.txt``), then
    M = ``git merge --no-ff side`` (parents B, C)."""

    def build_mr(self):
        r = self.root
        self.put("x", b"x\n")
        self.put("z", b"z\n")
        self.A = commit_all(r, "A")
        git(r, "checkout", "-q", "-b", "side")
        self.put("c.txt", b"c\n")
        self.C = commit_all(r, "C")
        git(r, "checkout", "-q", "main")
        git(r, "mv", "x", "y")
        git(r, "rm", "-q", "z")
        self.put("sp ace.txt")
        self.put("nl\nname.txt")
        self.B = commit_all(r, "B")
        git(r, "merge", "-q", "--no-ff", "-m", "M", "side")
        self.M = git(r, "rev-parse", "HEAD")

    def fast_import(self, text, root=None):
        p = subprocess.run(["git", "-C", root or self.root, "fast-import", "--quiet"], input=text.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)

    def chain(self, ref, n, base=None):
        """n empty commits on refs/heads/<ref>, the first on ``base`` (a sha) or a root commit."""
        out = []
        for i in range(1, n + 1):
            msg = "c%d" % i
            out.append("commit refs/heads/%s\ncommitter F <f@example.invalid> %d +0000\ndata %d\n%s\n"
                       % (ref, 1700000000 + i, len(msg), msg))
            if i == 1 and base:
                out.append("from %s\n" % base)
            out.append("\n")
        self.fast_import("".join(out))

    def shallow_clone(self):
        dest = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, dest)
        return dest


class LocalBranches(P21Case):
    def oracle(self, root):
        out = plain_git(root, "for-each-ref", "--format=%(refname)", "refs/heads").stdout.decode("utf-8")
        return sorted(n[len("refs/heads/"):] for n in out.split("\n") if n)

    def test_local_branches_sorted(self):  # LB1
        self.assertEqual(gitinfo.local_branches(self.root), ["main"])
        for b in ("a/b", "a-b", "Zed", "café"):
            git(self.root, "branch", b)
        got = gitinfo.local_branches(self.root)
        self.assertEqual(got, ["Zed", "a-b", "a/b", "café", "main"])
        self.assertEqual(got, self.oracle(self.root))

    def test_local_branches_tag_of_same_name(self):  # LB2, D-A13: --format=%(refname:short) prints heads/feat here
        git(self.root, "branch", "feat")
        git(self.root, "tag", "feat")
        self.assertEqual(gitinfo.local_branches(self.root), ["feat", "main"])
        short = plain_git(self.root, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.decode().split()
        self.assertIn("heads/feat", short)  # the plan's command text would give the wrong name

    def test_local_branches_unborn(self):  # LB3
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "trunk")
        self.assertEqual(gitinfo.local_branches(fresh), [])

    def test_local_branches_detached(self):  # LB4
        git(self.root, "branch", "other")
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(gitinfo.local_branches(self.root), ["main", "other"])

    def test_local_branches_mid_merge(self):  # LB5
        r = self.root
        git(r, "checkout", "-q", "-b", "c1")
        self.put("f", b"1\n")
        commit_all(r, "c1")
        git(r, "checkout", "-q", "main")
        self.put("f", b"2\n")
        commit_all(r, "m2")
        git(r, "merge", "-q", "c1", check=False)
        self.assertTrue(os.path.exists(os.path.join(r, ".git", "MERGE_HEAD")))
        self.assertEqual(gitinfo.local_branches(r), ["c1", "main"])

    def test_local_branches_packed(self):  # LB6
        git(self.root, "branch", "p/q")
        git(self.root, "pack-refs", "--all")
        self.assertEqual(gitinfo.local_branches(self.root), ["main", "p/q"])

    def test_local_branches_hexlike(self):  # LB7
        git(self.root, "branch", HEX40)
        self.assertEqual(gitinfo.local_branches(self.root), [HEX40, "main"])

    def test_local_branches_unexpected_ref(self):  # a ref outside refs/heads/ is a GateError, never a name
        with stub_run("for-each-ref", b"refs/heads/ok\nrefs/tags/t\n"):
            with self.assertRaises(GateError) as cm:
                gitinfo.local_branches(self.root)
        self.assertIn("unexpected ref", str(cm.exception))

    def test_local_branches_non_utf8(self):  # LB8 (the name cannot be created on APFS: stubbed output)
        with stub_run("for-each-ref", b"refs/heads/bad\xff\n"):
            with self.assertRaises(GateError) as cm:
                gitinfo.local_branches(self.root)
        self.assertIn("not valid UTF-8", str(cm.exception))

    def test_local_branches_ignore_colour_and_abbrev_config(self):  # LB9, plan :2703
        git(self.root, "branch", "20261101-x/integration")
        want = ["20261101-x/integration", "main"]
        self.assertEqual(gitinfo.local_branches(self.root), want)
        self.assertEqual(self.oracle(self.root), want)
        self.assertEqual(plain_git(self.root, "config", "color.ui").stdout.strip(), b"always")
        calls, patch = spy_runs()
        with patch:
            gitinfo.local_branches(self.root)
        argv = [a for a, _ in calls if "for-each-ref" in a][0]
        self.assertIn("--no-color", argv)
        self.assertIn("--format=%(refname)", argv)

    def test_local_branches_root_forms(self):  # LB10
        check_root_forms(self, root_forms(self.tmp, self.root), {"local_branches": gitinfo.local_branches})

    def test_local_branches_root_types(self):  # LB11
        for bad in (None, b".", 5, "", _Sub(".")):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.local_branches(bad)
                self.assertEqual(str(cm.exception), "root must be a string")

    def test_local_branches_env(self):  # LB12
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        git(other, "branch", "only-other")
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(other, ".git"), "GIT_INDEX_FILE": "/x/idx"}):
            calls, patch = spy_runs()
            with patch:
                got = gitinfo.local_branches(self.root)
        self.assertEqual(got, ["main"])
        env = [e for a, e in calls if "for-each-ref" in a][0]
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["GIT_INDEX_FILE"], "/x/idx")

    def test_local_branches_linked_worktree(self):  # LB13
        wt = self.linked("lw", branch="in-wt")
        self.assertEqual(gitinfo.local_branches(wt), gitinfo.local_branches(self.root))
        self.assertIn("in-wt", gitinfo.local_branches(wt))

    def test_local_branches_many(self):  # LB14
        text = "".join("create refs/heads/b%05d HEAD\n" % i for i in range(5000))
        p = subprocess.run(["git", "-C", self.root, "update-ref", "--stdin"], input=text.encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        calls, patch = spy_runs()
        with patch:
            got = gitinfo.local_branches(self.root)
        self.assertEqual(len(got), 5001)
        self.assertEqual(len([a for a, _ in calls if "for-each-ref" in a]), 1)

    def test_local_branches_returns_list(self):  # LB15
        a = gitinfo.local_branches(self.root)
        self.assertIs(type(a), list)
        self.assertTrue(all(type(x) is str for x in a))
        a.append("x")
        self.assertEqual(gitinfo.local_branches(self.root), ["main"])


class ChangedPaths(P21Case):
    def setUp(self):
        super().setUp()
        self.build_mr()

    def oracle(self, a, b=None):
        args = ["diff", "--name-only", "-z", "--no-renames", a] + ([b] if b else [])
        return sorted(e.decode("utf-8") for e in plain_git(self.root, *args).stdout.split(b"\0") if e)

    def test_changed_paths_rename_both_sides(self):  # CP1, plan :2716
        want = ["nl\nname.txt", "sp ace.txt", "x", "y", "z"]
        self.assertEqual(gitinfo.changed_paths(self.root, self.A, self.B), want)
        self.assertEqual(self.oracle(self.A, self.B), want)
        # git's own default (renames on, no flag) lists the pair as one path: the two sides are the flag's doing
        renames_on = plain_git(self.root, "diff", "--name-only", "-z", self.A, self.B).stdout
        self.assertNotIn(b"x\0", renames_on)

    def test_changed_paths_ignores_rename_config(self):  # CP2
        for v in ("copies", "true", "false"):
            git(self.root, "config", "diff.renames", v)
            self.assertEqual(gitinfo.changed_paths(self.root, self.A, self.B),
                             ["nl\nname.txt", "sp ace.txt", "x", "y", "z"])

    def test_changed_paths_deletion(self):  # CP3
        self.assertIn("z", gitinfo.changed_paths(self.root, self.A, self.B))

    def test_changed_paths_working_tree(self):  # CP4
        self.put("y", b"changed\n")
        self.assertEqual(gitinfo.changed_paths(self.root, self.M, None), ["y"])
        self.assertEqual(self.oracle(self.M, None), ["y"])

    def test_changed_paths_untracked_not_listed(self):  # CP5
        self.put("untracked.txt")
        self.assertEqual(gitinfo.changed_paths(self.root, self.M, None), [])

    def test_changed_paths_odd_names(self):  # CP6
        names = ["café.txt", "-dash.txt", '"q".txt', "tab\tname.txt", "sp ace2.txt", "nl\nname2.txt"]
        base = git(self.root, "rev-parse", "HEAD")
        for n in names:
            self.put(n)
        head = commit_all(self.root, "odd")
        self.assertEqual(gitinfo.changed_paths(self.root, base, head), sorted(names))
        git(self.root, "config", "core.quotePath", "true")
        self.assertEqual(gitinfo.changed_paths(self.root, base, head), sorted(names))

    def test_changed_paths_non_utf8(self):  # CP7 (cannot be created on APFS: stubbed output)
        with stub_run("diff --name-only", b"a\xff\0"):
            with self.assertRaises(GateError) as cm:
                gitinfo.changed_paths(self.root, self.A, self.B)
        self.assertIn("not valid UTF-8", str(cm.exception))

    def test_changed_paths_revision_forms(self):  # CP8
        git(self.root, "tag", "tb", self.B)
        for a, b in ((self.A, self.B), (self.A[:7], self.B[:7]), (self.A, "tb"), (self.M + "^1", self.M + "^2"),
                     (self.A, "main~1")):
            with self.subTest(a=a, b=b):
                self.assertEqual(gitinfo.changed_paths(self.root, a, b), self.oracle(a, b))
        self.assertEqual(gitinfo.changed_paths(self.root, self.A, "tb"), ["nl\nname.txt", "sp ace.txt", "x", "y", "z"])
        self.assertEqual(gitinfo.changed_paths(self.root, "HEAD", "HEAD"), [])

    def test_changed_paths_refused_revisions(self):  # CP9
        for bad in ("-x", "^x", "a" * 41):
            with self.subTest(bad=bad[:6]):
                with self.assertRaises(GateError):
                    gitinfo.changed_paths(self.root, bad, self.B)
                with self.assertRaises(GateError):
                    gitinfo.changed_paths(self.root, self.A, bad)

    def test_changed_paths_revision_named_like_a_file(self):  # CP10: without a trailing -- git exits 128
        self.put("main", b"f\n")
        commit_all(self.root, "file named main")
        self.assertEqual(plain_git(self.root, "diff", "--name-only", "main", "HEAD", check=False).returncode, 128)
        self.assertEqual(gitinfo.changed_paths(self.root, "main", "HEAD"), [])
        self.assertEqual(gitinfo.changed_paths(self.root, self.M, "main"), ["main"])

    def test_changed_paths_unknown_object(self):  # CP11
        with self.assertRaises(GateError) as cm:
            gitinfo.changed_paths(self.root, ABSENT40, self.B)
        self.assertEqual(str(cm.exception), "git diff --name-only failed (exit 128)")
        tree = git(self.root, "rev-parse", self.A + "^{tree}")
        self.assertEqual(gitinfo.changed_paths(self.root, tree, self.A), [])

    def test_changed_paths_equal(self):  # CP12
        self.assertEqual(gitinfo.changed_paths(self.root, self.B, self.B), [])

    def test_changed_paths_merge_commit_first_parent(self):  # CP13
        self.assertEqual(gitinfo.changed_paths(self.root, self.M + "^1", self.M), ["c.txt"])
        self.assertEqual(gitinfo.changed_paths(self.root, self.M + "^2", self.M),
                         ["nl\nname.txt", "sp ace.txt", "x", "y", "z"])

    def test_changed_paths_index_settings(self):  # CP14, D-A14: the settings are passed; see the report (measured)
        calls, patch = spy_runs()
        with patch:
            gitinfo.changed_paths(self.root, self.M, None)
        argv, env = [(a, e) for a, e in calls if "diff" in a][0]
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertIn("core.fsmonitor=false", argv)
        # Measured with git 2.50.1: git diff <rev> against the work tree refreshes .git/index of a stat-dirty file even
        # under GIT_OPTIONAL_LOCKS=0, so the bytes may change; what the index records (modes, ids, stages) never does.
        os.utime(os.path.join(self.root, "y"), (1, 1))
        before = git(self.root, "ls-files", "-s")
        self.assertEqual(gitinfo.changed_paths(self.root, self.M, None), [])
        self.assertEqual(git(self.root, "ls-files", "-s"), before)

    def test_changed_paths_ignore_user_config(self):  # CP15, plan :2716 (colour_root)
        ext = os.path.join(self.tmp, "ext.sh")
        with open(ext, "w") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(ext, 0o755)
        for k, v in (("diff.external", ext), ("diff.noprefix", "true"), ("core.quotePath", "true"),
                     ("diff.renames", "true"), ("diff.mnemonicPrefix", "true")):
            git(self.root, "config", k, v)
        self.assertEqual(gitinfo.changed_paths(self.root, self.A, self.B), ["nl\nname.txt", "sp ace.txt", "x", "y", "z"])
        calls, patch = spy_runs()
        with patch:
            gitinfo.changed_paths(self.root, self.A, self.B)
        argv = [a for a, _ in calls if "diff" in a][0]
        for flag in ("--no-color", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv"):
            self.assertIn(flag, argv)

    def test_changed_paths_ignores_replace_refs(self):  # CP16, D-A16
        git(self.root, "replace", self.B, self.C)
        self.assertNotEqual(plain_git(self.root, "diff", "--name-only", "-z", self.M + "^1", self.M).stdout, b"c.txt\0")
        self.assertEqual(gitinfo.changed_paths(self.root, self.M + "^1", self.M), ["c.txt"])

    def test_changed_paths_shallow_missing_parent(self):  # CP17
        dest = self.shallow_clone()
        with self.assertRaises(GateError):
            gitinfo.changed_paths(dest, self.A, self.M)

    def test_changed_paths_gitlink(self):  # CP18
        base = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,sub" % self.A)
        git(self.root, "commit", "-q", "-m", "gitlink")
        link = git(self.root, "rev-parse", "HEAD")
        git(self.root, "rm", "-q", "--cached", "sub")
        self.put("sub", b"file now\n")
        file_commit = commit_all(self.root, "file")
        self.assertEqual(gitinfo.changed_paths(self.root, base, link), ["sub"])
        self.assertEqual(gitinfo.changed_paths(self.root, link, file_commit), ["sub"])

    def test_changed_paths_root_forms_and_types(self):  # CP19
        check_root_forms(self, root_forms(self.tmp, self.root),
                         {"changed_paths": lambda p: gitinfo.changed_paths(p, "HEAD", "HEAD")})
        for bad in (None, b".", 5, "", _Sub(".")):
            with self.assertRaises(GateError) as cm:
                gitinfo.changed_paths(bad, "HEAD", "HEAD")
            self.assertEqual(str(cm.exception), "root must be a string")

    def test_changed_paths_b_types(self):  # CP20 (and the same for a, plus the empty revision of CP9)
        for bad in ("", b"x", 5, _Sub("HEAD"), True):
            with self.subTest(b=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.changed_paths(self.root, "HEAD", bad)
                self.assertEqual(str(cm.exception), "b must be None or a non-empty string")
            with self.subTest(a=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.changed_paths(self.root, bad, "HEAD")
                self.assertEqual(str(cm.exception), "a must be a non-empty string")

    def test_changed_paths_same_on_both(self):  # CP21
        names = ["Ⱟ.txt", "ࡰ.txt", "Ꟁ.txt"]
        base = git(self.root, "rev-parse", "HEAD")
        for n in names:
            self.put(n)
        head = commit_all(self.root, "u")
        self.assertEqual(gitinfo.changed_paths(self.root, base, head), sorted(names))


class RevList(P21Case):
    def setUp(self):
        super().setUp()
        self.build_mr()

    def test_rev_list_oldest_first(self):  # RL1, D-A13b: --reverse alone gives [C, B, M] on this fixture
        self.assertEqual(gitinfo.rev_list(self.root, self.A, self.M), [self.B, self.C, self.M])
        plain = plain_git(self.root, "rev-list", "--reverse", "%s..%s" % (self.A, self.M)).stdout.decode().split()
        self.assertEqual(plain, [self.C, self.B, self.M])  # the shape D-A13b rules out
        topo = plain_git(self.root, "rev-list", "--topo-order", "--reverse", "%s..%s" % (self.A, self.M))
        self.assertEqual(topo.stdout.decode().split(), [self.B, self.C, self.M])

    def test_rev_list_first_parent(self):  # RL2
        self.assertEqual(gitinfo.rev_list(self.root, self.A, self.M, first_parent=True), [self.B, self.M])

    def test_rev_list_equal(self):  # RL3
        self.assertEqual(gitinfo.rev_list(self.root, self.M, self.M), [])
        self.assertEqual(gitinfo.rev_list(self.root, self.M, self.M, first_parent=True), [])

    def test_rev_list_a_not_an_ancestor(self):  # RL4
        self.assertEqual(gitinfo.rev_list(self.root, self.M, self.A), [])

    def test_rev_list_unrelated(self):  # RL5
        self.chain("orphan", 2)
        tip = git(self.root, "rev-parse", "orphan")
        first = git(self.root, "rev-parse", "orphan~1")
        self.assertEqual(gitinfo.rev_list(self.root, self.M, "orphan"), [first, tip])

    def test_rev_list_revision_named_like_a_file(self):  # RL16: a range names no path, so git exits 0 even without --
        self.put("main", b"f\n")
        tip = commit_all(self.root, "file named main")
        self.assertEqual(plain_git(self.root, "rev-list", "%s..main" % self.M, check=False).returncode, 0)
        self.assertEqual(gitinfo.rev_list(self.root, self.M, "main"), [tip])

    def test_rev_list_range_named_like_a_file(self):  # RL17, F-20261118-2j6r: plan :33 "`--` before paths"
        git(self.root, "branch", "x", self.A)
        git(self.root, "branch", "y", self.M)
        self.put("x..y", b"f\n")
        commit_all(self.root, "file named x..y")
        bare = plain_git(self.root, "rev-list", "x..y", check=False)
        self.assertEqual(bare.returncode, 128)  # without --, git refuses: both revision and filename
        self.assertIn(b"ambiguous argument 'x..y'", bare.stderr)
        plain = plain_git(self.root, "rev-list", "--topo-order", "--reverse", "x..y", "--")
        want = [self.B, self.C, self.M]  # written here: the commits of M not in A, parents first
        self.assertEqual(plain.stdout.decode().split(), want)
        self.assertEqual(gitinfo.rev_list(self.root, "x", "y"), want)
        self.assertEqual(gitinfo.rev_list(self.root, "x", "y", first_parent=True), [self.B, self.M])

    def test_rev_list_unknown_revision(self):  # RL6
        for a, b in ((self.A, "nosuch"), (ABSENT40, self.M)):
            with self.subTest(a=a[:6], b=b[:6]):
                with self.assertRaises(GateError) as cm:
                    gitinfo.rev_list(self.root, a, b)
                self.assertEqual(str(cm.exception), "git rev-list failed (exit 128)")

    def test_rev_list_clock_skew(self):  # RL7: a child dated before its parent still comes after it
        r = self.root
        self.put("s1")
        env1 = {"GIT_COMMITTER_DATE": "2026-03-01T00:00:00+0000", "GIT_AUTHOR_DATE": "2026-03-01T00:00:00+0000"}
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "late parent", env=env1)
        p = git(r, "rev-parse", "HEAD")
        self.put("s2")
        env2 = {"GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000"}
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "early child", env=env2)
        q = git(r, "rev-parse", "HEAD")
        self.assertEqual(gitinfo.rev_list(r, self.M, q), [p, q])

    def test_rev_list_octopus(self):  # RL8
        r = self.root
        for b in ("o1", "o2"):
            git(r, "checkout", "-q", "-b", b, "main")
            self.put(b + ".txt")
            commit_all(r, b)
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "oct", "o1", "o2")
        o = git(r, "rev-parse", "HEAD")
        o1, o2 = git(r, "rev-parse", "o1"), git(r, "rev-parse", "o2")
        got = gitinfo.rev_list(r, self.M, o)
        self.assertEqual(sorted(got), sorted([o1, o2, o]))
        self.assertEqual(got[-1], o)
        self.assertEqual(gitinfo.rev_list(r, self.M, o, first_parent=True), [o])

    def test_rev_list_refused_revisions(self):  # RL9
        for bad in ("-x", "^x", "a" * 41):
            with self.subTest(bad=bad[:6]):
                with self.assertRaises(GateError):
                    gitinfo.rev_list(self.root, bad, self.M)
                with self.assertRaises(GateError):
                    gitinfo.rev_list(self.root, self.A, bad)
        for bad in ("", b"x", 5, None, _Sub("HEAD")):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.rev_list(self.root, bad, self.M)
                self.assertEqual(str(cm.exception), "a must be a non-empty string")
                with self.assertRaises(GateError) as cm:
                    gitinfo.rev_list(self.root, self.A, bad)
                self.assertEqual(str(cm.exception), "b must be a non-empty string")

    def test_rev_list_shallow(self):  # RL10
        dest = self.shallow_clone()
        with self.assertRaises(GateError):
            gitinfo.rev_list(dest, self.A, self.M)

    def test_rev_list_first_parent_type(self):  # RL11
        for bad in (1, 0, None, "yes", _Sub("x")):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.rev_list(self.root, self.A, self.M, first_parent=bad)
                self.assertEqual(str(cm.exception), "first_parent must be a bool")

    def test_rev_list_many(self):  # RL12
        self.chain("big", 20000, base=self.M)
        got = gitinfo.rev_list(self.root, self.M, "big")
        self.assertEqual(len(got), 20000)
        self.assertTrue(all(len(x) == 40 for x in got))
        self.assertEqual(got[-1], git(self.root, "rev-parse", "big"))

    def test_rev_list_ignores_user_config(self):  # RL13
        self.assertEqual(gitinfo.rev_list(self.root, self.A, self.M), [self.B, self.C, self.M])  # colour, abbrev 7
        git(self.root, "replace", self.B, self.C)
        self.assertEqual(gitinfo.rev_list(self.root, self.A, self.M, first_parent=True), [self.B, self.M])
        calls, patch = spy_runs()
        with patch:
            gitinfo.rev_list(self.root, self.A, self.M)
        argv = [a for a, _ in calls if "rev-list" in a][0]
        self.assertIn("--no-replace-objects", argv)

    def test_rev_list_head_states(self):  # RL14
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(gitinfo.rev_list(self.root, self.A, self.M), [self.B, self.C, self.M])
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "trunk")
        with self.assertRaises(GateError):
            gitinfo.rev_list(fresh, "HEAD", "HEAD")

    def test_rev_list_root_forms(self):  # RL15
        check_root_forms(self, root_forms(self.tmp, self.root),
                         {"rev_list": lambda p: gitinfo.rev_list(p, "HEAD", "HEAD")})
        with self.assertRaises(GateError) as cm:
            gitinfo.rev_list(None, "HEAD", "HEAD")
        self.assertEqual(str(cm.exception), "root must be a string")


class LsTreeEntries(P21Case):
    """``ls_tree_entries`` (F-20261118-bc74, D-A9): every entry directly under a folder at a ref with its mode and
    type, against the plain ``git ls-tree`` output. The folder ``requests`` holds a regular file, an executable, a
    gitlink, a symlink and a subfolder; ``ls_tree`` (unchanged) lists only the two regular files."""

    NAMES = ["a.yml", "e.yml", "g", "l.yml", "sub"]
    WANT = [("100644", "blob", "requests/a.yml"), ("100755", "blob", "requests/e.yml"),
            ("160000", "commit", "requests/g"), ("120000", "blob", "requests/l.yml"),
            ("040000", "tree", "requests/sub")]

    def setUp(self):
        super().setUp()
        r = self.root
        self.put("requests/a.yml")
        self.put("requests/e.yml")
        os.chmod(os.path.join(r, "requests/e.yml"), 0o755)
        os.symlink("a.yml", os.path.join(r, "requests", "l.yml"))
        self.put("requests/sub/x.yml")
        self.put("other/o.yml")
        git(r, "add", "-A")
        git(r, "update-index", "--add", "--cacheinfo", "160000,%s,requests/g" % ("1" * 40))
        git(r, "commit", "-q", "-m", "requests")
        self.head = git(r, "rev-parse", "HEAD")

    def test_entries_modes_types_names(self):
        got = gitinfo.ls_tree_entries(self.root, "HEAD", "requests")
        self.assertEqual(got, self.WANT)
        plain = plain_git(self.root, "ls-tree", "--full-tree", "HEAD", "--", "requests/").stdout.decode()
        lines = [l.split(" ", 2)[:2] + [l.split("\t", 1)[1]] for l in plain.split("\n") if l]
        self.assertEqual([tuple(x) for x in lines], self.WANT)   # the same three fields as the plain command

    def test_entries_by_sha_and_branch(self):
        for ref in (self.head, self.head[:7], "main", "refs/heads/main"):
            with self.subTest(ref=ref):
                self.assertEqual(gitinfo.ls_tree_entries(self.root, ref, "requests"), self.WANT)

    def test_ls_tree_unchanged(self):
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "requests"), ["requests/a.yml", "requests/e.yml"])

    def test_entries_only_direct_children(self):
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "requests/sub"),
                         [("100644", "blob", "requests/sub/x.yml")])
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "other"), [("100644", "blob", "other/o.yml")])

    def test_entries_root_missing_and_non_folder(self):
        top = gitinfo.ls_tree_entries(self.root, "HEAD", "")
        names = plain_git(self.root, "ls-tree", "--name-only", "HEAD").stdout.decode().split("\n")
        self.assertEqual([n for _, _, n in top], [n for n in names if n])
        self.assertIn(("040000", "tree", "requests"), top)
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "nope"), [])
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "requests/a.yml"), [])   # a file is no folder
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "requests/l.yml"), [])   # nor is a symlink
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "req"), [])              # no prefix match

    def test_entries_odd_names(self):
        names = ["sp ace.yml", "nl\nname.yml", "tab\tname.yml", "é.yml", "-lead.yml", "gl*ob.yml"]
        for n in names:
            self.put("odd/" + n)
        commit_all(self.root, "odd names")
        got = gitinfo.ls_tree_entries(self.root, "HEAD", "odd")
        self.assertEqual(sorted(got), sorted(("100644", "blob", "odd/" + n) for n in names))
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "odd/gl*"), [])    # a literal path, no glob
        self.put("-dir/f.yml")
        commit_all(self.root, "folder named like an option")
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "-dir"), [("100644", "blob", "-dir/f.yml")])

    def test_entries_unreadable_output(self):
        for bad in (b"garbage\0", b"100644 blob\tx\0", b"100644 blob abc def\tx\0"):
            with self.subTest(bad=bad):
                with stub_run("ls-tree", bad):
                    with self.assertRaises(GateError) as cm:
                        gitinfo.ls_tree_entries(self.root, "HEAD", "requests")
                self.assertEqual(str(cm.exception), "git ls-tree gave an entry that cannot be read")
        with stub_run("ls-tree", b"100644 blob abc\tbad\xff\0"):
            with self.assertRaises(GateError) as cm:
                gitinfo.ls_tree_entries(self.root, "HEAD", "requests")
        self.assertIn("not valid UTF-8", str(cm.exception))

    def test_entries_arguments(self):
        calls, patch = spy_runs()
        with patch:
            gitinfo.ls_tree_entries(self.root, "HEAD", "requests")
        argv = [a for a, _ in calls if "ls-tree" in a][0]
        for want in ("--no-replace-objects", "--literal-pathspecs", "-z", "--full-tree", "--"):
            self.assertIn(want, argv)
        self.assertEqual(argv[-2:], ["--", "requests/"])
        self.assertEqual(argv[argv.index("-C") + 1], self.root)

    def test_entries_ignore_user_config_and_replace(self):
        self.assertEqual(plain_git(self.root, "config", "color.ui").stdout.strip(), b"always")
        self.assertEqual(plain_git(self.root, "config", "core.abbrev").stdout.strip(), b"7")
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "requests"), self.WANT)
        # a replace ref for the tree of requests: git replace makes the real listing differ without the option
        t_req = git(self.root, "rev-parse", "HEAD:requests")
        t_other = git(self.root, "rev-parse", "HEAD:other")
        git(self.root, "replace", t_req, t_other)
        self.assertEqual(gitinfo.ls_tree_entries(self.root, "HEAD", "requests"), self.WANT)

    def test_entries_refused(self):
        for bad in ("-x", "^x", "a" * 41):
            with self.subTest(ref=bad[:6]):
                with self.assertRaises(GateError):
                    gitinfo.ls_tree_entries(self.root, bad, "requests")
        for bad in ("", b"x", 5, None, _Sub("HEAD")):
            with self.subTest(ref=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.ls_tree_entries(self.root, bad, "requests")
                self.assertEqual(str(cm.exception), "ref must be a non-empty string")
        for bad in (".", "./a", "a/.", "a//b", "requests/", "/requests", "..", "requests/../other"):
            with self.subTest(directory=bad):
                with self.assertRaises(GateError):
                    gitinfo.ls_tree_entries(self.root, "HEAD", bad)
        for bad in (None, 5, b"x", _Sub("requests")):
            with self.subTest(directory=repr(bad)):
                with self.assertRaises(GateError) as cm:
                    gitinfo.ls_tree_entries(self.root, "HEAD", bad)
                self.assertEqual(str(cm.exception), "directory must be a string")
        with self.assertRaises(GateError):
            gitinfo.ls_tree_entries(self.root, "nosuchref", "requests")
        with self.assertRaises(GateError):
            gitinfo.ls_tree_entries(self.root, ABSENT40, "requests")

    def test_entries_root_forms(self):
        check_root_forms(self, root_forms(self.tmp, self.root),
                         {"ls_tree_entries": lambda p: gitinfo.ls_tree_entries(p, "HEAD", "requests")})
        with self.assertRaises(GateError) as cm:
            gitinfo.ls_tree_entries(None, "HEAD", "requests")
        self.assertEqual(str(cm.exception), "root must be a string")
        sub = os.path.join(self.root, "requests")
        with self.assertRaises(GateError) as cm:
            gitinfo.ls_tree_entries(sub, "HEAD", "requests")
        self.assertIn("top level", str(cm.exception))


class Parents(P21Case):
    def setUp(self):
        super().setUp()
        self.build_mr()

    def test_parents_root(self):  # PA1
        first = git(self.root, "rev-list", "--max-parents=0", "HEAD")
        self.assertEqual(gitinfo.parents(self.root, first), [])

    def test_parents_one(self):  # PA2
        self.assertEqual(gitinfo.parents(self.root, self.B), [self.A])

    def test_parents_merge(self):  # PA3, plan :2716
        self.assertEqual(gitinfo.parents(self.root, self.M), [self.B, self.C])
        self.assertEqual(plain_git(self.root, "cat-file", "-p", self.M).stdout.decode().count("\nparent "), 2)

    def test_parents_octopus(self):  # PA4
        r = self.root
        for b in ("o1", "o2"):
            git(r, "checkout", "-q", "-b", b, "main")
            self.put(b + ".txt")
            commit_all(r, b)
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "oct", "o1", "o2")
        o = git(r, "rev-parse", "HEAD")
        self.assertEqual(gitinfo.parents(r, o), [self.M, git(r, "rev-parse", "o1"), git(r, "rev-parse", "o2")])

    def test_parents_non_commit(self):  # PA5, D-A15: an unpeeled call prints nothing for a tree
        tree = git(self.root, "rev-parse", self.M + "^{tree}")
        blob = git(self.root, "rev-parse", self.M + ":y")
        unpeeled = plain_git(self.root, "rev-list", "--parents", "-n", "1", tree)
        self.assertEqual((unpeeled.returncode, unpeeled.stdout), (0, b""))  # silent: no commit, no error
        for bad in (tree, blob):
            with self.subTest(bad=bad[:7]):
                with self.assertRaises(GateError):
                    gitinfo.parents(self.root, bad)

    def test_parents_unknown(self):  # PA6
        for bad in ("0" * 40, ABSENT40):
            with self.assertRaises(GateError):
                gitinfo.parents(self.root, bad)

    def test_parents_short_sha(self):  # PA7
        self.assertEqual(gitinfo.parents(self.root, self.M[:7]), [self.B, self.C])
        self.assertEqual(gitinfo.parents(self.root, "main"), [self.B, self.C])
        self.chain("many", 2500, base=self.M)
        seen = {}
        clash = None
        for sha in git(self.root, "rev-list", "many").split():
            if sha[:4] in seen:
                clash = sha[:4]
                break
            seen[sha[:4]] = sha
        self.assertIsNotNone(clash)
        with self.assertRaises(GateError):
            gitinfo.parents(self.root, clash)

    def test_parents_shallow_boundary(self):  # PA8: a stated limit; the tip of a shallow clone reads as a root
        dest = self.shallow_clone()
        self.assertEqual(plain_git(dest, "cat-file", "-p", "HEAD").stdout.decode().count("\nparent "), 2)
        self.assertEqual(gitinfo.parents(dest, "HEAD"), [])

    def test_parents_ignores_replace_refs(self):  # PA9
        git(self.root, "replace", self.B, self.C)
        self.assertEqual(gitinfo.parents(self.root, self.B), [self.A])
        calls, patch = spy_runs()
        with patch:
            gitinfo.parents(self.root, self.B)
        self.assertIn("--no-replace-objects", [a for a, _ in calls if "rev-list" in a][0])

    def test_parents_refused(self):  # PA10
        for bad in ("-x", "^x", "a" * 41, ""):
            with self.subTest(bad=bad[:6]):
                with self.assertRaises(GateError):
                    gitinfo.parents(self.root, bad)

    def test_parents_sha_types(self):  # PA11
        for bad in (None, b"x", 5, _Sub(self.M)):
            with self.subTest(bad=repr(bad)[:12]):
                with self.assertRaises(GateError) as cm:
                    gitinfo.parents(self.root, bad)
                self.assertEqual(str(cm.exception), "sha must be a string")

    def test_parents_root_forms_and_config(self):  # PA12
        check_root_forms(self, root_forms(self.tmp, self.root), {"parents": lambda p: gitinfo.parents(p, "HEAD")})
        with self.assertRaises(GateError) as cm:
            gitinfo.parents(None, "HEAD")
        self.assertEqual(str(cm.exception), "root must be a string")
        got = gitinfo.parents(self.root, self.M)  # core.abbrev=7 and colour in the repository config
        self.assertTrue(all(len(x) == 40 for x in got))

    def test_parents_returns_list(self):  # PA13
        got = gitinfo.parents(self.root, self.M)
        self.assertIs(type(got), list)
        got.append("x")
        self.assertEqual(gitinfo.parents(self.root, self.M), [self.B, self.C])


class PlanFixture(P21Case):
    """The fixture of the plan's test :2715-2716, written out with its own expected values: A the root commit, then B
    renaming x to y and deleting z, then M merging B and C; once in a plain repository and once in one whose config sets
    ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7``."""

    def history(self, name, colour):
        root = os.path.join(self.tmp, name)
        os.mkdir(root)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "commit.gpgsign", "false")
        if colour:
            for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
                git(root, "config", k, v)
        self.put("x", root=root)
        self.put("z", root=root)
        a = commit_all(root, "A")
        git(root, "checkout", "-q", "-b", "side")
        self.put("c.txt", root=root)
        c = commit_all(root, "C")
        git(root, "checkout", "-q", "main")
        git(root, "mv", "x", "y")
        git(root, "rm", "-q", "z")
        b = commit_all(root, "B")
        git(root, "merge", "-q", "--no-ff", "-m", "M", "side")
        return root, a, b, c, git(root, "rev-parse", "HEAD")

    def test_changed_paths_rev_list_parents(self):  # plan :2715-2716, owner answer Q-F80W-21 (a)
        for name, colour in (("plain", False), ("colour", True)):
            with self.subTest(repository=name):
                root, a, b, c, m = self.history(name, colour)
                self.assertEqual(gitinfo.changed_paths(root, a, b), ["x", "y", "z"])
                self.assertEqual(gitinfo.rev_list(root, a, m), [b, c, m])
                self.assertEqual(gitinfo.rev_list(root, a, m, first_parent=True), [b, m])
                self.assertEqual(gitinfo.rev_list(root, m, m), [])
                self.assertEqual(gitinfo.parents(root, a), [])
                self.assertEqual(gitinfo.parents(root, m), [b, c])


class MainWorktree(P21Case):
    def test_main_worktree_of_the_main_checkout(self):  # WT7 (main), D-A25
        self.assertEqual(os.path.realpath(gitinfo.main_worktree(self.root)), os.path.realpath(self.root))

    def test_main_worktree_of_a_linked_worktree(self):  # WT7 (linked)
        wt = self.linked("lw2", branch="lw2")
        got = gitinfo.main_worktree(wt)
        self.assertEqual(os.path.realpath(got), os.path.realpath(self.root))
        self.assertTrue(os.path.isabs(got))
        want = os.path.dirname(plain_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
                               .stdout.decode().strip())
        self.assertEqual(os.path.realpath(got), os.path.realpath(want))

    def test_main_worktree_separate_git_dir_refused(self):  # WT7: the common directory is not named .git
        dest = os.path.join(self.tmp, "sep")
        sepgit = os.path.join(self.tmp, "sep-git")
        git(self.tmp, "clone", "-q", "--separate-git-dir", sepgit, self.root, dest)
        with self.assertRaises(GateError) as cm:
            gitinfo.main_worktree(dest)
        self.assertIn("main worktree", str(cm.exception))
        self.assertNotIn(self.tmp, str(cm.exception))

    def test_main_worktree_bare_repository_refused(self):  # WT7: a linked worktree of a bare repository
        bare = os.path.join(self.tmp, "b.git")
        git(self.tmp, "clone", "-q", "--bare", self.root, bare)
        wt = os.path.join(self.tmp, "bare-wt")
        git(bare, "worktree", "add", "-q", wt, "main")
        with self.assertRaises(GateError):
            gitinfo.main_worktree(wt)

    def test_main_worktree_ignores_git_dir_env(self):  # WT7: GIT_DIR is cleared
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(other, ".git")}):
            self.assertEqual(os.path.realpath(gitinfo.main_worktree(self.root)), os.path.realpath(self.root))

    def test_main_worktree_git_version_stated(self):  # WT8: --path-format needs git 2.31
        self.assertIn("2.31", gitinfo.main_worktree.__doc__)
        calls, patch = spy_runs()
        with patch:
            gitinfo.main_worktree(self.root)
        argv = [a for a, _ in calls if "--git-common-dir" in a][0]
        self.assertIn("--path-format=absolute", argv)

    def test_main_worktree_lives_in_gitinfo(self):  # WT9
        self.assertTrue(callable(gitinfo.main_worktree))

    def test_main_worktree_root_forms_and_types(self):
        check_root_forms(self, root_forms(self.tmp, self.root), {"main_worktree": gitinfo.main_worktree})
        for bad in (None, b".", 5, "", _Sub(".")):
            with self.assertRaises(GateError) as cm:
                gitinfo.main_worktree(bad)
            self.assertEqual(str(cm.exception), "root must be a string")


if __name__ == "__main__":
    unittest.main()
