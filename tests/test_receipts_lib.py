"""Task 5a.2: ``gates/schemas/receipt.yml`` and ``gates/lib/receipts.py`` (plan 5196-5245; domain table 5a.2 with its
binding controller decisions D-Q1 (a) (``load`` also needs 40-hex shas and a final newline), D-Q2 (a)
(``O_NOFOLLOW | O_NONBLOCK`` and a regular-file check), PD1-PD14). Expected values are written by hand: blob ids from
git's own rule ``sha1("blob <n>\\0" + bytes)`` (and compared with ``git hash-object --no-filters``), the golden
receipt bytes in full. Receipt files read by ``load`` are written by hand, never by ``record``."""
import contextlib
import copy
import errno
import hashlib
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import unittest
from unittest import mock

from gates.lib import config, migrations, receipts, schema, yamlsub
from gates.lib.receipts import content_sha, load, record, session_problem
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, INT_LIMITS, git, make_repo, watched

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RCPT_TAG = "receipt/%d" % migrations.current_version("receipt")  # fixtures take the tag from the schema (plan P:32)
RCPT_TAGB = RCPT_TAG.encode()
SID = "3f2b8c1e-9d4a-4b7e-8f10-2a6c5d9e0b13"
HDR = ("schema: " + RCPT_TAG + "\nreads:\n")
EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
CRLF = "c30dea8a3641ea99b125d04d599d843712292759"
REMEDY = "delete it to start the session's receipts again"
RECEIPT_YML = os.path.join(schema.SCHEMAS_DIR, "receipt.yml")


def blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def row_text(p, s):
    return "  - path: %s\n    sha: %s\n" % (p, s)


def S40(c="a"):
    return c * 40


@contextlib.contextmanager
def open_hook(name, action, *, after=False, nth=1, directory=None):
    """Task 5a.2-f swap hook: wraps ``os.open`` (and ``os.close``). The ``nth`` open of the bare ``name`` made with
    ``dir_fd=`` (and, when ``directory`` is not None, with ``O_DIRECTORY`` set or clear) runs ``action()`` just before
    the real open (just after it with ``after=True``). The yielded dict counts the matching opens (``seen``), the
    firings (``fired``: a test asserts it is > 0, so a hook that never fires fails the test) and holds the descriptors
    opened and not yet closed (``live``). ``name=None`` only tracks descriptors."""
    st = {"seen": 0, "fired": 0, "live": set()}
    real_open, real_close = os.open, os.close

    def op(n, flags, *a, **k):
        fire = False
        if name is not None and n == name and "dir_fd" in k and (
                directory is None or bool(flags & os.O_DIRECTORY) == directory):
            st["seen"] += 1
            fire = st["seen"] == nth
        if fire and not after:
            st["fired"] += 1
            action()
        fd = real_open(n, flags, *a, **k)
        st["live"].add(fd)
        if fire and after:
            st["fired"] += 1
            action()
        return fd

    def cl(fd):
        st["live"].discard(fd)
        return real_close(fd)
    with mock.patch.object(receipts.os, "open", op), mock.patch.object(receipts.os, "close", cl):
        yield st


def bind_socket(at):
    """A bound AF_UNIX socket file at the path ``at`` (bound by a relative name: a socket path is limited to 104 bytes)."""
    s = socket.socket(socket.AF_UNIX)
    old = os.getcwd()
    os.chdir(os.path.dirname(at))
    try:
        s.bind(os.path.basename(at))
    finally:
        os.chdir(old)
        s.close()


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.real = os.path.realpath(self.root)
        self.cfg = config.load(self.root)
        self.rdir = self.root + "/.strict-delivery/receipts"
        self.rf = self.rdir + "/" + SID + ".yml"

    def put(self, rel, data=b"x\n", base=None):
        path = os.path.join(base or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def put_rf(self, data, session=SID):
        os.makedirs(self.rdir, exist_ok=True)
        with open(self.rdir + "/" + session + ".yml", "wb") as fh:
            fh.write(data)

    def rf_bytes(self, session=SID):
        with open(self.rdir + "/" + session + ".yml", "rb") as fh:
            return fh.read()

    def other(self):
        """A second temp directory outside the repository."""
        d = os.path.join(self.tmp, "outside")
        os.makedirs(d, exist_ok=True)
        return d

    def nothing_created(self):
        self.assertFalse(os.path.lexists(self.root + "/.strict-delivery/receipts"))


# ------------------------------------------------------------------------------------------------ the schema (SC)

class Schema(Base):
    def valid(self, value):
        return schema.validate(schema.load_schema(RECEIPT_YML), value, self.cfg)

    def with_reads(self, reads):
        return {"schema": RCPT_TAG, "reads": reads}

    def test_receipt_schema_loads(self):  # SC1
        sch = schema.load_schema(RECEIPT_YML)
        self.assertEqual((sch.kind, sch.version, sch.format), ("receipt", 1, "yaml"))
        self.assertEqual(sch.files, [{"dir": "receipts", "glob": "*.yml"}])

    def test_receipt_schema_fields_exactly(self):  # SC2
        sch = schema.load_schema(RECEIPT_YML)
        self.assertEqual(sorted(sch.fields), ["reads", "schema"])
        self.assertEqual(sorted(sch.fields["reads"]["items"]["fields"]), ["path", "sha"])

    def test_file_validates_against_receipt_schema(self):  # SC3
        self.put_rf((HDR + row_text("/r/a", S40())).encode())
        rel = ".strict-delivery/receipts/" + SID + ".yml"
        value = yamlsub.load(self.root + "/" + rel, rel)
        self.assertEqual(schema.validate(schema.load_schema(RECEIPT_YML), value, self.cfg), [])

    def test_receipt_schema_tag(self):  # SC4
        for tag in ("receipt/0", "Receipt/1", "receipt/1 ", "receipt/01", "decision/1", None, 1):
            with self.subTest(tag=tag):
                errs = self.valid({"schema": tag, "reads": []})
                self.assertEqual(len(errs), 1)
                self.assertTrue(errs[0].startswith("schema: expected receipt/1, got "), errs)
        self.assertEqual(self.valid({"schema": "receipt/2", "reads": []}),
                         ["schema: expected receipt/1, got receipt/2; run /strict-delivery:upgrade"])
        self.assertEqual(self.valid({"reads": []}), ["schema: expected receipt/1, got (missing)"])

    def test_receipt_schema_unknown_top_key(self):  # SC5
        for key in ("lines", "extra", "read"):
            with self.subTest(key=key):
                self.assertEqual(self.valid({"schema": RCPT_TAG, "reads": [], key: 3}), [key + ": unknown key"])
        self.assertEqual(self.valid({"schema": RCPT_TAG, "Reads": []}),
                         ["reads: required key is missing", "Reads: unknown key"])

    def test_receipt_schema_reads_type(self):  # SC6
        self.assertEqual(self.valid({"schema": RCPT_TAG}), ["reads: required key is missing"])
        self.assertEqual(self.valid(self.with_reads(None)), ["reads: must not be null"])
        self.assertEqual(self.valid(self.with_reads([])), [])
        for v in ("", {}, {"a": 1}, "x", 3, True):
            with self.subTest(v=v):
                self.assertEqual(self.valid(self.with_reads(v)), ["reads: must be a list"])

    def test_receipt_schema_row_type(self):  # SC7
        for v in ("x", 3, ["a"]):
            with self.subTest(v=v):
                self.assertEqual(self.valid(self.with_reads([v])), ["reads.0: must be a mapping"])
        self.assertEqual(self.valid(self.with_reads([None])), ["reads.0: must not be null"])

    def test_receipt_schema_row_keys(self):  # SC8
        ok = {"path": "/a", "sha": "abcdef1"}
        self.assertEqual(self.valid(self.with_reads([{"sha": "abcdef1"}])), ["reads.0.path: required key is missing"])
        self.assertEqual(self.valid(self.with_reads([{"path": "/a"}])), ["reads.0.sha: required key is missing"])
        self.assertEqual(self.valid(self.with_reads([{}])), ["reads.0.path: required key is missing",
                                                            "reads.0.sha: required key is missing"])
        for key in ("lines", "time", "Path", "SHA"):
            with self.subTest(key=key):
                self.assertEqual(self.valid(self.with_reads([dict(ok, **{key: "x"})])), ["reads.0.%s: unknown key" % key])

    def test_receipt_schema_path_value(self):  # SC9
        for v in ("", 3, True, ["a"], {"a": 1}):
            with self.subTest(v=v):
                self.assertEqual(self.valid(self.with_reads([{"path": v, "sha": "abcdef1"}])),
                                 ["reads.0.path: must be a non-empty string"])
        self.assertEqual(self.valid(self.with_reads([{"path": None, "sha": "abcdef1"}])),
                         ["reads.0.path: must not be null"])
        for v in (" ", "a.txt", "é", "a\nb", "x" * 5000):
            with self.subTest(v=v):
                self.assertEqual(self.valid(self.with_reads([{"path": v, "sha": "abcdef1"}])), [])

    def test_receipt_schema_sha_value(self):  # SC10
        for v in ("abcdef1", "a" * 40, "0123456789abcdef0123456789abcdef01234567"):
            with self.subTest(ok=v):
                self.assertEqual(self.valid(self.with_reads([{"path": "/a", "sha": v}])), [])
        bad = ("abcdef", "a" * 41, "A" * 40, "0x" + "a" * 38, 1234567, "", "g" * 40, "٣" * 40, "a" * 40 + "\n")
        for v in bad:
            with self.subTest(bad=v):
                self.assertEqual(self.valid(self.with_reads([{"path": "/a", "sha": v}])),
                                 ["reads.0.sha: must be 7 to 40 lowercase hex digits"])
        self.assertEqual(self.valid(self.with_reads([{"path": "/a", "sha": None}])), ["reads.0.sha: must not be null"])

    def test_short_sha_passes_schema_alone(self):  # SC11
        self.assertEqual(self.valid(self.with_reads([{"path": "/r/a", "sha": "3b18e51"}])), [])

    def test_receipt_schema_duplicates(self):  # SC12
        row = {"path": "/a", "sha": "abcdef1"}
        self.assertEqual(self.valid(self.with_reads([row, dict(row)])), [])
        for text in (("schema: " + RCPT_TAG + "\nschema: " + RCPT_TAG + "\nreads: []\n"),
                     HDR + "  - path: /a\n    sha: abcdef1\n    sha: abcdef1\n"):
            with self.subTest(text=text):
                with self.assertRaises(yamlsub.YamlError):
                    yamlsub.parse(text)

    def test_receipt_schema_entries_of(self):  # SC13
        self.put_rf(b"x")
        self.put_rf(b"x", "other")
        self.put(".strict-delivery/receipts/skip.txt", b"x")
        sch = schema.load_schema(RECEIPT_YML)
        got = schema.entries_of(sch, self.root, self.cfg)
        self.assertEqual([os.path.basename(g if type(g) is str else g[0]) for g in got], sorted(["other.yml", SID + ".yml"]))

    def test_receipt_schema_bom_crlf(self):  # SC14
        body = (HDR + row_text("/r/a", S40())).encode()
        for data in (b"\xef\xbb\xbf" + body, body.replace(b"\n", b"\r\n")):
            with self.subTest(data=data[:4]):
                self.put_rf(data)
                self.assertEqual(load(self.root, self.cfg, SID), [{"path": "/r/a", "sha": S40()}])

    def test_schema_dir_scans_clean_with_receipt(self):  # SC15
        loaded, problems = schema.scan_dir()
        self.assertEqual(problems, [])
        self.assertIn("receipt", [getattr(s, "kind", s) for s in (loaded.values() if hasattr(loaded, "values") else loaded)])

    def test_check_schema_ignores_receipts(self):  # SC16
        self.put_rf((HDR + "  - path: /r/a\n    sha: 3b18").encode())
        env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema"], cwd=self.root, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode()
        self.assertEqual(p.returncode, 0, out + p.stderr.decode())
        self.assertNotIn("schema.receipt", out)

    def test_receipt_declares_no_kind(self):  # SC18
        from gates import producers
        from gates.tools import receipt_cli
        self.assertEqual(getattr(receipts, "PRODUCES", ()), ())
        self.assertEqual(getattr(receipt_cli, "PRODUCES", ()), ())
        self.assertNotIn("gates.lib.receipts", producers.PRODUCER_MODULES)
        self.assertNotIn("gates.tools.receipt_cli", producers.PRODUCER_MODULES)


# ------------------------------------------------------------------------------------------------ session keys (SK)

class SessionKeys(unittest.TestCase):
    def test_session_re_literal(self):  # SK1
        self.assertEqual(receipts.SESSION_RE, "[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
        self.assertIs(type(receipts.SESSION_RE), str)

    def test_session_valid_keys(self):  # SK2, SK3
        for k in (SID, SID.upper(), "3f2b8c1e9d4a4b7e8f102a6c5d9e0b13", "a", "0", "Z", "a-", "a_b", "a-b_c-1", "9" * 128):
            with self.subTest(k=k):
                self.assertEqual(session_problem(k), "")

    def test_session_refused_keys(self):  # SK4, SK5, SK6
        for k in ("", "../x", "a/b", "/a", "a/", "a\\b", "x/../y", ".", "..", "a.b", "a.yml", ".hidden", "a."):
            with self.subTest(k=k):
                self.assertNotEqual(session_problem(k), "")

    def test_session_length_boundary(self):  # SK7
        self.assertEqual(session_problem("a" * 127), "")
        self.assertEqual(session_problem("a" * 128), "")
        self.assertNotEqual(session_problem("a" * 129), "")
        self.assertNotEqual(session_problem("9" * 129), "")

    def test_session_very_long(self):  # SK8, VN1
        for n in (4300, 4301, 10 ** 6):
            with self.subTest(n=n):
                self.assertNotEqual(session_problem("9" * n), "")
        self.assertNotEqual(session_problem("a" * 10 ** 6), "")

    def test_session_non_ascii(self):  # SK9, VN2
        for k in ("é", "ａ", "٣", "Ⱟ", "K", "﻿a", "a​", "ǅ", "ࡰ", "\U0001fae8"):
            with self.subTest(k=k):
                self.assertNotEqual(session_problem(k), "")

    def test_session_whitespace_controls(self):  # SK10
        for k in (" a", "a ", "a\n", "\na", "a\r", "a\t", "a\x00", "a\x1b", "a b"):
            with self.subTest(k=k):
                self.assertNotEqual(session_problem(k), "")

    def test_session_leading_punct(self):  # SK11
        for k in ("-a", "_a", "--help", "-", "_"):
            with self.subTest(k=k):
                self.assertNotEqual(session_problem(k), "")

    def test_session_non_str(self):  # SK12
        for k in (None, 3, True, 1.5, b"a", ["a"], {"a": 1}, ("a",), object()):
            with self.subTest(k=k):
                self.assertEqual(session_problem(k), "session: must be a string")

    def test_session_str_subclass(self):  # SK13
        class S(str):
            pass

        class Liar(str):
            def __eq__(self, o):
                raise AssertionError("method ran")

            __hash__ = str.__hash__

            def __str__(self):
                raise AssertionError("method ran")

            def __len__(self):
                raise AssertionError("method ran")

            def __getitem__(self, i):
                raise AssertionError("method ran")

        for k in (S("a"), Liar("a")):
            with self.subTest(k=type(k).__name__):
                self.assertEqual(session_problem(k), "session: must be a string")

    def test_session_problem_returns_str(self):  # SK14
        for k in ("a", "", None, 3, "../x", "a" * 129):
            self.assertIs(type(session_problem(k)), str)

    def test_session_case_variants_valid(self):  # SK15
        for k in ("A", "a", SID, SID.upper()):
            self.assertEqual(session_problem(k), "")

    def test_session_device_names(self):  # SK16
        for k in ("CON", "NUL"):
            self.assertEqual(session_problem(k), "")
        for k in ("~", "a~1"):
            self.assertNotEqual(session_problem(k), "")

    def test_session_problem_text(self):  # SK17
        want = "session: must be 1 to 128 characters, A-Z a-z 0-9 _ -, starting with a letter or a digit"
        for k in ("", "../x", "a\n", "x\x1b[31m", "a" * 129):
            with self.subTest(k=k):
                self.assertEqual(session_problem(k), want)

    def test_session_key_is_one_component(self):  # SK18
        for k in (SID, "a", "9" * 128, "a-b_c"):
            name = k + ".yml"
            self.assertEqual(session_problem(k), "")
            self.assertEqual(os.path.basename(name), name)
            self.assertFalse(name.startswith("."))
            self.assertLessEqual(len(name.encode()), 132)


# ------------------------------------------------------------------------------------------------ content_sha (CS)

class ContentSha(Base):
    def states(self):
        """(name, bytes) for every file state the table names."""
        return [("empty", b""), ("crlf", b"a\r\nb\r\n"), ("binary", bytes(range(256))), ("nul", b"a\0b"),
                ("bom", b"\xef\xbb\xbfx"), ("x", b"x"), ("xnl", b"x\n"), ("xcr", b"x\r"),
                ("utf8", "ééé".encode()), ("large", b"z" * (3 * 1024 * 1024 + 7))]

    def test_content_sha_equals_git_hash_object(self):  # CS1
        for name, data in self.states():
            with self.subTest(name=name):
                path = self.put("f_" + name, data)
                want = git(self.root, "hash-object", "--no-filters", "--", path)
                self.assertEqual(want, blob(data))
                self.assertEqual(content_sha(path), want)

    def test_content_sha_empty_file(self):  # CS2, VN7
        self.assertEqual(content_sha(self.put("e", b"")), EMPTY)

    def test_content_sha_crlf_raw(self):  # CS3
        self.assertEqual(content_sha(self.put("c", b"a\r\nb\r\n")), CRLF)

    def test_content_sha_ignores_filters(self):  # CS4
        git(self.root, "config", "core.autocrlf", "true")
        git(self.root, "config", "filter.x.clean", "tr a b")
        self.put(".gitattributes", b"*.txt text eol=lf filter=x\n")
        path = self.put("c.txt", b"a\r\nb\r\n")
        self.assertEqual(content_sha(path), CRLF)
        self.assertEqual(content_sha(path), git(self.root, "hash-object", "--no-filters", "--", path))

    def test_content_sha_binary(self):  # CS5
        self.assertEqual(content_sha(self.put("b", bytes(range(256)))), blob(bytes(range(256))))
        self.assertEqual(content_sha(self.put("n", b"a\0b")), blob(b"a\0b"))

    def test_content_sha_bytes_exact(self):  # CS6
        for i, data in enumerate((b"\xef\xbb\xbfx", b"x", b"x\n", b"x\r")):
            self.assertEqual(content_sha(self.put("f%d" % i, data)), blob(data))

    def test_content_sha_large_file(self):  # CS7
        data = b"q" * (3 * 1024 * 1024 + 7)
        self.assertEqual(content_sha(self.put("big", data)), blob(data))

    def test_content_sha_counts_bytes(self):  # CS8
        data = "ééé".encode()
        self.assertEqual(len(data), 6)
        data = "中中中".encode()
        self.assertEqual(len(data), 9)
        self.assertEqual(content_sha(self.put("u", data)), hashlib.sha1(b"blob 9\0" + data).hexdigest())

    def test_content_sha_is_40_hex(self):  # CS9
        for data in (b"", b"abc"):
            s = content_sha(self.put("h", data))
            self.assertIs(type(s), str)
            self.assertRegex(s, "^[0-9a-f]{40}\\Z")

    def test_content_sha_missing(self):  # CS10
        p = self.root + "/nope"
        with self.assertRaises(GateError) as cm:
            content_sha(p)
        self.assertIn(p, str(cm.exception))
        self.assertIn("No such file", str(cm.exception))

    def test_content_sha_directory(self):  # CS11
        os.mkdir(self.root + "/d")
        for p in (self.root + "/d", "", "."):
            with self.subTest(p=p):
                with self.assertRaises(GateError):
                    content_sha(p)

    def test_content_sha_fifo_never_blocks(self):  # CS12
        p = self.root + "/f"
        os.mkfifo(p)
        res = []

        def go():
            try:
                content_sha(p)
            except GateError as e:
                res.append(e)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(res), 1)
        self.assertIn("not a regular file", str(res[0]))

    def test_content_sha_non_regular(self):  # CS13
        import socket
        sp = os.path.join(self.tmp, "s.sock")
        s = socket.socket(socket.AF_UNIX)
        self.addCleanup(s.close)
        s.bind(sp)
        for p in [sp] + (["/dev/null"] if os.path.exists("/dev/null") else []):
            with self.subTest(p=p):
                with self.assertRaisesRegex(GateError, "not a regular file"):
                    content_sha(p)

    def test_content_sha_refuses_symlink(self):  # CS14 (5a.2-f U-A: a symlink is refused, no longer followed)
        t = self.put("t", b"abc")
        os.symlink(t, self.root + "/lnk")
        with self.assertRaisesRegex(GateError, "/lnk: is a symlink$"):
            content_sha(self.root + "/lnk")

    def test_content_sha_dangling_and_loop(self):  # CS15, VN6
        os.symlink(self.root + "/missing", self.root + "/dang")
        os.symlink(self.root + "/l2", self.root + "/l1")
        os.symlink(self.root + "/l1", self.root + "/l2")
        for n in ("dang", "l1"):
            with self.subTest(n=n):
                with self.assertRaises(GateError):
                    content_sha(self.root + "/" + n)

    def test_content_sha_symlink_to_dir(self):  # CS16
        os.mkdir(self.root + "/d")
        os.symlink(self.root + "/d", self.root + "/ld")
        with self.assertRaisesRegex(GateError, "/ld: is a symlink$"):  # 5a.2-f U-A: the link is refused as a link
            content_sha(self.root + "/ld")

    @unittest.skipIf(os.geteuid() == 0, "uid 0 reads a mode-000 file")
    def test_content_sha_unreadable(self):  # CS17
        p = self.put("u")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o600)
        with self.assertRaisesRegex(GateError, "Permission denied"):
            content_sha(p)

    @unittest.skipIf(os.geteuid() == 0, "uid 0 searches a mode-000 directory")
    def test_content_sha_parent_unsearchable(self):  # CS18
        p = self.put("d/f")
        os.chmod(self.root + "/d", 0)
        self.addCleanup(os.chmod, self.root + "/d", 0o700)
        with self.assertRaises(GateError):
            content_sha(p)

    def test_content_sha_nul_path(self):  # CS19
        with self.assertRaisesRegex(GateError, "invalid path: ValueError"):
            content_sha(self.root + "/a\0b")

    def test_content_sha_surrogate_path(self):  # CS20
        # self.root, not /tmp: /tmp is a symlink on macOS and a symlinked component is refused (5a.2-f CS-F2)
        with self.assertRaisesRegex(GateError, "invalid path: UnicodeEncodeError"):
            content_sha(self.root + "/x\ud800")
        with self.assertRaisesRegex(GateError, "No such file"):
            content_sha(self.root + "/x\udcff")

    def test_content_sha_wrong_types(self):  # CS21
        import pathlib
        p = self.put("w")

        class S(str):
            pass
        for v in (None, 3, True, p.encode(), pathlib.Path(p), S(p), [p]):
            with self.subTest(v=type(v).__name__):
                with self.assertRaisesRegex(GateError, "path must be a string"):
                    content_sha(v)

    def test_content_sha_empty_path(self):  # CS22
        for p in ("", " "):
            with self.assertRaises(GateError):
                content_sha(p)

    def test_content_sha_relative_refused(self):  # CS23 (5a.2-f CS-F6: a relative path is no longer read from the cwd)
        p = self.put("rel.txt", b"rel")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        with self.assertRaisesRegex(GateError, "^rel.txt: path must be absolute and normalised$"):
            content_sha("rel.txt")
        self.assertEqual(content_sha(p), blob(b"rel"))

    def test_content_sha_header_length_from_bytes_read(self):  # CS24
        p = self.put("g", b"abc")
        real_read = os.read
        state = {"n": 0}

        def read(fd, n):
            state["n"] += 1
            chunk = real_read(fd, n)
            if chunk == b"":
                with open(p, "ab") as fh:  # the file grows after the last read: its size is now 6, the bytes read 3
                    fh.write(b"def")
            return chunk
        with mock.patch("gates.lib.yamlsub.os.read", read):
            got = content_sha(p)
        self.assertEqual(got, blob(b"abc"))  # the id of the bytes actually read (3), not of the size 6 a later stat gives

    def test_no_subprocess_for_blob_id(self):  # CS25, RC33
        p = self.put("n", b"n")
        with mock.patch("subprocess.Popen", side_effect=AssertionError("subprocess")):
            self.assertEqual(content_sha(p), blob(b"n"))
            self.assertEqual(record(self.root, self.cfg, SID, "n")["sha"], blob(b"n"))

    def test_content_sha_closes_descriptor(self):  # CS26
        opened, closed = [], []
        real_open, real_close = os.open, os.close

        def op(*a, **k):
            fd = real_open(*a, **k)
            opened.append(fd)
            return fd

        def cl(fd):
            closed.append(fd)
            return real_close(fd)
        p = self.put("c")
        with mock.patch("gates.lib.yamlsub.os.open", op), mock.patch("gates.lib.yamlsub.os.close", cl):
            content_sha(p)
            with mock.patch("gates.lib.yamlsub.os.read", side_effect=OSError(errno.EIO, "io")):
                with self.assertRaises(GateError):
                    content_sha(p)
            with mock.patch("gates.lib.yamlsub.os.fstat", return_value=os.stat(self.root)):
                with self.assertRaises(GateError):
                    content_sha(p)
        # 5a.2-f: a call opens "/", every directory below it and the file: one descriptor per path component, plus "/"
        self.assertEqual(len(opened), 3 * (len(p.split("/")) - 1 + 1))
        self.assertEqual(sorted(opened), sorted(closed))

    def test_content_sha_depends_on_bytes_only(self):  # CS27
        self.assertEqual(content_sha(self.put("one", b"same")), content_sha(self.put("two", b"same")))


# ------------------------------------------------------------------------------------------------ record (RC)

class Record(Base):
    def test_record_appends_path_and_blob_id(self):  # RC1, LD3, RC14
        self.put("a.txt", b"hello\n")
        row = record(self.root, self.cfg, SID, "a.txt")
        want = hashlib.sha1(b"blob 6\0hello\n").hexdigest()
        self.assertEqual(want, git(self.root, "hash-object", "--no-filters", "--", "a.txt"))
        self.assertEqual(row, {"path": self.real + "/a.txt", "sha": want})
        self.assertEqual(list(row), ["path", "sha"])
        self.assertEqual(load(self.root, self.cfg, SID), [row])

    def test_bad_session_refused(self):  # RC2
        class S(str):
            pass
        self.put("a.txt")
        for s in ("", "../x", "a/b", "x" * 129, 3, None, True, b"a", ".", "a\n", S("a"), "é"):
            with self.subTest(s=s):
                with self.assertRaisesRegex(GateError, "^session: must be"):
                    record(self.root, self.cfg, s, "a.txt")
                self.nothing_created()

    def test_record_session_checked_before_path(self):  # RC3
        with self.assertRaisesRegex(GateError, "^session: must be"):
            record(self.root, self.cfg, "../x", "nope.txt")

    def test_record_root_types(self):  # RC4
        class S(str):
            pass
        self.put("a.txt")
        for r in (None, 3, "", b"/x", ["/x"], S(self.root)):
            with self.subTest(r=r):
                with self.assertRaisesRegex(GateError, "^root must be a string$"):
                    record(r, self.cfg, SID, "a.txt")
                with self.assertRaisesRegex(GateError, "^root must be a string$"):
                    load(r, self.cfg, SID)

    def test_record_root_forms(self):  # RC5
        self.put("a.txt", b"a")
        os.mkdir(self.root + "/sub")
        link = os.path.join(self.tmp, "lnk")
        os.symlink(self.root, link)
        bare = os.path.join(self.tmp, "bare")
        os.mkdir(bare)
        self.put("b.txt", b"b", base=bare)
        row = record(link, self.cfg, SID, "a.txt")
        self.assertEqual(row["path"], self.real + "/a.txt")
        self.assertTrue(os.path.isfile(self.rf))
        self.assertEqual(record(bare, self.cfg, SID, "b.txt")["path"], os.path.realpath(bare) + "/b.txt")
        self.assertTrue(os.path.isfile(bare + "/.strict-delivery/receipts/" + SID + ".yml"))
        self.assertEqual(record(self.root + "/sub", self.cfg, SID, "../a.txt")["path"], self.real + "/a.txt")
        self.assertTrue(os.path.isfile(self.root + "/sub/.strict-delivery/receipts/" + SID + ".yml"))
        for r in (self.root + "/missing", self.root + "/a.txt"):
            with self.subTest(r=r):
                with self.assertRaises(GateError):
                    record(r, self.cfg, SID, "a.txt")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(record("work", self.cfg, "rel", "a.txt")["path"], self.real + "/a.txt")
        self.assertTrue(os.path.isfile(self.rdir + "/rel.yml"))

    def test_record_cfg_shapes(self):  # RC6
        self.put("a.txt")
        for c in (None, {}, {"paths": {}}, {"paths": {"receipts": 3}}, {"paths": {"receipts": "/abs"}},
                  {"paths": {"receipts": "../x"}}, {"paths": {"receipts": ""}}, {"paths": {"receipts": "a//b"}},
                  {"schema": "config/2", "framework_version": "0.0.0", "profile": "strict"}, []):
            with self.subTest(c=c):
                with self.assertRaisesRegex(GateError, "paths.receipts"):
                    record(self.root, c, SID, "a.txt")
                with self.assertRaisesRegex(GateError, "paths.receipts"):
                    load(self.root, c, SID)
        for rel in ("a/b/c", ".strict-delivery/receipts"):
            cfg = copy.deepcopy(self.cfg)
            cfg["paths"]["receipts"] = rel
            record(self.root, cfg, SID, "a.txt")
            self.assertTrue(os.path.isfile(self.root + "/" + rel + "/" + SID + ".yml"))

    def test_record_path_types(self):  # RC7
        import pathlib

        class S(str):
            pass
        for p in (None, 3, True, b"a", pathlib.Path("a"), ["a"], S("a")):
            with self.subTest(p=type(p).__name__):
                with self.assertRaisesRegex(GateError, "^path must be a string$"):
                    record(self.root, self.cfg, SID, p)

    def test_record_path_empty_and_dot(self):  # RC8, RC17
        os.mkdir(self.root + "/dir")
        for p in ("", ".", "./", "dir/..", "dir", self.root):
            with self.subTest(p=p):
                with self.assertRaises(GateError):
                    record(self.root, self.cfg, SID, p)
                self.nothing_created()

    def test_directory_path_refused(self):  # RC17
        os.mkdir(self.root + "/dir")
        with self.assertRaises(GateError):
            record(self.root, self.cfg, SID, "dir")
        self.nothing_created()

    def test_record_relative_joined_to_root(self):  # RC9
        self.put("a.txt", b"a")
        self.put("sub/a.txt", b"s")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)  # not the root: a cwd join would fail
        self.put("a.txt", b"WRONG", base=self.tmp)
        for p in ("a.txt", "./a.txt", "sub/../a.txt"):
            with self.subTest(p=p):
                self.assertEqual(record(self.root, self.cfg, SID, p), {"path": self.real + "/a.txt", "sha": blob(b"a")})
        self.assertEqual(record(self.root, self.cfg, SID, "sub/a.txt")["path"], self.real + "/sub/a.txt")

    def test_record_absolute_path(self):  # RC10
        self.put("a.txt", b"a")
        want = {"path": self.real + "/a.txt", "sha": blob(b"a")}
        self.assertEqual(record(self.root, self.cfg, SID, self.root + "/a.txt"), want)
        self.assertEqual(record(self.root, self.cfg, SID, self.real + "/a.txt"), want)

    def test_record_outside_repository(self):  # RC11
        p = self.put("o.txt", b"o", base=self.other())
        self.assertEqual(record(self.root, self.cfg, SID, p), {"path": os.path.realpath(p), "sha": blob(b"o")})

    def test_record_dotdot_outside(self):  # RC12
        out = self.put("outside.txt", b"o", base=self.tmp)
        self.assertEqual(record(self.root, self.cfg, SID, "../outside.txt")["path"], os.path.realpath(out))

    def test_symlink_recorded_as_real_path(self):  # RC13
        self.put("a.txt", b"a")
        os.symlink("a.txt", self.root + "/link.txt")
        os.makedirs(self.root + "/d")
        self.put("d/in.txt", b"in")
        os.symlink(self.root + "/d", self.root + "/dir_link")
        os.symlink(self.root + "/link.txt", self.root + "/chain.txt")
        out = self.put("t.txt", b"t", base=self.other())
        os.symlink(out, self.root + "/ext.txt")
        want = {"link.txt": ("/a.txt", b"a"), "dir_link/in.txt": ("/d/in.txt", b"in"), "chain.txt": ("/a.txt", b"a")}
        for p, (real, data) in want.items():
            with self.subTest(p=p):
                self.assertEqual(record(self.root, self.cfg, SID, p), {"path": self.real + real, "sha": blob(data)})
        self.assertEqual(record(self.root, self.cfg, SID, "ext.txt"), {"path": os.path.realpath(out), "sha": blob(b"t")})

    def test_record_missing_path_creates_nothing(self):  # RC16
        with self.assertRaisesRegex(GateError, "nope.txt"):
            record(self.root, self.cfg, SID, "nope.txt")
        self.nothing_created()

    def test_record_fifo_refused(self):  # RC18
        os.mkfifo(self.root + "/f")
        res = []

        def go():
            try:
                record(self.root, self.cfg, SID, "f")
            except GateError as e:
                res.append(e)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(res), 1)
        self.nothing_created()

    @unittest.skipIf(os.geteuid() == 0, "uid 0 reads a mode-000 file")
    def test_record_unreadable_refused(self):  # RC19
        p = self.put("u")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o600)
        with self.assertRaises(GateError):
            record(self.root, self.cfg, SID, "u")
        self.nothing_created()

    def test_record_crlf_raw(self):  # RC20
        self.put("c", b"a\r\nb\r\n")
        self.assertEqual(record(self.root, self.cfg, SID, "c")["sha"], CRLF)

    def test_record_empty_file(self):  # RC21
        self.put("e", b"")
        self.assertEqual(record(self.root, self.cfg, SID, "e")["sha"], EMPTY)
        self.assertEqual(len(load(self.root, self.cfg, SID)), 1)

    def test_record_binary_file(self):  # RC22
        self.put("b", bytes(range(256)))
        self.assertEqual(record(self.root, self.cfg, SID, "b")["sha"],
                         git(self.root, "hash-object", "--no-filters", "--", "b"))

    def test_awkward_names_round_trip(self):  # RC23
        names = ["a: b#c 'd\".md", " lead.md", "trail ", "h#sh", "co: lon", "q'uote", "d\"q", "back\\slash", "per%cent",
                 "at@sign", "tick`s", "am&p", "st*ar", "ex!cl", "gt>x", "pi|pe", "{brace", "[brack", "-dash", "- dash",
                 "tab\there", "é中", "\U0001fae8", "plain.md", "k: v", "? q", "x #y", "'", "\"", "- ", "---"]
        for i, n in enumerate(names):
            with self.subTest(n=n):
                self.put(n, b"v%d" % i)
                row = record(self.root, self.cfg, SID, n)
                self.assertEqual(row["path"], self.real + "/" + n)
        got = load(self.root, self.cfg, SID)
        self.assertEqual([r["path"] for r in got], [self.real + "/" + n for n in names])
        self.assertTrue(got[0]["path"].endswith("a: b#c 'd\".md"))

    def test_name_with_newline_round_trips(self):  # RC24
        for i, n in enumerate(("x\ny", "x\n\ny", "x\n")):
            with self.subTest(n=n):
                self.put(n, b"v%d" % i)
                record(self.root, self.cfg, "nl%d" % i, n)
                self.assertEqual(load(self.root, self.cfg, "nl%d" % i)[0]["path"], self.real + "/" + n)

    def test_name_with_controls_round_trips(self):  # RC25
        for i, n in enumerate(("x\ry", "x\x1b", "x\x7f", "x\x01y")):
            with self.subTest(n=n):
                self.put(n, b"v")
                record(self.root, self.cfg, "c%d" % i, n)
                self.assertEqual(load(self.root, self.cfg, "c%d" % i)[0]["path"], self.real + "/" + n)

    def test_line_separators_in_name_round_trip(self):  # RC26
        for i, n in enumerate(("x y", "x y", "x\x85y", "x\x0by", "x\x0cy", "x\x1cy")):
            with self.subTest(n=n):
                self.put(n, b"v")
                record(self.root, self.cfg, "ls%d" % i, n)
                self.assertEqual(load(self.root, self.cfg, "ls%d" % i)[0]["path"], self.real + "/" + n)

    def test_record_nul_and_surrogate_path(self):  # RC27, VN4
        for p in ("a\0b", "/tmp/x\ud800", "/tmp/x\udcff"):
            with self.subTest(p=p):
                with self.assertRaisesRegex(GateError, "^path: invalid \\(a NUL or a lone surrogate\\)$"):
                    record(self.root, self.cfg, SID, p)
                self.nothing_created()

    test_nul_refused_before_filesystem = test_record_nul_and_surrogate_path  # VN4

    def test_record_case_variants_keep_spelling(self):  # RC15
        probe = os.path.join(self.tmp, "Probe.txt")
        with open(probe, "wb") as fh:
            fh.write(b"p")
        if not os.path.exists(os.path.join(self.tmp, "pROBE.TXT")):
            self.skipTest("the temp volume is case-sensitive: two spellings name two files there")
        self.put("Case.txt", b"c")
        r1 = record(self.root, self.cfg, SID, "Case.txt")
        r2 = record(self.root, self.cfg, SID, "CASE.TXT")
        self.assertEqual(r1["path"], self.real + "/Case.txt")
        self.assertEqual(r2["path"], self.real + "/CASE.TXT")  # realpath keeps the spelling it is given
        self.assertEqual(r1["sha"], r2["sha"])
        self.assertEqual(load(self.root, self.cfg, SID), [r1, r2])

    def test_record_path_too_long(self):  # RC28
        with self.assertRaises(GateError):
            record(self.root, self.cfg, SID, "n" * 4000)
        self.nothing_created()

    def test_record_path_is_receipt_file(self):  # RC29
        self.put("a.txt")
        record(self.root, self.cfg, SID, "a.txt")
        before = self.rf_bytes()
        row = record(self.root, self.cfg, SID, self.rf)
        self.assertEqual(row, {"path": self.real + "/.strict-delivery/receipts/" + SID + ".yml", "sha": blob(before)})

    def test_record_sha_taken_once(self):  # RC30
        p = self.put("a.txt", b"one")
        real = receipts.content_sha

        def sha(path):
            got = real(path)
            with open(p, "wb") as fh:
                fh.write(b"two")
            return got
        with mock.patch.object(receipts, "content_sha", sha):
            row = record(self.root, self.cfg, SID, "a.txt")
        self.assertEqual(row["sha"], blob(b"one"))
        self.assertEqual(load(self.root, self.cfg, SID), [row])

    def test_record_return_shape(self):  # RC31
        self.put("a.txt")
        row = record(self.root, self.cfg, SID, "a.txt")
        self.assertIs(type(row), dict)
        self.assertEqual(sorted(row), ["path", "sha"])
        self.assertIs(type(row["path"]), str)
        self.assertIs(type(row["sha"]), str)

    def test_record_changes_only_receipts(self):  # RC32
        self.put("a.txt")
        before = copy.deepcopy(self.cfg)
        tree = sorted(os.listdir(self.root))
        record(self.root, self.cfg, SID, "a.txt")
        self.assertEqual(self.cfg, before)
        self.assertEqual(sorted(os.listdir(self.root)), tree)
        self.assertEqual(os.listdir(self.rdir), [SID + ".yml"])
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all"),
                         "?? .strict-delivery/receipts/%s.yml\n?? a.txt" % SID)

    def test_receipts_are_git_ignored(self):  # RD10
        with open(REPO + "/.gitignore", "rb") as fh:
            self.put(".gitignore", fh.read())
        git(self.root, "add", "--", ".gitignore")
        git(self.root, "commit", "-q", "-m", "ignore")
        self.put("a.txt")
        git(self.root, "add", "--", "a.txt")
        git(self.root, "commit", "-q", "-m", "a")
        record(self.root, self.cfg, SID, "a.txt")
        git(self.root, "check-ignore", "-q", "--", ".strict-delivery/receipts/x.yml")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_same_file_twice_two_rows(self):  # RF23
        self.put("a.txt")
        r = record(self.root, self.cfg, SID, "a.txt")
        record(self.root, self.cfg, SID, "a.txt")
        self.assertEqual(load(self.root, self.cfg, SID), [r, r])

    def test_rows_in_append_order(self):  # RF24
        rows = []
        for n in "abc":
            self.put(n, n.encode())
            rows.append(record(self.root, self.cfg, SID, n))
        self.assertEqual(load(self.root, self.cfg, SID), rows)

    def test_changed_file_new_sha(self):  # RF26
        p = self.put("a.txt", b"1")
        r1 = record(self.root, self.cfg, SID, "a.txt")
        with open(p, "wb") as fh:
            fh.write(b"2")
        r2 = record(self.root, self.cfg, SID, "a.txt")
        self.assertNotEqual(r1["sha"], r2["sha"])
        self.assertEqual(load(self.root, self.cfg, SID), [r1, r2])


# ------------------------------------------------------------------------------------------------ directory (RD)

class ReceiptsDir(Base):
    def setUp(self):
        super().setUp()
        self.put("a.txt", b"a")

    def rec(self, cfg=None, s=SID):
        return record(self.root, cfg or self.cfg, s, "a.txt")

    def test_receipts_dir_created(self):  # RD1
        self.rec()
        self.assertEqual(stat.S_IMODE(os.stat(self.rdir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.rf).st_mode), 0o600)

    def test_receipts_dir_nested_created(self):  # RD2
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["receipts"] = "a/b/c"
        self.rec(cfg)
        for p in ("a", "a/b", "a/b/c"):
            self.assertTrue(stat.S_ISDIR(os.lstat(self.root + "/" + p).st_mode))
        self.assertTrue(os.path.isfile(self.root + "/a/b/c/" + SID + ".yml"))

    def test_receipts_dir_is_file(self):  # RD3
        os.makedirs(self.root + "/.strict-delivery", exist_ok=True)
        self.put(".strict-delivery/receipts", b"keep")
        with self.assertRaisesRegex(GateError, "receipts: is not a directory"):
            self.rec()
        with open(self.rdir, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")

    def test_receipts_dir_is_symlink(self):  # RD4, RD5
        target = os.path.join(self.other(), "elsewhere")
        os.mkdir(target)
        os.symlink(target, self.rdir)
        with self.assertRaisesRegex(GateError, "is a symlink; directories must be real directories"):
            self.rec()
        self.assertEqual(os.listdir(target), [])

    def test_receipts_dir_dangling_symlink(self):  # RD5
        target = os.path.join(self.other(), "missing")
        os.symlink(target, self.rdir)
        with self.assertRaisesRegex(GateError, "is a symlink"):
            self.rec()
        self.assertFalse(os.path.exists(target))

    def test_receipts_parent_component_symlink(self):  # RD6
        target = os.path.join(self.other(), "elsewhere")
        os.mkdir(target)
        os.symlink(target, self.root + "/.strict-delivery-x")
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["receipts"] = ".strict-delivery-x/r"
        with self.assertRaisesRegex(GateError, "^\\.strict-delivery-x: is a symlink"):
            self.rec(cfg)
        os.makedirs(self.root + "/a")
        os.symlink(target, self.root + "/a/b")
        cfg["paths"]["receipts"] = "a/b/c"
        with self.assertRaisesRegex(GateError, "^a/b: is a symlink"):
            self.rec(cfg)
        self.assertEqual(os.listdir(target), [])

    @unittest.skipIf(os.geteuid() == 0, "uid 0 writes anywhere")
    def test_receipts_dir_read_only(self):  # RD7
        os.makedirs(self.rdir)
        os.chmod(self.rdir, 0o500)
        with self.assertRaisesRegex(GateError, "Permission denied"):
            self.rec()
        os.chmod(self.rdir, 0o700)
        os.rmdir(self.rdir)
        os.chmod(self.root + "/.strict-delivery", 0o500)
        self.addCleanup(os.chmod, self.root + "/.strict-delivery", 0o700)
        with self.assertRaisesRegex(GateError, "Permission denied"):
            self.rec()

    def test_receipts_dir_is_fifo(self):  # RD8
        os.mkfifo(self.rdir)
        kind, val = watched(self.rec)  # R1-1: a FIFO opened by name would block; the watchdog fails it by name
        self.assertEqual(kind, "err")
        self.assertRegex(str(val), "is not a directory")

    def test_parallel_first_creation(self):  # RD9
        procs = [subprocess.Popen([sys.executable, "-m", "gates.tools.receipt_cli", "add", "--session", SID, "--path",
                                   "a.txt", "--root", self.root], cwd=self.tmp, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1"))
                 for _ in range(20)]
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual((p.returncode, err), (0, b""), err)
        self.assertEqual(len(load(self.root, self.cfg, SID)), 20)

    def rival_between_open_and_check(self, name, rival):
        """F-20261123-rrw3: the open of the directory ``name`` has failed ENOENT (it is absent); ``rival()`` then runs
        just before the first ``_kind`` of ``name``, as a second process would between the open and the check."""
        real_kind = receipts._kind
        st = {"fired": 0}

        def kind(n, dir_fd):
            if n == name and not st["fired"]:
                st["fired"] += 1
                rival()
            return real_kind(n, dir_fd)
        return st, mock.patch.object(receipts, "_kind", kind)

    def test_dir_made_by_rival_between_open_and_check(self):  # RD9, F-20261123-rrw3
        st, patch = self.rival_between_open_and_check("receipts", lambda: os.mkdir(self.rdir, 0o700))
        with patch:
            self.rec()
        self.assertEqual(st["fired"], 1)
        self.assertEqual(self.rf_bytes(), (HDR + row_text(self.real + "/a.txt", blob(b"a"))).encode())

    def test_created_subdirectory_made_by_rival_between_open_and_check(self):  # RD9, RD2, F-20261123-rrw3
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["receipts"] = "a/b/c"
        for name in ("a", "b", "c"):  # each component of the chain, in turn
            root = os.path.join(self.tmp, "root-" + name)
            os.mkdir(root)
            self.put("a.txt", b"a", base=root)
            parts = ["a", "b", "c"]
            path = os.path.join(root, *parts[:parts.index(name) + 1])
            st, patch = self.rival_between_open_and_check(name, lambda p=path: os.mkdir(p, 0o700))
            with patch:
                record(root, cfg, SID, "a.txt")
            self.assertEqual(st["fired"], 1, name)
            with open(os.path.join(root, "a/b/c", SID + ".yml"), "rb") as fh:
                self.assertEqual(fh.read(), (HDR + row_text(os.path.realpath(root) + "/a.txt", blob(b"a"))).encode())

    def test_read_path_dir_made_by_rival_between_open_and_check(self):  # F-20261123-rrw3 (create false)
        st, patch = self.rival_between_open_and_check("receipts", lambda: os.mkdir(self.rdir, 0o700))
        with patch:
            self.assertEqual(load(self.root, self.cfg, SID), [])
        self.assertEqual(st["fired"], 1)

    def test_rival_link_or_file_between_open_and_check_refused(self):  # RD3, RD4, F-20261123-rrw3 (contradiction)
        target = os.path.join(self.other(), "elsewhere")
        os.mkdir(target)
        with self.subTest("link"):
            st, patch = self.rival_between_open_and_check("receipts", lambda: os.symlink(target, self.rdir))
            with patch, self.assertRaisesRegex(GateError, "^\\.strict-delivery/receipts: is a symlink; directories must "
                                                         "be real directories$"):
                self.rec()
            self.assertEqual((st["fired"], os.listdir(target)), (1, []))
            os.unlink(self.rdir)
        with self.subTest("file"):
            st, patch = self.rival_between_open_and_check("receipts", lambda: open(self.rdir, "wb").close())
            with patch, self.assertRaisesRegex(GateError, "^\\.strict-delivery/receipts: is not a directory$"):
                self.rec()
            self.assertEqual(st["fired"], 1)

    def test_content_sha_dir_made_by_rival_between_open_and_check(self):  # F-20261124-cjyv (_read_by_descriptor)
        path = self.real + "/rivaldir/f.txt"
        st, patch = self.rival_between_open_and_check("rivaldir", lambda: os.mkdir(self.real + "/rivaldir", 0o700))
        with patch, self.assertRaisesRegex(
                GateError, "^" + re.escape(path) + ": cannot read file \\(No such file or directory\\)$"):
            content_sha(path)
        self.assertEqual(st["fired"], 1)  # the rival's directory was opened again: the error names the FILE
        self.assertTrue(os.path.isdir(self.real + "/rivaldir"))

    def test_content_sha_rival_link_or_file_at_directory_refused(self):  # F-20261124-cjyv (contradiction)
        path = self.real + "/rivaldir/f.txt"
        target = os.path.join(self.other(), "elsewhere")
        os.mkdir(target)
        self.put("f.txt", b"x", base=target)
        with self.subTest("link"):
            st, patch = self.rival_between_open_and_check("rivaldir", lambda: os.symlink(target, self.real + "/rivaldir"))
            with patch, self.assertRaisesRegex(
                    GateError, "^" + re.escape(self.real + "/rivaldir") + ": is a symlink; directories must be real directories$"):
                content_sha(path)
            self.assertEqual(st["fired"], 1)
            os.unlink(self.real + "/rivaldir")
        with self.subTest("file"):
            st, patch = self.rival_between_open_and_check("rivaldir", lambda: open(self.real + "/rivaldir", "wb").close())
            with patch, self.assertRaisesRegex(
                    GateError, "^" + re.escape(self.real + "/rivaldir") + ": is not a directory$"):
                content_sha(path)
            self.assertEqual(st["fired"], 1)

    @unittest.skipIf(os.geteuid() == 0, "uid 0 opens anything")
    def test_unreadable_existing_dir_is_refused_not_retried(self):  # F-20261123-rrw3 (only ENOENT is retried)
        os.makedirs(self.rdir)
        os.chmod(self.rdir, 0)
        self.addCleanup(os.chmod, self.rdir, 0o700)
        with open_hook("receipts", lambda: None, directory=True) as hk, self.assertRaisesRegex(
                GateError, "^\\.strict-delivery/receipts: cannot use the receipts directory \\(Permission denied\\)$"):
            self.rec()
        self.assertEqual(hk["seen"], 1)  # one open: no second attempt

    def test_missing_dir_with_failed_check_is_refused_not_retried(self):  # F-20261123-rrw3 (only "dir" is retried)
        with open_hook("receipts", lambda: None, directory=True) as hk, mock.patch.object(
                receipts, "_kind", lambda n, d: "other"), self.assertRaisesRegex(
                GateError, "^\\.strict-delivery/receipts: cannot use the receipts directory "
                           "\\(No such file or directory\\)$"):
            self.rec()
        self.assertEqual(hk["seen"], 1)  # one open: no second attempt
        self.nothing_created()

    def test_second_miss_after_rival_is_an_error_not_a_loop(self):  # F-20261123-rrw3 (the retry is once)
        real_open = os.open

        def op(n, flags, *a, **k):
            if n == "receipts" and "dir_fd" in k:
                raise FileNotFoundError(errno.ENOENT, "No such file or directory")
            return real_open(n, flags, *a, **k)
        st, patch = self.rival_between_open_and_check("receipts", lambda: os.mkdir(self.rdir, 0o700))
        with patch, mock.patch.object(receipts.os, "open", op), self.assertRaisesRegex(
                GateError, "^\\.strict-delivery/receipts: cannot use the receipts directory \\(No such file or directory\\)$"):
            self.rec()
        self.assertEqual(st["fired"], 1)

    def test_record_recreates_directory(self):  # RD11
        self.rec()
        os.unlink(self.rf)
        os.rmdir(self.rdir)
        self.rec()
        self.assertEqual(len(load(self.root, self.cfg, SID)), 1)

    def test_receipts_dir_under_bare_root(self):  # RD12
        bare = os.path.join(self.tmp, "bare")
        os.mkdir(bare)
        self.put("f", b"f", base=bare)
        record(bare, self.cfg, SID, "f")
        self.assertTrue(os.path.isfile(bare + "/.strict-delivery/receipts/" + SID + ".yml"))


# ------------------------------------------------------------------------------------------------ the file (RF)

class ReceiptFile(Base):
    def setUp(self):
        super().setUp()
        self.put("a.txt", b"a")
        self.sha_a = blob(b"a")
        self.arow = row_text(self.real + "/a.txt", self.sha_a)

    def rec(self, s=SID):
        return record(self.root, self.cfg, s, "a.txt")

    def test_parallel_appends_keep_every_row(self):  # RF1, LD25
        for i in range(20):
            self.put("f%d" % i, b"c%d" % i)
        env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1")
        procs = [subprocess.Popen([sys.executable, "-m", "gates.tools.receipt_cli", "add", "--session", SID, "--path",
                                   "f%d" % i, "--root", self.root], cwd=self.tmp, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env) for i in range(20)]
        for p in procs:
            _, err = p.communicate(timeout=60)
            self.assertEqual((p.returncode, err), (0, b""), err)
        rows = load(self.root, self.cfg, SID)
        self.assertEqual(sorted(r["path"] for r in rows), sorted(self.real + "/f%d" % i for i in range(20)))
        self.assertEqual(self.rf_bytes().count(b"schema: receipt/1"), 1)
        sch = schema.load_schema(RECEIPT_YML)
        self.assertEqual(schema.validate(sch, yamlsub.load(self.rf, "x"), self.cfg), [])

    def test_parallel_same_file(self):  # RF2
        env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1")
        procs = [subprocess.Popen([sys.executable, "-m", "gates.tools.receipt_cli", "add", "--session", SID, "--path",
                                   "a.txt", "--root", self.root], cwd=self.tmp, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env) for _ in range(20)]
        for p in procs:
            _, err = p.communicate(timeout=60)
            self.assertEqual((p.returncode, err), (0, b""), err)
        self.assertEqual(load(self.root, self.cfg, SID),
                         [{"path": self.real + "/a.txt", "sha": self.sha_a}] * 20)

    def test_header_decided_under_lock(self):  # RF3
        real_flock = receipts.fcntl.flock
        state = {"n": 0}

        def flock(fd, op):
            state["n"] += 1
            if state["n"] == 1:  # a rival writes the header and a row before this call gets the lock
                with open(self.rf, "ab") as fh:
                    fh.write((HDR + row_text("/r/rival", S40("b"))).encode())
            return real_flock(fd, op)
        with mock.patch.object(receipts.fcntl, "flock", flock):
            self.rec()
        self.assertEqual(self.rf_bytes(), (HDR + row_text("/r/rival", S40("b")) + self.arow).encode())
        self.assertEqual(len(load(self.root, self.cfg, SID)), 2)

    def test_empty_file_gets_header(self):  # RF4
        self.put_rf(b"")
        self.rec()
        self.assertEqual(self.rf_bytes(), (HDR + self.arow).encode())

    def test_header_present_row_appended(self):  # RF5
        self.put_rf((HDR + row_text("/r/x", S40("c"))).encode())
        self.rec()
        self.assertEqual(self.rf_bytes(), (HDR + row_text("/r/x", S40("c")) + self.arow).encode())

    def test_absent_file_created_with_header(self):  # RF6, RF7
        self.rec()
        self.assertEqual(self.rf_bytes(),
                         ("schema: receipt/1\nreads:\n  - path: " + self.real + "/a.txt\n    sha: " + self.sha_a
                          + "\n").encode())

    test_golden_bytes = test_absent_file_created_with_header  # RF7

    def test_row_is_one_write(self):  # RF8
        calls = []
        real = os.write

        def w(fd, data):
            calls.append(data)
            return real(fd, data)
        with mock.patch.object(receipts.os, "write", w):
            self.rec()
            self.assertEqual(calls, [HDR.encode(), self.arow.encode()])
            del calls[:]
            self.rec()
        self.assertEqual(calls, [self.arow.encode()])

    def test_unemittable_row_leaves_no_header(self):  # RF9
        with mock.patch.object(receipts.yamlsub, "emit", side_effect=yamlsub.EmitError("lone surrogate")):
            with self.assertRaisesRegex(GateError, "cannot be written"):
                self.rec()
        self.nothing_created()

    def test_short_write_refused(self):  # RF10
        real = os.write
        n = {"n": 0}

        def w(fd, data):
            n["n"] += 1
            return real(fd, data[:len(data) // 2]) if n["n"] == 2 else real(fd, data)
        with mock.patch.object(receipts.os, "write", w):
            with self.assertRaisesRegex(GateError, "short write"):
                self.rec()
        self.assertNotEqual(self.rf_bytes(), (HDR + self.arow).encode())

    def test_write_error_closes_and_unlocks(self):  # RF11, RF19
        real = os.write
        n = {"n": 0}
        opened, live = [], set()
        real_open, real_close = os.open, os.close

        def op(*a, **k):
            fd = real_open(*a, **k)
            if a[0] == SID + ".yml" and "dir_fd" in k:  # the receipt file, opened by name inside the directory
                opened.append(fd)
            live.add(fd)  # 5a.2-f: every descriptor, the directory ones included
            return fd

        def cl(fd):
            if fd in live:
                live.remove(fd)
            return real_close(fd)

        def w(fd, data):
            n["n"] += 1
            if n["n"] == 2:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(fd, data)
        with mock.patch.object(receipts.os, "write", w), mock.patch.object(receipts.os, "open", op), \
                mock.patch.object(receipts.os, "close", cl):
            with self.assertRaisesRegex(GateError, "No space left on device"):
                self.rec()
            self.assertEqual(self.rf_bytes(), HDR.encode())
            self.rec()  # the lock was released: a second record does not block
        self.assertEqual(len(opened), 2)
        self.assertEqual(live, set())
        self.assertEqual(self.rf_bytes(), (HDR + self.arow).encode())

    def test_open_flags(self):  # RF12
        seen = []
        real = os.open

        def op(path, flags, *a, **k):
            if path == SID + ".yml" and "dir_fd" in k:
                seen.append((flags, a))
            return real(path, flags, *a, **k)
        with mock.patch.object(receipts.os, "open", op):
            self.rec()
        self.assertEqual(seen, [(os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, (0o600,))])

    def test_record_appends_after_truncated_line(self):  # RF13, RF27, LD7
        for data in (b"garbage", (HDR + "  - path: /r/a\n    sha: 3b18").encode(),
                     (HDR + "  - path: /r/a\n    sha: " + S40()).encode()):
            with self.subTest(data=data):
                self.put_rf(data)
                self.rec()
                self.assertTrue(self.rf_bytes().startswith(data))
                self.assertTrue(self.rf_bytes().endswith(self.arow.encode()))
                with self.assertRaises(GateError):
                    load(self.root, self.cfg, SID)

    def test_receipt_file_is_directory(self):  # RF14
        os.makedirs(self.rf)
        with self.assertRaisesRegex(GateError, "is not a regular file"):
            self.rec()
        self.assertEqual(os.listdir(self.rf), [])

    def test_receipt_file_fifo_never_blocks(self):  # RF15
        os.makedirs(self.rdir)
        os.mkfifo(self.rf)
        res = []

        def go():
            try:
                self.rec()
            except GateError as e:
                res.append(e)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertRegex(str(res[0]), "is not a regular file")

    def test_receipt_file_symlink_refused(self):  # RF16
        target = self.put("x.yml", b"keep", base=self.other())
        os.makedirs(self.rdir)
        os.symlink(target, self.rf)
        with self.assertRaisesRegex(GateError, "is a symlink"):
            self.rec()
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")

    def test_receipt_file_dangling_symlink_refused(self):  # RF17
        target = os.path.join(self.other(), "new.yml")
        os.makedirs(self.rdir)
        os.symlink(target, self.rf)
        with self.assertRaisesRegex(GateError, "is a symlink"):
            self.rec()
        self.assertFalse(os.path.lexists(target))

    def test_symlink_swapped_in_before_open_is_refused_by_nofollow(self):  # RF16/RF17, O_NOFOLLOW alone (5a.2-f D-Q4 (a))
        target = os.path.join(self.other(), "new.yml")
        os.makedirs(self.rdir)
        with open_hook(SID + ".yml", lambda: os.symlink(target, self.rf), directory=False) as hk:
            with self.assertRaises(GateError) as cm:  # swapped in immediately before the receipt open
                self.rec()
        self.assertGreater(hk["fired"], 0)
        self.assertEqual(str(cm.exception), ".strict-delivery/receipts/" + SID
                         + ".yml: is a symlink; receipt files must be regular files")  # was "cannot append (...)"
        self.assertFalse(os.path.lexists(target))

    def test_receipt_file_fifo_swapped_in_before_open_never_blocks(self):  # RF15, O_NONBLOCK and fstat alone
        os.makedirs(self.rdir)
        with open_hook(SID + ".yml", lambda: os.mkfifo(self.rf), directory=False) as hk:
            kind, val = watched(self.rec)
        self.assertGreater(hk["fired"], 0)
        self.assertEqual(kind, "err")
        self.assertEqual(str(val), ".strict-delivery/receipts/" + SID
                         + ".yml: is not a regular file; receipt files must be regular files")

    def test_fstat_regular_check_on_descriptor(self):  # D-Q2: the descriptor check
        os.makedirs(self.rdir)
        fake = os.stat(self.root)  # a directory's stat result
        real = os.fstat
        n = {"n": 0}

        def fs(fd):
            n["n"] += 1
            return fake if n["n"] == 2 else real(fd)  # the 1st is content_sha's reader, the 2nd the receipt file's
        with mock.patch.object(receipts.os, "fstat", fs):
            with self.assertRaisesRegex(GateError, "is not a regular file"):
                self.rec()

    @unittest.skipIf(os.geteuid() == 0, "uid 0 writes anywhere")
    def test_receipt_file_read_only(self):  # RF18
        self.put_rf(b"")
        os.chmod(self.rf, 0o400)
        self.addCleanup(os.chmod, self.rf, 0o600)
        with self.assertRaisesRegex(GateError, "Permission denied"):
            self.rec()

    def test_record_releases_descriptor(self):  # RF19
        opened, live = [], set()
        real_open, real_close = os.open, os.close

        def op(*a, **k):
            fd = real_open(*a, **k)
            if a[0] == SID + ".yml" and "dir_fd" in k:
                opened.append(fd)
            live.add(fd)  # 5a.2-f: every descriptor, the directory ones included
            return fd

        def cl(fd):
            if fd in live:
                live.remove(fd)
            return real_close(fd)
        with mock.patch.object(receipts.os, "open", op), mock.patch.object(receipts.os, "close", cl):
            self.rec()
            os.unlink(self.rf)
            os.makedirs(self.rf)
            with self.assertRaises(GateError):
                self.rec()
            os.rmdir(self.rf)
            with mock.patch.object(receipts.fcntl, "flock", side_effect=OSError(errno.EINTR, "x")):
                with self.assertRaises(GateError):
                    self.rec()
        self.assertEqual(len(opened), 2)  # the successful call and the one that found a directory has no descriptor
        self.assertEqual(live, set())

    def test_flock_failure(self):  # RF20
        with mock.patch.object(receipts.fcntl, "flock", side_effect=OSError(errno.ENOLCK, "No locks available")):
            with self.assertRaisesRegex(GateError, "No locks available"):
                self.rec()
        self.assertEqual(self.rf_bytes(), b"")

    def test_two_sessions_two_files(self):  # RF21
        self.rec()
        self.rec("other")
        self.assertEqual(sorted(os.listdir(self.rdir)), sorted(["other.yml", SID + ".yml"]))
        self.assertEqual(self.rf_bytes("other"), (HDR + self.arow).encode())
        self.assertEqual(self.rf_bytes(), (HDR + self.arow).encode())

    def test_session_file_name(self):  # RF22
        for s in ("t", SID, "A_b-9"):
            self.rec(s)
            self.assertTrue(os.path.isfile(self.root + "/.strict-delivery/receipts/" + s + ".yml"))

    def test_exception_groups_not_referenced(self):  # VN3
        for mod in ("gates/lib/receipts.py", "gates/tools/receipt_cli.py"):
            with open(os.path.join(REPO, mod), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("ExceptionGroup", text)
            self.assertNotIn("except*", text)
        real = os.write
        with mock.patch.object(receipts.os, "write", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.rec()
        self.assertTrue(real)
        self.rec()  # nothing left locked or open by the interrupted call

    def test_unicode_version_independent(self):  # VN2
        for i, n in enumerate(("Ⱟx", "ࡰx", "\U0001fae8x", "Kx")):
            with self.subTest(n=n):
                self.put(n, b"u")
                record(self.root, self.cfg, "u%d" % i, n)
                self.assertEqual(self.rf_bytes("u%d" % i),
                                 (HDR + row_text(self.real + "/" + n, blob(b"u"))).encode())

    def test_digit_limits_same_on_both(self):  # VN1
        for limit in INT_LIMITS:
            with self.subTest(limit=limit):
                if limit is not None:
                    old = sys.get_int_max_str_digits()
                    self.addCleanup(sys.set_int_max_str_digits, old)
                    sys.set_int_max_str_digits(limit)
                for n in (1000, 1001, 4300, 4301):
                    self.put_rf((HDR + "  - path: /r/a\n    sha: " + "9" * n + "\n").encode())
                    with self.assertRaises(GateError):
                        load(self.root, self.cfg, SID)
                    self.put_rf(("schema: " + "9" * n + "\nreads: []\n").encode())
                    with self.assertRaises(GateError):
                        load(self.root, self.cfg, SID)
                self.assertNotEqual(session_problem("9" * 4301), "")
                self.assertNotEqual(session_problem("9" * 4300), "")


# ------------------------------------------------------------------------------------------------ load (LD)

class Load(Base):
    GOOD = HDR + row_text("/r/a", S40("a")) + row_text("/r/b", S40("b")) + row_text("/r/c", S40("c"))

    def msg(self):
        with self.assertRaises(GateError) as cm:
            load(self.root, self.cfg, SID)
        return str(cm.exception)

    def test_load_absent_file(self):  # LD1
        self.assertEqual(load(self.root, self.cfg, SID), [])
        os.makedirs(self.rdir)
        self.assertEqual(load(self.root, self.cfg, SID), [])

    def test_load_rows(self):  # LD2
        self.put_rf(self.GOOD.encode())
        rows = load(self.root, self.cfg, SID)
        self.assertEqual(rows, [{"path": "/r/a", "sha": S40("a")}, {"path": "/r/b", "sha": S40("b")},
                                {"path": "/r/c", "sha": S40("c")}])
        for r in rows:
            self.assertIs(type(r), dict)
            self.assertEqual(list(r), ["path", "sha"])

    def test_load_empty_file(self):  # LD4
        self.put_rf(b"")
        self.assertRegex(self.msg(), "top level: must be a mapping")

    def test_load_header_only(self):  # LD5
        self.put_rf(HDR.encode())
        self.assertRegex(self.msg(), "reads: must not be null")

    def test_load_empty_flow_list(self):  # LD6
        self.put_rf((b"schema: " + RCPT_TAGB + b"\nreads: []\n"))
        self.assertEqual(load(self.root, self.cfg, SID), [])

    def test_load_truncated_every_offset(self):  # LD7
        full = (HDR + row_text("/r/a", S40("a")) + row_text("/r/bb", S40("b"))).encode()
        second = len((HDR + row_text("/r/a", S40("a"))).encode())
        self.put_rf(full)
        self.assertEqual(len(load(self.root, self.cfg, SID)), 2)
        for cut in range(0, len(full)):
            with self.subTest(cut=cut):
                self.put_rf(full[:cut])
                try:
                    rows = load(self.root, self.cfg, SID)
                except GateError as e:
                    self.assertIn(".strict-delivery/receipts/" + SID + ".yml", str(e))
                else:
                    # only a cut exactly between the two rows is a whole, valid file
                    self.assertEqual(cut, second)
                    self.assertEqual(len(rows), 1)

    def test_load_schema_failure_names_file(self):  # LD8
        rel = ".strict-delivery/receipts/" + SID + ".yml"
        for text in ("schema: receipt/2\nreads: []\n", ("schema: " + RCPT_TAG + "\nreads: []\nextra: 1\n"),
                     HDR + "  - path: ''\n    sha: " + S40() + "\n", HDR + "  - path: /a\n    sha: ZZZ\n",
                     HDR + "  - path: /a\n    sha: abcdef1\n", HDR + "  - path: /a\n    sha: " + S40().upper() + "\n"):
            with self.subTest(text=text):
                self.put_rf(text.encode())
                m = self.msg()
                self.assertTrue(m.startswith(rel + ": "), m)

    def test_short_sha_refused_by_load(self):  # D-Q1
        self.put_rf((HDR + row_text("/r/a", "3b18e51")).encode())
        self.assertEqual(self.msg(), ".strict-delivery/receipts/%s.yml: reads.0.sha: must be exactly 40 lowercase hex "
                                     "digits; %s" % (SID, REMEDY))

    def test_final_newline_required(self):  # D-Q1
        self.put_rf((HDR + row_text("/r/a", S40())).encode()[:-1])
        self.assertEqual(self.msg(), ".strict-delivery/receipts/%s.yml: the last line is cut (no final newline); %s"
                         % (SID, REMEDY))

    def test_load_yaml_errors(self):  # LD9
        rel = ".strict-delivery/receipts/" + SID + ".yml"
        for data in ((b"schema: " + RCPT_TAGB + b"\nschema: " + RCPT_TAGB + b"\nreads: []\n"), (b"schema: " + RCPT_TAGB + b"\nreads:\n\t- a\n"),
                     (b"schema: " + RCPT_TAGB + b"\nreads: {a: 1}\n"), b"schema: &x receipt/1\nreads: []\n",
                     (b"schema: " + RCPT_TAGB + b"\nreads: []\x00\n"), (b"schema: " + RCPT_TAGB + b"\nreads: [\xff]\n"),
                     (b"schema: " + RCPT_TAGB + b"\nreads: ") + b"9" * 1001 + b"\n"):
            with self.subTest(data=data):
                self.put_rf(data)
                m = self.msg()
                self.assertTrue(m.startswith(rel + ": ") or m.startswith(rel + " "), m)
                self.assertTrue(m.endswith(REMEDY), m)

    def test_load_error_names_remedy(self):  # LD10
        for data in (b"", HDR.encode(), b"garbage\n", (HDR + row_text("/r/a", "abc1234")).encode()):
            with self.subTest(data=data):
                self.put_rf(data)
                self.assertTrue(self.msg().endswith("; " + REMEDY))

    def test_load_bom_crlf(self):  # LD11
        body = (HDR + row_text("/r/a", S40())).encode()
        for data in (b"\xef\xbb\xbf" + body, body.replace(b"\n", b"\r\n")):
            self.put_rf(data)
            self.assertEqual(load(self.root, self.cfg, SID), [{"path": "/r/a", "sha": S40()}])

    def test_load_receipts_dir_symlink(self):  # LD12
        real = os.path.join(self.other(), "real")
        os.mkdir(real)
        with open(real + "/" + SID + ".yml", "wb") as fh:
            fh.write(self.GOOD.encode())
        os.symlink(real, self.rdir)
        self.assertRegex(self.msg(), "^\\.strict-delivery/receipts: is a symlink")

    def test_load_receipts_dir_not_directory(self):  # LD13
        self.put(".strict-delivery/receipts", b"x")
        self.assertRegex(self.msg(), "receipts: is not a directory")
        os.unlink(self.rdir)
        os.mkfifo(self.rdir)
        kind, val = watched(self.msg)  # R1-1: watchdog, never only a hang
        self.assertEqual(kind, "ok")
        self.assertRegex(val, "receipts: is not a directory")

    def test_load_parent_symlink(self):  # LD14
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["receipts"] = "lnk/r"
        os.symlink(self.other(), self.root + "/lnk")
        with self.assertRaisesRegex(GateError, "^lnk: is a symlink"):
            load(self.root, cfg, SID)

    def test_load_receipt_symlink_refused(self):  # LD15
        valid = self.put("valid.yml", self.GOOD.encode(), base=self.other())
        os.makedirs(self.rdir)
        os.symlink(valid, self.rf)
        self.assertRegex(self.msg(), "is a symlink; receipt files must be regular files; " + REMEDY)

    def test_load_symlink_swapped_in_before_open(self):  # R1-1: O_NOFOLLOW on the open of load
        valid = self.put("valid.yml", self.GOOD.encode(), base=self.other())
        os.makedirs(self.rdir)
        self.put_rf(b"")

        def swap():
            os.unlink(self.rf)
            os.symlink(valid, self.rf)  # swapped in immediately before the open
        with open_hook(SID + ".yml", swap, directory=False) as hk:
            self.assertRegex(self.msg(), "is a symlink; receipt files must be regular files; " + REMEDY)
        self.assertGreater(hk["fired"], 0)

    def test_load_fifo_swapped_in_before_open_never_blocks(self):  # R1-1: O_NONBLOCK and the fstat check
        os.makedirs(self.rdir)
        self.put_rf(b"")

        def swap():
            os.unlink(self.rf)
            os.mkfifo(self.rf)
        with open_hook(SID + ".yml", swap, directory=False) as hk:
            kind, val = watched(self.msg)
        self.assertGreater(hk["fired"], 0)
        self.assertEqual(kind, "ok")
        self.assertRegex(val, "is not a regular file; receipt files must be regular files; " + REMEDY)

    def test_load_dangling_symlink(self):  # LD16
        os.makedirs(self.rdir)
        os.symlink(os.path.join(self.other(), "missing"), self.rf)
        self.assertRegex(self.msg(), "is a symlink")

    def test_load_directory_or_fifo(self):  # LD17
        os.makedirs(self.rf)
        self.assertRegex(self.msg(), "is not a regular file")
        os.rmdir(self.rf)
        os.mkfifo(self.rf)
        res = []
        t = threading.Thread(target=lambda: res.append(self.msg()), daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertRegex(res[0], "is not a regular file")

    @unittest.skipIf(os.geteuid() == 0, "uid 0 reads a mode-000 file")
    def test_load_unreadable(self):  # LD18
        self.put_rf(self.GOOD.encode())
        os.chmod(self.rf, 0)
        self.addCleanup(os.chmod, self.rf, 0o600)
        self.assertRegex(self.msg(), "Permission denied")

    def test_load_argument_forms(self):  # LD19
        class S(str):
            pass
        for r in (None, 3, "", b"/x", S(self.root)):
            with self.assertRaisesRegex(GateError, "^root must be a string$"):
                load(r, self.cfg, SID)
        for s in (None, 3, "../x", S("a"), "", "a/b"):
            with self.assertRaisesRegex(GateError, "^session: must be"):
                load(self.root, self.cfg, s)
        for c in (None, {}, {"paths": {"receipts": "../x"}}):
            with self.assertRaisesRegex(GateError, "paths.receipts"):
                load(self.root, c, SID)

    def test_load_duplicate_rows_kept(self):  # LD21
        self.put_rf((HDR + row_text("/r/a", S40()) * 2).encode())
        self.assertEqual(load(self.root, self.cfg, SID), [{"path": "/r/a", "sha": S40()}] * 2)

    def test_load_many_rows(self):  # LD22
        self.put_rf((HDR + row_text("/r/a", S40()) * 20000).encode())
        self.assertEqual(len(load(self.root, self.cfg, SID)), 20000)

    def test_truncated_receipt_not_seen_by_check_schema(self):  # LD23
        self.put_rf((HDR + "  - path: /r/a\n    sha: 3b18").encode())
        self.assertRegex(self.msg(), "delete it")
        env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema"], cwd=self.root, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stdout.decode())

    def test_load_returns_fresh_rows(self):  # LD24
        self.put_rf(self.GOOD.encode())
        a = load(self.root, self.cfg, SID)
        a[0]["path"] = "mutated"
        a.append("x")
        self.assertEqual(load(self.root, self.cfg, SID)[0]["path"], "/r/a")
        self.assertEqual(len(load(self.root, self.cfg, SID)), 3)

    def test_load_root_not_directory(self):  # root forms of load
        with self.assertRaises(GateError):
            load(self.root + "/missing", self.cfg, SID)


# ------------------------------------------------------------------------------------------------ 5a.2-f (race)

GOOD_ELSEWHERE = HDR + row_text("/elsewhere", S40("e"))
GOOD_MINE = HDR + row_text("/mine", S40("a"))
LINK_KINDS = ("in", "out", "dangling", "linkfile", "linkfifo")
NOTDIR_KINDS = ("file", "fifo")
S_LINK = "%s: is a symlink; directories must be real directories"
S_NOTDIR = "%s: is not a directory"
F_LINK = "%s: is a symlink; receipt files must be regular files"
F_NONREG = "%s: is not a regular file; receipt files must be regular files"


class ReceiptsDirRace(Base):
    """Task 5a.2-f (table task-5a.2-f-domain.md; row ids in the comments): the receipts directory is walked by
    descriptor, so a component swapped after the check is never followed; the receipt file in a swapped non-regular
    state gives the one sentence; ``content_sha`` refuses a symlink. Sentences are written out by hand."""

    n = 0

    def setUp(self):
        super().setUp()
        self.put("a.txt", b"a")

    def fresh(self, depth):
        """(base, out, parts, cfg): a plain directory as the root with a.txt in it, an outside directory, the
        components of ``paths.receipts`` (``depth`` of d1/d2/d3) and the config naming them."""
        ReceiptsDirRace.n += 1
        base = os.path.join(self.tmp, "r%d" % self.n)
        out = os.path.join(self.tmp, "o%d" % self.n)
        os.mkdir(base)
        os.mkdir(out)
        parts = ["d1", "d2", "d3"][:depth]
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["receipts"] = "/".join(parts)
        self.put("a.txt", b"a", base=base)
        return base, out, parts, cfg

    def plant(self, kind, at, rest, base, out, receipt):
        """Put a ``kind`` object at the path ``at``; a link's target holds the directories ``rest`` (and, with
        ``receipt``, a valid receipt that names /elsewhere)."""
        if kind in ("in", "out"):
            tgt = os.path.join(base, "inside") if kind == "in" else os.path.join(out, "o")
            d = os.path.join(tgt, *rest)
            os.makedirs(d)
            if receipt:
                with open(os.path.join(d, SID + ".yml"), "w") as fh:
                    fh.write(GOOD_ELSEWHERE)
            os.symlink(tgt, at)
        elif kind == "dangling":
            os.symlink(os.path.join(out, "nope"), at)
        elif kind == "linkfile":
            self.put("f", b"x", base=out)
            os.symlink(os.path.join(out, "f"), at)
        elif kind == "linkfifo":
            os.mkfifo(os.path.join(out, "ff"))
            os.symlink(os.path.join(out, "ff"), at)
        elif kind == "file":
            open(at, "w").close()
        elif kind == "fifo":
            os.mkfifo(at)
        elif kind == "socket":
            bind_socket(at)
        elif kind == "dir":
            os.mkdir(at)
        else:
            raise AssertionError(kind)

    def swap(self, kind, at, rest, base, out, receipt):
        """The swap: the real object at ``at`` is renamed away and a ``kind`` object put at its name."""
        def action():
            os.rename(at, at + ".moved")
            self.plant(kind, at, rest, base, out, receipt)
        return action

    def want_dir(self, kind, shown):
        return (S_LINK if kind in LINK_KINDS else S_NOTDIR) % shown

    def no_leak(self, base, out):
        """Nothing was written through a swapped component: no receipt file in the outside directory or in the
        in-root link target, and the dangling target was not created."""
        for top in (os.path.join(out), os.path.join(base, "inside")):
            for dp, dn, fn in os.walk(top):
                self.assertNotIn(SID + ".yml", fn, dp)
        self.assertFalse(os.path.lexists(os.path.join(out, "nope")))

    def positions(self):
        return [(d, p) for d in (1, 2, 3) for p in range(1, d + 1)]

    # -- 1a: a component swapped between the check and the use (the swap runs immediately before its open) ---------

    def test_record_component_swapped(self):  # DW1-DW7, DW10, DC6, DR2
        for depth, pos in self.positions():
            for kind in LINK_KINDS + NOTDIR_KINDS:
                with self.subTest(depth=depth, pos=pos, kind=kind):
                    base, out, parts, cfg = self.fresh(depth)
                    os.makedirs(os.path.join(base, *parts))
                    at = os.path.join(base, *parts[:pos])
                    with open_hook(parts[pos - 1], self.swap(kind, at, parts[pos:], base, out, False),
                                   directory=True) as hk:
                        kind_, val = watched(lambda: record(base, cfg, SID, "a.txt"))
                    self.assertGreater(hk["fired"], 0)
                    self.assertEqual(kind_, "err")
                    self.assertIs(type(val), GateError)
                    self.assertEqual(str(val), self.want_dir(kind, "/".join(parts[:pos])))
                    self.assertEqual(hk["live"], set())
                    self.no_leak(base, out)
                    for dp, dn, fn in os.walk(base):
                        self.assertNotIn(SID + ".yml", fn, dp)

    def test_record_created_component_swapped(self):  # DW1-DW7 for a component made by this call, DW10, DC6
        for depth, pos in self.positions():
            for kind in LINK_KINDS + NOTDIR_KINDS:
                with self.subTest(depth=depth, pos=pos, kind=kind):
                    base, out, parts, cfg = self.fresh(depth)
                    at = os.path.join(base, *parts[:pos])
                    # the first open of the name fails (missing), the mkdir makes it, the swap runs before the 2nd open
                    with open_hook(parts[pos - 1], self.swap(kind, at, parts[pos:], base, out, False), nth=2,
                                   directory=True) as hk:
                        kind_, val = watched(lambda: record(base, cfg, SID, "a.txt"))
                    self.assertGreater(hk["fired"], 0)
                    self.assertEqual(kind_, "err")
                    self.assertEqual(str(val), self.want_dir(kind, "/".join(parts[:pos])))
                    self.assertEqual(hk["live"], set())
                    self.no_leak(base, out)
                    for dp, dn, fn in os.walk(base):
                        self.assertNotIn(SID + ".yml", fn, dp)

    def test_load_component_swapped(self):  # DW1-DW7, DW10, DC7, DR2, DR3
        for depth, pos in self.positions():
            for kind in LINK_KINDS + NOTDIR_KINDS:
                with self.subTest(depth=depth, pos=pos, kind=kind):
                    base, out, parts, cfg = self.fresh(depth)
                    os.makedirs(os.path.join(base, *parts))
                    with open(os.path.join(base, *parts, SID + ".yml"), "w") as fh:
                        fh.write(GOOD_MINE)
                    at = os.path.join(base, *parts[:pos])
                    with open_hook(parts[pos - 1], self.swap(kind, at, parts[pos:], base, out, True),
                                   directory=True) as hk:
                        kind_, val = watched(lambda: load(base, cfg, SID))
                    self.assertGreater(hk["fired"], 0)
                    self.assertEqual(kind_, "err", val)  # never the rows of the swapped-in target
                    self.assertEqual(str(val), self.want_dir(kind, "/".join(parts[:pos])))
                    self.assertEqual(hk["live"], set())
                    self.assertFalse(os.path.lexists(os.path.join(out, "nope")))

    def test_component_swapped_to_socket(self):  # DW8
        for op in ("record", "load"):
            with self.subTest(op=op):
                base, out, parts, cfg = self.fresh(3)
                os.makedirs(os.path.join(base, *parts))
                at = os.path.join(base, "d1", "d2")
                call = (lambda: record(base, cfg, SID, "a.txt")) if op == "record" else (lambda: load(base, cfg, SID))
                with open_hook("d2", self.swap("socket", at, ["d3"], base, out, False), directory=True) as hk:
                    kind_, val = watched(call)
                self.assertGreater(hk["fired"], 0)
                self.assertEqual((kind_, str(val)), ("err", "d1/d2: is not a directory"))
                self.assertEqual(hk["live"], set())

    def test_component_swapped_to_other_real_directory(self):  # DW9: what is opened is what is checked
        def swap(at):
            def action():
                os.rename(at, at + ".moved")
                os.mkdir(at)
            return action
        base, out, parts, cfg = self.fresh(1)
        os.mkdir(os.path.join(base, "d1"))
        with open_hook("d1", swap(os.path.join(base, "d1")), directory=True) as hk:
            record(base, cfg, SID, "a.txt")
        self.assertGreater(hk["fired"], 0)
        self.assertTrue(os.path.isfile(os.path.join(base, "d1", SID + ".yml")))
        self.assertEqual(load(base, cfg, SID), [{"path": os.path.join(base, "a.txt"), "sha": blob(b"a")}])
        base, out, parts, cfg = self.fresh(1)
        os.mkdir(os.path.join(base, "d1"))
        with open(os.path.join(base, "d1", SID + ".yml"), "w") as fh:
            fh.write(GOOD_ELSEWHERE)

        def swap_load():
            os.rename(os.path.join(base, "d1"), os.path.join(base, "d1.moved"))
            os.mkdir(os.path.join(base, "d1"))
            with open(os.path.join(base, "d1", SID + ".yml"), "w") as fh:
                fh.write(GOOD_MINE)
        with open_hook("d1", swap_load, directory=True) as hk:
            rows = load(base, cfg, SID)
        self.assertGreater(hk["fired"], 0)
        self.assertEqual(rows, [{"path": "/mine", "sha": S40("a")}])

    def test_static_component_symlink_every_position(self):  # DS11: the first bad component is named, record and load
        for depth, pos in self.positions():
            with self.subTest(depth=depth, pos=pos):
                base, out, parts, cfg = self.fresh(depth)
                if pos > 1:
                    os.makedirs(os.path.join(base, *parts[:pos - 1]))
                os.symlink(out, os.path.join(base, *parts[:pos]))
                want = S_LINK % "/".join(parts[:pos])
                for fn in (lambda: record(base, cfg, SID, "a.txt"), lambda: load(base, cfg, SID)):
                    with self.assertRaises(GateError) as cm:
                        fn()
                    self.assertEqual(str(cm.exception), want)
                self.assertEqual(os.listdir(out), [])

    # -- 1b: a swap after the component was opened: the descriptor pins the object that was checked ------------------

    def test_swap_after_open_writes_to_checked_directory(self):  # DW11, Q3, M4, M15
        for depth, pos in ((1, 1), (3, 3), (3, 1), (3, 2)):
            for kind in LINK_KINDS + NOTDIR_KINDS:
                with self.subTest(depth=depth, pos=pos, kind=kind):
                    base, out, parts, cfg = self.fresh(depth)
                    os.makedirs(os.path.join(base, *parts))
                    at = os.path.join(base, *parts[:pos])
                    with open_hook(parts[pos - 1], self.swap(kind, at, parts[pos:], base, out, False), after=True,
                                   directory=True) as hk:
                        kind_, row = watched(lambda: record(base, cfg, SID, "a.txt"))  # R1-1: FIFO kinds never hang
                        self.assertEqual(kind_, "ok", row)
                    self.assertGreater(hk["fired"], 0)
                    self.assertEqual(row["path"], os.path.join(base, "a.txt"))
                    moved = os.path.join(base, *parts[:pos - 1], parts[pos - 1] + ".moved", *parts[pos:], SID + ".yml")
                    with open(moved, "rb") as fh:  # written into the directory object that was opened
                        self.assertEqual(fh.read(), (HDR + row_text(row["path"], blob(b"a"))).encode())
                    self.assertEqual(hk["live"], set())
                    self.no_leak(base, out)

    def test_mkdir_after_parent_swap_creates_in_checked_parent(self):  # DW12, Q3, M5
        base, out, parts, cfg = self.fresh(2)
        os.mkdir(os.path.join(base, "d1"))
        state = {"fired": 0}
        real_mkdir = os.mkdir

        def mk(name, mode=0o777, **k):
            if name == "d2" and "dir_fd" in k:
                state["fired"] += 1
                os.rename(os.path.join(base, "d1"), os.path.join(base, "d1.moved"))
                os.symlink(out, os.path.join(base, "d1"))
            return real_mkdir(name, mode, **k)
        with mock.patch.object(receipts.os, "mkdir", mk):
            record(base, cfg, SID, "a.txt")
        self.assertGreater(state["fired"], 0)
        self.assertTrue(os.path.isfile(os.path.join(base, "d1.moved", "d2", SID + ".yml")))
        self.assertEqual(os.listdir(out), [])

    def test_load_swap_after_open_reads_checked_directory(self):  # DW13, FS13
        for pos in (1, 2):
            with self.subTest(pos=pos):
                base, out, parts, cfg = self.fresh(2)
                os.makedirs(os.path.join(base, "d1", "d2"))
                with open(os.path.join(base, "d1", "d2", SID + ".yml"), "w") as fh:
                    fh.write(GOOD_MINE)
                at = os.path.join(base, *parts[:pos])
                with open_hook(parts[pos - 1], self.swap("out", at, parts[pos:], base, out, True), after=True,
                               directory=True) as hk:
                    rows = load(base, cfg, SID)
                self.assertGreater(hk["fired"], 0)
                self.assertEqual(rows, [{"path": "/mine", "sha": S40("a")}])  # never /elsewhere
                self.assertEqual(hk["live"], set())

    # -- 1d: creation and its race -----------------------------------------------------------------------------------

    def test_mkdir_lost_race_to_real_directory(self):  # DC1 (deterministic), M9: a lost mkdir re-opens the winner's
        base, out, parts, cfg = self.fresh(2)
        real_mkdir = os.mkdir

        def mk(name, mode=0o777, **k):
            real_mkdir(name, mode, **k)  # the rival made it first
            raise FileExistsError(errno.EEXIST, "File exists")
        with mock.patch.object(receipts.os, "mkdir", mk):
            record(base, cfg, SID, "a.txt")
        self.assertTrue(os.path.isfile(os.path.join(base, "d1", "d2", SID + ".yml")))

    def test_mkdir_lost_race_to_symlink(self):  # DC2
        base, out, parts, cfg = self.fresh(2)
        os.mkdir(os.path.join(base, "d1"))
        opens = []
        real_open = os.open
        real_mkdir = os.mkdir

        def op(n, flags, *a, **k):
            if n == "d2" and "dir_fd" in k:
                opens.append(n)
            return real_open(n, flags, *a, **k)

        def mk(name, mode=0o777, **k):
            if name == "d2" and "dir_fd" in k:
                os.symlink(out, os.path.join(base, "d1", "d2"))  # a rival's symlink wins the name
                raise FileExistsError(errno.EEXIST, "File exists")
            return real_mkdir(name, mode, **k)
        with mock.patch.object(receipts.os, "open", op), mock.patch.object(receipts.os, "mkdir", mk):
            with self.assertRaises(GateError) as cm:
                record(base, cfg, SID, "a.txt")
        self.assertEqual(str(cm.exception), S_LINK % "d1/d2")
        self.assertEqual(len(opens), 2)  # one re-open only
        self.assertEqual(os.listdir(out), [])

    def test_walk_bounded_retry(self):  # DC5, M9
        base, out, parts, cfg = self.fresh(1)
        real_mkdir = os.mkdir
        calls = {"mkdir": 0, "open": 0}
        real_open = os.open

        def op(n, flags, *a, **k):
            if n == "d1" and "dir_fd" in k:
                calls["open"] += 1
            return real_open(n, flags, *a, **k)

        def mk(name, mode=0o777, **k):
            calls["mkdir"] += 1
            if calls["mkdir"] > 1:
                raise AssertionError("a third attempt: the retry is not bounded")
            real_mkdir(name, mode, **k)
            os.rmdir(os.path.join(base, name))  # the component vanishes again
        with mock.patch.object(receipts.os, "open", op), mock.patch.object(receipts.os, "mkdir", mk):
            with self.assertRaises(GateError) as cm:
                record(base, cfg, SID, "a.txt")
        self.assertEqual(str(cm.exception), "d1: cannot use the receipts directory (No such file or directory)")
        self.assertEqual(calls, {"mkdir": 1, "open": 2})

    def test_load_missing_component_returns_empty_and_creates_nothing(self):  # DS12, DC7, M11
        base, out, parts, cfg = self.fresh(3)
        os.mkdir(os.path.join(base, "d1"))
        with open_hook(None, None) as hk:
            self.assertEqual(load(base, cfg, SID), [])
            self.assertEqual(hk["live"], set())  # DR3
        self.assertEqual(os.listdir(os.path.join(base, "d1")), [])
        self.assertEqual(sorted(os.listdir(base)), ["a.txt", "d1"])

    def test_nested_modes(self):  # DC3, PD9
        base, out, parts, cfg = self.fresh(3)
        old = os.umask(0)
        os.umask(old)
        record(base, cfg, SID, "a.txt")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(base, "d1")).st_mode), 0o777 & ~old)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(base, "d1", "d2")).st_mode), 0o777 & ~old)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(base, "d1", "d2", "d3")).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(base, "d1", "d2", "d3", SID + ".yml")).st_mode), 0o600)

    # -- 1e: support, names, permissions -----------------------------------------------------------------------------

    def unsupported(self, base, cfg, what):
        """``record`` (with the blob id supplied, so the walk's own check is reached) and ``load`` on a platform
        lacking ``what``: both refused, nothing opened or created."""
        opens = []
        real_open = os.open

        def op(*a, **k):
            opens.append(a)
            return real_open(*a, **k)
        want = "d1: cannot use the receipts directory (directory descriptors are not supported on this platform)"
        with mock.patch.object(receipts.os, "open", op), \
                mock.patch.object(receipts, "content_sha", return_value=blob(b"a")):
            with self.assertRaises(GateError) as cm:
                record(base, cfg, SID, "a.txt")
            self.assertEqual(str(cm.exception), want, what)
            if what != "mkdir":  # load never makes a directory
                with self.assertRaises(GateError) as cm:
                    load(base, cfg, SID)
                self.assertEqual(str(cm.exception), want, what)
            else:
                self.assertEqual(load(base, cfg, SID), [])
        if what != "mkdir":
            self.assertEqual(opens, [])
            self.assertEqual(os.listdir(base), ["a.txt"])

    def test_walk_refuses_without_dir_fd_support(self):  # DE1, VN4, M10, M12
        cur = set(os.supports_dir_fd)
        follow = set(os.supports_follow_symlinks)
        cases = [("all dir_fd", "supports_dir_fd", set()), ("open", "supports_dir_fd", cur - {os.open}),
                 ("stat", "supports_dir_fd", cur - {os.stat}), ("mkdir", "supports_dir_fd", cur - {os.mkdir}),
                 ("follow", "supports_follow_symlinks", follow - {os.stat}),
                 ("no follow at all", "supports_follow_symlinks", set())]
        for what, attr, value in cases:
            with self.subTest(what=what):
                base, out, parts, cfg = self.fresh(1)
                with mock.patch.object(os, attr, value):
                    self.unsupported(base, cfg, what)
        for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"):
            with self.subTest(flag=name):
                base, out, parts, cfg = self.fresh(1)
                saved = getattr(os, name)
                delattr(os, name)
                try:
                    self.unsupported(base, cfg, name)
                finally:
                    setattr(os, name, saved)

    def test_lstat_membership_is_not_needed(self):  # VN4, M12: os.lstat is not in supports_dir_fd on 3.9
        base, out, parts, cfg = self.fresh(2)
        real_lstat = os.lstat
        used = []

        def lstat(*a, **k):
            if "dir_fd" in k:
                used.append(a)
            return real_lstat(*a, **k)
        with mock.patch.object(os, "supports_dir_fd", set(os.supports_dir_fd) - {os.lstat}), \
                mock.patch.object(receipts.os, "lstat", lstat):
            record(base, cfg, SID, "a.txt")
            self.assertEqual(len(load(base, cfg, SID)), 1)
        self.assertEqual(used, [])  # os.stat(follow_symlinks=False) classifies, never os.lstat(dir_fd=)

    def test_receipts_component_name_too_long(self):  # DE2
        base, out, parts, cfg = self.fresh(1)
        cfg["paths"]["receipts"] = "x" * 255
        record(base, cfg, SID, "a.txt")
        self.assertTrue(os.path.isfile(os.path.join(base, "x" * 255, SID + ".yml")))
        cfg["paths"]["receipts"] = "x" * 256
        with self.assertRaises(GateError) as cm:
            record(base, cfg, SID, "a.txt")
        self.assertEqual(str(cm.exception), "%s: cannot use the receipts directory (File name too long)" % ("x" * 256))

    @unittest.skipIf(os.geteuid() == 0, "uid 0 opens a mode-000 directory")
    def test_receipts_inner_component_unreadable(self):  # DE3
        base, out, parts, cfg = self.fresh(2)
        os.mkdir(os.path.join(base, "d1"))
        os.chmod(os.path.join(base, "d1"), 0)
        self.addCleanup(os.chmod, os.path.join(base, "d1"), 0o700)
        for fn in (lambda: record(base, cfg, SID, "a.txt"), lambda: load(base, cfg, SID)):
            with self.assertRaises(GateError) as cm:
                fn()
            self.assertEqual(str(cm.exception), "d1: cannot use the receipts directory (Permission denied)")

    def test_receipts_component_non_ascii(self):  # DE4, VN2
        base, out, parts, cfg = self.fresh(1)
        cfg["paths"]["receipts"] = "é中"
        record(base, cfg, SID, "a.txt")
        self.assertEqual(len(load(base, cfg, SID)), 1)
        self.assertTrue(os.path.isfile(os.path.join(base, "é中", SID + ".yml")))
        cfg["paths"]["receipts"] = "Ⱟ"  # U+2C2F: printable at Unicode 15, not at 13: refused on both interpreters
        with self.assertRaisesRegex(GateError, "paths.receipts"):
            record(base, cfg, SID, "a.txt")

    def test_receipts_dir_case_variant(self):  # DE5
        base, out, parts, cfg = self.fresh(1)
        cfg["paths"]["receipts"] = "Receipts"
        os.mkdir(os.path.join(base, "receipts"))
        if not os.path.exists(os.path.join(base, "Receipts")):
            self.skipTest("a case-sensitive volume")
        record(base, cfg, SID, "a.txt")
        self.assertEqual(sorted(os.listdir(base)), ["a.txt", "receipts"])

    # -- 1f: descriptors ---------------------------------------------------------------------------------------------

    def test_dir_descriptors_closed_on_success(self):  # DR1
        base, out, parts, cfg = self.fresh(3)
        with open_hook(None, None) as hk:
            record(base, cfg, SID, "a.txt")
            self.assertEqual(hk["live"], set())
            self.assertEqual(len(load(base, cfg, SID)), 1)
            self.assertEqual(hk["live"], set())

    def test_dir_descriptor_closed_when_file_open_fails(self):  # DR4
        for kind in ("readonly", "link", "fifo", "dir"):
            with self.subTest(kind=kind):
                if kind == "readonly" and os.geteuid() == 0:
                    continue
                base, out, parts, cfg = self.fresh(1)
                d = os.path.join(base, "d1")
                os.mkdir(d)
                rf = os.path.join(d, SID + ".yml")
                if kind == "readonly":
                    with open(rf, "w") as fh:
                        fh.write(GOOD_MINE)
                    os.chmod(rf, 0)  # unreadable and unwritable: both opens fail
                    self.addCleanup(os.chmod, rf, 0o600)
                elif kind == "link":
                    os.symlink(os.path.join(out, "x"), rf)
                elif kind == "fifo":
                    os.mkfifo(rf)
                else:
                    os.mkdir(rf)
                with open_hook(None, None) as hk:
                    self.assertEqual(watched(lambda: record(base, cfg, SID, "a.txt"))[0], "err")
                    self.assertEqual(watched(lambda: load(base, cfg, SID))[0], "err")
                    self.assertEqual(hk["live"], set())

    def test_no_descriptor_growth(self):  # DR6
        base, out, parts, cfg = self.fresh(2)
        record(base, cfg, SID, "a.txt")
        before = len(os.listdir("/dev/fd"))
        for _ in range(100):
            record(base, cfg, SID, "a.txt")
        load(base, cfg, SID)
        self.assertEqual(len(os.listdir("/dev/fd")), before)

    # -- U-2 and D-Q4 (a): the receipt file in a non-regular state, static or swapped, record and load ---------------

    def file_state(self, kind, rf, out, base):
        if kind == "socket":
            bind_socket(rf)
        elif kind == "fifo":
            os.mkfifo(rf)
        elif kind == "dir":
            os.mkdir(rf)
        elif kind == "link":
            self.put("t.yml", b"keep", base=out)
            os.symlink(os.path.join(out, "t.yml"), rf)
        elif kind == "dangling":
            os.symlink(os.path.join(out, "new.yml"), rf)
        else:
            raise AssertionError(kind)

    def want_file(self, kind, remedy):
        shown = ".strict-delivery/receipts/" + SID + ".yml"
        text = (F_LINK if kind in ("link", "dangling") else F_NONREG) % shown
        return text + ("; " + REMEDY if remedy else "")

    def test_receipt_file_socket_static(self):  # FS1, FS8
        os.makedirs(self.rdir)
        bind_socket(self.rf)
        kind, val = watched(lambda: record(self.root, self.cfg, SID, "a.txt"))
        self.assertEqual((kind, str(val)), ("err", self.want_file("socket", False)))
        kind, val = watched(lambda: load(self.root, self.cfg, SID))
        self.assertEqual((kind, str(val)), ("err", self.want_file("socket", True)))

    def test_load_file_swapped_non_regular(self):  # FS2, FS4, FS6, FS7 (load)
        for kind in ("socket", "fifo", "dir", "link", "dangling"):
            with self.subTest(kind=kind):
                base, out, parts, cfg = self.fresh(1)
                d = os.path.join(base, "d1")
                os.mkdir(d)
                rf = os.path.join(d, SID + ".yml")
                with open(rf, "w") as fh:
                    fh.write(GOOD_MINE)

                def action():
                    os.rename(rf, rf + ".moved")
                    self.file_state(kind, rf, out, base)
                with open_hook(SID + ".yml", action, directory=False) as hk:
                    kind_, val = watched(lambda: load(base, cfg, SID))
                self.assertGreater(hk["fired"], 0)
                want = ("d1/" + SID + ".yml: is a symlink; receipt files must be regular files"
                        if kind in ("link", "dangling")
                        else "d1/" + SID + ".yml: is not a regular file; receipt files must be regular files")
                self.assertEqual((kind_, str(val)), ("err", want + "; " + REMEDY))
                self.assertEqual(hk["live"], set())
                self.assertFalse(os.path.lexists(os.path.join(out, "new.yml")))

    def test_record_file_swapped_non_regular(self):  # FS3, FS5, FS6, FS7 (record), D-Q4 (a)
        for kind in ("socket", "fifo", "dir", "link", "dangling"):
            for present in (False, True):
                with self.subTest(kind=kind, present=present):
                    base, out, parts, cfg = self.fresh(1)
                    d = os.path.join(base, "d1")
                    os.mkdir(d)
                    rf = os.path.join(d, SID + ".yml")
                    if present:
                        with open(rf, "w") as fh:
                            fh.write(GOOD_MINE)

                    def action():
                        if os.path.lexists(rf):
                            os.rename(rf, rf + ".moved")
                        self.file_state(kind, rf, out, base)
                    with open_hook(SID + ".yml", action, directory=False) as hk:
                        kind_, val = watched(lambda: record(base, cfg, SID, "a.txt"))
                    self.assertGreater(hk["fired"], 0)
                    want = ("d1/" + SID + ".yml: is a symlink; receipt files must be regular files"
                            if kind in ("link", "dangling")
                            else "d1/" + SID + ".yml: is not a regular file; receipt files must be regular files")
                    self.assertEqual((kind_, str(val)), ("err", want))
                    self.assertEqual(hk["live"], set())
                    self.assertFalse(os.path.lexists(os.path.join(out, "new.yml")))

    def test_file_open_error_keeps_strerror(self):  # FS11, FS12: a regular file after the failure keeps its strerror
        os.makedirs(self.rdir)
        self.put_rf(GOOD_MINE.encode())
        real_open = os.open

        def op(n, flags, *a, **k):
            if n == SID + ".yml" and "dir_fd" in k:
                raise OSError(errno.EIO, "Input/output error")
            return real_open(n, flags, *a, **k)
        with mock.patch.object(receipts.os, "open", op):
            with self.assertRaises(GateError) as cm:
                record(self.root, self.cfg, SID, "a.txt")
            self.assertEqual(str(cm.exception), ".strict-delivery/receipts/" + SID + ".yml: cannot append (Input/output error)")
            with self.assertRaises(GateError) as cm:
                load(self.root, self.cfg, SID)
            self.assertEqual(str(cm.exception), ".strict-delivery/receipts/" + SID
                             + ".yml: cannot read file (Input/output error); " + REMEDY)

    def test_sentence_not_chosen_by_errno(self):  # M13, M7: the same refusal whatever errno the platform gives
        real_open = os.open
        for err in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENXIO, errno.EOPNOTSUPP, errno.EIO, errno.EISDIR):
            for kind in ("link", "dangling", "fifo", "file"):
                with self.subTest(err=errno.errorcode[err], kind=kind):
                    base, out, parts, cfg = self.fresh(2)
                    os.mkdir(os.path.join(base, "d1"))

                    def op(n, flags, *a, **k):
                        if n == "d2" and "dir_fd" in k:
                            raise OSError(err, os.strerror(err))  # whatever this platform says for the swapped name
                        return real_open(n, flags, *a, **k)
                    at = os.path.join(base, "d1", "d2")
                    if kind in ("link", "dangling"):
                        os.symlink(out if kind == "link" else os.path.join(out, "nope"), at)
                        want = S_LINK % "d1/d2"
                    elif kind == "fifo":
                        os.mkfifo(at)
                        want = S_NOTDIR % "d1/d2"
                    else:
                        open(at, "w").close()
                        want = S_NOTDIR % "d1/d2"
                    with mock.patch.object(receipts.os, "open", op):
                        for fn in (lambda: record(base, cfg, SID, "a.txt"), lambda: load(base, cfg, SID)):
                            kind_, val = watched(fn)
                            self.assertEqual((kind_, str(val)), ("err", want))
                    self.assertFalse(os.path.lexists(os.path.join(out, "nope")))

    def test_file_sentence_not_chosen_by_errno(self):  # M13, M14: the receipt file's sentence, whatever the errno
        real_open = os.open
        for err in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENXIO, errno.EOPNOTSUPP, errno.EIO, errno.EISDIR):
            for kind in ("link", "dangling", "fifo", "dir", "socket"):
                with self.subTest(err=errno.errorcode[err], kind=kind):
                    base, out, parts, cfg = self.fresh(1)
                    os.mkdir(os.path.join(base, "d1"))
                    rf = os.path.join(base, "d1", SID + ".yml")
                    self.file_state(kind, rf, out, base)

                    def op(n, flags, *a, **k):
                        if n == SID + ".yml" and "dir_fd" in k:
                            raise OSError(err, os.strerror(err))
                        return real_open(n, flags, *a, **k)
                    shown = "d1/" + SID + ".yml"
                    want = (F_LINK if kind in ("link", "dangling") else F_NONREG) % shown
                    with mock.patch.object(receipts.os, "open", op):
                        kind_, val = watched(lambda: record(base, cfg, SID, "a.txt"))
                        self.assertEqual((kind_, str(val)), ("err", want))
                        kind_, val = watched(lambda: load(base, cfg, SID))
                        self.assertEqual((kind_, str(val)), ("err", want + "; " + REMEDY))

    # -- content_sha (U-A, rows CS-F1..CS-F6) ------------------------------------------------------------------------

    def hashed_tree(self, depth):
        """A real tree below the temp directory: ``c1/.../c<depth>/f.txt`` holding b"abc"."""
        ReceiptsDirRace.n += 1
        top = os.path.join(self.tmp, "h%d" % self.n)
        parts = ["c%d" % i for i in range(1, depth + 1)]
        path = self.put("/".join(parts + ["f.txt"]), b"abc", base=top)
        return top, parts, path

    def test_content_sha_refuses_final_symlink_swap(self):  # CS-F1, M-final-nofollow
        for kind in ("in", "out", "dangling"):
            with self.subTest(kind=kind):
                top, parts, path = self.hashed_tree(1)
                out = self.other()

                def action():
                    os.rename(path, path + ".moved")
                    if kind == "in":
                        os.symlink(path + ".moved", path)
                    elif kind == "out":
                        self.put("o.txt", b"other", base=out)
                        os.symlink(os.path.join(out, "o.txt"), path)
                    else:
                        os.symlink(os.path.join(out, "nope"), path)
                with open_hook("f.txt", action, directory=False) as hk:
                    with self.assertRaises(GateError) as cm:
                        content_sha(path)
                self.assertGreater(hk["fired"], 0)
                self.assertEqual(str(cm.exception), path + ": is a symlink")
                self.assertEqual(hk["live"], set())

    def test_content_sha_refusal_leaves_no_row(self):  # CS-F1 through record
        os.makedirs(self.rdir)
        out = self.other()
        self.put("o.txt", b"other", base=out)
        real = os.path.join(self.real, "a.txt")

        def action():
            os.rename(real, real + ".moved")
            os.symlink(os.path.join(out, "o.txt"), real)
        with open_hook("a.txt", action, directory=False) as hk:
            with self.assertRaisesRegex(GateError, "a.txt: is a symlink$"):
                record(self.root, self.cfg, SID, "a.txt")
        self.assertGreater(hk["fired"], 0)
        self.assertFalse(os.path.lexists(self.rf))

    def test_content_sha_refuses_dir_component_swap(self):  # CS-F2, M-component-nofollow
        for depth in (1, 2, 3):
            for pos in range(1, depth + 1):
                for kind in ("in", "out", "dangling"):
                    with self.subTest(depth=depth, pos=pos, kind=kind):
                        top, parts, path = self.hashed_tree(depth)
                        out = self.other()
                        at = os.path.join(top, *parts[:pos])

                        def action():
                            os.rename(at, at + ".moved")
                            if kind == "in":
                                os.symlink(at + ".moved", at)
                            elif kind == "out":
                                d = os.path.join(out, "o", *parts[pos:])
                                os.makedirs(d, exist_ok=True)
                                with open(os.path.join(d, "f.txt"), "wb") as fh:
                                    fh.write(b"other")
                                os.symlink(os.path.join(out, "o"), at)
                            else:
                                os.symlink(os.path.join(out, "nope"), at)
                        with open_hook(parts[pos - 1], action, directory=True) as hk:
                            with self.assertRaises(GateError) as cm:
                                content_sha(path)
                        self.assertGreater(hk["fired"], 0)
                        self.assertEqual(str(cm.exception), S_LINK % at)
                        self.assertEqual(hk["live"], set())

    def test_content_sha_refuses_non_regular_swap(self):  # CS-F3, M-nonblock, M-fstat
        for kind in ("fifo", "dir", "socket"):
            with self.subTest(kind=kind):
                top, parts, path = self.hashed_tree(1)

                def action():
                    os.rename(path, path + ".moved")
                    if kind == "fifo":
                        os.mkfifo(path)
                    elif kind == "dir":
                        os.mkdir(path)
                    else:
                        bind_socket(path)
                with open_hook("f.txt", action, directory=False) as hk:
                    kind_, val = watched(lambda: content_sha(path))
                self.assertGreater(hk["fired"], 0)
                self.assertEqual((kind_, str(val)), ("err", path + ": is not a regular file"))
                self.assertEqual(hk["live"], set())

    def test_content_sha_regular_files_unchanged(self):  # CS-F4 (with the CS1-CS27 tests above)
        for depth in (1, 2, 3):
            top, parts, path = self.hashed_tree(depth)
            self.assertEqual(content_sha(path), blob(b"abc"))
        self.assertEqual(content_sha(self.put("e", b"")), EMPTY)

    def test_content_sha_fails_closed_without_dir_fd_support(self):  # CS-F5, M-support
        top, parts, path = self.hashed_tree(1)
        cur = set(os.supports_dir_fd)
        want = path + ": cannot read file (directory descriptors are not supported on this platform)"
        cases = [("supports_dir_fd", set()), ("supports_dir_fd", cur - {os.open}), ("supports_dir_fd", cur - {os.stat}),
                 ("supports_follow_symlinks", set(os.supports_follow_symlinks) - {os.stat})]
        for attr, value in cases:
            with self.subTest(attr=attr, n=len(value)):
                with mock.patch.object(os, attr, value):
                    with open_hook(None, None) as hk:
                        with self.assertRaises(GateError) as cm:
                            content_sha(path)
                self.assertEqual(str(cm.exception), want)
                self.assertEqual(hk["live"], set())
        for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"):
            with self.subTest(flag=name):
                saved = getattr(os, name)
                delattr(os, name)
                try:
                    with self.assertRaises(GateError) as cm:
                        content_sha(path)
                finally:
                    setattr(os, name, saved)
                self.assertEqual(str(cm.exception), want)

    def test_content_sha_missing_directory_component(self):  # CS-F2 sibling: a missing component is the usual refusal
        top, parts, path = self.hashed_tree(1)
        p = top + "/nodir/f.txt"
        with self.assertRaises(GateError) as cm:
            content_sha(p)
        self.assertEqual(str(cm.exception), p + ": cannot read file (No such file or directory)")

    def test_root_that_is_not_a_directory_when_opened(self):  # the walk's root open, CD3 (root swapped after _top)
        base, out, parts, cfg = self.fresh(1)
        notdir = os.path.join(base, "a.txt")
        for fn in (lambda: load(base, cfg, SID), lambda: record(base, cfg, SID, "a.txt")):
            with mock.patch.object(receipts, "_top", return_value=notdir), \
                    mock.patch.object(receipts, "content_sha", return_value=blob(b"a")):
                with self.assertRaises(GateError) as cm:
                    fn()
            self.assertEqual(str(cm.exception), "root: cannot use the receipts directory (Not a directory)")

    def test_content_sha_refuses_unresolved_path(self):  # CS-F6
        top, parts, path = self.hashed_tree(2)
        for p in ("rel.txt", "c1/c2/f.txt", ".", "", "/", path + "/", top + "//c1/c2/f.txt", top + "/c1/../c1/c2/f.txt",
                  top + "/./c1/c2/f.txt", "//" + path[1:]):
            with self.subTest(p=p):
                with self.assertRaises(GateError) as cm:
                    content_sha(p)
                self.assertEqual(str(cm.exception), p + ": path must be absolute and normalised")
        self.assertEqual(content_sha(path), blob(b"abc"))


if __name__ == "__main__":
    unittest.main()
