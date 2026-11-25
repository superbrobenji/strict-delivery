"""Task CI3: the mutation tests of a pull request, run in CI from the tasks' committed mutant tables.

    python -m tests.ci_mutants split   --base REF --head SHA --parts N --part K
    python -m tests.ci_mutants run     --base REF --head SHA --parts N --part K --python LABEL=PATH --python LABEL=PATH [--timeout SECONDS]
    python -m tests.ci_mutants summary --base REF --head SHA --parts N

THE TABLE CONVENTION. A task commits one table on the pull request's branch, at ``.strict-delivery/mutants/<task-id>.py``
(the directory is TABLE_DIR; the file name matches ``[A-Za-z0-9][A-Za-z0-9._-]*.py``). Only the files directly under that
directory that the pull request adds or changes (``git diff --no-renames`` of the exact head against the merge base with
``--base``) are tables; a deleted table runs nothing; a file elsewhere is not run; a file under the directory that is no
table name is refused. A table holds exactly two literal assignments and nothing else (it is parsed with ``ast`` and is
never executed, imported or evaluated by this runner):

    M = {"id": ("relative/path.py", "old text", "new text")}      # par_mutants' table, so it stays usable there
    KILL = {"id": ("tests.test_a", "tests.test_b")}              # the test modules that should kill the id

An id is ASCII ``[A-Za-z0-9][A-Za-z0-9._-]{0,63}``, unique across the changed tables. A path is relative, ASCII
``[A-Za-z0-9_./+@=,-]``, the name of a tracked regular file reached without a symbolic link, and none of the protected
paths (this runner and its tests, every table, every killing module of every changed table, and ``.github``). ``old``
must occur exactly once in the file's bytes (overlapping occurrences count; no newline translation), else NOT_APPLIED.

``split`` prints the ids of part K of N: the sorted (table, id) pairs cut into N contiguous blocks whose sizes differ by
at most one (the larger blocks first); it depends on the sorted pairs only. ``run`` baselines every killing module of
its part on both interpreters, then for each id applies the one replacement, runs the id's modules on both interpreters
at once, restores the file byte for byte, checks the tree is clean, and prints one line per id::

    <id>: KILLED|SURVIVED|SPLIT|NOT_APPLIED|TIMEOUT|ERROR | <detail>

KILLED: both interpreters fail. SURVIVED: both pass. SPLIT: they differ. TIMEOUT: a run exceeded ``--timeout`` seconds
(default DEFAULT_TIMEOUT). NOT_APPLIED: ``old`` occurs 0 times or 2 or more times. ERROR: a refused path, a failing
baseline, a runner failure or a dirty tree. The lines are also appended to the file named by the environment variable
GITHUB_OUTPUT as the multi-line output ``lines``. ``summary`` reads every job's result and lines from the environment
(MUTANT_RESULT_k, MUTANT_LINES_k for k = 1..N) and fails on a non-success job, a missing, duplicated, unknown or
unreadable line, and any NOT_APPLIED, TIMEOUT or ERROR; survivors and SPLIT ids are listed and do not fail it.

Exit 0: success. Exit 1: a table, base or head refused, or an ERROR line (``ERROR <where>: <reason>`` names the table and
id). Exit 2: refused arguments (nothing is run). ``main(argv, root=..., execute=..., env=...)`` is the seam the tests use:
``execute(python_path, modules, root, timeout)`` returns ``(exit code, text, timed out)`` for one test run. POSIX only.
"""
import ast
import hashlib
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import threading

TABLE_DIR = ".strict-delivery/mutants"
DEFAULT_TIMEOUT = 900  # seconds per interpreter run: the slowest module of the suite is a few minutes on ubuntu-24.04
MAX_TABLE_BYTES = 1 << 20
MAX_PATH_LENGTH = 300
PROTECTED_FILES = ("tests/ci_mutants.py", "tests/test_ci_mutants.py")  # the runner, the splitter (one module) and their tests
PROTECTED_DIRS = (TABLE_DIR, ".github")
VERDICTS = ("KILLED", "SURVIVED", "SPLIT", "NOT_APPLIED", "TIMEOUT", "ERROR")

NUMBER = re.compile(r"[1-9][0-9]{0,5}")  # at most six digits: option values are never long numeric text
REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
HEAD = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
LABEL = re.compile(r"[A-Za-z0-9._-]{1,16}")
TABLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.py")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MODULE = re.compile(r"tests\.test[A-Za-z0-9_]*")
PATH_CHARS = re.compile(r"[A-Za-z0-9_./+@=,-]+")
LINE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,63}): (KILLED|SURVIVED|SPLIT|NOT_APPLIED|TIMEOUT|ERROR)( \|.*)?")
RAN = re.compile(r"^Ran (\d+) tests?", re.M)
USAGE = ("usage: python -m tests.ci_mutants (split|run|summary) --base REF --head SHA --parts N [--part K] "
         "[--python LABEL=PATH --python LABEL=PATH] [--timeout SECONDS]")
OPTIONS = {"split": ("--base", "--head", "--parts", "--part"),
           "run": ("--base", "--head", "--parts", "--part", "--python", "--timeout"),
           "summary": ("--base", "--head", "--parts")}
REQUIRED = {"split": ("--base", "--head", "--parts", "--part"), "run": ("--base", "--head", "--parts", "--part"),
            "summary": ("--base", "--head", "--parts")}


class Refused(Exception):
    """An argument the command refuses: main() prints it and exits 2."""


class Stop(Exception):
    """A refusal that ends the command before anything runs: printed as ``ERROR <where>: <reason>``, exit 1."""

    def __init__(self, where, message):
        Exception.__init__(self, message)
        self.where = where
        self.message = message


def show(text):
    """A bounded ASCII form of untrusted text for a message (quoted)."""
    return ascii(text if len(text) <= 80 else text[:80] + "...")


def clean(text, limit=200):
    """Untrusted text as one printable ASCII line: escapes, no quotes, bounded."""
    text = text if len(text) <= limit else text[:limit] + "..."
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    return re.sub(r"[^ -~]", lambda m: "\\x%02x" % ord(m.group()), text)


# ---- arguments ----------------------------------------------------------------------------------------------------
def number(option, text):
    if NUMBER.fullmatch(text) is None:
        raise Refused("%s needs a whole number from 1 to 999999 (ASCII digits, no sign, no leading zero), got %s"
                      % (option, show(text)))
    return int(text)


def parse(argv):
    """(command, {option: value}); ``--python`` holds a list of (label, path)."""
    if not argv:
        raise Refused(USAGE)
    command = argv[0]
    if command not in OPTIONS:
        raise Refused("unknown command %s; %s" % (show(command), USAGE))
    given = {"--python": []}
    i = 1
    while i < len(argv):
        option = argv[i]
        if option not in OPTIONS[command]:
            raise Refused("unknown argument %s; %s" % (show(option), USAGE))
        if option != "--python" and option in given:
            raise Refused("%s given twice; %s" % (option, USAGE))
        if i + 1 >= len(argv):
            raise Refused("%s needs a value; %s" % (option, USAGE))
        value = argv[i + 1]
        if option in ("--parts", "--part", "--timeout"):
            given[option] = number(option, value)
        elif option == "--base":
            if REF.fullmatch(value) is None or ".." in value or value.endswith(("/", ".lock")):
                raise Refused("--base needs a branch or ref name (letters, digits, _ . / -, no .., not starting with - or "
                              "a dot-dot), got %s" % show(value))
            given[option] = value
        elif option == "--head":
            if HEAD.fullmatch(value) is None:
                raise Refused("--head needs the full lowercase hex commit sha (40 or 64 digits), got %s" % show(value))
            given[option] = value
        else:
            label, sep, path = value.partition("=")
            if not sep or LABEL.fullmatch(label) is None or not path or "\0" in path:
                raise Refused("--python needs LABEL=PATH (label of 1-16 letters, digits, . _ -), got %s" % show(value))
            if not os.path.isabs(path):
                raise Refused("--python path must be absolute, got %s" % show(path))
            if any(label == other for other, _ in given["--python"]):
                raise Refused("--python label %s given twice" % show(label))
            given["--python"].append((label, path))
        i += 2
    for option in REQUIRED[command]:
        if option not in given:
            raise Refused("%s is required; %s" % (option, USAGE))
    if command == "run" and len(given["--python"]) != 2:
        raise Refused("run needs two --python LABEL=PATH options, got %d" % len(given["--python"]))
    if "--part" in given and given["--part"] > given["--parts"]:
        raise Refused("--part %d is past --parts %d" % (given["--part"], given["--parts"]))
    return command, given


# ---- git ----------------------------------------------------------------------------------------------------------
def git(root, *args):
    p = subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout


def tracked_files(root):
    """{path: mode} of the index (mode ``conflict`` for an unmerged path)."""
    code, out = git(root, "ls-files", "-s", "-z")
    if code != 0:
        raise Stop("tree", "git ls-files failed")
    found = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3:
            raise Stop("tree", "git ls-files printed an entry this runner cannot read")
        path = os.fsdecode(name)
        found[path] = fields[0].decode("ascii") if fields[2] == b"0" else "conflict"
    return found


def tree_problem(root):
    """The text of a problem with the tree (``git status`` shows any change, tracked or untracked), or ''."""
    code, out = git(root, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        return "git status failed"
    text = out.decode("utf-8", "replace").strip()
    if text:
        first = text.splitlines()[0]
        return "the tree is not clean (%d entries, first: %s)" % (len(text.splitlines()), clean(first, 80))
    return ""


def check_head(root, head):
    code, out = git(root, "rev-parse", "--verify", "--quiet", head + "^{commit}")
    code2, out2 = git(root, "rev-parse", "HEAD")
    if code != 0 or code2 != 0 or out.strip() != out2.strip():
        raise Stop("head", "the checkout is at %s, not at --head %s" % (clean(out2.decode("ascii", "replace").strip(), 64), head))


def changed_tables(root, base, head):
    """The table paths the head adds or changes against the merge base; Stop for an unusable base or an unreadable diff."""
    code, out = git(root, "merge-base", base, head)
    if code != 0 or HEAD.fullmatch(out.decode("ascii", "replace").strip()) is None:
        raise Stop("base %s" % base, "is missing or shares no history with the head")
    merge_base = out.decode("ascii").strip()
    code, out = git(root, "diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", merge_base, head, "--", TABLE_DIR)
    if code != 0:
        raise Stop("base %s" % base, "git diff against the merge base failed")
    tokens = out.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    if len(tokens) % 2:
        raise Stop("base %s" % base, "git diff printed output this runner cannot read")
    paths, errors = [], []
    for status, name in zip(tokens[0::2], tokens[1::2]):
        path = os.fsdecode(name)
        letter = status.decode("ascii", "replace")
        if letter == "D":
            continue  # a deleted table runs nothing
        prefix = TABLE_DIR + "/"
        if not path.startswith(prefix) or TABLE_NAME.fullmatch(path[len(prefix):]) is None:
            errors.append("ERROR table %s: not a table file name (a table is %s/<task-id>.py, the name from [A-Za-z0-9._-])"
                          % (clean(path), TABLE_DIR))
        elif letter not in ("A", "M", "T"):
            errors.append("ERROR table %s: unexpected change status %s" % (path, clean(letter, 8)))
        else:
            paths.append(path)
    return sorted(paths), errors


# ---- tables -------------------------------------------------------------------------------------------------------
def ident_text(ident):
    return ident if type(ident) is str and ID.fullmatch(ident) else show(repr(ident))


def regular_problem(root, rel, tracked):
    """Why ``rel`` is not a tracked regular file reached without a symbolic link, or ''."""
    mode = tracked.get(rel)
    if mode is None:
        return "is not a tracked regular file"
    if mode == "120000":
        return "is a symbolic link"
    if mode not in ("100644", "100755"):
        return "is not a tracked regular file (mode %s)" % mode
    parts = rel.split("/")
    cur = root
    try:
        for part in parts[:-1]:
            cur = os.path.join(cur, part)
            st = os.lstat(cur)
            if stat.S_ISLNK(st.st_mode):
                return "has a parent that is a symbolic link"
            if not stat.S_ISDIR(st.st_mode):
                return "has a parent that is not a directory"
        st = os.lstat(os.path.join(cur, parts[-1]))
    except OSError as err:
        return "cannot be read (%s)" % (err.strerror or type(err).__name__)
    if stat.S_ISLNK(st.st_mode):
        return "is a symbolic link"
    if not stat.S_ISREG(st.st_mode):
        return "is not a regular file (a directory or special file)"
    return ""


class Row:
    def __init__(self, table, ident, path, old, new, modules):
        self.table, self.id, self.path, self.old, self.new, self.modules = table, ident, path, old, new, modules

    @property
    def key(self):
        return (self.table, self.id)


def literal_assignments(tree):
    """{name: value node} of the two assignments; a list of problems when the module holds anything else."""
    found, problems = {}, []
    for node in tree.body:
        ok = (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in ("M", "KILL"))
        if not ok:
            problems.append("only the two literal assignments M = {...} and KILL = {...} are allowed (found %s)"
                            % type(node).__name__)
        elif node.targets[0].id in found:
            problems.append("%s is assigned twice; only the two literal assignments M = {...} and KILL = {...} are allowed"
                            % node.targets[0].id)
        else:
            found[node.targets[0].id] = node.value
    for name in ("M", "KILL"):
        if name not in found and not problems:
            problems.append("%s is missing; a table holds exactly the two literal assignments M = {...} and KILL = {...}" % name)
    return found, problems


def read_literals(node, name):
    """(value, problem): the literal of ``node`` and, for a dict, a problem when one key repeats."""
    try:
        value = ast.literal_eval(node)
        keys = [ast.literal_eval(k) for k in node.keys] if isinstance(node, ast.Dict) else []
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as err:
        return None, "%s is not a literal (%s)" % (name, type(err).__name__)
    seen = set()
    for key in keys:
        if key in seen:
            return None, "duplicate key %s in %s" % (show(repr(key)), name)
        seen.add(key)
    return value, None


def load_table(root, rel, tracked):
    """(rows, errors) of one table file; errors are finished ``ERROR table ...`` lines."""
    errors = []

    def err(message, ident=None):
        errors.append("ERROR table %s%s: %s" % (rel, "" if ident is None else " id " + ident_text(ident), message))

    try:
        st = os.lstat(os.path.join(root, *rel.split("/")))
    except OSError as e:
        err("cannot be read (%s)" % (e.strerror or type(e).__name__))
        return [], errors
    if not stat.S_ISREG(st.st_mode):
        err("is not a regular file (a symbolic link, directory or special file)")
        return [], errors
    if st.st_size > MAX_TABLE_BYTES:
        err("is too large (more than %d bytes)" % MAX_TABLE_BYTES)
        return [], errors
    with open(os.path.join(root, *rel.split("/")), "rb") as fh:
        data = fh.read(MAX_TABLE_BYTES + 1)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        err("is not valid UTF-8")
        return [], errors
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as e:
        err("cannot be parsed (syntax error, a NUL byte or nesting too deep: %s)" % type(e).__name__)
        return [], errors
    found, problems = literal_assignments(tree)
    for problem in problems:
        err(problem)
    if problems:
        return [], errors
    values = {}
    for name in ("M", "KILL"):
        values[name], problem = read_literals(found[name], name)
        if problem:
            err(problem)
    if errors:
        return [], errors
    m, kill = values["M"], values["KILL"]
    for name, value in (("M", m), ("KILL", kill)):
        if type(value) is not dict:
            err("%s must be a dict" % name)
    if errors:
        return [], errors
    rows = []
    for ident, value in m.items():
        before = len(errors)
        if type(ident) is not str:
            err("id is not a str", ident)
        elif ID.fullmatch(ident) is None:
            err("id must be ASCII [A-Za-z0-9][A-Za-z0-9._-]{0,63}", ident)
        elif not (type(value) is tuple and len(value) == 3 and all(type(x) is str for x in value)):
            err("value must be a 3-tuple of str (path, old, new)", ident)
        elif value[1] == value[2]:
            err("old equals new", ident)
        elif value[1] == "":
            err("empty old text", ident)
        else:
            try:
                old, new = value[1].encode("utf-8"), value[2].encode("utf-8")
            except UnicodeEncodeError:
                err("old or new is not encodable as UTF-8", ident)
        modules = kill.get(ident) if type(ident) is str else None
        if len(errors) == before and ident not in kill:
            err("no killing module (KILL has no entry for this id)", ident)
        elif len(errors) == before:
            if type(modules) is not tuple or not all(type(x) is str for x in modules):
                err("KILL value must be a tuple of str", ident)
            elif not modules:
                err("no killing module (the KILL tuple is empty)", ident)
            else:
                for module in modules:
                    if MODULE.fullmatch(module) is None or regular_problem(root, module.replace(".", "/") + ".py", tracked):
                        err("killing module %s is not a tracked tests/test*.py module (name it tests.test_x)" % show(module),
                            ident)
        if len(errors) == before:
            rows.append(Row(rel, ident, value[0], old, new, modules))
    for ident in kill:
        if ident not in m:
            err("id is in KILL but not in M", ident)
    return rows, errors


def gather(root, base, head):
    """(changed table paths, rows, errors, tracked): every changed table read; errors are finished lines."""
    check_head(root, head)
    paths, errors = changed_tables(root, base, head)
    tracked = tracked_files(root)
    rows = []
    for rel in paths:
        got, errs = load_table(root, rel, tracked)
        rows.extend(got)
        errors.extend(errs)
    owners = {}
    for row in rows:
        owners.setdefault(row.id, []).append(row.table)
    for ident, tables in sorted(owners.items()):
        if len(set(tables)) > 1:
            for table in sorted(set(tables)):
                other = ", ".join(t for t in sorted(set(tables)) if t != table)
                errors.append("ERROR table %s id %s: duplicate id, also in %s" % (table, ident, other))
    return paths, sorted(rows, key=lambda r: r.key), errors, tracked


def split(keys, parts):
    """``keys`` is a list of (table, id); returns ``parts`` lists: the sorted keys in contiguous blocks, sizes differing by
    at most one, the larger blocks first."""
    ordered = sorted(keys)
    size, extra = divmod(len(ordered), parts)
    out, at = [], 0
    for k in range(parts):
        n = size + (1 if k < extra else 0)
        out.append(ordered[at:at + n])
        at += n
    return out


# ---- running ------------------------------------------------------------------------------------------------------
def run_unittest(python, modules, root, timeout):
    """One test run: (exit code, output text, timed out). The run is a new session so a timeout kills its whole group."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([python, "-m", "unittest"] + list(modules), cwd=root, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out = proc.communicate(timeout=timeout)[0]
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        out = proc.communicate()[0] or b""
        timed_out = True
    return proc.returncode, out.decode("utf-8", "replace"), timed_out


class Result:
    def __init__(self, label, code, text, timed_out):
        ran = RAN.search(text)
        self.label, self.text, self.timed_out = label, text, timed_out
        self.passed = code == 0 and ran is not None and not timed_out and ran.group(1).strip("0") != ""
        if timed_out:
            self.detail = "%s timed out" % label
        else:
            self.detail = "%s %s %s" % (label, ran.group(0) if ran else "no Ran line", "OK" if self.passed else "FAILED")


def run_pair(execute, pythons, modules, root, timeout):
    """Run ``modules`` on both interpreters at once; the two Results in order. An exception of execute is re-raised."""
    slots = [None, None]

    def work(i):
        label, path = pythons[i]
        try:
            slots[i] = Result(label, *execute(path, modules, root, timeout))
        except Exception as err:  # noqa: BLE001 - re-raised below, after both runs ended
            slots[i] = err
    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for slot in slots:
        if isinstance(slot, Exception):
            raise slot
    return slots


def protected_reason(path, files, dirs):
    low = path.lower()  # ASCII only by now, so lower() is the same on every interpreter
    for f in files:
        if low == f:
            return "is protected (equal to %s)" % f
    for d in dirs:
        if low == d or low.startswith(d + "/"):
            return "is protected (%s)" % d
    return ""


def path_problem(root, path, tracked, files, dirs):
    if PATH_CHARS.fullmatch(path) is None or len(path) > MAX_PATH_LENGTH:
        return "path %s must be relative, at most %d characters of A-Z a-z 0-9 _ . / + @ = , -" % (show(path), MAX_PATH_LENGTH)
    if any(p in ("", ".", "..", ".git") or p.startswith("-") for p in path.split("/")):
        return "path %s has an empty, '.', '..', '.git' or option-like component" % show(path)
    why = protected_reason(path, files, dirs)
    if why:
        return "path %s %s" % (show(path), why)
    why = regular_problem(root, path, tracked)
    return "path %s %s" % (show(path), why) if why else ""


def count_problem(data, old):
    first = data.find(old)
    if first < 0:
        return -1, "0 matches"
    if data.find(old, first + 1) >= 0:  # overlapping occurrences count
        return -1, "2 or more matches"
    return first, ""


def one_row(root, row, pythons, timeout, execute):
    """The finished line of one id whose path and baseline are fine, and whether the tree is still clean."""
    target = os.path.join(root, *row.path.split("/"))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(target, flags)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return "%s: ERROR | path %s is not a regular file" % (row.id, show(row.path)), True
        data = fh.read()
    first, problem = count_problem(data, row.old)
    if first < 0:
        return "%s: NOT_APPLIED | %s of old in %s" % (row.id, problem, row.path), True
    digest = hashlib.sha256(data).hexdigest()
    try:
        with open(target, "wb") as fh:
            fh.write(data[:first] + row.new + data[first + len(row.old):])
        results = run_pair(execute, pythons, list(row.modules), root, timeout)
    except Exception as err:  # noqa: BLE001 - one ERROR line; the file is restored below
        line = "%s: ERROR | %s: %s" % (row.id, type(err).__name__, clean(str(err)))
        results = None
    finally:
        with open(target, "wb") as fh:
            fh.write(data)
    with open(target, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != digest:
            return "%s: ERROR | the file %s was not restored byte for byte" % (row.id, row.path), False
    if results is None:
        return line, True
    if any(r.timed_out for r in results):
        verdict = "TIMEOUT"
    else:
        passed = [r.passed for r in results]
        verdict = "SURVIVED" if all(passed) else "KILLED" if not any(passed) else "SPLIT"
    return "%s: %s | %s" % (row.id, verdict, " ; ".join(r.detail for r in results)), True


def run_rows(root, rows, tracked, protected_files, pythons, timeout, execute, emit):
    """Run ``rows``; ``emit(line)`` gets one finished line per row, in order. Returns whether any line is an ERROR."""
    problems = {row.id: path_problem(root, row.path, tracked, protected_files, PROTECTED_DIRS) for row in rows}
    baseline = {}
    for module in sorted({m for row in rows if not problems[row.id] for m in row.modules}):
        try:
            results = run_pair(execute, pythons, [module], root, timeout)
        except Exception as err:  # noqa: BLE001
            baseline[module] = "%s: %s: %s" % (module, type(err).__name__, clean(str(err)))
            continue
        bad = [r for r in results if not r.passed]
        if bad:
            baseline[module] = "%s failed on %s" % (module, " and ".join(r.detail for r in bad))
            for r in bad:
                for text_line in r.text.splitlines()[-30:]:
                    emit("| " + clean(text_line))
    why = tree_problem(root)
    errored = False
    stopped = ""
    for row in rows:
        if why:
            line = "%s: ERROR | %s after the baseline" % (row.id, why)
        elif stopped:
            line = "%s: ERROR | not run: %s" % (row.id, stopped)
        elif problems[row.id]:
            line = "%s: ERROR | %s" % (row.id, problems[row.id])
        elif any(m in baseline for m in row.modules):
            line = "%s: ERROR | baseline failed: %s" % (row.id, "; ".join(baseline[m] for m in row.modules if m in baseline))
        else:
            try:
                line, restored = one_row(root, row, pythons, timeout, execute)
            except Exception as err:  # noqa: BLE001
                line, restored = "%s: ERROR | %s: %s" % (row.id, type(err).__name__, clean(str(err))), True
            if restored:
                after = tree_problem(root)
                if after:
                    line = "%s: ERROR | %s after this id" % (row.id, after)
                    stopped = "%s after %s" % (after.split(" (")[0], row.id)
            else:
                stopped = "the file of %s was not restored" % row.id
        errored = errored or ": ERROR |" in line
        emit(line)
    return errored


def write_output(env, lines):
    """Append the lines to the GITHUB_OUTPUT file as the multi-line output ``lines``; the problem text, or ''."""
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return ""
    delim = "ci_mutants_" + secrets.token_hex(16)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("lines<<%s\n%s\n%s\n" % (delim, "\n".join(lines), delim))
    except OSError as err:
        return "cannot write GITHUB_OUTPUT (%s)" % (err.strerror or type(err).__name__)
    return ""


# ---- commands -----------------------------------------------------------------------------------------------------
def say(text):
    print(text)
    sys.stdout.flush()


def refusals(errors):
    for line in errors:
        say(line)
    return 1


def command_split(opts, root):
    paths, rows, errors, tracked = gather(root, opts["--base"], opts["--head"])
    if errors:
        return refusals(errors)
    mine = split([r.key for r in rows], opts["--parts"])[opts["--part"] - 1]
    say("ci_mutants: part %d of %d: %d mutants" % (opts["--part"], opts["--parts"], len(mine)))
    for table, ident in mine:
        say("  %s %s" % (table, ident))
    return 0


def command_run(opts, root, execute, env):
    paths, rows, errors, tracked = gather(root, opts["--base"], opts["--head"])
    if errors:
        return refusals(errors)
    why = tree_problem(root)
    if why:
        raise Stop("tree", why)
    k, n = opts["--part"], opts["--parts"]
    lines = []

    def emit(line):
        if LINE.fullmatch(line):
            lines.append(line)
        say(line)
    if not paths:
        say("ci_mutants: no mutant tables changed")
    else:
        mine = set(split([r.key for r in rows], n)[k - 1])
        todo = [r for r in rows if r.key in mine]
        if not todo:
            say("ci_mutants: part %d of %d has no mutants" % (k, n))
        else:
            say("ci_mutants: part %d of %d: %d mutants" % (k, n, len(todo)))
            files = set(PROTECTED_FILES) | {"tests/" + m.split(".", 1)[1] + ".py" for r in rows for m in r.modules}
            errored = run_rows(root, todo, tracked, {f.lower() for f in files}, opts["--python"],
                               opts.get("--timeout", DEFAULT_TIMEOUT), execute, emit)
            problem = write_output(env, lines)
            if problem:
                say("ERROR output: " + problem)
                return 1
            return 1 if errored else 0
    problem = write_output(env, lines)
    if problem:
        say("ERROR output: " + problem)
        return 1
    return 0


def command_summary(opts, root, env):
    paths, rows, errors, tracked = gather(root, opts["--base"], opts["--head"])
    if errors:
        return refusals(errors)
    expected = {r.id: r for r in rows}
    problems, seen = [], {}
    for k in range(1, opts["--parts"] + 1):
        result = env.get("MUTANT_RESULT_%d" % k)
        if result is None:
            problems.append("FAIL job %d: no result" % k)
        elif result != "success":
            problems.append("FAIL job %d: result %s" % (k, show(result)))
        for text_line in env.get("MUTANT_LINES_%d" % k, "").splitlines():
            if not text_line.strip():
                continue
            m = LINE.fullmatch(text_line)
            if m is None:
                problems.append("FAIL job %d: unreadable line %s" % (k, show(text_line)))
            else:
                seen.setdefault(m.group(1), []).append((m.group(2), (m.group(3) or "")[3:]))
    counts, listed = {}, []
    for ident in sorted(set(seen) | set(expected)):
        got = seen.get(ident, [])
        if ident not in expected:
            problems.append("FAIL %s: unknown id (no changed table names it)" % ident)
        elif not got:
            problems.append("FAIL %s: no line" % ident)
        elif len(got) > 1:
            problems.append("FAIL %s: %d lines" % (ident, len(got)))
        else:
            verdict, detail = got[0]
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict in ("NOT_APPLIED", "TIMEOUT", "ERROR"):
                problems.append("FAIL %s: %s %s" % (ident, verdict, clean(detail, 120)))
            elif verdict in ("SURVIVED", "SPLIT"):
                listed.append("%s: %s (%s) %s" % ("survivor" if verdict == "SURVIVED" else "split", ident,
                                                  expected[ident].table, clean(detail, 120)))
    if not paths:
        say("ci_mutants: no mutant tables changed")
    elif not expected:
        say("ci_mutants: no mutants in the changed tables")
    else:
        say("ci_mutants: summary: %d mutants: %s" % (len(expected), ", ".join(
            "%s %d" % (v, counts[v]) for v in VERDICTS if v in counts)))
    for item in listed:
        say(item)
    for item in problems:
        say(item)
    if problems:
        say("ci_mutants: summary FAILED (%d problems)" % len(problems))
        return 1
    return 0


def main(argv, root=None, execute=None, env=None):
    """Exit code of the command; see the module docstring."""
    root = os.path.abspath(root if root is not None else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        command, opts = parse(argv)
    except Refused as err:
        print("ci_mutants: refused: %s" % err, file=sys.stderr)
        return 2
    env = os.environ if env is None else env
    try:
        if command == "split":
            return command_split(opts, root)
        if command == "run":
            return command_run(opts, root, execute or run_unittest, env)
        return command_summary(opts, root, env)
    except Stop as stop:
        say("ERROR %s: %s" % (stop.where, stop.message))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
