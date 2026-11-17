"""Tests of Task 2b.3 (self-adoption: the CI workflow, the config keys, the hooks, `run_all` as the commit gate;
input-domain table task-2b.3-domain.md: rows G (config), H (hooks and copies), K3 here; the workflow rows W and the
PC1 rows K1 and K2 are WorkflowTest, added in the second commit of the task).

The tests read this checkout's real config and run the real ``python3 -m gates run_all``, ``githooks install`` and
``git commit`` in disposable clones under a temporary directory (a clone is of this checkout's working files: its
tracked and untracked files are copied over the clone and committed there, so a test run before this task's commit
reads the files under test). Nothing here installs a hook in this checkout's own hooks directory. Expected values are
written by hand from the plan (P:1806-1865) and the table."""
import contextlib
import inspect
import io
import os
import re
import shutil
import subprocess
import sys
import unittest

from gates import __main__ as gates_main
from gates.lib import config, yamlsub
from gates.tools import githooks
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = ".strict-delivery/config.yml"
BASE = "b7afa88"  # Task 2b.2's reviewed head: the config at the base holds exactly three keys
COMMANDS_TEST = "python3 -m unittest discover -s tests -t . && python3.13 -m unittest discover -s tests -t ."
NESTED = "SD_SELF_ADOPTION_NESTED"  # set in the suite run inside a clone: the clone tests do not recurse
UNSTAGED = "tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed"
SHALLOW = "FAIL %s.input: git merge-base failed (exit 1)\n"
# the two files the hook test creates in its clone; the names are unlike any file of this checkout, because the clone
# holds this checkout's working files, including a path staged by the commit this suite runs under (the commit gate)
CLEAN = "hookfixture-clean.txt"
STAGED = "hookfixture-staged.txt"


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def listing(path):
    """Every entry of a directory with its size and mode, so a change to any file shows."""
    out = []
    for name in sorted(os.listdir(path)):
        st = os.lstat(os.path.join(path, name))
        out.append((name, st.st_size, st.st_mode, st.st_mtime_ns))
    return out


def real_hooks_dir():
    """The shared hooks directory of this checkout (read only here)."""
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE, check=True)
    common = out.stdout.decode("utf-8").strip()
    if not os.path.isabs(common):
        common = os.path.join(REPO, common)
    return os.path.join(os.path.realpath(common), "hooks")


class ConfigTest(GitIsolatedTestCase):
    def load_raw(self):
        return yamlsub.load(os.path.join(REPO, CONFIG), CONFIG)

    def test_config_commands_test(self):  # G1, G4
        self.assertEqual(self.load_raw()["commands"], {"test": COMMANDS_TEST})
        cfg = config.load(REPO)  # G4: the loader accepts the file
        self.assertEqual(cfg["commands"], {"test": COMMANDS_TEST})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    def test_config_top_tier(self):  # G2
        raw = self.load_raw()
        self.assertEqual(raw["top_tier_roles"], ["final_verifier", "exception_reviewer"])
        self.assertEqual(config.load(REPO)["top_tier_roles"], ["final_verifier", "exception_reviewer"])
        self.assertNotIn("tier4", config.load(REPO)["models"]["tiers"])
        self.assertNotIn("tier4", raw.get("models", {}).get("tiers", {}))
        self.assertNotIn("top_tier_fallback", raw)

    def test_config_only_two_keys_added(self):  # G3
        p = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (BASE, CONFIG)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        base_path = os.path.join(self.tmp, "base.yml")
        with open(base_path, "wb") as fh:
            fh.write(p.stdout)
        base = yamlsub.load(base_path, CONFIG)
        self.assertEqual(base, {"schema": "config/1", "framework_version": "0.0.0", "profile": "strict"})
        current = dict(self.load_raw())
        self.assertEqual(sorted(set(current) - set(base)), ["commands", "top_tier_roles"])
        for key in ("commands", "top_tier_roles"):
            del current[key]
        self.assertEqual(current, base)
        # append only: the base's three lines open the file unchanged, the two keys follow
        text = read_text(os.path.join(REPO, CONFIG))
        self.assertTrue(text.startswith(p.stdout.decode("utf-8")))


class CopyCase(GitIsolatedTestCase):
    """Disposable clones of this checkout, one real git run at a time."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))  # the shim's python3 is this interpreter

    def env(self):
        e = dict(os.environ)
        e["LC_ALL"] = "C"
        e["PATH"] = self.bin + os.pathsep + e["PATH"]
        return e

    def run_proc(self, argv, cwd):
        p = subprocess.run(argv, cwd=cwd, env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode("utf-8", "replace")

    def clone_copy(self, name, main):
        """``git clone`` of this checkout, its working files copied over and committed, HEAD detached; ``main`` True
        gives a local ``main`` at HEAD, False leaves no local ``main``."""
        dst = os.path.join(self.tmp, name)
        git(self.tmp, "clone", "-q", REPO, dst)
        git(dst, "config", "user.email", "fixture@example.invalid")
        git(dst, "config", "user.name", "Fixture")
        git(dst, "config", "commit.gpgsign", "false")
        names = git(REPO, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        gone = set(git(REPO, "ls-files", "-z", "--deleted").split("\0"))
        for rel in names:
            if rel == "" or rel in gone:
                continue
            src = os.path.join(REPO, rel)
            if not os.path.isfile(src):
                continue
            to = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(to), exist_ok=True)
            shutil.copyfile(src, to)
            shutil.copymode(src, to)
        for rel in sorted(gone - {""}):
            git(dst, "rm", "-q", "--cached", "--ignore-unmatch", "--", rel)
            if os.path.exists(os.path.join(dst, rel)):
                os.unlink(os.path.join(dst, rel))
        commit_all(dst, "working files")
        git(dst, "checkout", "-q", "--detach")
        git(dst, "branch", "-D", "main", check=False)
        if main:
            git(dst, "branch", "main", "HEAD")
        return dst

    def has_local_main(self, root):
        return subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "refs/heads/main"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    def gates_run_all(self, root, *args):
        return self.run_proc([sys.executable, "-m", "gates", "run_all", "--root", root] + list(args), cwd=root)


class CopyTest(CopyCase):
    def test_hooks_in_a_disposable_clone(self):  # H1, H2, H3 (the automated form of plan Step 4)
        clone = self.clone_copy("hooks", main=True)
        path = os.path.join(clone, CONFIG)
        text = read_text(path)
        self.assertEqual(text.count(COMMANDS_TEST), 1)
        with open(path, "w", encoding="utf-8") as fh:  # H2: a fast command, so the suite does not recurse
            fh.write(text.replace(COMMANDS_TEST, "\"true\""))
        commit_all(clone, "fast commands.test")
        real = real_hooks_dir()
        before = listing(real)
        self.assertEqual(githooks.install(clone, REPO), [])
        self.assertEqual(listing(real), before)  # H3: this checkout's hooks directory is untouched
        for name in ("pre-commit", "pre-push"):
            self.assertTrue(os.path.isfile(os.path.join(clone, ".git", "hooks", name)))
        head = git(clone, "rev-parse", "HEAD")
        for name in (CLEAN, STAGED):
            self.assertFalse(os.path.exists(os.path.join(clone, name)), name)
        # the clean commit passes: run_all's lines, then the test command's
        with open(os.path.join(clone, CLEAN), "w", encoding="utf-8") as fh:
            fh.write("clean\n")
        git(clone, "add", CLEAN)
        code, out = self.run_proc(["git", "commit", "-q", "-m", "clean"], cwd=clone)
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertTrue(lines and all(ln.startswith("PASS ") for ln in lines), out)
        self.assertIn("PASS schema.config", lines)
        self.assertIn("PASS cites.landed", lines)
        self.assertEqual(lines[-1], "PASS githook.test")
        self.assertNotEqual(git(clone, "rev-parse", "HEAD"), head)
        # a staged new file and an unstaged change to a tracked file: refused before any gate
        head = git(clone, "rev-parse", "HEAD")
        with open(os.path.join(clone, STAGED), "w", encoding="utf-8") as fh:
            fh.write("staged\n")
        git(clone, "add", STAGED)
        with open(os.path.join(clone, CLEAN), "a", encoding="utf-8") as fh:
            fh.write("unstaged\n")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "unstaged"], cwd=clone)
        self.assertEqual(code, 1, out)
        self.assertEqual(out, "FAIL githook.unstaged: %s: %s\n" % (CLEAN, UNSTAGED))
        self.assertEqual(git(clone, "rev-parse", "HEAD"), head)
        # staging the file lets the same commit through
        git(clone, "add", CLEAN)
        code, out = self.run_proc(["git", "commit", "-q", "-m", "staged"], cwd=clone)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_proc([sys.executable, "-m", "gates", "githooks", "status", "--root", clone],
                                       cwd=REPO),
                         (0, "PASS githooks.pre-commit\nPASS githooks.pre-push\n"))

    def test_shim_fails_closed_when_framework_lacks_githook(self):  # H4
        added = git(REPO, "log", "--diff-filter=A", "--format=%H", "--", "gates/tools/githooks.py").split()
        self.assertEqual(len(added), 1, added)  # Task 2b.2 added the module once
        old = os.path.join(self.tmp, "old")
        git(self.tmp, "clone", "-q", "--no-checkout", REPO, old)
        git(old, "checkout", "-q", "--detach", added[0] + "^")
        self.assertFalse(os.path.exists(os.path.join(old, "gates", "tools", "githooks.py")))
        root = make_repo(os.path.join(self.work), None)
        self.assertEqual(githooks.install(root, old), [])  # the shim names the old framework checkout
        head = git(root, "rev-parse", "HEAD")
        with open(os.path.join(root, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        git(root, "add", "f.txt")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "x"], cwd=root)
        self.assertNotEqual(code, 0, out)  # refused, never passed silently
        self.assertEqual(git(root, "rev-parse", "HEAD"), head)
        self.assertIn("usage: python3 -m gates", out)

    def test_run_all_passes_on_a_copy_with_main(self):  # H5 (F-B2p-3)
        clone = self.clone_copy("copy", main=True)
        self.assertTrue(self.has_local_main(clone))
        code, out = self.gates_run_all(clone)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)

    def test_suite_needs_no_local_main(self):  # H6 (F-B2p-3)
        if os.environ.get(NESTED):
            # inside the clone below: the clone really has no local main; the nested run does not recurse
            self.assertFalse(self.has_local_main(REPO))
            return
        clone = self.clone_copy("nomain", main=False)
        self.assertFalse(self.has_local_main(clone))
        env = self.env()
        env[NESTED] = "1"
        p = subprocess.run([sys.executable, "-m", "unittest", "tests.test_run_all", "tests.test_self_adoption"],
                           cwd=clone, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace")[-3000:])

    def test_run_all_shallow_clone_fails_closed(self):  # H7
        full = self.clone_copy("full", main=True)
        commit_all(full, "ahead of main")  # HEAD one commit past main: a shallow history has no merge base
        deep = os.path.join(self.tmp, "deep")
        git(self.tmp, "clone", "-q", "--no-single-branch", "file://" + full, deep)
        code, out = self.gates_run_all(deep, "--base", "origin/main")
        self.assertEqual(code, 0, out)  # the control: a full clone passes
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + full, shallow)
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository"), "true")
        code, out = self.gates_run_all(shallow, "--base", "origin/main")
        self.assertEqual(code, 1, out)
        lines = out.splitlines(True)
        for gate in ("register", "decisions", "claims"):  # measured 2026-11-17: the three base gates, in this order
            self.assertIn(SHALLOW % gate, lines)
        self.assertEqual([ln for ln in lines if ln.startswith("FAIL")],
                         [SHALLOW % g for g in ("register", "decisions", "claims")])

    def test_no_exception_group_in_task_files(self):  # K3: the files of this task use no exception group
        word = "Exception" + "Group"
        for rel in (CONFIG, "tests/test_self_adoption.py"):
            self.assertNotIn(word, read_text(os.path.join(REPO, rel)), rel)


WORKFLOW = ".github/workflows/strict-delivery.yml"
# owner Q-G1-1 (a), 2026-11-16: the commit shas of the lightweight tags v7.0.1 and v7.1.0
PINS = {"actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        "actions/setup-python": ("6d4fd22b20465ccc0f7354476588e8df7c9ca0e0", "v7.1.0")}
BASE_EXPRESSION = ("github.event_name == 'pull_request' && github.base_ref || "
                   "github.event.repository.default_branch")
SUITE = "python -m unittest discover -s tests -t . -v"
RUN_ALL = "python -m gates run_all --base origin/${{ %s }}" % BASE_EXPRESSION


# ---- the workflow is read as text: it is not a framework data file (no strict YAML subset) ----------------------
def code_lines(text):
    """The lines of ``text`` without ``# comments`` (a comment starts at white space and ``#``), no trailing blank."""
    return [re.sub(r"\s+#.*$", "", ln).rstrip() for ln in text.split("\n")]


def top_block(text, key):
    """The indented lines under the top-level ``key:`` line."""
    out = None
    for ln in code_lines(text):
        if out is None:
            if ln == key + ":":
                out = []
        elif ln and not ln[0].isspace():
            break
        elif ln:
            out.append(ln)
    return [] if out is None else out


def flow_items(text, key):
    """The items of every ``key: [a, b]`` line, as written (quotes kept)."""
    found = []
    for ln in code_lines(text):
        m = re.fullmatch(r"\s*%s:\s*\[(.*)\]" % re.escape(key), ln)
        if m:
            found.append([item.strip() for item in m.group(1).split(",")])
    return found


def pythons(text):
    return flow_items(text, "python-version")


def oses(text):
    return flow_items(text, "os")


def uses(text):
    return [m.group(1) for m in (re.fullmatch(r"\s*(?:-\s+)?uses:\s*(\S+)", ln) for ln in code_lines(text)) if m]


def steps(text):
    """The steps of the job: a list of ``{key: value}`` (every ``key: value`` line of a step, ``with`` included)."""
    out = []
    inside = False
    for ln in code_lines(text):
        if re.fullmatch(r"\s+steps:", ln):
            inside = True
            continue
        if not inside or not ln:
            continue
        m = re.fullmatch(r"\s+-\s+(.*)", ln)
        if m and len(ln) - len(ln.lstrip()) == 6:
            out.append({})
            ln = m.group(1)
        kv = re.fullmatch(r"\s*([\w-]+):\s*(.*)", ln)
        if kv and out:
            out[-1][kv.group(1)] = kv.group(2)
    return out


def step_order(text):
    kinds = []
    for st in steps(text):
        if "uses" in st:
            kinds.append(st["uses"].split("@")[0].split("/")[-1])
        elif st.get("run", "").startswith("python -m unittest"):
            kinds.append("unittest")
        elif st.get("run", "") == "python -m gates index":
            kinds.append("index")
        elif st.get("run", "").startswith("python -m gates run_all"):
            kinds.append("run_all")
        else:
            kinds.append("?")
    return kinds


def lookup(payload, path):
    cur = payload
    for part in path.split("."):
        cur = cur[part]
    return cur


def evaluate(expr, payload):
    """The one ``a == 'lit' && b || c`` form the workflow uses, with GitHub's rule that an empty ``b`` falls to ``c``."""
    left, sep, other = expr.partition(" || ")
    assert sep, expr
    cond, sep, then = left.partition(" && ")
    assert sep, expr
    lhs, sep, lit = cond.partition(" == ")
    assert sep and lit.startswith("'") and lit.endswith("'"), expr
    chosen = lookup(payload, then)
    if lookup(payload, lhs) == lit[1:-1] and chosen:
        return chosen
    return lookup(payload, other)


def payload(event_name, base_ref, default_branch):
    return {"github": {"event_name": event_name, "base_ref": base_ref,
                       "event": {"repository": {"default_branch": default_branch}}}}


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_text(os.path.join(REPO, WORKFLOW))

    def test_workflow_is_not_a_data_file(self):  # W1
        self.assertNotIn("schema:", self.text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out.getvalue())

    def test_workflow_triggers(self):  # W2: both events, no filter that skips a branch
        self.assertEqual(top_block(self.text, "on"), ["  push:", "  pull_request:"])

    def test_workflow_matrix(self):  # W3, W4, W5
        self.assertEqual(oses(self.text), [["ubuntu-24.04", "macos-15"]])
        self.assertEqual(pythons(self.text), [['"3.9"', '"3.13"']])
        self.assertEqual([ln for ln in code_lines(self.text) if "runs-on:" in ln], ["    runs-on: ${{ matrix.os }}"])
        self.assertNotIn("latest", self.text)
        for word in ("include:", "exclude:"):
            self.assertNotIn(word, self.text)
        self.assertEqual([ln.strip() for ln in code_lines(self.text) if "fail-fast" in ln], ["fail-fast: false"])
        self.assertEqual([st["python-version"] for st in steps(self.text) if "python-version" in st],
                         ["${{ matrix.python-version }}"])

    def test_workflow_runs_suite_index_run_all_in_order(self):  # W6, W11
        self.assertEqual(step_order(self.text), ["checkout", "setup-python", "unittest", "index", "run_all"])
        self.assertEqual([st["run"] for st in steps(self.text) if "run" in st],
                         [SUITE, "python -m gates index", RUN_ALL])

    def test_workflow_full_history(self):  # W7
        self.assertEqual(steps(self.text)[0]["fetch-depth"], "0")
        self.assertEqual(sum("fetch-depth" in ln for ln in code_lines(self.text)), 1)

    def test_workflow_names_no_branch(self):  # W8: no branch name literal
        self.assertNotIn("origin/main", self.text)
        for word in ("main", "master", "develop", "trunk"):
            self.assertIsNone(re.search(r"\b%s\b" % word, self.text), word)

    def test_workflow_base_expression(self):  # W8, W9
        run = [st["run"] for st in steps(self.text) if st.get("run", "").startswith("python -m gates run_all")]
        self.assertEqual(len(run), 1)
        m = re.fullmatch(r"python -m gates run_all --base origin/\$\{\{ (.*) \}\}", run[0])
        self.assertIsNotNone(m, run[0])
        expr = m.group(1)
        self.assertEqual(expr, BASE_EXPRESSION)
        # push to the default branch, a pull request to another base, a push to another branch
        self.assertEqual(evaluate(expr, payload("push", "", "trunk")), "trunk")
        self.assertEqual(evaluate(expr, payload("pull_request", "release/1", "trunk")), "release/1")
        self.assertEqual(evaluate(expr, payload("push", "", "dev")), "dev")

    def test_actions_pinned(self):  # W10
        found = uses(self.text)
        self.assertEqual(len(found), 2)
        for value in found:
            self.assertRegex(value, r"[^@\s]+@[0-9a-f]{40}")
            self.assertIsNotNone(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value), value)
        self.assertEqual(found, ["%s@%s" % (repo, PINS[repo][0]) for repo in ("actions/checkout",
                                                                              "actions/setup-python")])
        for repo, (sha, tag) in PINS.items():  # the trailing comment names the tag
            self.assertIn("uses: %s@%s  # %s\n" % (repo, sha, tag), self.text)

    def test_workflow_permissions(self):  # W12
        self.assertEqual(top_block(self.text, "permissions"), ["  contents: read"])

    def test_workflow_parsers_text_only(self):  # K1, K2
        base = (pythons(self.text), oses(self.text), uses(self.text), steps(self.text), step_order(self.text),
                top_block(self.text, "on"), top_block(self.text, "permissions"))
        for digits in (4300, 4301):  # K1: a version of that many digits is text; nothing here reads a number
            text = self.text.replace('["3.9", "3.13"]', '["%s"]' % ("9" * digits))
            self.assertEqual(pythons(text), [['"%s"' % ("9" * digits)]])
            self.assertEqual(steps(text), steps(self.text))
        text = "\n".join(ln + "  # \U0001F6DD" if ln else ln for ln in self.text.split("\n"))  # K2
        self.assertEqual((pythons(text), oses(text), uses(text), steps(text), step_order(text),
                          top_block(text, "on"), top_block(text, "permissions")), base)
        for fn in (code_lines, top_block, flow_items, steps, step_order, evaluate):
            self.assertIsNone(re.search(r"\bint\(", inspect.getsource(fn)), fn.__name__)

    def test_no_exception_group_in_workflow(self):  # K3
        self.assertNotIn("Exception" + "Group", self.text)


if __name__ == "__main__":
    unittest.main()
