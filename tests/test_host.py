"""Tests of gates/lib/host.py (Task 4d.2 part A). Every ``gh`` is a fake script the test writes into its own temp
directory and puts first on PATH; no test runs a real ``gh`` or touches the network. Expected values are hand-written.
Row ids (task-4d.2-domain.md) are named in each test's comment."""
import ast
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates.lib import host
from gates.lib.host import HostError
from gates.lib.result import GateError
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit, make_repo, \
    root_forms

REPO_OK = {"id": 1, "allow_merge_commit": True, "allow_squash_merge": False, "allow_rebase_merge": False}
PROT_OK = {"enforce_admins": {"enabled": True}, "required_pull_request_reviews": {"required_approving_review_count": 0}}
REPO = "api repos/o/n"
PROT = "api repos/o/n/branches/main/protection"
NF = b"gh: Branch not protected (HTTP 404)\n"
STATE_KEYS = ["protected", "pr_required", "admins", "merge_commit", "squash", "rebase"]
UNPROT = dict(zip(STATE_KEYS, (False, False, False, True, False, False)))
PUT = ["gh", "api", "-X", "PUT", "repos/o/n/branches/main/protection", "--input", "-"]
PATCH = ["gh", "api", "-X", "PATCH", "repos/o/n", "-F", "allow_merge_commit=true", "-F", "allow_squash_merge=false",
         "-F", "allow_rebase_merge=false"]


def j(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FakeGh:
    """A ``#!/bin/sh`` fake ``gh`` in its own directory. ``rules`` maps the joined argv (``"$*"``) to
    ``(stdout bytes, stderr bytes, exit code)``; every call appends argv, pwd and the GH_* environment to logs."""

    def __init__(self, tc: unittest.TestCase, rules: dict, mode: int = 0o755, head: str = "#!/bin/sh",
                 deep: bool = False):
        td = tempfile.TemporaryDirectory()
        tc.addCleanup(td.cleanup)
        self.dir = os.path.realpath(td.name)
        lines = [head, "D='%s'" % self.dir, 'echo "$*" >> "$D/argv.log"', 'pwd >> "$D/pwd.log"']
        if deep:  # the environment and stdin are logged only where a row reads them (each costs a process)
            lines += ["/usr/bin/env | /usr/bin/grep -E '^(GH_|NO_COLOR|DEBUG)' | /usr/bin/sort >> \"$D/env.log\"",
                      '/bin/cat > "$D/stdin.$$"']
        lines.append('case "$*" in')
        for i, (key, (out, err, code)) in enumerate(rules.items()):
            esc = [("".join("\\%03o" % b for b in data)) for data in (out, err)]  # builtins only: no process per call
            lines.append("'%s') printf '%s'; printf '%s' >&2; exit %d;;" % (key, esc[0], esc[1], code))
        lines += ["esac", "echo unexpected >&2", "exit 99"]
        self.path = os.path.join(self.dir, "gh")
        with open(self.path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(self.path, mode)
        patcher = mock.patch.dict(os.environ, {"PATH": self.dir + os.pathsep + os.environ.get("PATH", "")})
        patcher.start()
        tc.addCleanup(patcher.stop)

    def log(self, name: str = "argv.log") -> list:
        try:
            with open(os.path.join(self.dir, name)) as fh:
                return fh.read().splitlines()
        except FileNotFoundError:
            return []


def only_path(tc: unittest.TestCase) -> str:
    td = tempfile.TemporaryDirectory()
    tc.addCleanup(td.cleanup)
    patcher = mock.patch.dict(os.environ, {"PATH": os.path.realpath(td.name)})
    patcher.start()
    tc.addCleanup(patcher.stop)
    return td.name


class RemoteTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.r = make_repo(self.work)

    def url(self, value, key="remote.origin.url"):
        git(self.r, "config", "--unset-all", key, check=False)
        git(self.r, "config", key, value)
        return host.github_remote(self.r)

    def test_gr_a1_root_type(self):  # GR-A1
        class S(str):
            pass
        for bad in (None, 1, b"x", [], S("x"), ""):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "^root must be a string$"):
                host.github_remote(bad)

    def test_gr_a2_root_kinds(self):  # GR-A2
        commit_all(self.r, "c")
        check_root_forms(self, root_forms(self.tmp, self.r), {"github_remote": host.github_remote})

    def test_gr_u_accepted_forms(self):  # GR-U1 U2 U3 U8 U15 U17 U20
        for url, slug in (("https://github.com/o/n", "o/n"), ("https://github.com/o/n.git", "o/n"),
                          ("git@github.com:o/n", "o/n"), ("git@github.com:o/n.git", "o/n"),
                          ("https://github.com/O/N", "O/N"), ("https://github.com/o-x/n_y.z", "o-x/n_y.z"),
                          ("https://github.com/o/n.v1", "o/n.v1"), ("https://github.com/o/-n", "o/-n"),
                          ("https://github.com/-o/n-", "-o/n-"), ("https://github.com/o/n.GIT", "o/n.GIT"),
                          ("https://github.com/" + "o" * 5000 + "/" + "n" * 5000, "o" * 5000 + "/" + "n" * 5000)):
            with self.subTest(url=url[:60]):
                self.assertEqual(self.url(url), slug)

    def test_gr_u_refused_forms(self):  # GR-U4 U5 U6 U7 U9 U10 U11 U12 U13 U14 U16 U18 U19
        bad = ["ssh://git@github.com/o/n.git", "ssh://git@github.com:22/o/n", "ssh://github.com/o/n",
               "http://github.com/o/n", "git://github.com/o/n", "file:///x/o/n", "/srv/o/n.git", "../o/n", "o/n",
               "https://github.com/o/n/", "https://github.com/o/n.git/", "https://GitHub.com/o/n",
               "https://GITHUB.COM/o/n", "git@GitHub.com:o/n", "https://user@github.com/o/n",
               "https://user:tok@github.com/o/n.git", "https://:tok@github.com/o/n", "https://github.com:443/o/n",
               "https://github.com/o/n?x=1", "https://github.com/o/n#f", "https://gitlab.com/o/n",
               "git@gitlab.com:o/n", "https://github.com.evil.example/o/n", "https://evilgithub.com/o/n",
               "https://github.company.com/o/n", "git@github.com.evil:o/n", "https://x.example/github.com/o/n",
               "https://github.com/o", "https://github.com/", "https://github.com//n", "https://github.com/o//n",
               "https://github.com/o/n/x", "https://github.com/o/n/x.git", "git@github.com:o", "git@github.com:/o/n",
               "git@github.com:o/n/x", "https://github.com/o/..", "https://github.com/o/.", "https://github.com/../n",
               "https://github.com/o/.git", "https://github.com/o/..git", "git@github.com:o/..",
               "https://github.com/o/n.git.git", "https://github.com/o_x/n", "https://github.com/o/n%2e",
               "https://github.com/o/n\\x", "https://github.com/o/n:x", "https://github.com/o/n@x",
               "https://github.com/o/n~", "https://github.com/é/n", "https://github.com/o/日",
               "https://github.com/ｏ/n", "https://github.com/o/n ", " https://github.com/o/n",
               "https://github.com/o/n\r", "https://github.com/o/n\t", "https://github.com/o/n\x1b", "",
               "-oProxyCommand=x", "https://github.com/o/n\nhttps://github.com/p/q", "https://github.com/Ⱟ/n",
               "https://Ⱟ.com/o/n"]
        for url in bad:
            with self.subTest(url=url[:60]):
                self.assertIsNone(self.url(url))

    def test_gr_r_remotes(self):  # GR-R1 R2 R3 R4 R5 R6 R7 R9 R10 R11
        fake = FakeGh(self, {})
        self.assertIsNone(host.github_remote(self.r))  # R1: no remote at all
        git(self.r, "remote", "add", "upstream", "https://github.com/o/n")
        self.assertIsNone(host.github_remote(self.r))  # R2
        git(self.r, "remote", "add", "origin", "https://gitlab.com/o/n")
        self.assertIsNone(host.github_remote(self.r))  # R3
        git(self.r, "config", "--add", "remote.origin.url", "https://github.com/o/n")
        self.assertIsNone(host.github_remote(self.r))  # R4: two URLs
        git(self.r, "config", "--unset-all", "remote.origin.url")
        git(self.r, "config", "remote.origin.url", "https://github.com/o/n")
        git(self.r, "config", "remote.origin.pushurl", "https://gitlab.com/x/y")
        r = host.github_remote(self.r)
        self.assertEqual(r, "o/n")  # R5
        self.assertIs(type(r), str)  # R10
        git(self.r, "config", "remote.origin.url", "https://example.com/o/n")
        git(self.r, "config", "url.https://github.com/.insteadOf", "https://example.com/")
        self.assertEqual(host.github_remote(self.r), "o/n")  # R6
        git(self.r, "config", "--unset-all", "url.https://github.com/.insteadOf")
        self.assertIsNone(self.url("-oProxyCommand=x"))  # R7
        self.assertEqual(fake.log(), [])  # R9: no gh call

    def test_gr_r_credentials_never_echoed(self):  # GR-U9, GR-R11
        self.assertIsNone(self.url("https://user:tok@github.com/o/n.git"))
        with self.assertRaises(GateError) as cm:
            host.github_remote(os.path.join(self.r, "missing"))
        self.assertNotIn("tok", str(cm.exception))

    def test_gr_r8_worktree_unborn_detached(self):  # GR-R8
        self.url("https://github.com/o/n")
        wt = os.path.join(self.tmp, "wt")
        git(self.r, "worktree", "add", "-q", "--detach", "--", wt)
        self.assertEqual(host.github_remote(wt), "o/n")
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        git(fresh, "config", "remote.origin.url", "git@github.com:p/q.git")
        self.assertEqual(host.github_remote(fresh), "p/q")

    def test_gr_u21_non_utf8_url(self):  # GR-U21
        with open(os.path.join(self.r, ".git", "config"), "ab") as fh:
            fh.write(b'[remote "origin"]\n\turl = https://github.com/o/n\xff\n')
        self.assertIsNone(host.github_remote(self.r))

    def test_gr_r12_hostile_config(self):  # GR-R12
        for key, value in (("color.ui", "always"), ("core.abbrev", "7"), ("core.quotepath", "true")):
            git(self.r, "config", key, value)
        self.assertEqual(self.url("https://github.com/o/n"), "o/n")


class StateTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.r = self.work

    def state(self, rules, slug="o/n", branch="main"):
        return host.read_state(self.r, slug, branch)

    def rules(self, repo=REPO_OK, prot=None, prot_err=b"", prot_code=0, repo_code=0, repo_err=b""):
        return {REPO: (j(repo), repo_err, repo_code),
                PROT: (j(prot) if prot is not None else b"", prot_err, prot_code)}

    def test_rs_a_arguments(self):  # RS-A1 RS-A2 RS-A3 RS-A4
        class S(str):
            pass
        fake = FakeGh(self, self.rules(prot=PROT_OK))
        for bad in (None, 1, b"x", [], S("x"), ""):
            with self.subTest(root=bad), self.assertRaisesRegex(GateError, "^root must be a string$"):
                host.read_state(bad, "o/n", "main")
        for bad in (os.path.join(self.r, "missing"), os.path.join(self.r, "..", "x")):
            with self.assertRaisesRegex(GateError, "^root: not a directory$"):
                host.read_state(bad, "o/n", "main")
        for bad in (None, 1, b"o/n", S("o/n"), "", "o", "o/n/x", "/o/n", "o/n/", "o/..", "../n", "o/n?x=1", "o/n#f",
                    "o /n", "o/n\n", "é/n", "o/n.git", "o/n;x", "o/$(x)", "o/`x`", "o/n|x"):
            with self.subTest(slug=bad), self.assertRaisesRegex(GateError, "^slug: must be owner/name$"):
                host.read_state(self.r, bad, "main")
        for bad in (None, 1, b"main", S("main"), "", "-x", "a b", "a?b", "a#b", "a%2Fb", "a/../b", "../x", "a\nb",
                    "é", "a//b", "a/./b", "/a", "a/", "x" * 0 + ".", "a;b"):
            with self.subTest(branch=bad), self.assertRaisesRegex(GateError, "^branch: must hold only"):
                host.read_state(self.r, "o/n", bad)
        self.assertEqual(fake.log(), [])  # no gh call before the arguments are accepted
        for branch in ("main", "release/1", "a.b_c-d", "x" * 300):
            with self.subTest(branch=branch):
                FakeGh(self, {REPO: (j(REPO_OK), b"", 0), "api repos/o/n/branches/%s/protection" % branch:
                              (b"", NF, 1)})
                self.assertEqual(host.read_state(self.r, "o/n", branch)["protected"], False)

    def test_rs_v_values(self):  # RS-V1 RS-V2 RS-V3 RS-V4 RS-V5 RS-V6 RS-V7 RS-V8 RS-E14 RS-E15 RS-E13 RS-E11
        fake = FakeGh(self, self.rules(prot_err=NF, prot_code=1))
        got = self.state(None)
        self.assertEqual(got, dict(zip(STATE_KEYS, (False, False, False, True, False, False))))
        self.assertEqual(list(got), STATE_KEYS)
        self.assertTrue(all(type(v) is bool for v in got.values()))
        self.assertEqual(fake.log(), [REPO, PROT])  # RS-E14: two reads, repository first, nothing else
        self.assertFalse(any(w in line for line in fake.log() for w in ("-X", "PUT", "--input", "-F", "-f")))
        self.assertEqual(fake.log("pwd.log"), [self.r, self.r])  # RS-E13
        FakeGh(self, self.rules(prot=PROT_OK))
        self.assertEqual(self.state(None), dict(zip(STATE_KEYS, (True, True, True, True, False, False))))
        prot = {"enforce_admins": {"enabled": False}, "required_pull_request_reviews": {}, "Extra": 1}
        FakeGh(self, self.rules(prot=prot))
        self.assertEqual(self.state(None), dict(zip(STATE_KEYS, (True, True, False, True, False, False))))
        FakeGh(self, self.rules(prot={"enforce_admins": {"enabled": True, "url": "u"}}))
        self.assertEqual(self.state(None), dict(zip(STATE_KEYS, (True, False, True, True, False, False))))
        for combo in ((False, False, False), (True, True, False), (True, False, True), (True, True, True),
                      (False, True, False), (False, False, True), (False, True, True), (True, False, False)):
            repo = dict(REPO_OK, allow_merge_commit=combo[0], allow_squash_merge=combo[1], allow_rebase_merge=combo[2])
            FakeGh(self, self.rules(repo=repo, prot=PROT_OK))
            got = self.state(None)
            self.assertEqual((got["merge_commit"], got["squash"], got["rebase"]), combo)

    def test_rs_j_malformed_bodies(self):  # RS-J1 J2 J3 J4 J5 J6 J7 J9 J11 J12
        def refused(repo=None, prot=None, raw_repo=None, raw_prot=None, **kw):
            rules = {REPO: (raw_repo if raw_repo is not None else j(repo or REPO_OK), b"", kw.get("rc", 0)),
                     PROT: (raw_prot if raw_prot is not None else j(prot or PROT_OK), b"", 0)}
            FakeGh(self, rules)
            with self.assertRaises(HostError) as cm:
                self.state(None)
            self.assertTrue(str(cm.exception).startswith("gh api repos/o/n"), str(cm.exception))
            return str(cm.exception)
        for raw in (b"", b"  \n", b"not json", b"{", b'{"a":1}{"b":2}', b"{} x", b"\xef\xbb\xbf{}", b"\xff{}",
                    "{}".encode("utf-16"), b"[" * 100000):
            with self.subTest(raw=raw[:20]):
                self.assertIn("invalid JSON", refused(raw_repo=raw))
                self.assertIn("invalid JSON", refused(raw_prot=raw))
        for raw in (b"[]", b"null", b'"x"', b"1", b"true"):
            self.assertIn("not a JSON object", refused(raw_repo=raw))
        for key in ("allow_merge_commit", "allow_squash_merge", "allow_rebase_merge"):
            repo = dict(REPO_OK)
            del repo[key]
            self.assertIn("%s is missing" % key, refused(repo=repo))
            for bad in ("true", 1, 0, None, []):
                self.assertIn("%s must be a bool" % key, refused(repo=dict(REPO_OK, **{key: bad})))
        self.assertIn("enforce_admins must be an object", refused(prot={"x": 1}))
        for bad in (True, None, [], "x"):
            self.assertIn("enforce_admins must be an object", refused(prot={"enforce_admins": bad}))
        for bad in ("yes", 1, None, []):
            self.assertIn("enabled must be a bool", refused(prot={"enforce_admins": {"enabled": bad}}))
        self.assertIn("enabled is missing", refused(prot={"enforce_admins": {}}))
        for bad in ([], True, None, "x"):
            self.assertIn("required_pull_request_reviews must be an object",
                          refused(prot=dict(PROT_OK, required_pull_request_reviews=bad)))
        self.assertIn("invalid JSON", refused(raw_repo=b'{"allow_merge_commit": true, "allow_merge_commit": false}'))
        for const in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            self.assertIn("invalid JSON", refused(raw_repo=b'{"x": ' + const + b"}"))
        self.assertIn("is missing", refused(raw_repo=j({"message": "Not Found", "status": "404"})))  # J12
        FakeGh(self, {REPO: (j(REPO_OK), b"gh: boom (HTTP 500)\n", 1), PROT: (j(PROT_OK), b"", 0)})  # J11
        with self.assertRaisesRegex(HostError, r"HTTP 500\) \(exit 1\)$"):
            self.state(None)

    def test_vr1_numeral_4300_4301_gh_json(self):  # RS-J8, VR1 (a): the verdict is one on both interpreters
        for digits in (1, 600, 601, 4300, 4301):
            for limit in INT_LIMITS:
                with self.subTest(digits=digits, limit=limit), int_limit(limit):
                    body = b'{"id": ' + b"1" * digits + b', "allow_merge_commit": true, "allow_squash_merge": false,'\
                        b' "allow_rebase_merge": false}'
                    FakeGh(self, {REPO: (body, b"", 0), PROT: (j(PROT_OK), b"", 0)})
                    if digits <= 600:
                        self.assertTrue(self.state(None)["merge_commit"])
                    else:
                        with self.assertRaisesRegex(HostError, "invalid JSON .an integer of more than 600 digits"):
                            self.state(None)

    def test_vr1_int_limits(self):  # VR1: nothing in host.py calls int()
        with open(host.__file__) as fh:
            tree = ast.parse(fh.read())
        names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("int", names)

    def test_rs_e_failures(self):  # RS-E1 RS-E2 RS-E3 RS-E4 RS-E5 RS-E6 RS-E7 RS-E9 RS-E16 RS-E17
        only_path(self)
        with self.assertRaises(HostError) as cm:
            self.state(None)
        self.assertEqual(str(cm.exception), "gh api repos/o/n: gh not found on PATH")
        self.assertTrue(issubclass(HostError, GateError))
        FakeGh(self, {}, mode=0o644)
        with self.assertRaisesRegex(HostError, "^gh api repos/o/n: cannot run gh: Permission denied$"):
            self.state(None)
        FakeGh(self, {}, head="#!/nonexistent/interp")
        with self.assertRaisesRegex(HostError, "^gh api repos/o/n: cannot run gh: "):
            self.state(None)
        FakeGh(self, {REPO: (b"", b"To get started with GitHub CLI, please run:  gh auth login\n", 4)})
        with self.assertRaisesRegex(HostError, r"^gh api repos/o/n: To get started with GitHub CLI.* \(exit 4\)$"):
            self.state(None)
        for code, err in ((1, b"gh: Bad credentials (HTTP 401)\n"), (1, b"gh: x (HTTP 403)\n"),
                          (1, b"gh: Not Found (HTTP 404)\n"), (1, b"gh: y (HTTP 422)\n"), (2, b"z\n"),
                          (126, b"z\n"), (127, b"z\n"), (130, b"z\n"), (255, b"ghp_x\n")):
            with self.subTest(code=code, err=err):
                FakeGh(self, {REPO: (j(REPO_OK), err, code)})
                with self.assertRaisesRegex(HostError, r"^gh api repos/o/n: %s \(exit %d\)$"
                                            % (err.decode().strip().replace("(", r"\(").replace(")", r"\)"), code)):
                    self.state(None)
        FakeGh(self, {REPO: (j(REPO_OK), b"", 0), PROT: (b"", b"gh: Bad credentials (HTTP 401)\n", 1)})
        with self.assertRaisesRegex(HostError, "^gh api repos/o/n/branches/main/protection: gh: Bad cred"):
            self.state(None)
        for err in (b"gh: Not Found (HTTP 404)\n", b"gh: Branch not protected (HTTP 404)"):  # RS-E6: unprotected
            FakeGh(self, {REPO: (j(REPO_OK), b"", 0), PROT: (b"", err, 1)})
            self.assertFalse(self.state(None)["protected"])
        for err in (b"gh: Not Found (HTTP 4040)\n", b"\ngh: Not Found (HTTP 404)\n", b"first\ngh: x (HTTP 404)\n",
                    b"HTTP 404\n"):
            FakeGh(self, {REPO: (j(REPO_OK), b"", 0), PROT: (b"", err, 1)})
            with self.assertRaises(HostError):
                self.state(None)
        FakeGh(self, {REPO: (b"", b"", 0), PROT: (b"", NF, 1)})
        FakeGh(self, {REPO: (b"{}", b"gh: Not Found (HTTP 404)\n", 1)})  # a 404 on the repository call is an error
        with self.assertRaisesRegex(HostError, "^gh api repos/o/n: gh: Not Found"):
            self.state(None)

    def test_rs_e8_stderr_first_line(self):  # RS-E8 RS-E17, VR2 (3)
        cases = ((b"", "(no message)"), (b"\n\n  text \n", "text"), (b"one\ntwo\n", "one"), (b"x" * 5000, "x" * 200),
                 (b"a\x1b[31mb", "a?[31mb"), (b"a\x00b", "a?b"), (b"line\r\nnext", "line"), (b"a\xffb", "a�b"),
                 (b"ghp_x token\n", "ghp_x token"), ("Ⱟ ok".encode(), "Ⱟ ok"), (b"del\x7f", "del?"))
        for err, want in cases:
            with self.subTest(err=err[:20]):
                FakeGh(self, {REPO: (b"", err, 1)})
                with self.assertRaises(HostError) as cm:
                    self.state(None)
                self.assertEqual(str(cm.exception), "gh api repos/o/n: %s (exit 1)" % want)

    def test_rs_e10_timeout(self):  # RS-E10
        fake = FakeGh(self, {REPO: (b"", b"", 0)})
        with open(fake.path, "w") as fh:
            fh.write("#!/bin/sh\nexec /bin/sleep 30\n")
        with mock.patch.object(host, "TIMEOUT", 1), self.assertRaisesRegex(HostError, "^gh api repos/o/n: timed out"):
            self.state(None)

    def test_rs_e12_environment_and_stdin(self):  # RS-E12 RS-E11 RS-E19
        fake = FakeGh(self, self.rules(prot=PROT_OK), deep=True)
        env = {"GH_HOST": "ghe.example", "GH_REPO": "x/y", "GH_TOKEN": "t", "GH_DEBUG": "api", "DEBUG": "1"}
        os.environ.pop("NO_COLOR", None)
        with mock.patch.dict(os.environ, env):
            self.state(None)
            self.state(None)
        first = fake.log("env.log")[:len(fake.log("env.log")) // 4]
        self.assertEqual(fake.log("env.log")[:len(first)], sorted(first))
        for want in ("GH_HOST=github.com", "GH_PROMPT_DISABLED=1", "GH_TOKEN=t", "GH_NO_UPDATE_NOTIFIER=1", "NO_COLOR=1"):
            self.assertIn(want, first)
        for gone in ("GH_REPO=x/y", "GH_DEBUG=api", "DEBUG=1", "GH_HOST=ghe.example"):
            self.assertNotIn(gone, fake.log("env.log"))
        self.assertEqual(fake.log(), [REPO, PROT, REPO, PROT])  # no cache
        for name in os.listdir(fake.dir):
            if name.startswith("stdin."):
                with open(os.path.join(fake.dir, name)) as fh:
                    self.assertEqual(fh.read(), "")


class CallsTest(unittest.TestCase):
    def test_hc_a_arguments(self):  # HC-A1 HC-A2 HC-A3
        class D(dict):
            pass
        for bad in (None, [], D(UNPROT), {}):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                host.calls(bad, "o/n", "main")
        for key in STATE_KEYS:
            lacking = {k: v for k, v in UNPROT.items() if k != key}
            with self.assertRaisesRegex(GateError, "^state: %s is missing$" % key):
                host.calls(lacking, "o/n", "main")
            for bad in (1, 0, "true", None, []):
                with self.assertRaisesRegex(GateError, "^state: %s must be a bool$" % key):
                    host.calls(dict(UNPROT, **{key: bad}), "o/n", "main")
        with self.assertRaisesRegex(GateError, "^state: holds a key other than"):
            host.calls(dict(UNPROT, extra=True), "o/n", "main")
        with self.assertRaisesRegex(GateError, "^slug: must be owner/name$"):
            host.calls(UNPROT, "o/n.git", "main")
        with self.assertRaisesRegex(GateError, "^branch: must hold only"):
            host.calls(UNPROT, "o/n", "a b")
        self.assertEqual(host.calls(dict(UNPROT, pr_required=True, admins=True), "o/n", "main"), [PUT])  # HC-A3/C18

    def test_hc_c_calls(self):  # HC-C1 C2 C3 C4 C5 C7 C8 C9 C10 C11 C12 C13 C14 C16 C17 C18 C20 C21
        self.assertEqual(host.calls(UNPROT, "o/n", "main"), [PUT])
        for combo in ((True, True, True), (False, False, False), (True, True, False), (True, False, True),
                      (False, True, False), (False, False, True), (False, True, True)):
            state = dict(UNPROT, merge_commit=combo[0], squash=combo[1], rebase=combo[2])
            self.assertEqual(host.calls(state, "o/n", "main"), [PUT, PATCH], combo)
        self.assertEqual(PATCH[1:][6:8], ["-F", "allow_squash_merge=false"])
        for call in host.calls(dict(UNPROT, squash=True), "o/n", "main"):
            self.assertTrue(all(type(a) is str for a in call))
        everything = dict(zip(STATE_KEYS, (True, True, True, True, False, False)))
        self.assertEqual(host.calls(everything, "o/n", "main"), [])
        self.assertEqual(host.calls(dict(everything, pr_required=False), "o/n", "main"), [])
        self.assertEqual(host.calls(dict(everything, admins=False), "o/n", "main"), [])
        for combo in ((True, True, True), (False, False, False), (False, True, False)):  # Q-4d2-9 (1): no call
            state = dict(everything, merge_commit=combo[0], squash=combo[1], rebase=combo[2], pr_required=False)
            self.assertEqual(host.calls(state, "o/n", "main"), [])
        got = host.calls(UNPROT, "o-x/n_y.z", "release/1")
        self.assertEqual(got[0][4], "repos/o-x/n_y.z/branches/release/1/protection")
        got[0].append("x")
        self.assertEqual(host.calls(UNPROT, "o/n", "main"), [PUT])  # fresh lists
        self.assertEqual(json.loads(host.body_text()), {
            "required_status_checks": None, "enforce_admins": True,
            "required_pull_request_reviews": {"required_approving_review_count": 0}, "restrictions": None})
        self.assertEqual(host.body_text(), '{"required_status_checks": null, "enforce_admins": true, '
                         '"required_pull_request_reviews": {"required_approving_review_count": 0}, "restrictions": null}')
        self.assertEqual(list(host.PROTECTION_BODY), ["required_status_checks", "enforce_admins",
                                                      "required_pull_request_reviews", "restrictions"])

    def test_missing_texts_and_order(self):  # CD9 adjusted, HC-C10 C11 C12 C13 C14
        everything = dict(zip(STATE_KEYS, (True, True, True, True, False, False)))
        self.assertEqual(host.missing(everything), [])
        self.assertEqual(host.missing(dict(everything, pr_required=False)), ["pull request not required"])
        self.assertEqual(host.missing(dict(everything, admins=False)), ["administrators not enforced"])
        self.assertEqual(host.missing(dict(everything, admins=False, pr_required=False)),
                         ["pull request not required", "administrators not enforced"])
        self.assertEqual(host.missing(dict(everything, merge_commit=False, squash=True, rebase=True,
                                           pr_required=False, admins=False)),
                         ["pull request not required", "administrators not enforced", "merge commit not allowed",
                          "squash merge allowed", "rebase merge allowed"])
        with self.assertRaises(GateError):
            host.missing({})


class RunTest(GitIsolatedTestCase):
    def test_run_put_and_patch(self):  # IN-A5 side: the PUT reads the body on stdin; other argvs read nothing
        key = "api -X PUT repos/o/n/branches/main/protection --input -"
        fake = FakeGh(self, {key: (b"{}", b"", 0), "api -X PATCH repos/o/n -F allow_merge_commit=true "
                             "-F allow_squash_merge=false -F allow_rebase_merge=false": (b"{}", b"", 0)}, deep=True)
        self.assertEqual(host.run(self.work, PUT), "{}")
        host.run(self.work, PATCH)
        self.assertEqual(fake.log(), [key[:], " ".join(PATCH[1:])])
        stdins = sorted(os.listdir(fake.dir))
        bodies = []
        for name in stdins:
            if name.startswith("stdin."):
                with open(os.path.join(fake.dir, name)) as fh:
                    bodies.append(fh.read())
        self.assertEqual(sorted(bodies), sorted([host.body_text(), ""]))
        FakeGh(self, {key: (b"", b"gh: nope (HTTP 403)\n", 1)})
        with self.assertRaisesRegex(HostError, r"^gh api -X PUT repos/o/n/branches/main/protection --input -: "
                                    r"gh: nope \(HTTP 403\) \(exit 1\)$"):
            host.run(self.work, PUT)
        for bad in (None, [], ["gh"], ["sh", "api"], ["gh", "api", 1], "gh api"):
            with self.assertRaises(GateError):
                host.run(self.work, bad)
        with self.assertRaises(GateError):
            host.run(os.path.join(self.work, "missing"), PUT)


class SourceScanTest(unittest.TestCase):
    def test_vr2_vr3_vr4_source_rules(self):  # VR2 (scan) VR3 VR4
        banned = {"lower", "upper", "casefold", "isprintable", "isspace", "isalnum", "isdigit", "isalpha",
                  "isdecimal", "isnumeric", "isidentifier"}
        for mod in ("host", "docmove"):
            path = os.path.join(os.path.dirname(host.__file__), mod + ".py")
            with open(path) as fh:
                src = fh.read()
            tree = ast.parse(src)
            self.assertTrue(src.split('"""')[2].lstrip().startswith("from __future__ import annotations"), mod)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, banned, mod)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, banned | {"unicodedata", "ExceptionGroup", "BaseExceptionGroup"}, mod)
                self.assertNotIsInstance(node, getattr(ast, "TryStar", ()), mod)
                if isinstance(node, ast.Import):
                    self.assertNotIn("unicodedata", [a.name for a in node.names])
            self.assertNotIn("\\w", src.replace("\\w-style", ""))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is not None:
                    self.assertNotIn("Exception", ast.dump(node.type).replace("GateError", ""), mod)

    def test_vr4_imports_on_both_interpreters(self):  # VR4: a fresh interpreter imports both modules
        p = subprocess.run([sys.executable, "-c", "import gates.lib.host, gates.lib.docmove"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.getcwd())
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_vr2_u2c2f_host_slug_and_class(self):  # VR2 (2) (4): U+2C2F is outside every explicit class
        self.assertIsNone(host._SLUG.fullmatch("Ⱟ/n"))
        self.assertIsNone(host._SLUG.fullmatch("o/Ⱟ"))
        self.assertIsNone(host._BRANCH.fullmatch("Ⱟ"))


if __name__ == "__main__":
    unittest.main()
