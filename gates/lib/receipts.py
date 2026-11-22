"""Read receipts (spec 9; plan Task 5a.2; task domain table 5a.2 with its binding controller decisions).

Standard library only. One file per session, ``<paths.receipts>/<session>.yml``, written by the Read hook through
``record`` and read by ``load`` (for ``gate_context`` alone: ``gate_schema`` never reads the git-ignored receipts,
Q-B5plan-5 (b), so this module declares no produced kind). ``record`` computes the git blob id of the raw bytes in
Python (R5a-4, no git call), refuses a symlink or non-directory on the receipts path and a symlink or non-regular
receipt file, and appends under ``flock`` so parallel Read hooks of one session cannot interleave or lose rows.
``load`` validates against ``receipt/1`` and additionally requires every ``sha`` to be 40 lowercase hex and the file
to end in a newline (decision D-Q1 (a)), so a row cut by a crash is always refused.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import stat

from gates.lib import config, schema, yamlsub
from gates.lib.result import GateError

SESSION_RE = "[A-Za-z0-9][A-Za-z0-9_-]{0,127}"

_HEADER = b"schema: receipt/1\nreads:\n"
_REMEDY = "delete it to start the session's receipts again"
_SHA40 = re.compile("[0-9a-f]{40}")


def session_problem(key: object) -> str:
    """``""`` when ``key`` is a valid session key, else a one-line problem that never echoes the key."""
    if type(key) is not str:
        return "session: must be a string"
    if re.fullmatch(SESSION_RE, key) is None:
        return "session: must be 1 to 128 characters, A-Z a-z 0-9 _ -, starting with a letter or a digit"
    return ""


_REAL_OPEN, _REAL_MKDIR, _REAL_STAT = os.open, os.mkdir, os.stat  # membership is judged on these, not on a test's wrapper
_NO_FD = "directory descriptors are not supported on this platform"


def _need_fd_support(create: bool, shown: str, what: str) -> None:
    """Decision D-Q1: a platform without the descriptor calls is refused, never served by a path walk."""
    ok = (_REAL_OPEN in os.supports_dir_fd and _REAL_STAT in os.supports_dir_fd
          and _REAL_STAT in os.supports_follow_symlinks and (not create or _REAL_MKDIR in os.supports_dir_fd)
          and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"))
    if not ok:
        raise GateError("%s: %s (%s)" % (shown, what, _NO_FD))


def _kind(name: str, dir_fd: int) -> str:
    """What ``name`` is in the directory ``dir_fd`` right now, never following a symlink (decision D-Q2: the sentence is
    chosen by this ``stat`` after a failed open, never by errno): gone, other (the stat failed), link, dir, reg, special."""
    try:
        mode = os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return "gone"
    except OSError:
        return "other"
    if stat.S_ISLNK(mode):
        return "link"
    if stat.S_ISDIR(mode):
        return "dir"
    return "reg" if stat.S_ISREG(mode) else "special"


def _step(parent: int, name: str, shown: str, create: bool, mode: int, what: str) -> object:
    """The descriptor of the directory ``name`` inside ``parent``, opened ``O_DIRECTORY | O_NOFOLLOW`` so the object
    checked is the object used (F-20261121-vhs6). ``None`` when it is missing and ``create`` is false. A missing one
    is made with ``mkdir(dir_fd=)`` and opened once more; a second miss is an error, never a loop."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for attempt in (0, 1):
        try:
            return os.open(name, flags, dir_fd=parent)
        except OSError as e:
            err = e
        kind = _kind(name, parent)
        if kind == "link":
            raise GateError("%s: is a symlink; directories must be real directories" % shown)
        if kind in ("reg", "special"):
            raise GateError("%s: is not a directory" % shown)
        if kind == "gone" and isinstance(err, FileNotFoundError) and attempt == 0:
            if not create:
                return None
            try:
                os.mkdir(name, mode, dir_fd=parent)
            except FileExistsError:
                pass  # a rival made it first: opened (and checked) by the second attempt
            except OSError as e:
                raise GateError("%s: %s (%s)" % (shown, what, e.strerror or type(e).__name__)) from None
            continue
        raise GateError("%s: %s (%s)" % (shown, what, err.strerror or type(err).__name__)) from None
    raise AssertionError("unreachable")  # pragma: no cover


def _descend(fd: int, parts: list, base: str, create: bool, what: str) -> object:
    """Open ``parts`` one below the other from the directory ``fd`` (which is consumed: closed on every exit). The last
    component of a created chain is 0o700. Returns the descriptor of the last one, or ``None`` when one is missing."""
    try:
        for i, comp in enumerate(parts):
            nxt = _step(fd, comp, base + "/".join(parts[:i + 1]), create, 0o700 if i == len(parts) - 1 else 0o777, what)
            os.close(fd)
            fd = nxt
            if fd is None:
                return None
        out, fd = fd, None
        return out
    finally:
        if fd is not None:
            os.close(fd)


def _read_by_descriptor(path: str, parts: list) -> bytes:
    """The bytes of the regular file ``path`` (absolute, normalised, ``parts`` its components), every directory and the
    file opened by descriptor with no symlink followed and no FIFO opened blocking (U-A)."""
    what = "cannot read file"
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise GateError("/: %s (%s)" % (what, e.strerror or type(e).__name__)) from None
    dirfd = _descend(fd, parts[:-1], "/", False, what)
    if dirfd is None:
        raise GateError("%s: %s (%s)" % (path, what, os.strerror(errno.ENOENT)))
    try:
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
        except OSError as e:
            kind = _kind(parts[-1], dirfd)
            if kind == "link":
                raise GateError("%s: is a symlink" % path) from None
            if kind in ("dir", "special"):
                raise GateError("%s: is not a regular file" % path) from None
            raise GateError("%s: %s (%s)" % (path, what, e.strerror or type(e).__name__)) from None
    finally:
        os.close(dirfd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise GateError("%s: is not a regular file" % path)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as e:
        raise GateError("%s: %s (%s)" % (path, what, e.strerror or type(e).__name__)) from None
    finally:
        os.close(fd)


def content_sha(path: str) -> str:
    """The 40-hex git blob id of the raw bytes of the regular file ``path``, computed here (no git, no filters).
    ``path`` must be absolute and normalised (``record`` passes a ``realpath``); a symlink at any component is refused."""
    if type(path) is not str:
        raise GateError("path must be a string")
    parts = path.split("/")[1:] if path.startswith("/") else [""]
    if any(p in ("", ".", "..") for p in parts):
        raise GateError("%s: path must be absolute and normalised" % path)
    _need_fd_support(False, path, "cannot read file")
    try:
        data = _read_by_descriptor(path, parts)
    except ValueError as e:  # embedded NUL, unencodable name
        raise GateError("%s: cannot read file (invalid path: %s)" % (path, type(e).__name__)) from None
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _bad_path(path: str) -> bool:
    return "\0" in path or any(0xD800 <= ord(c) <= 0xDFFF for c in path)


def _check_args(root: object, cfg: object, session: object) -> str:
    """The receipts directory (relative, from ``paths.receipts``) after every argument but a path is checked."""
    if type(root) is not str or root == "":
        raise GateError("root must be a string")
    problem = session_problem(session)
    if problem:
        raise GateError(problem)
    if type(cfg) is not dict or type(cfg.get("paths")) is not dict or "receipts" not in cfg["paths"]:
        raise GateError("cfg: paths.receipts is required")
    rel = cfg["paths"]["receipts"]
    config._check_path("paths.receipts", rel)
    return rel


def _top(root: str) -> str:
    if _bad_path(root):
        raise GateError("root: invalid path")
    top = os.path.realpath(root)
    if not os.path.isdir(top):
        raise GateError("%s: root is not a directory" % root)
    return top


def _walk(top: str, rel: str, create: bool) -> object:
    """The descriptor of the receipts directory below ``top`` (the caller closes it): ``top`` is opened once and each
    component is opened from the descriptor of the one before, ``O_DIRECTORY | O_NOFOLLOW``, so none is a symlink or a
    non-directory when used (F-20261121-vhs6). ``None`` when a component is missing and ``create`` is false; with
    ``create`` the missing ones are made (the last 0o700)."""
    parts = rel.split("/")
    what = "cannot use the receipts directory"
    _need_fd_support(create, parts[0], what)
    try:
        fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)  # the root: not judged here (decision CD3)
    except OSError as e:
        raise GateError("root: %s (%s)" % (what, e.strerror or type(e).__name__)) from None
    return _descend(fd, parts, "", create, what)


def _row_text(row: dict) -> bytes:
    try:
        text = yamlsub.emit([row])
    except ValueError as e:  # EmitError: a lone surrogate
        raise GateError("path cannot be written: %s" % e) from None
    # the two-space indent splits on "\n" only: str.splitlines would also split U+2028, U+0085 and others
    return "".join("  " + line + "\n" for line in text.split("\n")[:-1]).encode("utf-8")


def record(root: str, cfg: dict, session: str, path: str) -> dict:
    """Append the read of ``path`` to the session's receipt file; return the row ``{path, sha}``."""
    rel = _check_args(root, cfg, session)
    if type(path) is not str:
        raise GateError("path must be a string")
    if _bad_path(path):
        raise GateError("path: invalid (a NUL or a lone surrogate)")
    top = _top(root)
    real = os.path.realpath(os.path.join(top, path))  # an absolute path replaces top in the join
    row = {"path": real, "sha": content_sha(real)}
    body = _row_text(row)  # built before anything is created: a refusal leaves no header-only file
    dirfd = _walk(top, rel, True)
    name = session + ".yml"
    shown = rel + "/" + name
    try:
        try:
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
            fd = os.open(name, flags, 0o600, dir_fd=dirfd)
        except OSError as e:
            kind = _kind(name, dirfd)  # decision D-Q4 (a): the same sentences as a file that was a symlink all along
            if kind == "link":
                raise GateError("%s: is a symlink; receipt files must be regular files" % shown) from None
            if kind in ("dir", "special"):
                raise GateError("%s: is not a regular file; receipt files must be regular files" % shown) from None
            raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise GateError("%s: is not a regular file; receipt files must be regular files" % shown)
            fcntl.flock(fd, fcntl.LOCK_EX)  # released by the close
            if os.fstat(fd).st_size == 0:  # decided under the lock: a rival may have written the header
                _write(fd, _HEADER, shown)
            _write(fd, body, shown)
        finally:
            os.close(fd)
    except OSError as e:
        raise GateError("%s: cannot append (%s)" % (shown, e.strerror or type(e).__name__)) from None
    finally:
        os.close(dirfd)
    return row


def _write(fd: int, data: bytes, shown: str) -> None:
    if os.write(fd, data) != len(data):
        raise GateError("%s: short write" % shown)


def _read_nofollow(dirfd: int, name: str, shown: str, fail) -> object:
    """The bytes of the receipt file ``name`` in the directory ``dirfd`` (``None`` when there is none), opened
    ``O_NOFOLLOW | O_NONBLOCK`` and checked regular on the descriptor: a symlink, FIFO, socket or directory, present at
    the open or swapped in just before it, gets the one sentence (decisions D-Q2, D-Q4 (a))."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
    except OSError as e:
        kind = _kind(name, dirfd)
        if kind == "gone" and isinstance(e, FileNotFoundError):
            return None
        if kind == "link":
            raise fail("%s: is a symlink; receipt files must be regular files" % shown) from None
        if kind in ("dir", "special"):
            raise fail("%s: is not a regular file; receipt files must be regular files" % shown) from None
        raise yamlsub.YamlError(0, "%s: cannot read file (%s)" % (shown, e.strerror or type(e).__name__)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise fail("%s: is not a regular file; receipt files must be regular files" % shown)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as e:
        raise yamlsub.YamlError(0, "%s: cannot read file (%s)" % (shown, e.strerror or type(e).__name__)) from None
    finally:
        os.close(fd)


def load(root: str, cfg: dict, session: str) -> list:
    """The session's rows ``[{path, sha}, ...]`` in file order; ``[]`` when there is no file. A file that fails
    ``receipt/1``, holds a sha that is not 40 hex or lacks its final newline raises a GateError naming it."""
    rel = _check_args(root, cfg, session)
    top = _top(root)
    dirfd = _walk(top, rel, False)
    if dirfd is None:
        return []
    name = session + ".yml"
    shown = rel + "/" + name

    def fail(why: str) -> GateError:
        return GateError("%s; %s" % (why, _REMEDY))

    try:
        try:
            data = _read_nofollow(dirfd, name, shown, fail)
        finally:
            os.close(dirfd)
        if data is None:
            return []
        try:
            text = yamlsub._file_text(data)
        except UnicodeDecodeError:
            raise yamlsub.YamlError(0, "%s: not valid UTF-8" % shown) from None
        try:
            value = yamlsub.parse(text)
        except yamlsub.YamlError as e:
            raise yamlsub.YamlError(e.line, "%s: %s" % (shown, e.reason)) from None
    except yamlsub.YamlError as e:
        raise fail("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
    sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "receipt.yml"))
    errs = schema.validate(sch, value, cfg)
    if not errs:
        errs = ["reads.%d.sha: must be exactly 40 lowercase hex digits" % i
                for i, r in enumerate(value["reads"]) if not _SHA40.fullmatch(r["sha"])]
    if not errs and not data.endswith(b"\n"):
        errs = ["the last line is cut (no final newline)"]
    if errs:
        raise fail("%s: %s" % (shown, "; ".join(errs)))
    return [{"path": r["path"], "sha": r["sha"]} for r in value["reads"]]
