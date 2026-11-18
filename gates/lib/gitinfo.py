"""Read-only git queries for the gates (standard library only).

Every call passes an argument list (never a shell string), forces the C locale, clears the git names that point at
another repository (``CLEARED_ENV``: ``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_COMMON_DIR``, ``GIT_OBJECT_DIRECTORY``,
``GIT_ALTERNATE_OBJECT_DIRECTORIES``, ``GIT_NAMESPACE``, ``GIT_CEILING_DIRECTORIES``; owner Q-1a-ver-3) from the
caller's environment, keeps ``GIT_INDEX_FILE`` inherited, and puts ``--`` before any user path. Failure messages
name the git command and never the directory. A ref or sha that starts with ``-`` or ``^`` is never given to git
(owner Q-1a-ver-2): the bool queries return False, the others raise a GateError naming the rule.
"""
from __future__ import annotations

import os
import posixpath
import re
import shutil
import stat
import subprocess
import tempfile
from typing import List, Optional

from gates.lib.result import GateError, GitNotFound

_REGULAR = ("100644", "100755")
_HEX = "0123456789abcdefABCDEF"
LONG_HEX = re.compile(r"[0-9a-fA-F]{41,}")  # longer than a sha-1: git would match it zero-padded (F-1a2r-5)


CLEARED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
               "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
# D-18 (owner Q-G1-4 (a)): the hooks' index-reading calls run with core.fsmonitor off, so git stats every tracked file
# and never trusts an fsmonitor-valid bit that hides a work-tree change (a hook or daemon that reports no change).
# ``_run`` puts these options before ``-C root`` and the subcommand; they override every config source, including
# ``git -c`` and GIT_CONFIG_COUNT (measured with git 2.50.1).
FSMONITOR_OFF = ["-c", "core.fsmonitor=false"]
REFUSED_LEAD = ("-", "^")  # an option, or an exclusion marker that names no object (F-1a-ver-2)


def _env() -> dict:
    env = dict(os.environ)
    for name in CLEARED_ENV:
        env.pop(name, None)
    # GIT_INDEX_FILE stays inherited on purpose: a pre-commit hook reads the index being committed.
    env["LC_ALL"] = "C"
    return env


def _argv(root: str, args: List[str], literal: bool, opts: Optional[List[str]]) -> List[str]:
    """The argument list ``_run`` gives to git (one definition, so ``_chunks`` measures what really runs)."""
    return ["git"] + (opts or []) + (["--literal-pathspecs"] if literal else []) + ["-C", root] + args


def _run(root: str, name: str, args: List[str], ok: Optional[tuple] = (0,),
         literal: bool = False, opts: Optional[List[str]] = None,
         index: Optional[str] = None, extra_env: Optional[dict] = None) -> "subprocess.CompletedProcess":
    """Run ``git [opts] -C root <args>``; with ``ok`` a tuple, any other exit status is a GateError naming
    ``name``. ``index`` sets ``GIT_INDEX_FILE`` for this call only (``blob_ids``'s temporary copy);
    ``extra_env`` adds names to this call's environment only (``dirty_paths``: ``GIT_OPTIONAL_LOCKS``)."""
    env = _env()
    if index is not None:
        env["GIT_INDEX_FILE"] = index
    if extra_env:
        env.update(extra_env)
    argv = _argv(root, args, literal, opts)
    try:
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GitNotFound("git not found on PATH; install git") from None
    except (OSError, ValueError):
        raise GateError("git %s failed: unusable argument" % name) from None
    if ok is not None and p.returncode not in ok:
        raise GateError("git %s failed (exit %d)" % (name, p.returncode))
    return p


def _text(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("git %s gave output that is not valid UTF-8" % what) from None


def _check_ref(ref: str) -> None:
    for lead in REFUSED_LEAD:
        if ref.startswith(lead):
            raise GateError("ref must not start with '%s'" % lead)


def _check_rev(ref: str) -> None:
    """_check_ref, and a ref holding more than 40 hex digits in a row is refused."""
    _check_ref(ref)
    if LONG_HEX.search(ref):
        raise GateError("ref must not hold more than 40 hex digits in a row")


def _ensure_repo(root: str) -> None:
    _run(root, "rev-parse --git-dir", ["rev-parse", "--git-dir"])


def _require_toplevel(root: str) -> None:
    """Every function that maps a repo-relative path goes through here (owner Q-1a-fin-1): git reads
    ``--full-tree`` paths from the top level, so a root that is a subdirectory would silently see another tree."""
    top = toplevel(root)  # a missing or non-repository root is a GateError here
    try:
        same = os.path.samefile(root, top)
    except OSError:
        same = False
    if not same:
        raise GateError("git rev-parse --show-toplevel: root must be the repository top level")


def _check_norm(path: str, what: str, allow_empty: bool = False) -> None:
    """A repo-relative path must be normalised (owner Q-1a-fin-2): no '.', '..' or empty segment, no leading
    or trailing '/'. ``""`` is accepted only where ``allow_empty`` says it means the root."""
    if allow_empty and path == "":
        return
    segs = path.split("/")
    if ".." in segs:
        raise GateError("%s must not hold a '..' segment" % what)
    if any(s in ("", ".") for s in segs):
        raise GateError("%s must be a normalised repo-relative path (no '.', empty segment, leading or "
                        "trailing '/')" % what)


def _entries(stdout: bytes, what: str) -> list:
    """Parse ``-z`` ls-tree or ls-files --stage output into (mode, third field, path) triples.

    The third field is the object id for ls-tree (``mode type sha``) and the stage for ls-files."""
    out = []
    for raw in stdout.split(b"\0"):
        if not raw:
            continue
        head, _, path = raw.partition(b"\t")
        mode, _, third = head.split(b" ")
        out.append((mode.decode("ascii"), third.decode("ascii"), _text(path, what)))
    return out


def toplevel(root: str) -> str:
    p = _run(root, "rev-parse --show-toplevel", ["rev-parse", "--show-toplevel"])
    return _text(p.stdout, "rev-parse --show-toplevel").rstrip("\n")


def head_sha(root: str) -> str:
    _require_toplevel(root)
    p = _run(root, "rev-parse HEAD", ["rev-parse", "HEAD"])
    return _text(p.stdout, "rev-parse").strip()


def commit_exists(root: str, sha: str) -> bool:
    """True iff git resolves ``sha`` to an object that peels to a commit (an annotated tag is peeled).

    A ref name wins over a hex-prefix reading, as in git. A bare hex value (any letter case) is resolved
    with no type hint and ``core.disambiguate=none``, so git refuses it exactly when no ref rule matches
    and it is a prefix of more than one object (owner Q-1a2r-2). Any other value is git's own verdict
    (owner Q-1a2r-7). More than 40 hex digits in a row is refused (F-1a2r-5)."""
    _require_toplevel(root)
    if sha.startswith(REFUSED_LEAD) or LONG_HEX.search(sha):
        return False
    bare_hex = all(c in _HEX for c in sha)
    p = _run(root, "rev-parse --verify", ["rev-parse", "--verify", "--quiet", "--end-of-options", sha],
             ok=None, opts=["-c", "core.disambiguate=none"] if bare_hex else None)
    if p.returncode != 0:
        return False  # git resolves no object (for a bare hex value: no ref, and not a unique prefix)
    oid = _text(p.stdout, "rev-parse").strip()
    p = _run(root, "rev-parse --verify", ["rev-parse", "--verify", "--quiet", "--end-of-options",
                                          oid + "^{commit}"], ok=None)
    return p.returncode == 0


def blob_exists(root: str, sha: str, path: str) -> bool:
    _ensure_repo(root)
    _require_toplevel(root)
    _check_norm(path, "ls-tree: path", allow_empty=True)
    if sha.startswith(REFUSED_LEAD) or LONG_HEX.search(sha):
        return False
    p = _run(root, "ls-tree", ["ls-tree", "-z", "--full-tree", sha, "--", path], ok=None, literal=True)
    return any(mode in _REGULAR and name == path for mode, _, name in _entries(p.stdout, "ls-tree"))


def tracked_files(root: str) -> frozenset:
    _require_toplevel(root)
    top = toplevel(root)
    p = _run(top, "ls-files", ["ls-files", "-z", "--stage"])
    return frozenset(name for mode, _, name in _entries(p.stdout, "ls-files") if mode in _REGULAR)


def show(root: str, ref: str, path: str) -> Optional[str]:
    _check_rev(ref)
    _require_toplevel(root)
    _check_norm(path, "ls-tree: path", allow_empty=True)
    p = _run(root, "ls-tree", ["ls-tree", "-z", "--full-tree", ref, "--", path], literal=True)
    raw = None
    for mode, sha, name in _entries(p.stdout, "ls-tree"):
        if mode in _REGULAR and name == path:
            raw = sha
    if raw is None:
        return None
    blob = _run(root, "cat-file blob", ["cat-file", "blob", raw])
    try:
        return blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("%s: not valid UTF-8" % path) from None


def ls_tree(root: str, ref: str, directory: str) -> list:
    _check_rev(ref)
    _require_toplevel(root)
    _check_norm(directory, "ls-tree: directory", allow_empty=True)
    d = directory
    args = ["ls-tree", "-z", "--full-tree", ref]
    if d:
        args += ["--", d + "/"]
    p = _run(root, "ls-tree", args, literal=True)
    return [name for mode, _, name in _entries(p.stdout, "ls-tree")
            if mode in _REGULAR and posixpath.dirname(name) == d]


def merge_base(root: str, a: str, b: str) -> str:
    _require_toplevel(root)
    _check_rev(a)
    _check_rev(b)
    p = _run(root, "merge-base", ["merge-base", a, b])
    return _text(p.stdout, "merge-base").strip()


def is_ancestor(root: str, a: str, b: str) -> bool:
    """True iff commit ``a`` is an ancestor of (or the same commit as) ``b``: ``git merge-base --is-ancestor``.
    Exit 1 is False; any other failure (an unknown object, a bad root) is a GateError (owner Q-PLP-5 (a))."""
    _check_rev(a)
    _check_rev(b)
    _require_toplevel(root)
    p = _run(root, "merge-base --is-ancestor", ["merge-base", "--is-ancestor", a, b], ok=(0, 1))
    return p.returncode == 0


def _stage_entries(stdout: bytes, what: str) -> list:
    """Parse ``ls-files -z --stage`` output into (mode, object id, stage, path). ``-z`` ends each entry with NUL
    and quotes nothing, so a tab or newline in a path stays part of the path: the head before the first tab holds
    none."""
    out = []
    for raw in stdout.split(b"\0"):
        if not raw:
            continue
        head, _, path = raw.partition(b"\t")
        mode, sha, stage = head.split(b" ")
        out.append((mode.decode("ascii"), sha.decode("ascii"), stage.decode("ascii"), _text(path, what)))
    return out


# Decision (owner delegation 2026-11-09, F1 of review 5): no argv that ``blob_ids`` builds holds more than this many
# bytes (each argument and its NUL, fixed arguments included), so a large claim file never meets the argument-length
# limit. It is far under the smallest common limit (Windows 32767 characters for a whole command line; macOS
# ARG_MAX 1 MiB and Linux 2 MiB, both shared with the environment; Linux MAX_ARG_STRLEN 128 KiB per argument) and
# large enough that a 6000-path claim file takes some 40 git calls per command. Too small costs only git calls.
ARGV_BYTES = 30000


def _arg_bytes(arg: str) -> int:
    """Bytes of one argument and its NUL. ``surrogatepass`` never raises, and it counts an escaped byte as three,
    so the count is never below what ``os.fsencode`` passes to the kernel."""
    return len(arg.encode("utf-8", "surrogatepass")) + 1


def _chunks(fixed: List[str], paths: List[str]) -> List[List[str]]:
    """``paths`` in order, split so that ``fixed`` plus each chunk takes at most ``ARGV_BYTES`` (read at call
    time); a path that alone goes over the bound gets a chunk of its own."""
    base = sum(_arg_bytes(a) for a in fixed)
    out: List[List[str]] = []
    size = base
    for path in paths:
        n = _arg_bytes(path)
        if not out or size + n > ARGV_BYTES:
            out.append([])
            size = base
        out[-1].append(path)
        size += n
    return out


def _staged(root: str, paths: List[str], tmp: str) -> dict:
    """Copy the index git reads (``GIT_INDEX_FILE`` honoured, through ``rev-parse --git-path index``) to ``tmp``
    keeping its mtime (so git's racy-entry check is the real index's), stage ``paths`` into the copy and read the
    stage-0 ids back. Both path-list calls (``git add``, ``git ls-files``) run once per ``_chunks`` chunk, every
    chunk against the same copy."""
    p = _run(root, "rev-parse --git-path", ["rev-parse", "--git-path", "index"])
    src = os.path.join(root, _text(p.stdout, "rev-parse --git-path").rstrip("\n"))
    try:
        shutil.copy2(src, tmp)
    except FileNotFoundError:
        pass  # no index yet: git add starts an empty one
    except OSError as e:
        raise GateError("blob id: cannot copy the index (%s)" % (e.strerror or type(e).__name__)) from None
    # core.safecrlf only warns or refuses, it never changes the stored bytes; core.splitIndex=false keeps every
    # write inside the copy (no shared index file in the git directory).
    opts = ["-c", "core.safecrlf=false", "-c", "core.splitIndex=false"]
    for chunk in _chunks(_argv(root, ["add", "--"], True, opts), paths):
        _run(root, "add", ["add", "--"] + chunk, literal=True, opts=opts, index=tmp)
    got = {}
    ls = ["ls-files", "-z", "--stage", "--"]
    for chunk in _chunks(_argv(root, ls, True, None), paths):
        p = _run(root, "ls-files", ls + chunk, literal=True, index=tmp)
        got.update({name: sha for mode, sha, stage, name in _stage_entries(p.stdout, "ls-files")
                    if stage == "0" and mode in _REGULAR})
    for path in paths:
        if path not in got:
            raise GateError("git ls-files: no stage-0 entry for %s after git add" % path)
    return {path: got[path] for path in paths}


def _drop(tmpdir: str) -> None:
    """Remove the temporary index directory: the index copy and a lock git may have left, then the directory."""
    try:
        for name in os.listdir(tmpdir):
            os.unlink(os.path.join(tmpdir, name))
        os.rmdir(tmpdir)
    except OSError as e:
        raise GateError("blob id: cannot remove the temporary index (%s)" % (e.strerror or type(e).__name__)) \
            from None


def blob_ids(root: str, paths: list) -> dict:
    """``{path: id}``: the blob id ``git add`` stores for each regular file in ``paths`` (owner Q-B2plan-4 (a),
    Q-2a2r1-2 (a)). The paths are staged with ``git add`` into a temporary copy of the index, once per call, and
    the ids read with ``git ls-files -s``, so every index-dependent conversion (``core.autocrlf`` true or input,
    ``text=auto``, ``eol``, clean filters, a CRLF entry already in the index) is git's own. The real index never
    changes; git writes the blobs to the object database, as ``git add`` does. Each path must be a normalised
    repo-relative ``str``, checked before git runs; a leading ``-`` is a path, never an option, because ``--``
    comes before it. Every component up to it must be a real directory and the path a regular file (``lstat``),
    so a FIFO is never read and a symlink is never followed. The temporary index is removed on every exit; any
    failure is a GateError."""
    if type(paths) is not list or any(type(p) is not str for p in paths):
        raise GateError("add: paths must be a list of strings")
    for path in paths:
        _check_norm(path, "add: path")
    _require_toplevel(root)
    want = list(dict.fromkeys(paths))
    for path in want:
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            rel = "/".join(parts[:i])
            try:
                mode = os.lstat(os.path.join(root, *parts[:i])).st_mode
            except OSError:
                raise GateError("add: %s does not exist" % rel) from None
            last = i == len(parts)
            if not (stat.S_ISREG(mode) if last else stat.S_ISDIR(mode)):
                raise GateError("add: %s is not a %s" % (rel, "regular file" if last else "real directory"))
    if not want:
        return {}
    try:
        tmpdir = tempfile.mkdtemp(prefix="sd-index-")
    except OSError as e:
        raise GateError("blob id: cannot make a temporary index (%s)" % (e.strerror or type(e).__name__)) from None
    try:
        got = _staged(root, want, os.path.join(tmpdir, "index"))
    finally:
        _drop(tmpdir)
    return got


def blob_id(root: str, path: str) -> str:
    """``blob_ids(root, [path])[path]``: one path, the same rule (no second implementation)."""
    return blob_ids(root, [path])[path]


def user_email(root: str) -> Optional[str]:
    _require_toplevel(root)
    p = _run(root, "config user.email", ["config", "user.email"], ok=(0, 1))
    value = _text(p.stdout, "config").strip()
    return value or None


def unstaged_paths(root: str) -> list:
    """The tracked paths whose work-tree content differs from the index git is using (``GIT_INDEX_FILE`` inherited;
    a relative value resolves against ``root``, because the call runs with ``-C root``): git's own ``diff`` rule, so a
    stat-only change is not listed, and a deleted file, an intent-to-add file and a changed submodule are (task 2b.2;
    owner Q-RC-1 (a): colour, external diff and text conversion are switched off; ruling R-G1-1:
    ``--ignore-submodules=none``, so ``diff.ignoreSubmodules`` and ``submodule.<name>.ignore`` cannot hide a changed
    submodule, and a submodule holding only untracked files is listed too)."""
    _require_toplevel(root)
    p = _run(root, "diff --name-only", ["diff", "--no-color", "--name-only", "-z", "--no-ext-diff", "--no-textconv",
                                        "--ignore-submodules=none"], opts=FSMONITOR_OFF)
    return [_text(raw, "diff --name-only") for raw in p.stdout.split(b"\0") if raw]


def flagged_paths(root: str) -> list:
    """The tracked paths flagged assume-unchanged (a lowercase ASCII tag in ``git ls-files -v``) or skip-worktree
    (tag ``S``), in git's order: the rule of spec C-29 (``git ls-files -v | grep '^[a-zS]'``), so ``git diff`` cannot
    show a change to them (task 2b.2, owner Q-G1-3 (a), D-14; ``GIT_INDEX_FILE`` inherited as in ``unstaged_paths``).
    An entry that is not ``<ASCII letter> <space> <path>`` is a GateError: the hook fails closed."""
    _require_toplevel(root)
    p = _run(root, "ls-files -v", ["ls-files", "-v", "-z"], opts=FSMONITOR_OFF)
    data = p.stdout
    if data and not data.endswith(b"\0"):
        raise GateError("git ls-files -v: unexpected entry %r" % data.rsplit(b"\0", 1)[-1])
    out = []
    for raw in (data.split(b"\0")[:-1] if data else []):
        if len(raw) < 3 or raw[1:2] != b" " or not (b"a" <= raw[:1] <= b"z" or b"A" <= raw[:1] <= b"Z"):
            raise GateError("git ls-files -v: unexpected entry %r" % raw)
        path = _text(raw[2:], "ls-files -v")
        if raw[:1] == b"S" or raw[:1].islower():
            out.append(path)
    return out


def hooks_dir(root: str) -> str:
    """The absolute directory git runs hooks from (``rev-parse --git-path hooks``: the common git directory's
    ``hooks`` for a linked worktree, ``core.hooksPath`` when set), a relative answer taken from ``root``."""
    _require_toplevel(root)
    p = _run(root, "rev-parse --git-path hooks", ["rev-parse", "--git-path", "hooks"])
    path = _text(p.stdout, "rev-parse --git-path hooks")
    if path.endswith("\n"):
        path = path[:-1]  # git's one line terminator; every other byte (spaces, more newlines) is the path's own
    return os.path.abspath(os.path.join(root, path))


def _need_root(root: object) -> None:
    """Decision D-Q14 (Task P1.3): the functions of this task take a ``str`` root, never ``""``, ``bytes`` or a subclass."""
    if type(root) is not str or root == "":
        raise GateError("root must be a string")


_HEADS = "refs/heads/"


def current_branch(root: str) -> Optional[str]:
    """The branch HEAD is on, or ``None`` when HEAD is detached (Task P1.3, decision D-Q6): ``git symbolic-ref --quiet
    HEAD`` with ``refs/heads/`` stripped, not the ``--short`` form, which prints ``heads/<b>`` when a tag ``<b>``
    exists. An unborn branch gives its name. A target outside ``refs/heads/`` is a GateError (fail closed)."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "symbolic-ref", ["symbolic-ref", "--quiet", "HEAD"], ok=(0, 1))
    if p.returncode == 1:
        return None
    ref = _text(p.stdout, "symbolic-ref")
    if ref.endswith("\n"):
        ref = ref[:-1]  # git's one line terminator
    if not ref.startswith(_HEADS) or len(ref) == len(_HEADS):
        raise GateError("git symbolic-ref: HEAD does not name a branch under refs/heads/")
    return ref[len(_HEADS):]


def dirty_paths(root: str) -> list:
    """The paths of the work tree at ``root`` that ``git status`` reports (staged, unstaged, untracked, unmerged, a
    changed submodule), in git's order, each once (Task P1.3; decisions D-Q7, D-Q8). ``--porcelain=v1 -z`` quotes
    nothing; ``--no-renames`` makes every entry one path (the text after the three bytes ``XY ``; minimum git 2.18);
    ``--ignore-submodules=none`` as ``unstaged_paths``; ``--untracked-files=all`` and ``--ignored=no`` override the
    user's ``status.showUntrackedFiles``; ``GIT_OPTIONAL_LOCKS=0`` keeps this call from rewriting ``.git/index``;
    ``core.fsmonitor`` is off as in the hooks' calls. ``GIT_INDEX_FILE`` is inherited. A linked worktree's paths are
    never listed: git answers for the work tree of ``root``."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "status --porcelain", ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=no",
                                          "--no-renames", "--ignore-submodules=none"],
             opts=FSMONITOR_OFF, extra_env={"GIT_OPTIONAL_LOCKS": "0"})
    out = []
    for raw in p.stdout.split(b"\0"):
        if not raw:
            continue
        if len(raw) < 4 or raw[2:3] != b" ":
            raise GateError("git status --porcelain: unexpected entry %r" % raw)
        out.append(_text(raw[3:], "status --porcelain"))
    return out


def upstream_sha(root: str) -> Optional[str]:
    """The commit ``@{upstream}`` names, ``None`` when the branch has none (never configured, the remote branch gone,
    a detached HEAD, measured with git 2.50.1): ``git rev-parse --verify --quiet`` exits 1 then (Task P1.3). Read from local
    refs only."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "rev-parse @{upstream}", ["rev-parse", "--verify", "--quiet", "--end-of-options", "@{upstream}"],
             ok=(0, 1))
    if p.returncode == 1:
        return None
    return _text(p.stdout, "rev-parse").strip()


def remotes(root: str) -> list:
    """The names ``git remote`` lists, in git's order; any listed name counts (Task P1.3, decision D-Q12)."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "remote", ["remote"])
    return [n for n in _text(p.stdout, "remote").split("\n") if n]


# Task P2.1 part i (decisions D-A13, D-A13b, D-A14, D-A15, D-A16, D-A23, D-A25). The three history readers pass the
# global option ``--no-replace-objects`` (D-A16: a ``refs/replace`` ref must not change the answer of a merge-policy
# check); the existing calls above are unchanged.
_NO_REPLACE = ["--no-replace-objects"]


def local_branches(root: str) -> list:
    """Every ``refs/heads/`` branch name, sorted (Task P2.1; decisions D-A13, D-A23): ``git for-each-ref --no-color
    --format=%(refname) refs/heads`` with ``refs/heads/`` stripped, not the ``%(refname:short)`` form, which prints
    ``heads/<b>`` when a tag ``<b>`` exists. A name that is not valid UTF-8 is a GateError."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "for-each-ref", ["for-each-ref", "--no-color", "--format=%(refname)", "refs/heads"])
    names = []
    for line in _text(p.stdout, "for-each-ref").split("\n"):
        if not line:
            continue
        if not line.startswith(_HEADS):
            raise GateError("git for-each-ref: unexpected ref %r" % line)
        names.append(line[len(_HEADS):])
    return sorted(names)


def _need_revision(value: object, name: str) -> str:
    """``value`` is a non-empty ``str`` (a subclass is refused) and passes ``_check_rev``; GateError otherwise."""
    if type(value) is not str or value == "":
        raise GateError("%s must be a non-empty string" % name)
    _check_rev(value)
    return value


def changed_paths(root: str, a: str, b: Optional[str]) -> list:
    """The paths that differ between ``a`` and ``b`` (``None``: the working tree), in git's order, both sides of a
    rename listed (Task P2.1; decisions D-A14, D-A16): ``git diff --no-color --name-only -z --no-renames --no-ext-diff
    --no-textconv a [b] --``. The trailing ``--`` keeps a revision from being read as a path; ``GIT_OPTIONAL_LOCKS=0``
    and ``core.fsmonitor`` off are set as in ``dirty_paths`` (D-A14). Measured with git 2.50.1: a call against the
    work tree (``b`` ``None``) still refreshes the stat data of ``.git/index``, never what it records. Untracked
    files are never listed."""
    _need_root(root)
    _need_revision(a, "a")
    if b is not None:
        if type(b) is not str or b == "":
            raise GateError("b must be None or a non-empty string")
        _check_rev(b)
    _require_toplevel(root)
    args = ["diff", "--no-color", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", a]
    if b is not None:
        args.append(b)
    p = _run(root, "diff --name-only", args + ["--"], opts=_NO_REPLACE + FSMONITOR_OFF,
             extra_env={"GIT_OPTIONAL_LOCKS": "0"})
    return [_text(raw, "diff --name-only") for raw in p.stdout.split(b"\0") if raw]


def rev_list(root: str, a: str, b: str, first_parent: bool = False) -> list:
    """The commits of ``a..b``, oldest first (parents before children): ``git rev-list --topo-order --reverse
    [--first-parent] a..b --`` (Task P2.1; decisions D-A13b, D-A16). ``--reverse`` alone orders unrelated commits by
    date, which a skewed clock turns into a child before its parent; ``--first-parent`` lists only the first-parent
    line. ``a`` equal to ``b``, or ``b`` an ancestor of ``a``, gives ``[]``."""
    _need_root(root)
    _need_revision(a, "a")
    _need_revision(b, "b")
    if type(first_parent) is not bool:
        raise GateError("first_parent must be a bool")
    _require_toplevel(root)
    args = ["rev-list", "--topo-order", "--reverse"] + (["--first-parent"] if first_parent else [])
    p = _run(root, "rev-list", args + ["%s..%s" % (a, b), "--"], opts=_NO_REPLACE)
    return [x for x in _text(p.stdout, "rev-list").split("\n") if x]


def ls_tree_entries(root: str, ref: str, directory: str) -> list:
    """Every entry directly under ``directory`` at ``ref`` as ``(mode, type, path)`` (Task P2.1 review 1, finding
    F-20261118-bc74, decision D-A9): ``git ls-tree -z --full-tree ref -- directory/``. ``mode`` is git's six digits
    (``100644``, ``100755``, ``120000`` a symlink, ``160000`` a gitlink, ``040000`` a tree), ``type`` is ``blob``,
    ``tree`` or ``commit``, ``path`` is repo-relative. ``ls_tree`` lists only the regular files and hides the
    rest; this lists them all, so a caller can refuse a stray entry. A ``directory`` that is no folder at ``ref``
    (missing, a file, a symlink) gives ``[]``; ``""`` is the repository root."""
    _need_root(root)
    _need_revision(ref, "ref")
    if type(directory) is not str:
        raise GateError("directory must be a string")
    _require_toplevel(root)
    _check_norm(directory, "ls-tree: directory", allow_empty=True)
    args = ["ls-tree", "-z", "--full-tree", ref] + (["--", directory + "/"] if directory else [])
    p = _run(root, "ls-tree", args, literal=True, opts=_NO_REPLACE)
    out = []
    for raw in p.stdout.split(b"\0"):
        if not raw:
            continue
        head, _, path = raw.partition(b"\t")
        fields = head.split(b" ")
        if len(fields) != 3:
            raise GateError("git ls-tree gave an entry that cannot be read")
        out.append((fields[0].decode("ascii"), fields[1].decode("ascii"), _text(path, "ls-tree")))
    return out


def parents(root: str, sha: str) -> list:
    """The parents of commit ``sha``, first parent first, as full ids; ``[]`` for a root commit (Task P2.1; decisions
    D-A15, D-A16): ``git rev-list --parents -n 1 --end-of-options <sha>^{commit}``. The ``^{commit}`` peel makes a
    tree or blob id a GateError, where an unpeeled call prints nothing and reads as no commit. The tip of a shallow
    clone reads as a root commit (git cuts its parents), so a caller that needs two parents fails closed."""
    _need_root(root)
    if type(sha) is not str:
        raise GateError("sha must be a string")
    _need_revision(sha, "sha")
    _require_toplevel(root)
    p = _run(root, "rev-list --parents", ["rev-list", "--parents", "-n", "1", "--end-of-options", sha + "^{commit}"],
             opts=_NO_REPLACE)
    ids = _text(p.stdout, "rev-list --parents").split()
    if not ids:
        raise GateError("git rev-list --parents gave no commit")
    return ids[1:]


def main_worktree(root: str) -> str:
    """The absolute path of the main worktree: the parent of ``git rev-parse --path-format=absolute
    --git-common-dir`` (Task P2.1; decision D-A25). ``--path-format`` needs git 2.31. The common directory must be
    named ``.git``: a clone made with ``--separate-git-dir``, a bare repository's worktree and a submodule have no
    main worktree beside it, and are a GateError (fail closed)."""
    _need_root(root)
    _require_toplevel(root)
    p = _run(root, "rev-parse --git-common-dir", ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    common = _text(p.stdout, "rev-parse --git-common-dir")
    if common.endswith("\n"):
        common = common[:-1]
    if not os.path.isabs(common) or posixpath.basename(common) != ".git":
        raise GateError("git rev-parse --git-common-dir: no main worktree (the common git directory is not a "
                        "directory named .git)")
    return posixpath.dirname(common)
