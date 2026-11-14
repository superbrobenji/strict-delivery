"""Hook session store: locked per-session state kept outside every repository (standard library only).

The state of one Claude Code session lives at ``${CLAUDE_PLUGIN_DATA}/sessions/<session_id>.yml`` (a strict-YAML-subset
file whose first key is ``schema: hook-session/1``) with a lock file ``<session_id>.lock`` beside it. No tree holds it,
so ``state_errors`` is its only schema check. ``locked`` yields the state under an exclusive ``flock`` and writes it back
on a clean exit. An unreadable store fails closed with ``SessionUnavailable``; only ``reset`` (SessionStart) moves a
corrupt file aside, and it never parses what it moves.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import os
import re
import stat
import time
from typing import Mapping, Optional

from gates.lib import yamlsub
from gates.lib.result import GateError, safe_text

SCHEMA = "hook-session/1"
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOP_KEYS = ("schema", "session", "dispatches", "surfaced")
_ENTRY_KEYS = ("sha", "role", "depth", "parent", "worktree", "branch")
_POLL_S = 0.02
_CREATE_TRIES = 20


class SessionUnavailable(GateError):
    """The session store cannot be used; the message is the FAIL reason."""


class _Unreadable(Exception):
    """The state file at hand cannot be read as a valid state (internal; ``reason`` is the text for the message)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _now() -> float:
    return time.time()


def _quoted(text: object) -> str:
    return "'" + safe_text(text) + "'"


# ---------------------------------------------------------------- validation

def state_errors(state: object, session_id: str) -> list:
    """Every way ``state`` departs from the ``hook-session/1`` shape, as ``<key path>: <problem>`` strings.

    Order: the four top keys in schema order (a ``dispatches`` entry's errors follow its own list check), then the
    unknown top keys in file order; each entry likewise lists its six keys in order, then its unknown keys."""
    if type(state) is not dict:
        return ["state: must be a mapping"]
    errors = []
    for key in _TOP_KEYS:
        if key not in state:
            errors.append(key + ": missing key")
            continue
        value = state[key]
        if key == "schema":
            if type(value) is not str or value != SCHEMA:
                errors.append("schema: must be " + _quoted(SCHEMA))
        elif key == "session":
            if type(value) is not str or value != session_id:
                errors.append("session: must be " + _quoted(session_id))
        elif key == "dispatches":
            if type(value) is not list:
                errors.append("dispatches: must be a list")
                continue
            for i, entry in enumerate(value):
                errors.extend(_entry_errors(entry, "dispatches[%d]" % i))
        else:
            if type(value) is not list:
                errors.append("surfaced: must be a list")
                continue
            for i, item in enumerate(value):
                if type(item) is not str:
                    errors.append("surfaced[%d]: must be a str" % i)
    for key in state:
        if key not in _TOP_KEYS:
            errors.append(_key_text(key) + ": unknown key")
    return errors


def _key_text(key: object) -> str:
    return safe_text(key) if type(key) is str else "<" + type(key).__name__ + " key>"


def _entry_errors(entry: object, path: str) -> list:
    if type(entry) is not dict:
        return [path + ": must be a mapping"]
    errors = []
    for key in _ENTRY_KEYS:
        if key not in entry:
            errors.append("%s.%s: missing key" % (path, key))
            continue
        value = entry[key]
        if key == "sha":
            if type(value) is not str or not _SHA.match(value):
                errors.append(path + ".sha: must be 64 lowercase hex digits")
        elif key == "depth":
            if type(value) is not int or value < 1:
                errors.append(path + ".depth: must be an integer >= 1")
        elif key == "worktree":
            if type(value) is not str or not (value == "" or value.startswith("/")):
                errors.append(path + '.worktree: must be an absolute path or ""')
        elif type(value) is not str:
            errors.append("%s.%s: must be a str" % (path, key))
    for key in entry:
        if key not in _ENTRY_KEYS:
            errors.append("%s.%s: unknown key" % (path, _key_text(key)))
    return errors


def _check_id(session_id: object) -> str:
    """The id when it is a plain ``str`` matching ``SESSION_ID``; otherwise ``SessionUnavailable``."""
    if type(session_id) is not str:
        raise SessionUnavailable("session id must be a plain str, got %s" % type(session_id).__name__)
    if not SESSION_ID.match(session_id):
        raise SessionUnavailable("session id %s is not valid (1 to 128 of A-Z a-z 0-9 _ -)" % _quoted(session_id))
    return session_id


# ---------------------------------------------------------------- directory

def _plugin_data(env: Mapping[str, str]) -> str:
    value = env.get("CLAUDE_PLUGIN_DATA")
    if value is None:
        raise SessionUnavailable("CLAUDE_PLUGIN_DATA is not set")
    if not issubclass(type(value), str):
        raise SessionUnavailable("CLAUDE_PLUGIN_DATA must be a str, got %s" % type(value).__name__)
    value = str.__str__(value)  # a plain copy: no override of a subclass is ever called
    if "\x00" in value:
        raise SessionUnavailable("CLAUDE_PLUGIN_DATA contains a NUL character")
    if not os.path.isabs(value):
        raise SessionUnavailable("CLAUDE_PLUGIN_DATA must be an absolute path: " + _quoted(value))
    return value


def session_dir(env: Mapping[str, str]) -> str:
    """``<CLAUDE_PLUGIN_DATA>/sessions``; touches no file."""
    return os.path.join(_plugin_data(env), "sessions")


def _make_private(path: str) -> None:
    """Create ``path`` with mode 0o700 (exactly, whatever the umask); an existing path is left alone."""
    try:
        os.makedirs(path, mode=0o700)
    except FileExistsError:
        return
    os.chmod(path, 0o700)


def _open_sessions(env: Mapping[str, str]) -> tuple:
    """Create ``P`` and ``S`` when absent, open ``S`` once (``O_DIRECTORY | O_NOFOLLOW``) and check that descriptor:
    a directory owned by the current uid. Returns ``(descriptor, S)``; every later file call of the store goes
    through the descriptor (``dir_fd``), so a swap of ``S`` after this point has no effect."""
    plugin = _plugin_data(env)
    sessions = os.path.join(plugin, "sessions")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        _make_private(plugin)
        try:
            dfd = os.open(sessions, flags)
        except FileNotFoundError:
            _make_private(sessions)
            dfd = os.open(sessions, flags)
    except (OSError, ValueError) as e:
        raise SessionUnavailable("the session directory %s is not usable, not a real directory or cannot be "
                                 "created (%s)" % (sessions, _why(e))) from None
    try:
        if os.fstat(dfd).st_uid != os.getuid():
            raise SessionUnavailable("the session directory %s is owned by another user" % sessions)
    except BaseException:
        os.close(dfd)
        raise
    return dfd, sessions


def _why(e: Exception) -> str:
    return (e.strerror if isinstance(e, OSError) and e.strerror else type(e).__name__)


# ---------------------------------------------------------------- lock and files

def _check_timeout(timeout_s: object) -> None:
    if type(timeout_s) is not int or timeout_s < 0:
        got = safe_text(timeout_s) if type(timeout_s) is int else type(timeout_s).__name__
        raise SessionUnavailable("timeout_s must be an int >= 0 (got %s)" % got)


def _acquire(dfd: int, name: str, path: str, timeout_s: int) -> int:
    """Open ``name`` in ``dfd`` (``O_CREAT | O_NOFOLLOW``, exactly 0o600, a regular file) and take
    ``flock(LOCK_EX)``, polling ``LOCK_NB`` for ``timeout_s`` seconds (at least one try). Returns the descriptor;
    it is closed on every refusal."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    for attempt in range(_CREATE_TRIES):
        try:
            fd = os.open(name, flags, 0o600, dir_fd=dfd)
            break
        except FileNotFoundError as e:
            # macOS answers ENOENT to a create-open that races another process creating the same name in a
            # directory reached through a descriptor (about 1 in 400 starts); the directory is held open, so retry
            if attempt == _CREATE_TRIES - 1:
                raise SessionUnavailable("cannot open the lock file %s (%s)" % (path, _why(e))) from None
            time.sleep(_POLL_S / 4)
        except OSError as e:
            raise SessionUnavailable("cannot open the lock file %s (%s)" % (path, _why(e))) from None
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES):
                    raise SessionUnavailable("cannot lock %s (%s)" % (path, _why(e))) from None
            if time.monotonic() >= deadline:
                raise SessionUnavailable("the session lock %s is held by another process (waited %s s)"
                                         % (path, timeout_s))
            time.sleep(_POLL_S)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):  # a FIFO can be flocked on some systems
                raise SessionUnavailable("the lock file %s is not a regular file" % path)
            os.fchmod(fd, 0o600)
        except OSError as e:
            raise SessionUnavailable("cannot use the lock file %s (%s)" % (path, _why(e))) from None
        return fd
    except BaseException:
        os.close(fd)
        raise


def _unreadable(path: str, reason: str) -> SessionUnavailable:
    return SessionUnavailable(
        "the session state file %s is unreadable (%s); start a new session (SessionStart moves it aside), "
        "or as the human delete it: rm '%s'" % (path, reason, path.replace("'", "'\\''")))


def _read(dfd: int, name: str) -> bytes:
    """The bytes of ``name`` in ``dfd``: opened ``O_NOFOLLOW | O_NONBLOCK``, so a symlink is refused and a FIFO
    can neither block nor feed the state (a directory or a socket fail the open or the read)."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0), dir_fd=dfd)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _load(dfd: int, name: str, path: str, session_id: str) -> Optional[dict]:
    """The valid state in ``name``; ``None`` when there is no file; ``_Unreadable`` for anything else."""
    try:
        data = _read(dfd, name)
    except FileNotFoundError:
        return None
    except OSError as e:  # a symlink (ELOOP), a directory, EACCES ...
        raise _Unreadable(_why(e)) from None
    try:
        state = yamlsub.parse(yamlsub._file_text(data))
    except yamlsub.YamlError as e:
        raise _Unreadable(str(yamlsub.YamlError(e.line, "%s: %s" % (path, e.reason)))) from None
    except UnicodeDecodeError:
        raise _Unreadable(str(yamlsub.YamlError(0, "%s: not valid UTF-8" % path))) from None
    except Exception as e:  # nothing the file holds may escape as anything but "unreadable"
        raise _Unreadable(type(e).__name__) from None
    errors = state_errors(state, session_id)
    if errors:
        raise _Unreadable("; ".join(errors))
    return state


def _write(dfd: int, name: str, path: str, state: object, session_id: str) -> None:
    """Check ``state`` and write it to ``name`` through ``<name>.tmp`` and ``os.replace`` (all in ``dfd``)."""
    errors = state_errors(state, session_id)
    if errors:
        raise SessionUnavailable("the session state for %s is invalid and was not written (%s)"
                                 % (_quoted(session_id), "; ".join(errors)))
    try:
        data = yamlsub.emit(state).encode("utf-8")
    except (yamlsub.EmitError, UnicodeError) as e:
        raise SessionUnavailable("the session state for %s cannot be written (%s)" % (_quoted(session_id), e)) from None
    tmp = name + ".tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(tmp, flags, 0o600, dir_fd=dfd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SessionUnavailable("the temporary file %s.tmp is not a regular file" % path)
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError as e:
        raise SessionUnavailable("cannot write the session state file %s (%s)" % (path, _why(e))) from None


@contextlib.contextmanager
def _exclusive(env: Mapping[str, str], session_id: str, timeout_s: int):
    """Validate the arguments, open the directory and hold the lock; yields ``(dir descriptor, file name, path)``
    of the state file."""
    _check_id(session_id)
    _check_timeout(timeout_s)
    dfd, sessions = _open_sessions(env)
    try:
        fd = _acquire(dfd, session_id + ".lock", os.path.join(sessions, session_id + ".lock"), timeout_s)
        try:
            yield dfd, session_id + ".yml", os.path.join(sessions, session_id + ".yml")
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def _empty(session_id: str) -> dict:
    return {"schema": SCHEMA, "session": session_id, "dispatches": [], "surfaced": []}


@contextlib.contextmanager
def locked(env: Mapping[str, str], session_id: str, timeout_s: int = 10):
    """Hold the session lock and yield the state dict; write it back on a clean exit only.

    An absent file gives the empty state. An unreadable or invalid file, a held lock, a bad id or timeout or an
    unusable directory raise ``SessionUnavailable``; nothing is reset. Any exception from the body
    (``BaseException`` included) propagates unchanged and nothing is written."""
    with _exclusive(env, session_id, timeout_s) as (dfd, name, path):
        try:
            state = _load(dfd, name, path, session_id)
        except _Unreadable as e:
            raise _unreadable(path, e.reason) from None
        if state is None:
            state = _empty(session_id)
        yield state
        _write(dfd, name, path, state, session_id)


def _utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(_now()))


def _move_aside(dfd: int, name: str, path: str) -> str:
    """Rename ``name`` (whatever it is, unparsed) to ``<name>.corrupt-<UTC stamp>``, with ``-1``, ``-2``... when
    the name is taken; returns the new path."""
    base = ".corrupt-" + _utc_stamp()
    suffix, n = base, 0
    while True:
        try:
            os.stat(name + suffix, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            break
        except OSError as e:
            raise SessionUnavailable("cannot move %s aside (%s)" % (path, _why(e))) from None
        n += 1
        suffix = "%s-%d" % (base, n)
    try:
        os.rename(name, name + suffix, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError as e:
        raise SessionUnavailable("cannot move %s aside (%s)" % (path, _why(e))) from None
    return path + suffix


def reset(env: Mapping[str, str], session_id: str, timeout_s: int = 10) -> Optional[str]:
    """SessionStart's reset, under the lock. A readable file keeps ``surfaced`` and loses its ``dispatches``; an
    absent file gets the empty state (both return ``None``). An unreadable one is moved aside without being parsed
    further, a fresh empty state is written, and the new name is returned. A lock that cannot be taken or a bad
    directory still raises ``SessionUnavailable``."""
    with _exclusive(env, session_id, timeout_s) as (dfd, name, path):
        moved = None
        try:
            state = _load(dfd, name, path, session_id)
        except _Unreadable:
            state, moved = None, _move_aside(dfd, name, path)
        if state is None:
            state = _empty(session_id)
        state["dispatches"] = []
        _write(dfd, name, path, state, session_id)
        return moved


# ---------------------------------------------------------------- pure helpers

def prompt_sha(prompt: str) -> str:
    """SHA-256 of the prompt's UTF-8 bytes, lowercase hex (``TypeError`` for a non-str, ``UnicodeEncodeError`` for a lone surrogate)."""
    return hashlib.sha256(str.encode(prompt, "utf-8")).hexdigest()


def add_dispatch(state: dict, sha: str, role: str, depth: int, parent: str, worktree: str = "",
                 branch: str = "") -> None:
    state["dispatches"].append({"sha": sha, "role": role, "depth": depth, "parent": parent,
                                "worktree": worktree, "branch": branch})


def end_dispatch(state: dict, sha: str) -> bool:
    """Remove the first live entry with ``sha``; ``False`` when there is none."""
    entries = state["dispatches"]
    for i, entry in enumerate(entries):
        if entry["sha"] == sha:
            del entries[i]
            return True
    return False


def live_total(state: dict) -> int:
    return len(state["dispatches"])


def live_children(state: dict, parent: str) -> int:
    return sum(1 for entry in state["dispatches"] if entry["parent"] == parent)


def lookup(state: dict, sha: str) -> Optional[tuple]:
    """``(role, depth, worktree, branch)`` when every live entry with ``sha`` agrees on all four; else ``None``."""
    found = {(e["role"], e["depth"], e["worktree"], e["branch"]) for e in state["dispatches"] if e["sha"] == sha}
    return found.pop() if len(found) == 1 else None


def mark_surfaced(state: dict, decision_id: str) -> bool:
    """Record ``decision_id`` as surfaced; ``True`` the first time."""
    if decision_id in state["surfaced"]:
        return False
    state["surfaced"].append(decision_id)
    return True
