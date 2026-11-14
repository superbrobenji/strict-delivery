"""Tests for the hook session store (gates.lib.session): locked per-session state outside the repository.

Every test runs on real temporary directories set as CLAUDE_PLUGIN_DATA. Expected values are written here by hand,
not derived from the code under test. Patching is limited to the clock (R4), the uid (L6) and the parse failure (R5).
"""
import builtins
import fcntl
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from gates.lib import session, yamlsub
from gates.lib.result import GateError
from gates.lib.session import (SESSION_ID, SessionUnavailable, add_dispatch, end_dispatch, live_children,
                               live_total, locked, lookup, mark_surfaced, prompt_sha, reset, session_dir,
                               state_errors)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHA = "0123456789abcdef" * 4
SHA2 = "fedcba9876543210" * 4
DEC = "DEC-20261101-k3f9"
UNASSIGNED = "\U0001F6DD"  # unassigned in UCD 13.0 (python 3.9), assigned from 14.0: the two interpreters differ
HOLDER = (
    "import fcntl, os, sys, time\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "time.sleep(120)\n"
)
WRITER = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from gates.lib import session\n"
    "env = {'CLAUDE_PLUGIN_DATA': sys.argv[2]}\n"
    "tag = sys.argv[3]\n"
    "for n in range(50):\n"
    "    with session.locked(env, 's1', timeout_s=60) as st:\n"
    "        session.add_dispatch(st, '0123456789abcdef' * 4, tag + str(n), 1, tag)\n"
)


class Sub(str):
    """A str subclass whose overrides all raise: no code may call them."""

    def __str__(self):
        raise AssertionError("__str__ called")

    def __eq__(self, other):
        raise AssertionError("__eq__ called")

    __hash__ = str.__hash__

    def startswith(self, *a):
        raise AssertionError("startswith called")

    def __add__(self, other):
        raise AssertionError("__add__ called")

    def __fspath__(self):
        raise AssertionError("__fspath__ called")


class Plain(str):
    """A well-behaved str subclass."""


def entry_text(sha=SHA, role="implementer", depth="1", parent="session", worktree='""', branch='""'):
    return ("  - sha: %s\n    role: %s\n    depth: %s\n    parent: %s\n    worktree: %s\n    branch: %s\n"
            % (sha, role, depth, parent, worktree, branch))


def state_text(sid="s1", entries=(), surfaced="[]", schema="hook-session/1"):
    body = "dispatches: []\n" if not entries else "dispatches:\n" + "".join(entries)
    return "schema: %s\nsession: %s\n%ssurfaced: %s\n" % (schema, sid, body, surfaced)


def empty(sid):
    return {"schema": "hook-session/1", "session": sid, "dispatches": [], "surfaced": []}


def good_entry(**kw):
    e = {"sha": SHA, "role": "implementer", "depth": 1, "parent": "session", "worktree": "", "branch": ""}
    e.update(kw)
    return e


def enter(cm):
    with cm as st:
        return st


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def fd_count():
    return len(os.listdir("/dev/fd"))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.P = os.path.join(self.tmp, "data")
        self.env = {"CLAUDE_PLUGIN_DATA": self.P}
        self.S = os.path.join(self.P, "sessions")
        self.F = os.path.join(self.S, "s1.yml")
        self.K = os.path.join(self.S, "s1.lock")

    def use(self, name):
        """Point the fixture at a fresh plugin-data directory called ``name``."""
        self.P = os.path.join(self.tmp, name)
        self.env = {"CLAUDE_PLUGIN_DATA": self.P}
        self.S = os.path.join(self.P, "sessions")
        self.F = os.path.join(self.S, "s1.yml")
        self.K = os.path.join(self.S, "s1.lock")

    def foreign_dir_uid(self):
        """os.fstat patched: a directory descriptor reports another uid (the sessions directory is the only one)."""
        real = os.fstat

        def fake(fd, *a, **kw):
            st = real(fd, *a, **kw)
            if stat.S_ISDIR(st.st_mode):
                vals = list(st)[:10]
                vals[4] = st.st_uid + 1
                return os.stat_result(vals)
            return st

        return mock.patch("os.fstat", fake)

    def make_sessions(self):
        os.makedirs(self.S, mode=0o700)

    def put_state(self, data, sid="s1"):
        if not os.path.isdir(self.S):
            self.make_sessions()
        path = os.path.join(self.S, sid + ".yml")
        write_bytes(path, data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def script(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def hold_lock(self, sid="s1"):
        """A child process holding the flock on <sid>.lock; killed on cleanup."""
        if not os.path.isdir(self.S):
            self.make_sessions()
        script = self.script("holder.py", HOLDER)
        proc = subprocess.Popen([sys.executable, script, os.path.join(self.S, sid + ".lock")],
                                stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)

        def stop():
            proc.kill()
            proc.wait()
            proc.stdout.close()

        self.addCleanup(stop)
        self.assertEqual(proc.stdout.readline(), b"held\n")
        return proc


class ConstantsTest(unittest.TestCase):
    def test_session_unavailable_is_gate_error(self):
        self.assertTrue(issubclass(SessionUnavailable, GateError))

    def test_session_id_pattern_literal(self):
        self.assertEqual(SESSION_ID.pattern, r"[A-Za-z0-9_-]{1,128}\Z")
        self.assertIsNone(SESSION_ID.match("s1\n"))
        self.assertIsNotNone(SESSION_ID.match("s1"))


class SessionDirTest(Base):
    def test_unset_plugin_data_is_unavailable(self):
        with self.assertRaises(SessionUnavailable) as cm:
            session_dir({})
        self.assertIn("CLAUDE_PLUGIN_DATA", str(cm.exception))

    def test_empty_plugin_data_is_unavailable(self):
        with self.assertRaises(SessionUnavailable):
            session_dir({"CLAUDE_PLUGIN_DATA": ""})

    def test_relative_plugin_data_is_unavailable(self):
        for value in ("rel", "./rel", "~/x"):
            with self.subTest(value=value):
                with self.assertRaises(SessionUnavailable):
                    session_dir({"CLAUDE_PLUGIN_DATA": value})

    def test_session_dir_joins_sessions(self):
        for value, want in (("/p", "/p/sessions"), ("/p/", "/p/sessions"), ("//p", "//p/sessions")):
            with self.subTest(value=value):
                self.assertEqual(session_dir({"CLAUDE_PLUGIN_DATA": value}), want)

    def test_session_dir_touches_nothing(self):
        self.assertEqual(session_dir(self.env), self.S)
        self.assertFalse(os.path.lexists(self.P))
        enter(locked(self.env, "s1"))
        self.assertTrue(os.path.isdir(self.S))

    def test_non_str_plugin_data_is_unavailable(self):
        for value in (None, b"/p", 1):
            with self.subTest(value=value):
                with self.assertRaises(SessionUnavailable):
                    session_dir({"CLAUDE_PLUGIN_DATA": value})

    def test_str_subclass_plugin_data_copied(self):
        got = session_dir({"CLAUDE_PLUGIN_DATA": Sub("/p")})
        self.assertEqual(got, "/p/sessions")
        self.assertIs(type(got), str)
        enter(locked({"CLAUDE_PLUGIN_DATA": Sub(self.P)}, "s1"))
        self.assertTrue(os.path.isfile(self.F))

    def test_nul_plugin_data_is_unavailable(self):
        with self.assertRaises(SessionUnavailable):
            session_dir({"CLAUDE_PLUGIN_DATA": "/p\x00q"})
        with self.assertRaises(SessionUnavailable):
            enter(locked({"CLAUDE_PLUGIN_DATA": "/p\x00q"}, "s1"))

    def test_unencodable_plugin_data_is_unavailable(self):
        with self.assertRaises(SessionUnavailable):
            enter(locked({"CLAUDE_PLUGIN_DATA": os.path.join(self.tmp, "d\ud800")}, "s1"))


class DirectoryTest(Base):
    def test_round_trip_and_mode(self):
        with locked(self.env, "s1") as st:
            self.assertEqual(st, empty("s1"))
            add_dispatch(st, SHA, "implementer", 1, "session")
        with locked(self.env, "s1") as st:
            self.assertTrue(live_total(st) == 1 and live_children(st, "session") == 1)
            self.assertEqual(st, {"schema": "hook-session/1", "session": "s1",
                                  "dispatches": [good_entry()], "surfaced": []})
        self.assertEqual(stat.S_IMODE(os.stat(self.K).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.S).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.P).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.F).st_mode), 0o600)
        self.assertEqual(sorted(os.listdir(self.S)), ["s1.lock", "s1.yml"])
        self.assertEqual(yamlsub.load(self.F, "F"), {"schema": "hook-session/1", "session": "s1",
                                                    "dispatches": [good_entry()], "surfaced": []})
        with open(self.F) as f:
            self.assertEqual(f.read(), state_text(entries=[entry_text()]))

    def test_sessions_created_under_existing_plugin_data(self):
        os.mkdir(self.P, 0o755)
        enter(locked(self.env, "s1"))
        self.assertEqual(stat.S_IMODE(os.stat(self.S).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.P).st_mode), 0o755)

    def test_plugin_data_file_is_unavailable(self):
        write_bytes(self.P, b"keep")
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(read_bytes(self.P), b"keep")

    def test_plugin_data_symlink_dir_accepted(self):
        real = os.path.join(self.tmp, "real")
        os.mkdir(real)
        os.symlink(real, self.P)
        with locked(self.env, "s1") as st:
            add_dispatch(st, SHA, "implementer", 1, "session")
        self.assertTrue(os.path.isfile(os.path.join(real, "sessions", "s1.yml")))
        self.assertEqual(live_total(enter(locked(self.env, "s1"))), 1)

    def test_sessions_symlink_refused(self):
        os.mkdir(self.P)
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        os.symlink(other, self.S)
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(os.listdir(other), [])

    def test_sessions_file_refused(self):
        os.mkdir(self.P)
        write_bytes(self.S, b"keep")
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(read_bytes(self.S), b"keep")

    def test_sessions_foreign_uid_refused(self):
        self.make_sessions()
        before = fd_count()
        with self.foreign_dir_uid():
            with self.assertRaises(SessionUnavailable) as cm:
                enter(locked(self.env, "s1"))
        self.assertIn(self.S, str(cm.exception))
        self.assertEqual(os.listdir(self.S), [])
        self.assertEqual(fd_count(), before)

    def test_sessions_dir_swap_has_no_effect(self):
        """L8: the swap happens right after the directory is opened and checked (the os.fstat of that descriptor)."""
        self.put_state(state_text(surfaced="[%s]" % DEC))
        evil = os.path.join(self.tmp, "evil")
        moved = os.path.join(self.tmp, "moved")
        os.mkdir(evil)
        evil_text = state_text(surfaced="[DEC-20261101-evil]").encode()
        write_bytes(os.path.join(evil, "s1.yml"), evil_text)
        real, done = os.fstat, []

        def hook(fd, *a, **kw):
            st = real(fd, *a, **kw)
            if stat.S_ISDIR(st.st_mode) and not done:
                done.append(1)
                os.rename(self.S, moved)
                os.symlink(evil, self.S)
            return st

        with mock.patch("os.fstat", hook):
            with locked(self.env, "s1") as st:
                self.assertEqual(st["surfaced"], [DEC])
                add_dispatch(st, SHA, "implementer", 1, "session")
            self.assertEqual(done, [1])
            self.assertTrue(os.path.islink(self.S))
        self.assertEqual(sorted(os.listdir(evil)), ["s1.yml"])
        self.assertEqual(read_bytes(os.path.join(evil, "s1.yml")), evil_text)
        self.assertEqual(sorted(os.listdir(moved)), ["s1.lock", "s1.yml"])
        self.assertEqual(yamlsub.load(os.path.join(moved, "s1.yml"), "m")["dispatches"], [good_entry()])

    def test_spurious_enoent_on_lock_create_is_retried(self):
        """macOS answers ENOENT to a racing create-open of the lock file: injected once, the store retries."""
        self.make_sessions()
        real, calls = os.open, []

        def flaky(path, flags, *a, **kw):
            if path == "s1.lock" and not calls:
                calls.append(1)
                raise FileNotFoundError(2, "No such file or directory", path)
            return real(path, flags, *a, **kw)

        with mock.patch("os.open", flaky):
            enter(locked(self.env, "s1"))
        self.assertEqual(calls, [1])
        self.assertTrue(os.path.isfile(self.F))

    def test_sessions_dir_removed_after_open_is_unavailable(self):
        self.make_sessions()
        real = os.fstat

        def hook(fd, *a, **kw):
            st = real(fd, *a, **kw)
            if stat.S_ISDIR(st.st_mode) and os.path.isdir(self.S):
                os.rmdir(self.S)
            return st

        t0 = time.monotonic()
        with mock.patch("os.fstat", hook):
            with self.assertRaises(SessionUnavailable) as cm:
                enter(locked(self.env, "s1"))
        self.assertLess(time.monotonic() - t0, 3)
        self.assertIn("No such file or directory", str(cm.exception))

    def test_sessions_dir_swap_has_no_effect_on_reset(self):
        self.put_state(b"\xff\xfe")
        taken = self.F + ".corrupt-20231114T221320"  # in the real directory only: the moved name must skip it
        write_bytes(taken, b"first")
        evil = os.path.join(self.tmp, "evil")
        moved = os.path.join(self.tmp, "moved")
        os.mkdir(evil)
        real, done = os.fstat, []

        def hook(fd, *a, **kw):
            st = real(fd, *a, **kw)
            if stat.S_ISDIR(st.st_mode) and not done:
                done.append(1)
                os.rename(self.S, moved)
                os.symlink(evil, self.S)
            return st

        with mock.patch("os.fstat", hook), mock.patch.object(session, "_now", return_value=1700000000.0):
            result = reset(self.env, "s1")
        self.assertEqual(result, self.F + ".corrupt-20231114T221320-1")
        self.assertEqual(os.listdir(evil), [])
        self.assertEqual(read_bytes(os.path.join(moved, "s1.yml.corrupt-20231114T221320")), b"first")
        self.assertEqual(sorted(os.listdir(moved)), sorted(["s1.lock", "s1.yml", os.path.basename(result),
                                                              "s1.yml.corrupt-20231114T221320"]))
        self.assertEqual(read_bytes(os.path.join(moved, os.path.basename(result))), b"\xff\xfe")
        self.assertEqual(yamlsub.load(os.path.join(moved, "s1.yml"), "m"), empty("s1"))

    def test_modes_exact_under_restrictive_umask(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        for n, um in enumerate((0o022, 0o077, 0o277, 0o200, 0o300)):
            with self.subTest(umask=oct(um)):
                self.use("u%d" % n)
                os.umask(um)
                with locked(self.env, "s1") as st:
                    add_dispatch(st, SHA, "implementer", 1, "session")
                self.assertIsNone(reset(self.env, "s1"))
                os.umask(0o022)
                for path, want in ((self.P, 0o700), (self.S, 0o700), (self.K, 0o600), (self.F, 0o600)):
                    self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), want, path)
                with locked(self.env, "s1", timeout_s=0) as st:  # the next process (default umask) still works
                    self.assertEqual(live_total(st), 0)
                os.umask(um)
                with locked(self.env, "s1", timeout_s=0):
                    pass
                os.umask(0o022)
                self.assertEqual(stat.S_IMODE(os.stat(self.F).st_mode), 0o600)

    def test_existing_sessions_mode_kept(self):
        os.mkdir(self.P)
        os.mkdir(self.S)
        os.chmod(self.S, 0o755)
        enter(locked(self.env, "s1"))
        self.assertEqual(stat.S_IMODE(os.stat(self.S).st_mode), 0o755)


class SessionIdTest(Base):
    def test_good_session_ids_accepted(self):
        for sid in ("s1", "-", "_", "a-b_C9", "a" * 128, "-_" * 64):
            with self.subTest(sid=sid):
                enter(locked(self.env, sid))
                self.assertTrue(os.path.isfile(os.path.join(self.S, sid + ".yml")))

    def test_bad_session_ids_refused(self):
        bad = ("", "a" * 129, ".", "..", "a/b", "a\x00b", "s1\n", "é", UNASSIGNED, "１", "a b")
        for sid in bad:
            with self.subTest(sid=sid):
                with self.assertRaises(SessionUnavailable) as cm:
                    enter(locked(self.env, sid))
                self.assertFalse(os.path.lexists(self.P))

    def test_bad_session_id_message_shows_escaped_id(self):
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(self.env, "a\x00b"))
        self.assertIn("'a\\x00b'", str(cm.exception))
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(self.env, ".."))
        self.assertIn("'..'", str(cm.exception))

    def test_str_subclass_session_id_refused(self):
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, Plain("s1")))
        self.assertFalse(os.path.lexists(self.P))

    def test_non_str_session_id_refused(self):
        for sid in (None, 1, b"s1", True):
            with self.subTest(sid=sid):
                with self.assertRaises(SessionUnavailable):
                    enter(locked(self.env, sid))
                self.assertFalse(os.path.lexists(self.P))


class StateFileTest(Base):
    def test_absent_state_is_empty(self):
        self.assertEqual(enter(locked(self.env, "s1")), empty("s1"))

    def test_empty_state_file_fails_closed(self):
        self.put_state(b"")
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(read_bytes(self.F), b"")

    def corrupt_cases(self):
        cases = {}
        entry = good_entry()

        def doc(top=None, **entry_kw):
            d = {"schema": "hook-session/1", "session": "s1", "dispatches": [good_entry(**entry_kw)], "surfaced": []}
            d.update(top or {})
            return yamlsub.emit(d).encode()

        cases["top unknown key"] = yamlsub.emit({**empty("s1"), "extra": 1}).encode()
        cases["entry unknown key"] = doc(extra=1)
        for k in ("schema", "session", "dispatches", "surfaced"):
            cases["missing top " + k] = yamlsub.emit({a: b for a, b in empty("s1").items() if a != k}).encode()
        for k in entry:
            d = empty("s1")
            d["dispatches"] = [{a: b for a, b in entry.items() if a != k}]
            cases["missing entry " + k] = yamlsub.emit(d).encode()
        for name, v in (("true", True), ("zero", 0), ("negative", -1), ("quoted", "1")):
            cases["depth " + name] = doc(depth=v)
        for name, v in (("63", SHA[:63]), ("65", SHA + "0"), ("upper", SHA.upper()), ("g", "g" + SHA[1:])):
            cases["sha " + name] = doc(sha=v)
        cases["session other"] = yamlsub.emit({**empty("s1"), "session": "s2"}).encode()
        cases["schema v2"] = yamlsub.emit({**empty("s1"), "schema": "hook-session/2"}).encode()
        cases["schema one"] = yamlsub.emit({**empty("s1"), "schema": 1}).encode()
        cases["dispatches scalar"] = yamlsub.emit({**empty("s1"), "dispatches": "x"}).encode()
        cases["entry is list"] = yamlsub.emit({**empty("s1"), "dispatches": [["x"]]}).encode()
        cases["surfaced int item"] = yamlsub.emit({**empty("s1"), "surfaced": [1]}).encode()
        cases["surfaced scalar"] = yamlsub.emit({**empty("s1"), "surfaced": "x"}).encode()
        cases["top list"] = b"- a\n- b\n"
        cases["top scalar"] = b"x\n"
        cases["relative worktree"] = doc(worktree="w/x")
        cases["tab indent"] = b"schema: hook-session/1\nsession: s1\ndispatches:\n\t- a\nsurfaced: []\n"
        cases["flow mapping"] = b"schema: hook-session/1\nsession: s1\ndispatches: []\nsurfaced: {a: 1}\n"
        cases["not utf-8"] = b"\xff\xfe"
        cases["huge depth text 4300"] = state_text(entries=[entry_text(depth="1" + "0" * 4299)]).encode()
        cases["huge depth text 4301"] = state_text(entries=[entry_text(depth="1" + "0" * 4300)]).encode()
        return cases

    def test_corrupt_state_fails_closed_never_resets(self):
        for name, data in self.corrupt_cases().items():
            with self.subTest(case=name):
                self.put_state(data)
                with self.assertRaises(SessionUnavailable):
                    enter(locked(self.env, "s1"))
                self.assertEqual(read_bytes(self.F), data)

    def test_valid_state_in_fixture_set_is_accepted(self):
        self.put_state(state_text(entries=[entry_text(worktree="/w/x", branch="b")], surfaced="[%s]" % DEC))
        st = enter(locked(self.env, "s1"))
        self.assertEqual(st["dispatches"], [good_entry(worktree="/w/x", branch="b")])
        self.assertEqual(st["surfaced"], [DEC])

    def test_symlinked_state_refused(self):
        self.make_sessions()
        target = os.path.join(self.tmp, "target.yml")
        text = state_text(entries=[entry_text()]).encode()
        write_bytes(target, text)
        os.symlink(target, self.F)
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(read_bytes(target), text)
        self.assertTrue(os.path.islink(self.F))

    def test_directory_state_refused(self):
        self.make_sessions()
        os.mkdir(self.F)
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertTrue(os.path.isdir(self.F))

    def test_unreadable_message_names_recovery(self):
        self.make_sessions()
        for data in (b"", b"\xff\xfe", state_text(schema="hook-session/2").encode(), b"- a\n", b"a: [1\n"):
            with self.subTest(data=data):
                self.put_state(data)
                self.check_message(self.F)
        os.unlink(self.F)
        os.mkdir(self.F)
        self.check_message(self.F)
        os.rmdir(self.F)
        target = os.path.join(self.tmp, "t.yml")
        write_bytes(target, state_text().encode())
        os.symlink(target, self.F)
        self.check_message(self.F)

    def check_message(self, path):
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(self.env, "s1"))
        msg = str(cm.exception)
        self.assertIn("the session state file %s is unreadable (" % path, msg)
        self.assertIn("start a new session (SessionStart moves it aside)", msg)
        self.assertIn("rm '%s'" % path, msg)
        self.assertTrue(msg.endswith("rm '%s'" % path))
        return msg

    def test_unreadable_message_carries_the_reason(self):
        self.make_sessions()
        self.put_state(b"a: [1\n")
        with self.assertRaises(yamlsub.YamlError) as ye:
            yamlsub.load(self.F, self.F)
        self.assertIn("(%s)" % ye.exception, self.check_message(self.F))
        self.put_state(state_text(sid="s2"))
        self.assertIn("(session: must be 's1')", self.check_message(self.F))
        self.put_state(b"")
        self.assertIn("(state: must be a mapping)", self.check_message(self.F))
        self.put_state(yamlsub.emit({**empty("s1"), "session": "s2", "extra": 1}))
        self.assertIn("(session: must be 's1'; extra: unknown key)", self.check_message(self.F))

    def test_unreadable_message_quotes_single_quote_in_path(self):
        P = os.path.join(self.tmp, "it's")
        env = {"CLAUDE_PLUGIN_DATA": P}
        os.makedirs(os.path.join(P, "sessions"))
        F = os.path.join(P, "sessions", "s1.yml")
        write_bytes(F, b"")
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(env, "s1"))
        msg = str(cm.exception)
        self.assertIn("rm '" + F.replace("'", "'\\''") + "'", msg)
        self.assertIn("the session state file %s is unreadable (" % F, msg)


class WriteTest(Base):
    def test_invalid_state_not_written(self):
        base = state_text(entries=[entry_text()]).encode()

        def depth_zero(st):
            st["dispatches"][0]["depth"] = 0

        def extra_key(st):
            st["extra"] = 1

        def upper_sha(st):
            st["dispatches"][0]["sha"] = SHA.upper()

        for name, mutate in (("depth", depth_zero), ("key", extra_key), ("sha", upper_sha)):
            with self.subTest(case=name):
                self.put_state(base)
                with self.assertRaises(SessionUnavailable):
                    with locked(self.env, "s1") as st:
                        mutate(st)
                self.assertEqual(read_bytes(self.F), base)
                self.assertEqual(sorted(os.listdir(self.S)), ["s1.lock", "s1.yml"])

    def test_unemittable_state_not_written(self):
        base = state_text(entries=[entry_text()]).encode()

        def huge(st):
            st["dispatches"][0]["depth"] = 10 ** 4301

        def a_set(st):
            st["surfaced"].append({1})

        for name, mutate in (("huge", huge), ("set", a_set)):
            with self.subTest(case=name):
                self.put_state(base)
                with self.assertRaises(SessionUnavailable):
                    with locked(self.env, "s1") as st:
                        mutate(st)
                self.assertEqual(read_bytes(self.F), base)

    def test_leftover_tmp_replaced(self):
        self.make_sessions()
        tmp = self.F + ".tmp"
        write_bytes(tmp, b"crash leftover " * 1000)
        with locked(self.env, "s1") as st:
            add_dispatch(st, SHA, "implementer", 1, "session")
        self.assertFalse(os.path.lexists(tmp))
        self.assertEqual(live_total(enter(locked(self.env, "s1"))), 1)

    def test_tmp_symlink_refused(self):
        self.make_sessions()
        outside = os.path.join(self.tmp, "outside")
        write_bytes(outside, b"keep")
        os.symlink(outside, self.F + ".tmp")
        with self.assertRaises(SessionUnavailable):
            with locked(self.env, "s1") as st:
                add_dispatch(st, SHA, "implementer", 1, "session")
        self.assertEqual(read_bytes(outside), b"keep")
        self.assertFalse(os.path.lexists(self.F))

    def test_body_error_not_written(self):
        base = state_text(entries=[entry_text()]).encode()
        self.put_state(base)
        err = ValueError("boom")
        with self.assertRaises(ValueError) as cm:
            with locked(self.env, "s1") as st:
                add_dispatch(st, SHA2, "implementer", 1, "session")
                raise err
        self.assertIs(cm.exception, err)
        self.assertEqual(read_bytes(self.F), base)
        enter(locked(self.env, "s1", timeout_s=0))

    def test_body_interrupt_not_written(self):
        base = state_text(entries=[entry_text()]).encode()
        self.put_state(base)
        with self.assertRaises(KeyboardInterrupt):
            with locked(self.env, "s1") as st:
                add_dispatch(st, SHA2, "implementer", 1, "session")
                raise KeyboardInterrupt()
        self.assertEqual(read_bytes(self.F), base)
        enter(locked(self.env, "s1", timeout_s=0))

    @unittest.skipUnless(hasattr(builtins, "BaseExceptionGroup"), "BaseExceptionGroup is absent on 3.9")
    def test_exception_group_not_written(self):
        base = state_text(entries=[entry_text()]).encode()
        self.put_state(base)
        for group in (builtins.ExceptionGroup("g", [ValueError()]),
                      builtins.BaseExceptionGroup("g", [KeyboardInterrupt()])):
            with self.subTest(group=type(group).__name__):
                with self.assertRaises(BaseException) as cm:
                    with locked(self.env, "s1") as st:
                        add_dispatch(st, SHA2, "implementer", 1, "session")
                        raise group
                self.assertIs(cm.exception, group)
                self.assertEqual(read_bytes(self.F), base)
                enter(locked(self.env, "s1", timeout_s=0))

    def test_huge_depth_same_on_both(self):
        for n in (4299, 4300):
            with self.subTest(power=n):
                with self.assertRaises(SessionUnavailable):
                    with locked(self.env, "s1") as st:
                        add_dispatch(st, SHA, "implementer", 10 ** n, "session")
                self.assertFalse(os.path.lexists(self.F))
        for digits in (4300, 4301):
            with self.subTest(digits=digits):
                data = state_text(entries=[entry_text(depth="1" + "0" * (digits - 1))]).encode()
                self.put_state(data)
                with self.assertRaises(SessionUnavailable):
                    enter(locked(self.env, "s1"))
                self.assertEqual(read_bytes(self.F), data)

    def test_unicode_version_independent(self):
        P = os.path.join(self.tmp, "d" + UNASSIGNED)
        env = {"CLAUDE_PLUGIN_DATA": P}
        u = UNASSIGNED
        with locked(env, "s1") as st:
            add_dispatch(st, SHA, "r" + u, 1, "p" + u, "/w/" + u, "b" + u)
        with locked(env, "s1") as st:
            self.assertEqual(st["dispatches"], [good_entry(role="r" + u, parent="p" + u, worktree="/w/" + u,
                                                           branch="b" + u)])
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(env, u))
        # the id is shown escaped by the fixed print table (the same text on every interpreter)
        self.assertIn("session id '\\U0001f6dd' is not valid", str(cm.exception))
        self.assertFalse(os.path.lexists(os.path.join(P, "sessions", u + ".yml")))
        with open(session.__file__) as f:
            source = f.read()
        for banned in (".lower(", "casefold", "isprintable", "unicodedata"):
            self.assertNotIn(banned, source)


class LockTest(Base):
    def test_lock_timeout(self):
        enter(locked(self.env, "s1"))
        self.hold_lock()
        t0 = time.monotonic()
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1", timeout_s=1))
        elapsed = time.monotonic() - t0
        self.assertTrue(1 <= elapsed < 3, elapsed)

    def test_killed_holder_releases(self):
        enter(locked(self.env, "s1"))
        proc = self.hold_lock()
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1", timeout_s=0))
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        enter(locked(self.env, "s1", timeout_s=0))

    def test_lock_symlink_refused(self):
        self.make_sessions()
        outside = os.path.join(self.tmp, "outside")
        os.symlink(outside, self.K)
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertFalse(os.path.lexists(outside))
        write_bytes(outside, b"keep")
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(read_bytes(outside), b"keep")

    def test_lock_directory_refused(self):
        self.make_sessions()
        os.mkdir(self.K)
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertTrue(os.path.isdir(self.K))

    def test_lock_released_on_every_path(self):
        self.put_state(state_text(entries=[entry_text()]))

        def clean(st):
            pass

        def invalid(st):
            st["extra"] = 1

        def unemittable(st):
            st["dispatches"][0]["depth"] = 10 ** 4301

        def raises(st):
            raise ValueError("x")

        def interrupt(st):
            raise KeyboardInterrupt()

        enter(locked(self.env, "s1"))
        before = fd_count()
        for name, body, exc in (("clean", clean, None), ("invalid", invalid, SessionUnavailable),
                                ("unemittable", unemittable, SessionUnavailable), ("raises", raises, ValueError),
                                ("interrupt", interrupt, KeyboardInterrupt)):
            with self.subTest(path=name):
                try:
                    with locked(self.env, "s1") as st:
                        body(st)
                except BaseException as e:
                    self.assertIsNotNone(exc)
                    self.assertIs(type(e), exc)
                else:
                    self.assertIsNone(exc)
                enter(locked(self.env, "s1", timeout_s=0))
                self.assertEqual(fd_count(), before)
        self.put_state(b"")
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1"))
        self.assertEqual(fd_count(), before)

    def test_zero_timeout_single_try(self):
        enter(locked(self.env, "s1"))
        self.hold_lock()
        t0 = time.monotonic()
        before = fd_count()
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1", timeout_s=0))
        self.assertLess(time.monotonic() - t0, 0.9)
        self.assertEqual(fd_count(), before)

    def test_nested_same_id_times_out(self):
        with locked(self.env, "s1"):
            with self.assertRaises(SessionUnavailable):
                enter(locked(self.env, "s1", timeout_s=0))
        enter(locked(self.env, "s1", timeout_s=0))

    def test_parallel_writers_lose_nothing(self):
        script = self.script("writer.py", WRITER)
        procs = [subprocess.Popen([sys.executable, script, ROOT, self.P, tag], stdin=subprocess.DEVNULL)
                 for tag in ("a", "b")]
        for p in procs:
            self.assertEqual(p.wait(), 0)
        final = enter(locked(self.env, "s1"))
        self.assertEqual(live_total(final), 100)
        roles = sorted(e["role"] for e in final["dispatches"])
        self.assertEqual(roles, sorted(tag + str(n) for tag in ("a", "b") for n in range(50)))
        self.assertEqual(live_children(final, "a"), 50)


class OsErrorTest(Base):
    """Rows E9, K9, W9, K10 and F-6: real filesystem conditions, never a raw OSError and never a hang."""

    def alarm(self, seconds=30):
        def boom(signum, frame):
            raise AssertionError("hung")

        old = signal.signal(signal.SIGALRM, boom)
        signal.alarm(seconds)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        self.addCleanup(signal.alarm, 0)

    def make_socket(self, directory, name):
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        old = os.getcwd()
        os.chdir(directory)
        try:
            sock.bind(name)
        finally:
            os.chdir(old)

    def can_lock(self, path):
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_real_os_errors_are_unavailable(self):
        # lstat(F) EACCES: another process holds the lock; while locked() polls, S loses its search bit
        self.use("e1")
        self.put_state(state_text())
        self.addCleanup(os.chmod, self.S, 0o700)
        proc = self.hold_lock()
        box = {}

        def run():
            try:
                enter(locked(self.env, "s1", timeout_s=60))
            except BaseException as e:
                box["error"] = e

        fds = fd_count()
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 30
        while fd_count() < fds + 2 and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)  # bounded wait for the thread's two descriptors: the directory and the lock file
        self.assertGreaterEqual(fd_count(), fds + 2)
        os.chmod(self.S, 0o600)
        proc.kill()
        proc.wait()
        thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(box.get("error"), SessionUnavailable)
        self.assertIn("Permission denied", str(box["error"]))
        self.assertIn(self.F, str(box["error"]))
        os.chmod(self.S, 0o700)
        # rename(F) EACCES: reset has to move a corrupt file aside in a directory that is no longer writable
        self.use("e2")
        self.put_state(b"\xff")
        write_bytes(self.K, b"")
        os.chmod(self.K, 0o600)
        self.addCleanup(os.chmod, self.S, 0o700)
        os.chmod(self.S, 0o500)
        with self.assertRaises(SessionUnavailable) as cm:
            reset(self.env, "s1")
        self.assertIn("Permission denied", str(cm.exception))
        self.assertIn(self.F, str(cm.exception))
        os.chmod(self.S, 0o700)
        self.assertEqual(read_bytes(self.F), b"\xff")
        # the same reset when S has no search bit at all: the unreadable file cannot be moved aside either
        os.chmod(self.S, 0o600)
        with self.assertRaises(SessionUnavailable) as cm:
            reset(self.env, "s1")
        self.assertIn("Permission denied", str(cm.exception))
        os.chmod(self.S, 0o700)
        self.assertEqual(read_bytes(self.F), b"\xff")
        # flock ENOTSUP (macOS) or a refused file kind: a FIFO as the lock file
        self.use("e3")
        self.make_sessions()
        os.mkfifo(self.K)
        self.alarm()
        t0 = time.monotonic()
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(self.env, "s1"))
        self.assertLess(time.monotonic() - t0, 2)  # refused at once, not after the 10 s lock timeout
        self.assertIn(self.K, str(cm.exception))
        self.assertNotIn("held by another process", str(cm.exception))
        self.assertFalse(os.path.lexists(self.F))

    def test_lock_poll_sleeps(self):
        self.make_sessions()
        self.hold_lock()
        cpu, t0 = time.process_time(), time.monotonic()
        with self.assertRaises(SessionUnavailable):
            enter(locked(self.env, "s1", timeout_s=2))
        self.assertGreaterEqual(time.monotonic() - t0, 2)
        self.assertLess(time.process_time() - cpu, 0.1)

    def test_tmp_path_kinds_fail_closed(self):
        self.alarm()
        for kind in ("directory", "fifo", "socket"):
            with self.subTest(kind=kind):
                self.use("w" + kind)
                self.make_sessions()
                tmp = self.F + ".tmp"
                if kind == "directory":
                    os.mkdir(tmp)
                elif kind == "fifo":
                    os.mkfifo(tmp)
                else:
                    self.make_socket(self.S, "s1.yml.tmp")
                before = fd_count()
                with self.assertRaises(SessionUnavailable):
                    with locked(self.env, "s1", timeout_s=1) as st:
                        add_dispatch(st, SHA, "implementer", 1, "session")
                self.assertEqual(fd_count(), before)
                self.can_lock(self.K)
                self.assertFalse(os.path.lexists(self.F))
                self.assertTrue(os.path.lexists(tmp))

    def test_tmp_fifo_with_reader_is_refused(self):
        self.alarm()
        self.make_sessions()
        os.mkfifo(self.F + ".tmp")
        reader = os.open(self.F + ".tmp", os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, reader)
        with self.assertRaises(SessionUnavailable) as cm:
            with locked(self.env, "s1", timeout_s=1) as st:
                add_dispatch(st, SHA, "implementer", 1, "session")
        self.assertIn("not a regular file", str(cm.exception))
        self.assertFalse(os.path.lexists(self.F))
        self.assertEqual(os.read(reader, 10), b"")  # nothing was written into the FIFO

    def test_fifo_fed_by_a_writer_is_not_state(self):
        """R2-1: a FIFO at F with a valid state queued and a writer present must not be read as the state."""
        self.alarm()
        self.make_sessions()
        os.mkfifo(self.F)
        writer = os.open(self.F, os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, writer)
        os.write(writer, state_text(surfaced="[%s]" % DEC).encode())
        with self.assertRaises(SessionUnavailable) as cm:
            enter(locked(self.env, "s1", timeout_s=1))
        self.assertIn("not a regular file", str(cm.exception))
        self.assertTrue(stat.S_ISFIFO(os.lstat(self.F).st_mode))
        moved = reset(self.env, "s1")  # unreadable: moved aside whole, its content never reaches the new state
        self.assertTrue(stat.S_ISFIFO(os.lstat(moved).st_mode))
        self.assertEqual(enter(locked(self.env, "s1"))["surfaced"], [])

    def test_sessions_path_kinds_fail_closed(self):
        """R2-2: a FIFO or a socket at S (and at P) is refused at once, never opened blocking."""
        self.alarm()
        for kind in ("fifo", "socket"):
            for where in ("S", "P"):
                with self.subTest(kind=kind, where=where):
                    self.use("%s%s" % (kind, where))
                    if where == "S":
                        os.makedirs(self.P)
                        path, parent, name = self.S, self.P, "sessions"
                    else:
                        path, parent, name = self.P, self.tmp, os.path.basename(self.P)
                    if kind == "fifo":
                        os.mkfifo(path)
                    else:
                        self.make_socket(parent, name)
                    before = fd_count()
                    t0 = time.monotonic()
                    with self.assertRaises(SessionUnavailable):
                        enter(locked(self.env, "s1", timeout_s=1))
                    with self.assertRaises(SessionUnavailable):
                        reset(self.env, "s1", timeout_s=1)
                    self.assertLess(time.monotonic() - t0, 3)
                    self.assertEqual(fd_count(), before)
                    mode = os.lstat(path).st_mode
                    self.assertTrue(stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode))

    def test_fifo_and_socket_at_state_and_lock_fail_closed(self):
        self.alarm()
        for kind in ("fifo", "socket"):
            for where in ("F", "K"):
                with self.subTest(kind=kind, where=where):
                    self.use("%s%s" % (kind, where))
                    self.make_sessions()
                    path = self.F if where == "F" else self.K
                    if kind == "fifo":
                        os.mkfifo(path)
                    else:
                        self.make_socket(self.S, os.path.basename(path))
                    before = fd_count()
                    with self.assertRaises(SessionUnavailable):
                        enter(locked(self.env, "s1", timeout_s=1))
                    self.assertEqual(fd_count(), before)
                    if where == "F":
                        moved = reset(self.env, "s1")  # unreadable: moved aside whole, never opened
                        self.assertTrue(os.path.lexists(moved))
                        self.assertEqual(live_total(enter(locked(self.env, "s1"))), 0)

    def test_timeout_s_domain(self):
        for value in (0, 5):
            with self.subTest(value=value):
                self.use("t%d" % value)
                enter(locked(self.env, "s1", timeout_s=value))
                reset(self.env, "s1", timeout_s=value)
        for n, value in enumerate((-1, -(10 ** 30), 1.5, float("nan"), float("inf"), None, True, False, "1", b"1")):
            with self.subTest(value=value):
                self.use("bad%d" % n)
                with self.assertRaises(SessionUnavailable) as cm:
                    enter(locked(self.env, "s1", timeout_s=value))
                self.assertIn("timeout_s", str(cm.exception))
                with self.assertRaises(SessionUnavailable):
                    reset(self.env, "s1", timeout_s=value)
                self.assertFalse(os.path.lexists(self.P))

    def test_bad_session_id_message_exact(self):
        tail = " is not valid (1 to 128 of A-Z a-z 0-9 _ -)"
        for sid, shown in (("a/b", "'a/b'"), ("a\x00b", "'a\\x00b'"), ("a\nb", "'a\\nb'"),
                           ("a'b", "'a'b'"), ('a"b', "'a\"b'"), (UNASSIGNED, "'\\U0001f6dd'")):
            with self.subTest(sid=sid):
                with self.assertRaises(SessionUnavailable) as cm:
                    enter(locked(self.env, sid))
                self.assertEqual(str(cm.exception), "session id " + shown + tail)
                with self.assertRaises(SessionUnavailable) as cm:
                    reset(self.env, sid)
                self.assertEqual(str(cm.exception), "session id " + shown + tail)


class StateErrorsTest(unittest.TestCase):
    def test_state_errors_valid_is_empty(self):
        self.assertEqual(state_errors(empty("s1"), "s1"), [])
        full = {"schema": "hook-session/1", "session": "s1",
                "dispatches": [good_entry(worktree="/w/x", branch="b"), good_entry(depth=7)], "surfaced": [DEC]}
        self.assertEqual(state_errors(full, "s1"), [])

    def test_state_errors_exact_lists(self):
        def top(**kw):
            d = empty("s1")
            d.update(kw)
            return d

        def with_entry(**kw):
            d = empty("s1")
            d["dispatches"] = [good_entry(**kw)]
            return d

        def without(d, k):
            return {a: b for a, b in d.items() if a != k}

        cases = [
            (top(extra=1), ["extra: unknown key"]),
            (with_entry(extra=1), ["dispatches[0].extra: unknown key"]),
            (without(empty("s1"), "schema"), ["schema: missing key"]),
            (without(empty("s1"), "session"), ["session: missing key"]),
            (without(empty("s1"), "dispatches"), ["dispatches: missing key"]),
            (without(empty("s1"), "surfaced"), ["surfaced: missing key"]),
            (top(schema="hook-session/2"), ["schema: must be 'hook-session/1'"]),
            (top(schema=1), ["schema: must be 'hook-session/1'"]),
            (top(session="s2"), ["session: must be 's1'"]),
            (top(dispatches="x"), ["dispatches: must be a list"]),
            (top(dispatches=[["x"]]), ["dispatches[0]: must be a mapping"]),
            (top(surfaced=[1]), ["surfaced[0]: must be a str"]),
            (top(surfaced=[DEC, 1]), ["surfaced[1]: must be a str"]),
            (top(surfaced="x"), ["surfaced: must be a list"]),
            (with_entry(depth=True), ["dispatches[0].depth: must be an integer >= 1"]),
            (with_entry(depth=0), ["dispatches[0].depth: must be an integer >= 1"]),
            (with_entry(depth=-1), ["dispatches[0].depth: must be an integer >= 1"]),
            (with_entry(depth="1"), ["dispatches[0].depth: must be an integer >= 1"]),
            (with_entry(sha=SHA[:63]), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(sha=SHA + "0"), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(sha=SHA.upper()), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(sha="g" + SHA[1:]), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(sha=SHA + "\n"), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(sha=5), ["dispatches[0].sha: must be 64 lowercase hex digits"]),
            (with_entry(role=1), ["dispatches[0].role: must be a str"]),
            (with_entry(parent=None), ["dispatches[0].parent: must be a str"]),
            (with_entry(branch=1), ["dispatches[0].branch: must be a str"]),
            (with_entry(worktree="w/x"), ["dispatches[0].worktree: must be an absolute path or \"\""]),
            (with_entry(worktree=1), ["dispatches[0].worktree: must be an absolute path or \"\""]),
            (None, ["state: must be a mapping"]),
            ([], ["state: must be a mapping"]),
            (1, ["state: must be a mapping"]),
            ("x", ["state: must be a mapping"]),
            (True, ["state: must be a mapping"]),
        ]
        for state, want in cases:
            with self.subTest(state=state):
                self.assertEqual(state_errors(state, "s1"), want)
        entry = good_entry()
        for k in entry:
            d = empty("s1")
            d["dispatches"] = [{a: b for a, b in entry.items() if a != k}]
            with self.subTest(missing=k):
                self.assertEqual(state_errors(d, "s1"), ["dispatches[0].%s: missing key" % k])
        d = empty("s1")
        d["dispatches"] = [good_entry(), good_entry(depth=0)]
        self.assertEqual(state_errors(d, "s1"), ["dispatches[1].depth: must be an integer >= 1"])
        # several defects at once: every one reported, in the fixed order
        d = {"schema": "hook-session/1", "session": "s2", "dispatches": [good_entry(depth=0, extra=1)],
             "surfaced": [], "more": 1}
        self.assertEqual(state_errors(d, "s1"), ["session: must be 's1'",
                                                 "dispatches[0].depth: must be an integer >= 1",
                                                 "dispatches[0].extra: unknown key",
                                                 "more: unknown key"])


class ResetTest(Base):
    def test_reset_absent_writes_empty(self):
        self.assertIsNone(reset(self.env, "s1"))
        with open(self.F) as f:
            self.assertEqual(f.read(), state_text())
        self.assertEqual(os.listdir(self.S).count("s1.yml"), 1)

    def test_reset_keeps_surfaced(self):
        self.put_state(state_text(entries=[entry_text(), entry_text(sha=SHA2)], surfaced="[%s]" % DEC))
        self.assertIsNone(reset(self.env, "s1"))
        st = enter(locked(self.env, "s1"))
        self.assertTrue(st["dispatches"] == [] and st["surfaced"] == [DEC])
        self.assertEqual(sorted(os.listdir(self.S)), ["s1.lock", "s1.yml"])

    def corrupt_files(self):
        """name -> maker(path); each puts an unreadable thing at F."""
        t = os.path.join(self.tmp, "t.yml")

        def blob(data):
            return lambda p: write_bytes(p, data)

        def link(p):
            write_bytes(t, state_text(entries=[entry_text()]).encode())
            os.symlink(t, p)

        def directory(p):
            os.mkdir(p)
            write_bytes(os.path.join(p, "inner"), b"x")

        return {"yaml error": blob(b"a: [1\n\t- x\n"),
                "state_errors": blob(state_text(sid="s2").encode()),
                "not utf-8": blob(b"\xff\xfe"), "empty": blob(b""), "directory": directory, "symlink": link}

    def test_reset_moves_corrupt_file_aside_unparsed(self):
        for n, (name, make) in enumerate(self.corrupt_files().items()):
            with self.subTest(case=name):
                self.use("c%d" % n)
                self.make_sessions()
                make(self.F)
                if os.path.islink(self.F):
                    snapshot = ("link", os.readlink(self.F), read_bytes(os.path.join(self.tmp, "t.yml")))
                elif os.path.isdir(self.F):
                    snapshot = ("dir", os.listdir(self.F), read_bytes(os.path.join(self.F, "inner")))
                else:
                    snapshot = ("file", read_bytes(self.F))
                moved = reset(self.env, "s1")
                self.assertTrue(os.path.isabs(moved))
                self.assertTrue(re.match(re.escape(self.F) + r"\.corrupt-\d{8}T\d{6}\Z", moved), moved)
                if snapshot[0] == "link":
                    self.assertEqual(os.readlink(moved), snapshot[1])
                    self.assertEqual(read_bytes(os.path.join(self.tmp, "t.yml")), snapshot[2])
                elif snapshot[0] == "dir":
                    self.assertEqual(os.listdir(moved), snapshot[1])
                    self.assertEqual(read_bytes(os.path.join(moved, "inner")), snapshot[2])
                else:
                    self.assertEqual(read_bytes(moved), snapshot[1])
                with open(self.F) as f:
                    self.assertEqual(f.read(), state_text())
                self.assertFalse(os.path.islink(self.F))

    def test_reset_corrupt_name_taken(self):
        self.put_state(b"\xff\xfe")
        stamp = ".corrupt-20231114T221320"
        write_bytes(self.F + stamp, b"first")
        os.symlink(os.path.join(self.tmp, "nowhere"), self.F + stamp + "-1")  # a dangling link takes a name too
        old_tz = os.environ.get("TZ")

        def restore_tz():
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

        self.addCleanup(restore_tz)
        os.environ["TZ"] = "XYZ-5"  # local time is UTC+5: the stamp must still be UTC
        time.tzset()
        with mock.patch.object(session, "_now", return_value=1700000000.0):
            moved = reset(self.env, "s1")
            self.assertEqual(moved, self.F + stamp + "-2")
            self.assertEqual(read_bytes(moved), b"\xff\xfe")
            write_bytes(self.F, b"\xfe\xff")
            moved2 = reset(self.env, "s1")
            self.assertEqual(moved2, self.F + stamp + "-3")
            self.assertEqual(read_bytes(moved2), b"\xfe\xff")
        self.assertEqual(read_bytes(self.F + stamp), b"first")
        self.assertTrue(os.path.islink(self.F + stamp + "-1"))
        self.assertEqual(read_bytes(moved), b"\xff\xfe")

    def test_reset_never_uses_corrupt_content(self):
        class Distinct(Exception):
            pass

        marker = "# CORRUPT-MARKER\n"
        text = (marker + state_text(entries=[entry_text()], surfaced="[%s]" % DEC)).encode()
        real_text, real_parse = yamlsub._file_text, yamlsub.parse

        def file_text(data):
            if marker.encode() in data:
                raise Distinct("boom")
            return real_text(data)

        def parse(t):
            if marker in t:
                raise Distinct("boom")
            return real_parse(t)

        for target, fake in (("_file_text", file_text), ("parse", parse)):
            with self.subTest(patched=target):
                self.put_state(text)
                with mock.patch.object(yamlsub, target, side_effect=fake):
                    moved = reset(self.env, "s1")
                self.assertEqual(read_bytes(moved), text)
                self.assertEqual(yamlsub.load(self.F, "F"), empty("s1"))
                os.unlink(moved)

    def test_reset_lock_symlink_still_raises(self):
        self.make_sessions()
        write_bytes(self.F, b"\xff")
        os.symlink(os.path.join(self.tmp, "outside"), self.K)
        with self.assertRaises(SessionUnavailable):
            reset(self.env, "s1")
        self.assertEqual(os.listdir(self.S).count("s1.yml"), 1)
        self.assertEqual(len(os.listdir(self.S)), 2)
        self.assertEqual(read_bytes(self.F), b"\xff")

    def test_reset_sessions_foreign_uid_still_raises(self):
        self.make_sessions()
        write_bytes(self.F, b"\xff")
        with self.foreign_dir_uid():
            with self.assertRaises(SessionUnavailable):
                reset(self.env, "s1")
        self.assertEqual(sorted(os.listdir(self.S)), ["s1.yml"])
        self.assertEqual(read_bytes(self.F), b"\xff")

    def test_reset_lock_held_still_raises(self):
        self.put_state(b"\xff")
        self.hold_lock()
        with self.assertRaises(SessionUnavailable):
            reset(self.env, "s1", timeout_s=0)
        self.assertEqual(sorted(os.listdir(self.S)), ["s1.lock", "s1.yml"])
        self.assertEqual(read_bytes(self.F), b"\xff")

    def test_reset_bad_id_refused(self):
        for sid in ("", "a" * 129, "..", "a/b", "a\x00b", "s1\n", "é", Plain("s1"), None, 1, b"s1", True):
            with self.subTest(sid=sid):
                with self.assertRaises(SessionUnavailable):
                    reset(self.env, sid)
                self.assertFalse(os.path.lexists(self.P))


class HelpersTest(unittest.TestCase):
    def test_prompt_sha_known_values(self):
        self.assertEqual(prompt_sha(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(prompt_sha("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        # sha256 of the two bytes c3 a9 (UTF-8 for e-acute)
        self.assertEqual(prompt_sha("é"), "4a99557e4033c3539de2eb65472017cad5f9557f7a0625a09f1c3f6e2ba69c4c")
        big = prompt_sha("x" * 1000000)
        self.assertTrue(re.match(r"[0-9a-f]{64}\Z", big))

    def test_prompt_sha_bad_input(self):
        with self.assertRaises(UnicodeEncodeError):
            prompt_sha("\ud800")
        for v in (None, b"x"):
            with self.subTest(v=v):
                with self.assertRaises(TypeError):
                    prompt_sha(v)

    def test_add_dispatch_defaults(self):
        st = empty("s1")
        add_dispatch(st, SHA, "implementer", 1, "session")
        self.assertEqual(st["dispatches"], [{"sha": SHA, "role": "implementer", "depth": 1, "parent": "session",
                                             "worktree": "", "branch": ""}])
        self.assertEqual(list(st["dispatches"][0]), ["sha", "role", "depth", "parent", "worktree", "branch"])
        add_dispatch(st, SHA2, "reviewer", 2, "agent-1", "/w/x", "b")
        self.assertEqual(st["dispatches"][1], {"sha": SHA2, "role": "reviewer", "depth": 2, "parent": "agent-1",
                                               "worktree": "/w/x", "branch": "b"})

    def test_end_dispatch_cases(self):
        st = empty("s1")
        self.assertFalse(end_dispatch(st, SHA))
        self.assertEqual(st, empty("s1"))
        add_dispatch(st, SHA, "a", 1, "session")
        add_dispatch(st, SHA2, "b", 1, "session")
        add_dispatch(st, SHA, "c", 1, "session")
        before = [dict(e) for e in st["dispatches"]]
        self.assertFalse(end_dispatch(st, "0" * 64))
        self.assertEqual(st["dispatches"], before)
        self.assertTrue(end_dispatch(st, SHA))
        self.assertEqual([e["role"] for e in st["dispatches"]], ["b", "c"])
        self.assertTrue(end_dispatch(st, SHA))
        self.assertEqual([e["role"] for e in st["dispatches"]], ["b"])
        self.assertFalse(end_dispatch(st, SHA))

    def test_live_counts(self):
        st = empty("s1")
        self.assertEqual((live_total(st), live_children(st, "session")), (0, 0))
        add_dispatch(st, SHA, "a", 1, "session")
        self.assertEqual((live_total(st), live_children(st, "session"), live_children(st, "agent-1")), (1, 1, 0))
        add_dispatch(st, SHA2, "b", 2, "agent-1")
        add_dispatch(st, SHA2, "c", 2, "agent-1")
        self.assertEqual((live_total(st), live_children(st, "session"), live_children(st, "agent-1")), (3, 1, 2))

    def test_lookup_ambiguous_is_none(self):
        st = empty("s1")
        self.assertIsNone(lookup(st, SHA))
        add_dispatch(st, SHA2, "other", 1, "session")
        self.assertIsNone(lookup(st, SHA))
        add_dispatch(st, SHA, "controller", 2, "session", "/w/p/s/main", "p/s/main")
        self.assertEqual(lookup(st, SHA), ("controller", 2, "/w/p/s/main", "p/s/main"))
        add_dispatch(st, SHA, "controller", 2, "agent-1", "/w/p/s/main", "p/s/main")
        self.assertEqual(lookup(st, SHA), ("controller", 2, "/w/p/s/main", "p/s/main"))
        for kw in ({"role": "reviewer"}, {"depth": 3}, {"worktree": "/w/other"}, {"branch": "other"}):
            with self.subTest(differs=kw):
                other = {"role": "controller", "depth": 2, "worktree": "/w/p/s/main", "branch": "p/s/main"}
                other.update(kw)
                st2 = empty("s1")
                add_dispatch(st2, SHA, "controller", 2, "session", "/w/p/s/main", "p/s/main")
                add_dispatch(st2, SHA, other["role"], other["depth"], "session", other["worktree"], other["branch"])
                self.assertIsNone(lookup(st2, SHA))

    def test_lookup_carries_worktree(self):
        st = empty("s1")
        add_dispatch(st, SHA, "implementer", 3, "session", "/w/p/s/g", "p/s/g")
        self.assertEqual(lookup(st, SHA), ("implementer", 3, "/w/p/s/g", "p/s/g"))
        st2 = empty("s1")
        add_dispatch(st2, SHA, "implementer", 3, "session", "/w/p/s/g", "p/s/g")
        add_dispatch(st2, SHA, "implementer", 3, "session", "/w/p/s/h", "p/s/g")
        self.assertIsNone(lookup(st2, SHA))

    def test_mark_surfaced_once(self):
        st = empty("s1")
        self.assertTrue(mark_surfaced(st, DEC))
        self.assertEqual(st["surfaced"], [DEC])
        self.assertFalse(mark_surfaced(st, DEC))
        self.assertEqual(st["surfaced"], [DEC])
        self.assertTrue(mark_surfaced(st, "DEC-20261101-aaaa"))
        self.assertEqual(st["surfaced"], [DEC, "DEC-20261101-aaaa"])


if __name__ == "__main__":
    unittest.main()
