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
from gates.lib import config, migrations, yamlsub
from gates.tools import githooks
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = ".strict-delivery/config.yml"
BASE = "b7afa88"  # Task 2b.2's reviewed head: the config at the base holds exactly the three keys schema, framework_version, profile
COMMANDS_TEST = (
    "python3 -c \"import sys; sys.exit(0 if sys.version_info[:2] == (3, 9) else 'commands.test: python3 is not Python 3.9')\" "
    "&& python3.13 -c \"import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else "
    "'commands.test: python3.13 is not Python 3.13')\" "
    "&& python3 -m unittest discover -s tests -t . && python3.13 -m unittest discover -s tests -t .")
NESTED = "SD_SELF_ADOPTION_NESTED"  # set in the suite run inside a clone: the clone tests do not recurse
UNSTAGED = "tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed"
SHALLOW = "FAIL %s.input: git merge-base failed (exit 1)\n"
# the two files the hook test creates in its clone; the names are unlike any file of this checkout, because the clone
# holds this checkout's working files, including a path staged by the commit this suite runs under (the commit gate)
CLEAN = "hookfixture-clean.txt"
STAGED = "hookfixture-staged.txt"


# Task CI2: a test of tests.test_run_all or tests.test_self_adoption whose source runs git or the gates on this checkout
# (``cwd=REPO``, ``-C REPO``, ``git(REPO``, ``self.sub(``) or on a clone of it (``clone_copy``, ``gates_run_all``), or asks
# whether it has a local main, can resolve a base branch or ``main`` of the clone; every other test of the two modules
# builds its own fixture repository under a temporary directory and never reads the clone's refs.
NESTED_MODULES = ("tests.test_run_all", "tests.test_self_adoption")
NESTED_SELECT = re.compile(r"clone_copy|gates_run_all|self\.sub\(|has_local_main|cwd=REPO|\"-C\", REPO|git\(REPO")


def nested_ids(modules=NESTED_MODULES, select=NESTED_SELECT):
    """The test ids of ``modules`` whose method source matches ``select`` (inherited methods included), in load order."""
    import importlib
    ids = []

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                fn = getattr(type(item), item._testMethodName)
                if select.search(inspect.getsource(fn)):
                    ids.append(item.id())
    for name in modules:
        walk(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
    return ids


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

    def test_config_only_four_keys_added(self):  # G3 (edited, RC5): commands, top_tier_roles, reviews and merge (Q-M1)
        p = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (BASE, CONFIG)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        base_path = os.path.join(self.tmp, "base.yml")
        with open(base_path, "wb") as fh:
            fh.write(p.stdout)
        base = yamlsub.load(base_path, CONFIG)
        # exempt literal (P:32): the content of the config at BASE, read from git; its tag is that commit's own
        self.assertEqual(base, {"schema": "config/1", "framework_version": "0.0.0", "profile": "strict"})
        current = dict(self.load_raw())
        self.assertEqual(sorted(set(current) - set(base)), ["commands", "merge", "reviews", "top_tier_roles"])
        for key in ("commands", "merge", "reviews", "top_tier_roles"):
            del current[key]
        # this repository is migrated to config/2 (Task 2c.2): the base keys under the migrated tag
        self.assertEqual(current, migrations.migrate("config", base))
        # append only: the base's lines open the file unchanged but for the first line's tag, the new keys follow
        old_text = p.stdout.decode("utf-8")
        first, nl, rest = old_text.partition("\n")
        self.assertEqual((first, nl), ("schema: config/1", "\n"))
        tag = "config/%d" % migrations.current_version("config")
        text = read_text(os.path.join(REPO, CONFIG))
        self.assertTrue(text.startswith("schema: " + tag + "\n" + rest))


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
        raw = "'" + COMMANDS_TEST.replace("'", "''") + "'"  # the single-quoted YAML scalar of the config
        self.assertEqual(text.count(raw), 1)
        with open(path, "w", encoding="utf-8") as fh:  # H2: a fast command, so the suite does not recurse
            fh.write(text.replace(raw, "\"true\""))
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
        # CI2 (suite speed): the nested run holds the tests whose path runs git or the gates on this checkout or on a
        # clone of it (nested_ids), not the fixture-only tests of the two modules, which never read the clone's refs
        ids = nested_ids()
        self.assertTrue(ids)  # an empty list would make unittest discover and run everything
        from tests.test_nested_selection import EXPECTED  # row N1: the whole selection runs, this test included
        self.assertEqual(sorted(ids), EXPECTED)  # (a slice would still exit 0 and "Ran" its own length)
        p = subprocess.run([sys.executable, "-m", "unittest"] + ids,
                           cwd=clone, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        text = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, text[-3000:])
        self.assertIn("\nRan %d test%s in " % (len(ids), "" if len(ids) == 1 else "s"), text)

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
SUITE = "python -m tests.ci_shards --shards 5 --index ${{ matrix.shard }}"  # Task CI1: the suite runs as five shard jobs
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
        if len(ln) - len(ln.lstrip()) <= 4:  # Task CI1: the next key of the job or the next job ends the steps (two matrix jobs)
            inside = False
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
        elif st.get("run", "").startswith("python -m tests.ci_shards"):
            kinds.append("shard")
        elif st.get("name") == "Require every shard":
            kinds.append("require")
        elif st.get("run", "") == "python -m gates index":
            kinds.append("index")
        elif st.get("name") == "Create the local base branch":
            kinds.append("base")
        elif st.get("run", "").startswith("python -m gates run_all"):
            kinds.append("run_all")
        else:
            kinds.append("?")
    return kinds


def job_text(text, name):
    """The raw lines of the job ``name`` (its ``  name:`` line to the next line at two-space indent), joined, no trailing
    blank: Task P3.1 adds a second job, so the matrix job's pins read this job only."""
    out = None
    for ln in text.split("\n"):
        if out is None:
            if ln == "  %s:" % name:
                out = [ln]
        elif re.match(r"  \S", ln) or (ln and not ln[0].isspace()):
            break
        else:
            out.append(ln)
    while out and out[-1] == "":  # trailing blank lines only: a space at the end of the last line is part of the job
        out.pop()
    return "" if out is None else "\n".join(out) + "\n"


# the matrix job as Task 2b.3 wrote it plus the base branch step before run_all (FR-P3-1, plan :3038: a cleanup pull
# request must pass CI, and the register gate needs a local base branch); the table's WF10 pins it byte for byte
# Task CI1 (edited on purpose): the suite moved to the shard job below, the gates job gains needs, if and a first step
GATES_JOB = (
    "  gates:\n"
    "    needs: shard\n"
    "    if: always()\n"
    "    runs-on: ${{ matrix.os }}\n"
    "    strategy:\n"
    "      fail-fast: false\n"
    "      matrix:\n"
    "        os: [ubuntu-24.04, macos-15]\n"
    "        python-version: [\"3.9\", \"3.13\"]\n"
    "    steps:\n"
    "      - name: Require every shard\n"
    "        env:\n"
    "          SHARD_RESULT: ${{ needs.shard.result }}\n"
    "        run: |\n"
    "          [ \"$SHARD_RESULT\" = success ] || { echo \"the shard jobs did not all succeed (result: $SHARD_RESULT)\" >&2; "
    "exit 1; }\n"
    "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1\n"
    "        with:\n"
    "          fetch-depth: 0\n"
    "      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7.1.0\n"
    "        with:\n"
    "          python-version: ${{ matrix.python-version }}\n"
    "      - run: python -m gates index\n"
    "      - name: Create the local base branch\n"
    "        if: github.event_name == 'pull_request'\n"
    "        env:\n"
    "          BASE_REF: ${{ github.base_ref }}\n"
    "        run: |\n"
    "          git rev-parse --verify --quiet \"refs/heads/$BASE_REF\" > /dev/null || git branch \"$BASE_REF\" "
    "\"origin/$BASE_REF\"\n"
    "      - run: python -m gates run_all --base origin/${{ github.event_name == 'pull_request' && github.base_ref || "
    "github.event.repository.default_branch }}\n")

# Task CI1: the shard job, byte for byte (W4, W6, W7, W8)
SHARD_JOB = (
    "  shard:\n"
    "    runs-on: ${{ matrix.os }}\n"
    "    strategy:\n"
    "      fail-fast: false\n"
    "      matrix:\n"
    "        os: [ubuntu-24.04, macos-15]\n"
    "        python-version: [\"3.9\", \"3.13\"]\n"
    "        shard: [1, 2, 3, 4, 5]\n"
    "    steps:\n"
    "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1\n"
    "        with:\n"
    "          fetch-depth: 0\n"
    "      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7.1.0\n"
    "        with:\n"
    "          python-version: ${{ matrix.python-version }}\n"
    "      - run: python -m tests.ci_shards --shards 5 --index ${{ matrix.shard }}\n")


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
        cls.gates = job_text(cls.text, "gates")  # the matrix job: W3, W6, W7, W10 read it alone (Task P3.1, D-Q6)
        cls.shard = job_text(cls.text, "shard")  # Task CI1: the suite's matrix job

    def test_workflow_is_not_a_data_file(self):  # W1
        self.assertNotIn("schema:", self.text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out.getvalue())

    def test_workflow_triggers(self):  # W2: pull_request plus push to main only (owner answer 2026-11-22), nothing looser
        self.assertEqual(top_block(self.text, "on"), ["  push:", "    branches: [main]", "  pull_request:"])

    def test_workflow_matrix(self):  # W3, W4, W5 (W3 scoped to the matrix job, edited on purpose); CI1 W1: two matrix jobs
        self.assertEqual(oses(self.text), [["ubuntu-24.04", "macos-15"]] * 2)  # the shard job and the gates job
        self.assertEqual(pythons(self.text), [['"3.9"', '"3.13"']] * 2)
        self.assertEqual([ln for ln in code_lines(self.gates) if "runs-on:" in ln], ["    runs-on: ${{ matrix.os }}"])
        self.assertEqual([ln for ln in code_lines(self.shard) if "runs-on:" in ln], ["    runs-on: ${{ matrix.os }}"])
        self.assertEqual([ln for ln in code_lines(self.gates) if ln.startswith("    name:")], [])  # CI1 W1: no job name
        self.assertNotIn("latest", self.text)
        for word in ("include:", "exclude:"):
            self.assertNotIn(word, self.text)
        self.assertEqual([ln.strip() for ln in code_lines(self.text) if "fail-fast" in ln], ["fail-fast: false"] * 2)
        self.assertEqual([st["python-version"] for st in steps(self.gates) if "python-version" in st],
                         ["${{ matrix.python-version }}"])
        self.assertEqual([st["python-version"] for st in steps(self.shard) if "python-version" in st],
                         ["${{ matrix.python-version }}"])

    def test_workflow_runs_suite_index_run_all_in_order(self):  # W6, W11 (scoped to the matrix job, edited on purpose)
        self.assertEqual(step_order(self.gates), ["require", "checkout", "setup-python", "index", "base", "run_all"])
        self.assertEqual(step_order(self.shard), ["checkout", "setup-python", "shard"])  # CI1 W7: the suite runs in the shards only
        self.assertEqual([st["run"] for st in steps(self.gates) if "run" in st],
                         ["|", "python -m gates index", "|", RUN_ALL])
        self.assertEqual([st["run"] for st in steps(self.shard) if "run" in st], [SUITE])
        self.assertNotIn("unittest", self.text)  # the discover step is gone: the shards' union is the suite

    def test_workflow_full_history(self):  # W7 (scoped to the matrix job, edited on purpose)
        self.assertEqual(steps(self.gates)[1]["fetch-depth"], "0")  # the first step is the shard check (Task CI1)
        self.assertEqual(sum("fetch-depth" in ln for ln in code_lines(self.gates)), 1)
        self.assertEqual(steps(self.shard)[0]["fetch-depth"], "0")  # CI1 W8: the shards read the history too
        self.assertEqual(sum("fetch-depth" in ln for ln in code_lines(self.shard)), 1)

    def test_workflow_names_no_branch(self):  # W8: no branch name literal outside the on: block (W2 pins that block exactly)
        lines, skip = [], False
        for ln in self.text.splitlines():
            if ln == "on:":
                skip = True
            elif skip and ln and not ln[0].isspace():
                skip = False
            if not skip:
                lines.append(ln)
        outside = "\n".join(lines)
        self.assertNotIn("origin/main", outside)
        for word in ("main", "master", "develop", "trunk"):
            self.assertIsNone(re.search(r"\b%s\b" % word, outside), word)
        self.assertEqual(len(re.findall(r"\bmain\b", self.text)), 1)  # the W2 line only

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

    def test_actions_pinned(self):  # W10 (the matrix job's two; the pull-request job's are pinned below), WF12
        for scope in (self.shard, self.gates, job_text(self.text, "pull-request")):  # Task CI1: the shard job's two as well
            found = uses(scope)
            self.assertEqual(len(found), 2)
            for value in found:
                self.assertRegex(value, r"[^@\s]+@[0-9a-f]{40}")
                self.assertIsNotNone(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value), value)
            self.assertEqual(found, ["%s@%s" % (repo, PINS[repo][0]) for repo in ("actions/checkout",
                                                                                  "actions/setup-python")])
            for repo, (sha, tag) in PINS.items():  # the trailing comment names the tag
                self.assertIn("uses: %s@%s  # %s\n" % (repo, sha, tag), scope)
        self.assertEqual(len(uses(self.text)), 6)  # no other action anywhere (CI1 W6: six in all)

    def test_workflow_permissions(self):  # W12
        self.assertEqual(top_block(self.text, "permissions"), ["  contents: read"])

    def test_workflow_parsers_text_only(self):  # K1, K2
        base = (pythons(self.text), oses(self.text), uses(self.text), steps(self.text), step_order(self.text),
                top_block(self.text, "on"), top_block(self.text, "permissions"))
        for digits in (4300, 4301):  # K1: a version of that many digits is text; nothing here reads a number
            text = self.text.replace('["3.9", "3.13"]', '["%s"]' % ("9" * digits))
            self.assertEqual(pythons(text), [['"%s"' % ("9" * digits)]] * 2)  # CI1: two matrix jobs
            self.assertEqual(steps(text), steps(self.text))
        text = "\n".join(ln + "  # \U0001F6DD" if ln else ln for ln in self.text.split("\n"))  # K2
        self.assertEqual((pythons(text), oses(text), uses(text), steps(text), step_order(text),
                          top_block(text, "on"), top_block(text, "permissions")), base)
        for fn in (code_lines, top_block, flow_items, steps, step_order, evaluate, job_text):
            self.assertIsNone(re.search(r"\bint\(", inspect.getsource(fn)), fn.__name__)

    def test_no_exception_group_in_workflow(self):  # K3
        self.assertNotIn("Exception" + "Group", self.text)

    def test_repo_subagent_limits(self):  # P4.3 LM1-LM3, D-Q9 (a); owner answer 2026-11-01, file committed at 1e5bdc1
        import json
        with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
            got = json.load(fh)
        self.assertEqual(got, {"env": {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5",
                                       "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30"}})
        for v in got["env"].values():
            self.assertIs(type(v), str)

    # ---- Task P3.1: the pull-request job (rows WF1-WF16; decision D-Q6)
    def pr(self):
        return job_text(self.text, "pull-request")

    def test_pr_job_checks_out_head_sha(self):  # WF1, plan :2949-2951; review 4 F-Pp4-4
        self.assertIn("github.event.pull_request.head.sha", self.text)
        self.assertIn("check streams --branch", self.text)
        self.assertEqual(steps(self.pr())[0]["ref"], "${{ github.event.pull_request.head.sha }}")  # not the test-merge ref
        self.assertNotIn("refs/pull", self.text)
        self.assertNotIn("merge_commit_sha", self.text)

    def test_pr_job_full_history(self):  # WF2
        self.assertEqual(steps(self.pr())[0]["fetch-depth"], "0")
        self.assertEqual(sum("fetch-depth" in ln for ln in code_lines(self.pr())), 1)

    def test_pr_job_streams_command(self):  # WF3: the head ref reaches the shell through env, never through ${{ }} in run
        # Edited on purpose by Task P3.3 (D-Q5 (i), D-Q7): the step list is exact, the streams step is the fifth of six,
        # and the head ref and the base ref each reach a shell only through an env: line.
        sts = steps(self.pr())
        self.assertEqual([st.get("name") for st in sts], [None, None, "Create the local integration branches",
                                                          "Create the local base branch",
                                                          "Check the streams of the head branch",
                                                          "Check the cleanup of a cleanup head"])
        streams = sts[4]
        self.assertEqual(streams["run"], 'python -m gates check streams --branch "$HEAD_REF"')
        self.assertEqual(streams["HEAD_REF"], "${{ github.head_ref }}")
        for st in sts:
            self.assertNotIn("${{", st.get("run", ""))
        self.assertEqual([ln for ln in code_lines(self.pr()) if "${{" in ln],
                         ["          ref: ${{ github.event.pull_request.head.sha }}",
                          "          BASE_REF: ${{ github.base_ref }}", "          HEAD_REF: ${{ github.head_ref }}",
                          "          HEAD_REF: ${{ github.head_ref }}"])
        self.assertEqual(self.pr().count("github.head_ref"), 2)  # the streams step and the cleanup step, env lines only
        self.assertEqual(self.pr().count("github.base_ref"), 1)

    def test_pr_job_creates_integration_before_streams(self):  # WF4
        names = [st.get("name") for st in steps(self.pr())]
        make = names.index("Create the local integration branches")
        check = names.index("Check the streams of the head branch")
        self.assertLess(make, check)
        self.assertLess(make, names.index("Create the local base branch"))  # Task P3.3: after the loop, so it never repeats it
        self.assertEqual(self.pr().count("git branch "), 2)  # the loop and the base branch step (edited on purpose)
        self.assertEqual(self.pr().count("refs/remotes/origin/*/integration"), 1)

    def test_workflow_runs_cleanup_for_cleanup_heads(self):  # plan test
        self.assertIn("gates check cleanup --plan", self.text)
        self.assertIn("gates check cleanup --plan", self.pr())
        self.assertNotIn("check cleanup", self.gates)  # the matrix job never runs it (P3.3 WF1)
        self.assertEqual(self.gates, GATES_JOB)

    def test_cleanup_step_order(self):  # WF10
        names = [st.get("name") for st in steps(self.pr())]
        self.assertEqual(names[:2], [None, None])  # checkout and setup-python first
        last = names.index("Check the cleanup of a cleanup head")
        self.assertLess(names.index("Create the local base branch"), last)
        self.assertLess(names.index("Check the streams of the head branch"), last)  # check streams is not replaced
        self.assertIn("    if: github.event_name == 'pull_request'", code_lines(self.pr()))  # the job's only trigger

    def test_pr_job_passes_branch(self):  # WF7: a detached checkout has no branch; the gate must be told it
        for ln in code_lines(self.text):
            if "check streams" in ln:
                self.assertIn('--branch "$HEAD_REF"', ln)

    def test_pr_job_only_on_pull_request(self):  # WF8: github.head_ref is empty on a push, and --branch "" is refused
        self.assertIn("    if: github.event_name == 'pull_request'", code_lines(self.pr()))
        self.assertEqual(sum("if:" in ln for ln in code_lines(self.text)), 3)  # Task CI1: and the gates job's `if: always()`
        self.assertEqual(code_lines(self.gates).count("        if: github.event_name == 'pull_request'"), 1)  # FR-P3-1

    def test_pr_job_runner(self):  # WF13 and the table's D-Q6: ubuntu-24.04, one Python 3.13, nothing else
        self.assertIn("    runs-on: ubuntu-24.04", code_lines(self.pr()))
        self.assertEqual([st["python-version"] for st in steps(self.pr()) if "python-version" in st], ['"3.13"'])
        self.assertNotIn("matrix", self.pr())
        self.assertEqual(top_block(self.text, "permissions"), ["  contents: read"])

    def test_gates_job_unchanged(self):  # WF10: the run_all job is byte for byte Task 2b.3's plus the base branch step (FR-P3-1)
        self.assertEqual(self.gates, GATES_JOB)  # Task CI1: and its needs, if and first step; W1, W3, W5
        self.assertEqual(self.shard, SHARD_JOB)  # CI1 W4, W6, W7, W8
        self.assertEqual(code_lines(self.gates)[1:3], ["    needs: shard", "    if: always()"])
        self.assertFalse([ln for ln in self.gates.split("\n") if ln.startswith("    name:")])  # W1: no name, so the check is `gates (os, py)`
        self.assertEqual(self.text.count("  gates:\n"), 1)


class PullRequestJobTest(GitIsolatedTestCase):
    """The creation step of the pull-request job, run as the shell would run it on a clone with remote branches."""

    @classmethod
    def setUpClass(cls):
        cls.script = cls.step_script(job_text(read_text(os.path.join(REPO, WORKFLOW)), "pull-request"),
                                     "Create the local integration branches")

    @staticmethod
    def step_script(job, name):
        lines = job.split("\n")
        at = lines.index("      - name: " + name)
        body = []
        for ln in lines[at + 1:]:
            if ln.startswith("      - "):
                break
            body.append(ln)
        start = body.index("        run: |")
        return "\n".join(ln[10:] for ln in body[start + 1:] if ln.strip()) + "\n"

    def clone(self, branches):
        src = make_repo(self.work)
        for b in branches:
            git(src, "checkout", "-q", "-b", b, "main")
            commit_all(src, "tip of " + b)  # each branch has its own tip: a branch made from HEAD is not the origin one
        git(src, "checkout", "-q", "main")
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", remote)
        git(src, "push", "-q", remote, "--all")
        dst = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", remote, dst)
        git(dst, "checkout", "-q", "--detach")  # the job checks out the head sha: no local branch
        return dst

    def local(self, root):
        return git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads").split("\n")

    def run_step(self, root):
        return subprocess.run(["sh", "-c", self.script], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_pr_job_no_integration_ref_is_not_an_error(self):  # WF5: an empty list of refs creates nothing and succeeds
        root = self.clone(["feat"])
        before = self.local(root)
        p = self.run_step(root)
        self.assertEqual((p.returncode, p.stdout), (0, b""))
        self.assertEqual(self.local(root), before)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "streams", "--root", root, "--branch", "feat"])
        self.assertEqual((out.getvalue(), code), ("PASS streams.none\n", 0))
        out = io.StringIO()  # a program-shaped head ref with no integration branch is the gate's own refusal
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "streams", "--root", root, "--branch", "20260101-x/integration"])
        self.assertEqual((out.getvalue(), code),
                         ("FAIL streams.input: branch 20260101-x/integration does not exist locally; create it from the remote\n", 1))

    def test_pr_job_branch_name_forms(self):  # WF6: p/integration is created from origin; nested names and others are not
        root = self.clone(["feat", "20260101-x/integration", "20260102-y/integration", "a/b/integration", "integration"])
        p = self.run_step(root)
        self.assertEqual(p.returncode, 0, p.stdout)
        said = p.stdout.decode("utf-8").split("\n")[:-1]  # git branch says only that each new branch tracks its origin
        self.assertEqual([ln.split("'")[1] for ln in said], ["20260101-x/integration", "20260102-y/integration"])
        self.assertEqual(self.local(root), ["20260101-x/integration", "20260102-y/integration", "main"])  # main: the clone's own
        for name in ("20260101-x/integration", "20260102-y/integration"):
            self.assertEqual(git(root, "rev-parse", name), git(root, "rev-parse", "origin/" + name))


class CleanupStepTest(GitIsolatedTestCase):
    """The cleanup step and the base branch step of the pull-request job (Task P3.3, rows WF3-WF9; decisions D-Q4, D-Q5 (i),
    D-Q7), run as ``sh -c`` runs them with ``python`` the interpreter of this run."""

    CLEANUP = "Check the cleanup of a cleanup head"
    BASE = "Create the local base branch"

    @classmethod
    def setUpClass(cls):
        job = job_text(read_text(os.path.join(REPO, WORKFLOW)), "pull-request")
        cls.cleanup = PullRequestJobTest.step_script(job, cls.CLEANUP)
        cls.base = PullRequestJobTest.step_script(job, cls.BASE)

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        shim = os.path.join(self.bin, "python")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(shim, 0o755)
        self.repo = make_repo(self.work)

    def run_step(self, script, cwd, **env):
        full = dict(os.environ, PYTHONPATH=REPO, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        full.update(env)
        p = subprocess.run(["sh", "-c", script], cwd=cwd, env=full, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode("utf-8")

    def head(self, ref):
        return self.run_step(self.cleanup, self.repo, HEAD_REF=ref)

    def test_cleanup_step_in_pull_request_job_only(self):  # WF1
        text = read_text(os.path.join(REPO, WORKFLOW))
        code = "\n".join(code_lines(text))
        self.assertEqual(code.count("check cleanup"), 2)  # the step and its program-close echo, both in one job
        self.assertEqual("\n".join(code_lines(job_text(text, "pull-request"))).count("check cleanup"), 2)

    def test_cleanup_step_runs_for_cleanup_heads(self):  # WF4: the slug is the tail after cleanup/
        self.assertEqual(self.head("cleanup/fx"), (1, "FAIL cleanup.merge: plan fx has no final merge on the base branch\n"))

    def test_cleanup_step_skipped_for_other_heads(self):  # WF5 (D-Q7 (a): an exact, case-sensitive match)
        for ref in ("feat/x", "block/p3", "cleanup", "cleanup-fx", "xcleanup/fx", "feat/cleanup/fx", "Cleanup/fx",
                    "20261101-x/integration", ""):
            with self.subTest(ref=ref):
                self.assertEqual(self.head(ref), (0, ""))

    def test_cleanup_step_slug_forms(self):  # WF6
        bad = "FAIL cleanup.input: --plan must match [a-z0-9][a-z0-9-]*\n"
        for ref, want in (("cleanup/fx", None), ("cleanup/2026-10-31-x", None), ("cleanup/a/b", bad), ("cleanup/-x", bad),
                          ("cleanup/FX", bad), ("cleanup/café", bad), ("cleanup/", bad)):
            with self.subTest(ref=ref):
                code, out = self.head(ref)
                if want is None:
                    self.assertEqual((code, out.split(":")[0]), (1, "FAIL cleanup.merge"))
                else:
                    self.assertEqual((code, out), (1, want))
        code, out = self.head("cleanup/" + "a" * 300)
        self.assertEqual(code, 1)
        self.assertIn(out.split(":")[0], ("FAIL cleanup.merge", "FAIL cleanup.input"))

    def test_cleanup_step_hostile_head_refs(self):  # WF7: no shell interpretation of any git-legal name
        tails = ["$(touch PWNED)", "a;touch PWNED", "a`touch PWNED`", "a'b", 'a"b', "a|b", "a&b", "a>b", "a#b", "a{b", "a%b",
                 "$(id)"]
        for tail in tails:
            with self.subTest(tail=tail):
                code, out = self.head("cleanup/" + tail)
                self.assertFalse(os.path.exists(os.path.join(self.repo, "PWNED")))
                self.assertFalse(os.path.exists(os.path.join(self.repo, "b")))
                self.assertEqual((code, out), (1, "FAIL cleanup.input: --plan must match [a-z0-9][a-z0-9-]*\n"))
        self.assertNotIn("${{", self.cleanup)  # head_ref and base_ref only in env: lines (WorkflowTest pins the lines)

    def test_cleanup_step_program_close_head(self):  # WF9, D-Q4 (a): a tail that names a program is checked by hand
        code, out = self.head("cleanup/20261101-x")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("program close: "), out)
        self.assertEqual(self.head("cleanup/20261301-x")[0], 1)  # not a calendar date: not a program name, a plan slug
        self.assertEqual(self.head("cleanup/2026-10-31-x")[0], 1)

    def test_cleanup_step_needs_local_base_branch(self):  # WF8, EN8: a detached checkout has no local base branch
        src = self.repo
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", remote)
        git(src, "checkout", "-q", "-b", "20261101-x/integration")
        commit_all(src, "integration tip")
        git(src, "checkout", "-q", "main")
        git(src, "push", "-q", remote, "--all")
        dst = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", remote, dst)
        git(dst, "checkout", "-q", "--detach")
        git(dst, "branch", "-q", "-D", "main")
        self.assertEqual(git(dst, "for-each-ref", "--format=%(refname:short)", "refs/heads"), "")
        code, out = self.run_step(self.base, dst, BASE_REF="main")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("branch 'main' set up to track"), out)
        self.assertEqual(git(dst, "rev-parse", "main"), git(dst, "rev-parse", "origin/main"))
        self.assertEqual(self.run_step(self.base, dst, BASE_REF="main"), (0, ""))  # a second run changes nothing
        self.assertEqual(self.run_step(self.base, dst, BASE_REF="20261101-x/integration")[0], 0)
        self.assertEqual(self.run_step(self.base, dst, BASE_REF="20261101-x/integration"), (0, ""))
        self.assertEqual(self.run_step(self.base, dst, BASE_REF="nosuch")[0], 128)


class MatrixJobBaseBranchTest(GitIsolatedTestCase):
    """FR-P3-1 (F-20261122-w4im, plan :3038): the matrix job runs ``run_all``, whose register gate reads a deleted resolved
    finding through ``cleanup.final_merge``, which needs a local ``refs/heads/<base>``; a pull_request checkout has none."""

    BASE = "Create the local base branch"

    @classmethod
    def setUpClass(cls):
        job = job_text(read_text(os.path.join(REPO, WORKFLOW)), "gates")
        cls.script = PullRequestJobTest.step_script(job, cls.BASE)

    def ci_clone(self):
        """A clone as the matrix job sees a cleanup pull request: bare remote, detached at the cleanup head, no local branch."""
        from tests import test_gate_register as gr
        cfg = {**minimal_config(), "merge": {"mode": "controller"}}
        src = make_repo(self.work, cfg)
        write_record(src, gr.fpath(gr.F), gr.frow(gr.F, "closed"))
        os.makedirs(os.path.join(src, "src"))
        with open(os.path.join(src, "src", "x.py"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        commit_all(src, "fixture")
        git(src, "checkout", "-q", "-b", "t")
        plan = os.path.join(src, ".strict-delivery", "state", "plans", "p")
        os.makedirs(plan)
        with open(os.path.join(plan, "work.md"), "w", encoding="utf-8") as fh:
            fh.write("w\n")
        head = commit_all(src, "work")
        git(src, "checkout", "-q", "main")
        git(src, "merge", "-q", "--no-ff", "-m", "merge", "t")
        merge = git(src, "rev-parse", "HEAD")
        with open(os.path.join(plan, "ledger.md"), "w", encoding="utf-8") as fh:
            fh.write("<!-- schema: ledger/1 -->\nMERGED pr=12 head=%s merge=%s merged_by=u at=2026-11-02T06:23:42Z final=yes "
                     "approval=chat pr=12 head=%s words=approve PR 12\n" % (head, merge, head))
        commit_all(src, "ledger")
        git(src, "checkout", "-q", "-b", "cleanup/p")
        git(src, "rm", "-q", gr.fpath(gr.F))
        commit_all(src, "cleanup")
        git(src, "checkout", "-q", "main")
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", remote)
        git(src, "push", "-q", remote, "--all")
        dst = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", remote, dst)
        git(dst, "checkout", "-q", "--detach", "origin/cleanup/p")
        git(dst, "branch", "-q", "-D", "main")
        self.assertEqual(git(dst, "for-each-ref", "--format=%(refname:short)", "refs/heads"), "")
        return dst, gr.F

    def register(self, root):
        env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
        p = subprocess.run([sys.executable, "-m", "gates", "check", "register", "--root", root, "--base", "origin/main"],
                           cwd=root, env=dict(env, PYTHONPATH=REPO), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_cleanup_register_needs_the_matrix_base_step(self):  # FR-P3-1
        root, fid = self.ci_clone()
        code, out, err = self.register(root)
        self.assertEqual(code, 1, out + err)
        self.assertIn("FAIL register.base.deleted.%s" % fid, out)
        p = subprocess.run(["sh", "-c", self.script], cwd=root, env=dict(os.environ, BASE_REF="main"),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout)
        code, out, err = self.register(root)
        self.assertEqual((code, err), (0, ""), out)
        self.assertNotIn("register.base.deleted", out)


if __name__ == "__main__":
    unittest.main()
