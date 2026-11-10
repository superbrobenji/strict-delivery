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
         index: Optional[str] = None) -> "subprocess.CompletedProcess":
    """Run ``git [opts] -C root <args>``; with ``ok`` a tuple, any other exit status is a GateError naming
    ``name``. ``index`` sets ``GIT_INDEX_FILE`` for this call only (``blob_ids``'s temporary copy)."""
    env = _env()
    if index is not None:
        env["GIT_INDEX_FILE"] = index
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
