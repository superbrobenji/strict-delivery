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
``[A-Za-z0-9_./+@=,-]``, the name of a tracked regular file with exactly one hard link, reached without a symbolic
link, and none of the protected paths (this runner and its tests, every table, every killing module of every changed
table, the ``tests.test*`` modules those import directly or through any ``tests`` module, ``tests/__init__.py``, and
``.github``). ``old``
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
JOB_ENV = re.compile(r"MUTANT_(RESULT|LINES)_(.*)", re.S)  # every name that looks like a job's result or lines
USAGE = ("usage: python -m tests.ci_mutants (split|run|summary) --base REF --head SHA --parts N [--part K] "
         "[--python LABEL=PATH --python LABEL=PATH] [--timeout SECONDS]")
OPTIONS = {"split": ("--base", "--head", "--parts", "--part"),
           "run": ("--base", "--head", "--parts", "--part", "--python", "--timeout"),
           "summary": ("--base", "--head", "--parts")}
REQUIRED = {"split": ("--base", "--head", "--parts", "--part"), "run": ("--base", "--head", "--parts", "--part"),
            "summary": ("--base", "--head", "--parts")}


class _Refused(ValueError):
    """An argument the command refuses: main() prints it and exits 2. split, open_target and count_problem raise it for an
    argument of the wrong type (exact types only: an exact type is accepted, a subclass is refused)."""


class _Stop(Exception):
    """A refusal that ends the command before anything runs: printed as ``ERROR <where>: <reason>``, exit 1."""

    def __init__(self, where, message):
        Exception.__init__(self, message)
        self.where = where
        self.message = message


def _show(text):
    """A bounded ASCII form of untrusted text for a message (quoted)."""
    return ascii(text if len(text) <= 80 else text[:80] + "...")


def _clean(text, limit=200):
    """Untrusted text as one printable ASCII line: escapes, no quotes, bounded."""
    text = text if len(text) <= limit else text[:limit] + "..."
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    return re.sub(r"[^ -~]", lambda m: "\\x%02x" % ord(m.group()), text)


# ---- arguments ----------------------------------------------------------------------------------------------------
def _number(option, text):
    if NUMBER.fullmatch(text) is None:
        raise _Refused("%s needs a whole number from 1 to 999999 (ASCII digits, no sign, no leading zero), got %s"
                      % (option, _show(text)))
    return int(text)


def _parse(argv):
    """(command, {option: value}); ``--python`` holds a list of (label, path)."""
    if not argv:
        raise _Refused(USAGE)
    command = argv[0]
    if command not in OPTIONS:
        raise _Refused("unknown command %s; %s" % (_show(command), USAGE))
    given = {"--python": []}
    i = 1
    while i < len(argv):
        option = argv[i]
        if option not in OPTIONS[command]:
            raise _Refused("unknown argument %s; %s" % (_show(option), USAGE))
        if option != "--python" and option in given:
            raise _Refused("%s given twice; %s" % (option, USAGE))
        if i + 1 >= len(argv):
            raise _Refused("%s needs a value; %s" % (option, USAGE))
        value = argv[i + 1]
        if option in ("--parts", "--part", "--timeout"):
            given[option] = _number(option, value)
        elif option == "--base":
            if REF.fullmatch(value) is None or ".." in value or value.endswith(("/", ".lock")):
                raise _Refused("--base needs a branch or ref name (letters, digits, _ . / -, no .., not starting with - or "
                              "a dot-dot), got %s" % _show(value))
            given[option] = value
        elif option == "--head":
            if HEAD.fullmatch(value) is None:
                raise _Refused("--head needs the full lowercase hex commit sha (40 or 64 digits), got %s" % _show(value))
            given[option] = value
        else:
            label, sep, path = value.partition("=")
            if not sep or LABEL.fullmatch(label) is None or not path or "\0" in path:
                raise _Refused("--python needs LABEL=PATH (label of 1-16 letters, digits, . _ -), got %s" % _show(value))
            if not os.path.isabs(path):
                raise _Refused("--python path must be absolute, got %s" % _show(path))
            if any(label == other for other, _ in given["--python"]):
                raise _Refused("--python label %s given twice" % _show(label))
            given["--python"].append((label, path))
        i += 2
    for option in REQUIRED[command]:
        if option not in given:
            raise _Refused("%s is required; %s" % (option, USAGE))
    if command == "run" and len(given["--python"]) != 2:
        raise _Refused("run needs two --python LABEL=PATH options, got %d" % len(given["--python"]))
    if "--part" in given and given["--part"] > given["--parts"]:
        raise _Refused("--part %d is past --parts %d" % (given["--part"], given["--parts"]))
    return command, given


# ---- git ----------------------------------------------------------------------------------------------------------
def _git(root, *args):
    p = subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout


def _tracked_files(root):
    """{path: mode} of the index (mode ``conflict`` for an unmerged path)."""
    code, out = _git(root, "ls-files", "-s", "-z")
    if code != 0:
        raise _Stop("tree", "git ls-files failed")
    found = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3:
            raise _Stop("tree", "git ls-files printed an entry this runner cannot read")
        path = os.fsdecode(name)
        found[path] = fields[0].decode("ascii") if fields[2] == b"0" else "conflict"
    return found


def _tree_problem(root):
    """The text of a problem with the tree (``git status`` shows any change, tracked or untracked), or ''."""
    code, out = _git(root, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        return "git status failed"
    text = out.decode("utf-8", "replace").strip()
    if text:
        first = text.splitlines()[0]
        return "the tree is not clean (%d entries, first: %s)" % (len(text.splitlines()), _clean(first, 80))
    return ""


def _check_head(root, head):
    code, out = _git(root, "rev-parse", "--verify", "--quiet", head + "^{commit}")
    code2, out2 = _git(root, "rev-parse", "HEAD")
    if code != 0 or code2 != 0 or out.strip() != out2.strip():
        raise _Stop("head", "the checkout is at %s, not at --head %s" % (_clean(out2.decode("ascii", "replace").strip(), 64), head))


def _changed_tables(root, base, head):
    """The table paths the head adds or changes against the merge base; _Stop for an unusable base or an unreadable diff."""
    code, out = _git(root, "merge-base", base, head)
    if code != 0 or HEAD.fullmatch(out.decode("ascii", "replace").strip()) is None:
        raise _Stop("base %s" % base, "is missing or shares no history with the head")
    merge_base = out.decode("ascii").strip()
    code, out = _git(root, "diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", merge_base, head, "--", TABLE_DIR)
    if code != 0:
        raise _Stop("base %s" % base, "git diff against the merge base failed")
    tokens = out.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    if len(tokens) % 2:
        raise _Stop("base %s" % base, "git diff printed output this runner cannot read")
    paths, errors = [], []
    for status, name in zip(tokens[0::2], tokens[1::2]):
        path = os.fsdecode(name)
        letter = status.decode("ascii", "replace")
        if letter == "D":
            continue  # a deleted table runs nothing
        prefix = TABLE_DIR + "/"
        if not path.startswith(prefix) or TABLE_NAME.fullmatch(path[len(prefix):]) is None:
            errors.append("ERROR table %s: not a table file name (a table is %s/<task-id>.py, the name from [A-Za-z0-9._-])"
                          % (_clean(path), TABLE_DIR))
        elif letter not in ("A", "M", "T"):
            errors.append("ERROR table %s: unexpected change status %s" % (path, _clean(letter, 8)))
        else:
            paths.append(path)
    return sorted(paths), errors


# ---- tables -------------------------------------------------------------------------------------------------------
def _ident_text(ident):
    return ident if type(ident) is str and ID.fullmatch(ident) else _show(repr(ident))


def _regular_problem(root, rel, tracked):
    """Why ``rel`` is not a tracked regular file with exactly one hard link, reached without a symbolic link, or ''."""
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
    if st.st_nlink != 1:
        return "has more than one hard link"
    return ""


class _Row:
    def __init__(self, table, ident, path, old, new, modules):
        self.table, self.id, self.path, self.old, self.new, self.modules = table, ident, path, old, new, modules

    @property
    def key(self):
        return (self.table, self.id)


def _literal_assignments(tree):
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


def _read_literals(node, name):
    """(value, problem): the literal of ``node`` and, for a dict, a problem when one key repeats."""
    try:
        value = ast.literal_eval(node)
        keys = [ast.literal_eval(k) for k in node.keys] if isinstance(node, ast.Dict) else []
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as err:
        return None, "%s is not a literal (%s)" % (name, type(err).__name__)
    seen = set()
    for key in keys:
        if key in seen:
            return None, "duplicate key %s in %s" % (_show(repr(key)), name)
        seen.add(key)
    return value, None


def _load_table(root, rel, tracked):
    """(rows, errors) of one table file; errors are finished ``ERROR table ...`` lines."""
    errors = []

    def err(message, ident=None):
        errors.append("ERROR table %s%s: %s" % (rel, "" if ident is None else " id " + _ident_text(ident), message))

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
    found, problems = _literal_assignments(tree)
    for problem in problems:
        err(problem)
    if problems:
        return [], errors
    values = {}
    for name in ("M", "KILL"):
        values[name], problem = _read_literals(found[name], name)
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
                    if MODULE.fullmatch(module) is None or _regular_problem(root, module.replace(".", "/") + ".py", tracked):
                        err("killing module %s is not a tracked tests/test*.py module (name it tests.test_x)" % _show(module),
                            ident)
        if len(errors) == before:
            rows.append(_Row(rel, ident, value[0], old, new, modules))
    for ident in kill:
        if ident not in m:
            err("id is in KILL but not in M", ident)
    return rows, errors


def _gather(root, base, head):
    """(changed table paths, rows, errors, tracked): every changed table read; errors are finished lines."""
    _check_head(root, head)
    paths, errors = _changed_tables(root, base, head)
    tracked = _tracked_files(root)
    rows = []
    for rel in paths:
        got, errs = _load_table(root, rel, tracked)
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
    at most one, the larger blocks first. Exact types only: ``keys`` an exact list of exact 2-tuples of exact str,
    ``parts`` an exact int of at least 1 (not a bool); anything else raises _Refused before any work."""
    if type(keys) is not list:
        raise _Refused("keys must be an exact list of (table, id) tuples of exact str (a subclass or another type is "
                       "refused), got type %s" % _clean(type(keys).__name__, 40))
    if not all(type(k) is tuple and len(k) == 2 and type(k[0]) is str and type(k[1]) is str for k in keys):
        raise _Refused("keys must be an exact list of (table, id) tuples of exact str: an item is not an exact 2-tuple of "
                       "exact str")
    if type(parts) is not int or parts < 1:
        raise _Refused("parts must be an exact int of at least 1 (a bool, a subclass or another type is refused), got "
                       "type %s" % _clean(type(parts).__name__, 40))
    ordered = sorted(keys)
    size, extra = divmod(len(ordered), parts)
    out, at = [], 0
    for k in range(parts):
        n = size + (1 if k < extra else 0)
        out.append(ordered[at:at + n])
        at += n
    return out


# ---- running ------------------------------------------------------------------------------------------------------
def _run_unittest(python, modules, root, timeout):
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


class _Result:
    def __init__(self, label, code, text, timed_out):
        ran = RAN.search(text)
        self.label, self.text, self.timed_out = label, text, timed_out
        self.passed = code == 0 and ran is not None and not timed_out and ran.group(1).strip("0") != ""
        if timed_out:
            self.detail = "%s timed out" % label
        else:
            self.detail = "%s %s %s" % (label, ran.group(0) if ran else "no Ran line", "OK" if self.passed else "FAILED")


def _run_pair(execute, pythons, modules, root, timeout):
    """Run ``modules`` on both interpreters at once; the two Results in order. An exception of execute is re-raised."""
    slots = [None, None]

    def work(i):
        label, path = pythons[i]
        try:
            slots[i] = _Result(label, *execute(path, modules, root, timeout))
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


def _protected_reason(path, files, dirs):
    low = path.lower()  # ASCII only by now, so lower() is the same on every interpreter
    for f in files:
        if low == f:
            return "is protected (equal to %s)" % f
    for d in dirs:
        if low == d or low.startswith(d + "/"):
            return "is protected (%s)" % d
    return ""


def _path_problem(root, path, tracked, files, dirs):
    if PATH_CHARS.fullmatch(path) is None or len(path) > MAX_PATH_LENGTH:
        return "path %s must be relative, at most %d characters of A-Z a-z 0-9 _ . / + @ = , -" % (_show(path), MAX_PATH_LENGTH)
    if any(p in ("", ".", "..", ".git") or p.startswith("-") for p in path.split("/")):
        return "path %s has an empty, '.', '..', '.git' or option-like component" % _show(path)
    why = _protected_reason(path, files, dirs)
    if why:
        return "path %s %s" % (_show(path), why)
    why = _regular_problem(root, path, tracked)
    return "path %s %s" % (_show(path), why) if why else ""


def count_problem(data, old):
    """(index of the one match, '') or (-1, why not): ``data`` is the file's bytes, ``old`` the replaced text encoded as
    UTF-8; overlapping occurrences count. Exact bytes only (a str, a bytes subclass or another type raises _Refused)."""
    if type(data) is not bytes:
        raise _Refused("data must be exact bytes (a str, a subclass or another type is refused), got type %s"
                       % _clean(type(data).__name__, 40))
    if type(old) is not bytes:
        raise _Refused("old must be exact bytes (a str, a subclass or another type is refused), got type %s"
                       % _clean(type(old).__name__, 40))
    first = data.find(old)
    if first < 0:
        return -1, "0 matches"
    if data.find(old, first + 1) >= 0:  # overlapping occurrences count
        return -1, "2 or more matches"
    return first, ""


class _Unsafe(Exception):
    """The path no longer opens as the tracked regular file it was checked to be: a link or another file type was swapped
    in after the check. The message is the finished ``path ... changed after the check (...)`` text."""


def open_target(root, rel, write):
    """The open file (``rb``, or ``r+b`` truncated when ``write``) of the checked path ``rel`` below ``root``.

    Nothing is followed, nothing blocks and nothing is truncated before the file is known to be the right one: every parent
    is opened as a directory with O_NOFOLLOW (one step at a time, from the root), the last component with O_NOFOLLOW and
    O_NONBLOCK (and without O_TRUNC), and the opened file must be a regular file with exactly one hard link (fstat);
    only then is it truncated, through the descriptor. Otherwise _Unsafe (the path was swapped for a symbolic link, a
    directory, a FIFO or a hard link after the check; a hard link would write through to a file elsewhere).

    Exact types only: ``root`` and ``rel`` exact str, ``write`` an exact bool; anything else raises _Refused before
    anything is opened."""
    if type(root) is not str:
        raise _Refused("root must be an exact str (a subclass, bytes or a path object is refused), got type %s"
                       % _clean(type(root).__name__, 40))
    if type(rel) is not str:
        raise _Refused("rel must be an exact str (a subclass, bytes or a path object is refused), got type %s"
                       % _clean(type(rel).__name__, 40))
    if type(write) is not bool:
        raise _Refused("write must be an exact bool (an int or another object is refused), got type %s"
                       % _clean(type(write).__name__, 40))
    flags = (os.O_RDWR if write else os.O_RDONLY) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    parts = rel.split("/")
    try:
        dfd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            for part in parts[:-1]:
                nfd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=dfd)
                os.close(dfd)
                dfd = nfd
            fd = os.open(parts[-1], flags, dir_fd=dfd)
        finally:
            os.close(dfd)
    except OSError as err:
        raise _Unsafe("path %s changed after the check (cannot be opened as a regular file: %s)"
                     % (_show(rel), err.strerror or type(err).__name__))
    st = os.fstat(fd)
    problem = ("it is not a regular file" if not stat.S_ISREG(st.st_mode)
               else "it has more than one hard link" if st.st_nlink != 1 else "")
    if not problem and write:
        try:
            os.ftruncate(fd, 0)
        except OSError as err:
            problem = "cannot be truncated: %s" % (err.strerror or type(err).__name__)
    if problem:
        os.close(fd)
        raise _Unsafe("path %s changed after the check (%s)" % (_show(rel), problem))
    return os.fdopen(fd, "r+b" if write else "rb")


def _restore(root, rel, data):
    """'' when the file holds ``data`` again (written and read back through one open), else why it does not."""
    try:
        with open_target(root, rel, True) as fh:
            fh.write(data)
            fh.flush()
            fh.seek(0)
            back = fh.read()
    except _Unsafe as err:
        return str(err)
    except OSError as err:
        return "%s: %s" % (type(err).__name__, _clean(str(err)))
    return "" if back == data else "the bytes read back differ"


def _one_row(root, row, pythons, timeout, execute):
    """The finished line of one id whose path and baseline are fine, and whether the tree is still clean."""
    try:
        with open_target(root, row.path, False) as fh:
            data = fh.read()
    except _Unsafe as err:
        return "%s: ERROR | %s" % (row.id, err), True
    first, problem = count_problem(data, row.old)
    if first < 0:
        return "%s: NOT_APPLIED | %s of old in %s" % (row.id, problem, row.path), True
    line, problem = "", ""
    try:
        with open_target(root, row.path, True) as fh:
            fh.write(data[:first] + row.new + data[first + len(row.old):])
        results = _run_pair(execute, pythons, list(row.modules), root, timeout)
    except Exception as err:  # noqa: BLE001 - one ERROR line; the file is restored below
        line = "%s: ERROR | %s" % (row.id, err if isinstance(err, _Unsafe) else "%s: %s" % (type(err).__name__, _clean(str(err))))
        results = None
    finally:
        problem = _restore(root, row.path, data)
    if problem:
        head = line + "; " if line else "%s: ERROR | " % row.id
        return "%sthe file %s was not restored: %s" % (head, row.path, problem), False
    if results is None:
        return line, True
    if any(r.timed_out for r in results):
        verdict = "TIMEOUT"
    else:
        passed = [r.passed for r in results]
        verdict = "SURVIVED" if all(passed) else "KILLED" if not any(passed) else "SPLIT"
    return "%s: %s | %s" % (row.id, verdict, " ; ".join(r.detail for r in results)), True


def _run_rows(root, rows, tracked, protected_files, pythons, timeout, execute, emit):
    """Run ``rows``; ``emit(line)`` gets one finished line per row, in order. Returns whether any line is an ERROR."""
    problems = {row.id: _path_problem(root, row.path, tracked, protected_files, PROTECTED_DIRS) for row in rows}
    baseline = {}
    for modules in sorted({tuple(row.modules) for row in rows if not problems[row.id]}):  # each KILL tuple, as it is run
        name = " ".join(modules)
        try:
            results = _run_pair(execute, pythons, list(modules), root, timeout)
        except Exception as err:  # noqa: BLE001
            baseline[modules] = "%s: %s: %s" % (name, type(err).__name__, _clean(str(err)))
            continue
        bad = [r for r in results if not r.passed]
        if bad:
            baseline[modules] = "%s failed on %s" % (name, " and ".join(r.detail for r in bad))
            for r in bad:
                for text_line in r.text.splitlines()[-30:]:
                    emit("| " + _clean(text_line))
    why = _tree_problem(root)
    errored = False
    stopped = ""
    for row in rows:
        if why:
            line = "%s: ERROR | %s after the baseline" % (row.id, why)
        elif stopped:
            line = "%s: ERROR | not run: %s" % (row.id, stopped)
        elif problems[row.id]:
            line = "%s: ERROR | %s" % (row.id, problems[row.id])
        elif tuple(row.modules) in baseline:
            line = "%s: ERROR | baseline failed: %s" % (row.id, baseline[tuple(row.modules)])
        else:
            try:
                line, restored = _one_row(root, row, pythons, timeout, execute)
            except Exception as err:  # noqa: BLE001
                line, restored = "%s: ERROR | %s: %s" % (row.id, type(err).__name__, _clean(str(err))), True
            if restored:
                after = _tree_problem(root)
                if after:
                    line = "%s: ERROR | %s after this id" % (row.id, after)
                    stopped = "%s after %s" % (after.split(" (")[0], row.id)
            else:
                stopped = "the file of %s was not restored" % row.id
        errored = errored or ": ERROR |" in line
        emit(line)
    return errored


def _write_output(env, lines):
    """Append the lines to the GITHUB_OUTPUT file as the multi-line output ``lines``; the problem text, or ''.

    GITHUB_OUTPUT missing: nothing is written (a local run; the summary fails ``no line`` for every id of the part).
    Set, it must be an absolute path (empty or relative: refused) of a regular file, or of a file that does not exist yet;
    a symbolic link, a directory, a FIFO or another special file is refused (nothing blocks, nothing is followed)."""
    path = env.get("GITHUB_OUTPUT")
    if path is None:
        return ""
    if "\0" in path or not os.path.isabs(path):
        return "GITHUB_OUTPUT must be an absolute path, got %s" % _show(path)
    delim = "ci_mutants_" + secrets.token_hex(16)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, 0o666)
    except OSError as err:
        return "cannot write GITHUB_OUTPUT (%s)" % (err.strerror or type(err).__name__)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as fh:  # the file object owns the descriptor from here
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return "GITHUB_OUTPUT is not a regular file"
            fh.write("lines<<%s\n%s\n%s\n" % (delim, "\n".join(lines), delim))
    except OSError as err:
        return "cannot write GITHUB_OUTPUT (%s)" % (err.strerror or type(err).__name__)
    return ""


def _import_closure(root, modules):
    """The ``tests/`` paths of the oracle of the killing ``modules``: every ``tests.test*`` module they import, directly or
    through any module of ``tests`` (``tests/helpers.py`` and the like are walked but stay mutable), and the package
    ``tests/__init__.py``. Found by ast, nothing imported or run. Forms read: ``import tests.x``, ``from tests import x``,
    ``from tests.x import y``, the relative ``from . import x`` and ``from .x import y``, and ``import_module("tests.x")``
    or ``__import__("tests.x")`` with a literal name (a name built at run time cannot be read, and is not followed)."""
    found, todo, seen = {"tests/__init__.py"}, list(modules), set()
    while todo:
        name = todo.pop()
        if name in seen or re.fullmatch(r"tests\.[A-Za-z0-9_]+", name) is None:
            continue
        seen.add(name)
        if MODULE.fullmatch(name):
            found.add("tests/" + name.split(".")[1] + ".py")
        try:
            path = os.path.join(root, "tests", name.split(".")[1] + ".py")
            if not stat.S_ISREG(os.lstat(path).st_mode) or os.lstat(path).st_size > (8 << 20):
                continue
            with open(path, "rb") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (OSError, SyntaxError, ValueError, MemoryError, RecursionError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                todo.extend(".".join(a.name.split(".")[:2]) for a in node.names if a.name.startswith("tests."))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "tests":
                todo.extend("tests." + a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("tests."):
                todo.append(".".join(node.module.split(".")[:2]))
            elif isinstance(node, ast.ImportFrom) and node.level == 1:  # a module of tests/ imports its siblings
                if node.module is None:
                    todo.extend("tests." + a.name for a in node.names)
                else:
                    todo.append("tests." + node.module.split(".")[0])
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and node.args[0].value.startswith("tests.") \
                    and (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) in ("import_module", "__import__"):
                todo.append(".".join(node.args[0].value.split(".")[:2]))
    return found


# ---- commands -----------------------------------------------------------------------------------------------------
def _say(text):
    print(text)
    sys.stdout.flush()


def _refusals(errors):
    for line in errors:
        _say(line)
    return 1


def _command_split(opts, root):
    paths, rows, errors, tracked = _gather(root, opts["--base"], opts["--head"])
    if errors:
        return _refusals(errors)
    mine = split([r.key for r in rows], opts["--parts"])[opts["--part"] - 1]
    _say("ci_mutants: part %d of %d: %d mutants" % (opts["--part"], opts["--parts"], len(mine)))
    for table, ident in mine:
        _say("  %s %s" % (table, ident))
    return 0


def _command_run(opts, root, execute, env):
    paths, rows, errors, tracked = _gather(root, opts["--base"], opts["--head"])
    if errors:
        return _refusals(errors)
    why = _tree_problem(root)
    if why:
        raise _Stop("tree", why)
    k, n = opts["--part"], opts["--parts"]
    lines = []

    def emit(line):
        if LINE.fullmatch(line):
            lines.append(line)
        _say(line)
    if not paths:
        _say("ci_mutants: no mutant tables changed")
    else:
        mine = set(split([r.key for r in rows], n)[k - 1])
        todo = [r for r in rows if r.key in mine]
        if not todo:
            _say("ci_mutants: part %d of %d has no mutants" % (k, n))
        else:
            _say("ci_mutants: part %d of %d: %d mutants" % (k, n, len(todo)))
            files = set(PROTECTED_FILES) | _import_closure(root, sorted({m for r in rows for m in r.modules}))
            errored = _run_rows(root, todo, tracked, {f.lower() for f in files}, opts["--python"],
                               opts.get("--timeout", DEFAULT_TIMEOUT), execute, emit)
            problem = _write_output(env, lines)
            if problem:
                _say("ERROR output: " + problem)
                return 1
            return 1 if errored else 0
    problem = _write_output(env, lines)
    if problem:
        _say("ERROR output: " + problem)
        return 1
    return 0


def _command_summary(opts, root, env):
    paths, rows, errors, tracked = _gather(root, opts["--base"], opts["--head"])
    if errors:
        return _refusals(errors)
    expected = {r.id: r for r in rows}
    problems, seen = [], {}
    valid = {str(k) for k in range(1, opts["--parts"] + 1)}  # the canonical decimal job indexes: no sign, no leading zero
    for name in sorted(env):
        m = JOB_ENV.fullmatch(name)
        if m is not None and m.group(2) not in valid:
            problems.append("FAIL env %s: job index %s is outside 1..%d" % (_show(name), _show(m.group(2)), opts["--parts"]))
    for k in range(1, opts["--parts"] + 1):
        result = env.get("MUTANT_RESULT_%d" % k)
        if result is None:
            problems.append("FAIL job %d: no result" % k)
        elif result != "success":
            problems.append("FAIL job %d: result %s" % (k, _show(result)))
        for text_line in env.get("MUTANT_LINES_%d" % k, "").splitlines():
            if not text_line.strip():
                continue
            m = LINE.fullmatch(text_line)
            if m is None:
                problems.append("FAIL job %d: unreadable line %s" % (k, _show(text_line)))
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
                problems.append("FAIL %s: %s %s" % (ident, verdict, _clean(detail, 120)))
            elif verdict in ("SURVIVED", "SPLIT"):
                listed.append("%s: %s (%s) %s" % ("survivor" if verdict == "SURVIVED" else "split", ident,
                                                  expected[ident].table, _clean(detail, 120)))
    if not paths:
        _say("ci_mutants: no mutant tables changed")
    elif not expected:
        _say("ci_mutants: no mutants in the changed tables")
    else:
        _say("ci_mutants: summary: %d mutants: %s" % (len(expected), ", ".join(
            "%s %d" % (v, counts[v]) for v in VERDICTS if v in counts)))
    for item in listed:
        _say(item)
    for item in problems:
        _say(item)
    if problems:
        _say("ci_mutants: summary FAILED (%d problems)" % len(problems))
        return 1
    return 0


def main(argv, root=None, execute=None, env=None):
    """Exit code of the command; see the module docstring. Exact types only (an exact type is accepted, a subclass is
    refused): ``argv`` an exact list of exact str; ``root`` None or an exact str; ``execute`` None or a callable; ``env``
    None, an exact dict of exact str to exact str, or ``os.environ`` itself. Any other value: exit 2 and one
    ``ci_mutants: refused:`` line on stderr, before anything runs."""
    if type(argv) is not list or any(type(a) is not str for a in argv):
        print("ci_mutants: refused: argv must be an exact list of exact str (a subclass, a tuple or another type is refused), "
              "got type %s" % _clean(type(argv).__name__, 40), file=sys.stderr)
        return 2
    if root is not None and type(root) is not str:
        print("ci_mutants: refused: root must be None or an exact str (a subclass, bytes or a path object is refused), "
              "got type %s" % _clean(type(root).__name__, 40), file=sys.stderr)
        return 2
    if execute is not None and not callable(execute):
        print("ci_mutants: refused: execute must be None or a callable, got type %s" % _clean(type(execute).__name__, 40),
              file=sys.stderr)
        return 2
    if env is not None and env is not os.environ and not (
            type(env) is dict and all(type(k) is str and type(v) is str for k, v in env.items())):
        print("ci_mutants: refused: env must be None, os.environ itself, or an exact dict of exact str to exact str (a "
              "subclass or another mapping is refused), got type %s" % _clean(type(env).__name__, 40), file=sys.stderr)
        return 2
    root = os.path.abspath(root if root is not None else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        command, opts = _parse(argv)
    except _Refused as err:
        print("ci_mutants: refused: %s" % err, file=sys.stderr)
        return 2
    env = os.environ if env is None else env
    try:
        if command == "split":
            return _command_split(opts, root)
        if command == "run":
            return _command_run(opts, root, execute or _run_unittest, env)
        return _command_summary(opts, root, env)
    except _Stop as stop:
        _say("ERROR %s: %s" % (stop.where, stop.message))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
