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


def content_sha(path: str) -> str:
    """The 40-hex git blob id of the raw bytes of the regular file ``path``, computed here (no git, no filters)."""
    if type(path) is not str:
        raise GateError("path must be a string")
    try:
        data = yamlsub._read_regular_file(path, path)
    except yamlsub.YamlError as e:
        raise GateError(e.reason) from None
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
    """The receipts directory below ``top``: every component ``lstat``-ed, none a symlink or a non-directory. ``None``
    when a component is missing and ``create`` is false; with ``create`` the missing ones are made (the last 0o700)."""
    cur = top
    parts = rel.split("/")
    for i, comp in enumerate(parts):
        cur = os.path.join(cur, comp)
        shown = "/".join(parts[:i + 1])
        try:
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                if not create:
                    return None
                try:
                    os.mkdir(cur, 0o700 if i == len(parts) - 1 else 0o777)
                except FileExistsError:
                    pass  # a rival made it first: checked below
                st = os.lstat(cur)
        except OSError as e:
            raise GateError("%s: cannot use the receipts directory (%s)" % (shown, e.strerror or type(e).__name__)) \
                from None
        if stat.S_ISLNK(st.st_mode):
            raise GateError("%s: is a symlink; directories must be real directories" % shown)
        if not stat.S_ISDIR(st.st_mode):
            raise GateError("%s: is not a directory" % shown)
    return cur


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
    dirpath = _walk(top, rel, True)
    fpath = os.path.join(dirpath, session + ".yml")
    shown = rel + "/" + session + ".yml"
    try:
        try:
            st = os.lstat(fpath)
        except FileNotFoundError:
            st = None
        if st is not None and not stat.S_ISREG(st.st_mode):
            raise GateError("%s: %s; receipt files must be regular files" % (
                shown, "is a symlink" if stat.S_ISLNK(st.st_mode) else "is not a regular file"))
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(fpath, flags, 0o600)
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
    return row


def _write(fd: int, data: bytes, shown: str) -> None:
    if os.write(fd, data) != len(data):
        raise GateError("%s: short write" % shown)


def load(root: str, cfg: dict, session: str) -> list:
    """The session's rows ``[{path, sha}, ...]`` in file order; ``[]`` when there is no file. A file that fails
    ``receipt/1``, holds a sha that is not 40 hex or lacks its final newline raises a GateError naming it."""
    rel = _check_args(root, cfg, session)
    top = _top(root)
    dirpath = _walk(top, rel, False)
    if dirpath is None:
        return []
    fpath = os.path.join(dirpath, session + ".yml")
    shown = rel + "/" + session + ".yml"

    def fail(why: str) -> GateError:
        return GateError("%s; %s" % (why, _REMEDY))

    try:
        st = os.lstat(fpath)
    except FileNotFoundError:
        return []
    except OSError as e:
        raise fail("%s: cannot read file (%s)" % (shown, e.strerror or type(e).__name__)) from None
    if not stat.S_ISREG(st.st_mode):
        raise fail("%s: %s; receipt files must be regular files" % (
            shown, "is a symlink" if stat.S_ISLNK(st.st_mode) else "is not a regular file"))
    try:
        data = yamlsub._read_regular_file(fpath, shown)
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
