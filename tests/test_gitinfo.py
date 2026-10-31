"""Tests for the git helpers (gates.lib.gitinfo), on real repositories built with plain git."""
import hashlib
import os
import subprocess
import unittest
from unittest import mock

from gates.lib import gitinfo
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo

INVALID_UTF8 = b"ok \xff\xfe bad\n"


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


class RootKindsTest(Fixture):
    def test_repo_and_subdir_work(self):  # G1
        sub = os.path.join(self.root, "dir")
        self.assertEqual(gitinfo.head_sha(self.root), self.head)
        self.assertEqual(gitinfo.head_sha(sub), self.head)
        self.assertTrue(gitinfo.commit_exists(sub, self.head))
        self.assertTrue(gitinfo.blob_exists(sub, self.head, "dir/x.txt"))
        self.assertEqual(gitinfo.show(sub, "HEAD", "dir/x.txt"), "x\n")
        self.assertEqual(gitinfo.ls_tree(sub, "HEAD", "dir"), ["dir/x.txt"])
        self.assertEqual(gitinfo.tracked_files(sub), gitinfo.tracked_files(self.root))

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
        self.assertIsNone(gitinfo.user_email(plain))
        with self.assertRaises(GateError):
            gitinfo.user_email(missing)

    def test_git_not_installed_is_gate_error(self):
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "nowhere")}):
            with self.assertRaises(GateError) as e:
                gitinfo.head_sha(self.root)
        self.assertEqual(str(e.exception), "git: command not found")


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


class BlobExistsTest(Fixture):
    def test_blob_exists_only_for_blobs(self):  # G4
        h = self.head
        yes = ["a.txt", "dir/x.txt", "dir/sub/y.txt", "bin/run", "empty.txt", "sp ace/f g.txt",
               "é/ü.txt", "-lead.txt", "co:lon.txt", "nl\nname.txt", "gl*ob/f.txt", ":(top)tm.txt", ":(top)md/f.txt"]
        no = ["dir", "dir/", "nope", "link", "dir/lnk", "subm", "gl*", "gl?ob/f.txt", "a.txt/",
              "dir/../a.txt", "./a.txt", "", "dir/x.tx", "gl*ob"]
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
        self.assertIsNone(gitinfo.show(self.root, "HEAD", "dir/../a.txt"))

    def test_directory_symlink_gitlink_are_none(self):  # owner Q-1a2-5
        for p in ("dir", "dir/", "link", "dir/lnk", "subm"):
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
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir/"), ["dir/x.txt"])
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
        self.assertEqual(gitinfo.ls_tree(self.root, "HEAD", "dir/../bin"), [])
        self.assertEqual(gitinfo.ls_tree(self.root, self.config_sha, "dir"), [])

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


if __name__ == "__main__":
    unittest.main()
