"""Task 5a.2: ``gates/schemas/receipt.yml`` and ``gates/lib/receipts.py`` (plan 5194-5243; domain table 5a.2 with its
binding controller decisions D-Q1 (a) (``load`` also needs 40-hex shas and a final newline), D-Q2 (a)
(``O_NOFOLLOW | O_NONBLOCK`` and a regular-file check), PD1-PD14). Expected values are written by hand: blob ids from
git's own rule ``sha1("blob <n>\\0" + bytes)`` (and compared with ``git hash-object --no-filters``), the golden
receipt bytes in full. Receipt files read by ``load`` are written by hand, never by ``record``."""
import copy
import errno
import hashlib
import os
import stat
import subprocess
import sys
import threading
import unittest
from unittest import mock

from gates.lib import config, receipts, schema, yamlsub
from gates.lib.receipts import content_sha, load, record, session_problem
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, INT_LIMITS, git, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SID = "3f2b8c1e-9d4a-4b7e-8f10-2a6c5d9e0b13"
HDR = "schema: receipt/1\nreads:\n"
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
        return {"schema": "receipt/1", "reads": reads}

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
                self.assertEqual(self.valid({"schema": "receipt/1", "reads": [], key: 3}), [key + ": unknown key"])
        self.assertEqual(self.valid({"schema": "receipt/1", "Reads": []}),
                         ["reads: required key is missing", "Reads: unknown key"])

    def test_receipt_schema_reads_type(self):  # SC6
        self.assertEqual(self.valid({"schema": "receipt/1"}), ["reads: required key is missing"])
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
        for text in ("schema: receipt/1\nschema: receipt/1\nreads: []\n",
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

    def test_content_sha_follows_symlink(self):  # CS14
        t = self.put("t", b"abc")
        os.symlink(t, self.root + "/lnk")
        self.assertEqual(content_sha(self.root + "/lnk"), blob(b"abc"))

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
        with self.assertRaisesRegex(GateError, "not a regular file"):
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
        with self.assertRaisesRegex(GateError, "invalid path: UnicodeEncodeError"):
            content_sha("/tmp/x\ud800")
        with self.assertRaisesRegex(GateError, "No such file"):
            content_sha("/tmp/x\udcff")

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

    def test_content_sha_relative_is_cwd(self):  # CS23
        p = self.put("rel.txt", b"rel")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        self.assertEqual(content_sha("rel.txt"), blob(b"rel"))
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
        self.assertEqual(len(opened), 3)
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
        with self.assertRaisesRegex(GateError, "is not a directory"):
            self.rec()

    def test_parallel_first_creation(self):  # RD9
        procs = [subprocess.Popen([sys.executable, "-m", "gates.tools.receipt_cli", "add", "--session", SID, "--path",
                                   "a.txt", "--root", self.root], cwd=self.tmp, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1"))
                 for _ in range(20)]
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual((p.returncode, err), (0, b""), err)
        self.assertEqual(len(load(self.root, self.cfg, SID)), 20)

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

    def absent(self, real_lstat):
        try:
            real_lstat(self.rf)
        except FileNotFoundError:
            return True
        return False

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
            if a[0] == self.rf:
                opened.append(fd)
                live.add(fd)
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
            if path == self.rf:
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

    def test_symlink_swapped_in_after_lstat_is_refused_by_nofollow(self):  # RF16/RF17, O_NOFOLLOW alone
        target = os.path.join(self.other(), "new.yml")
        os.makedirs(self.rdir)
        real_lstat = os.lstat

        def lstat(p, *a, **k):
            if p == self.rf and self.absent(real_lstat):
                os.symlink(target, self.rf)  # swapped in between the lstat and the open
                raise FileNotFoundError(errno.ENOENT, "No such file or directory")
            return real_lstat(p, *a, **k)
        with mock.patch.object(receipts.os, "lstat", lstat):
            with self.assertRaisesRegex(GateError, "cannot append"):
                self.rec()
        self.assertFalse(os.path.lexists(target))

    def test_receipt_file_fifo_swapped_in_after_lstat_never_blocks(self):  # RF15, O_NONBLOCK and fstat alone
        os.makedirs(self.rdir)
        real_lstat = os.lstat
        res = []

        def lstat(p, *a, **k):
            if p == self.rf and self.absent(real_lstat):
                os.mkfifo(self.rf)
                raise FileNotFoundError(errno.ENOENT, "No such file or directory")
            return real_lstat(p, *a, **k)

        def go():
            with mock.patch.object(receipts.os, "lstat", lstat):
                try:
                    self.rec()
                except GateError as e:
                    res.append(e)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(res), 1)

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
            if a[0] == self.rf:
                opened.append(fd)
                live.add(fd)
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
        self.put_rf(b"schema: receipt/1\nreads: []\n")
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
        for text in ("schema: receipt/2\nreads: []\n", "schema: receipt/1\nreads: []\nextra: 1\n",
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
        for data in (b"schema: receipt/1\nschema: receipt/1\nreads: []\n", b"schema: receipt/1\nreads:\n\t- a\n",
                     b"schema: receipt/1\nreads: {a: 1}\n", b"schema: &x receipt/1\nreads: []\n",
                     b"schema: receipt/1\nreads: []\x00\n", b"schema: receipt/1\nreads: [\xff]\n",
                     b"schema: receipt/1\nreads: " + b"9" * 1001 + b"\n"):
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
        self.assertRegex(self.msg(), "receipts: is not a directory")

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

    def test_load_symlink_swapped_in_after_lstat(self):  # R1-1: O_NOFOLLOW on the open of load
        valid = self.put("valid.yml", self.GOOD.encode(), base=self.other())
        os.makedirs(self.rdir)
        self.put_rf(b"")
        real_lstat = os.lstat

        def lstat(p, *a, **k):
            st = real_lstat(p, *a, **k)
            if p == self.rf and not stat.S_ISLNK(st.st_mode):
                os.unlink(self.rf)
                os.symlink(valid, self.rf)  # swapped in between the lstat and the open
            return st
        with mock.patch.object(receipts.os, "lstat", lstat):
            self.assertRegex(self.msg(), "is a symlink; receipt files must be regular files; " + REMEDY)

    def test_load_fifo_swapped_in_after_lstat_never_blocks(self):  # R1-1: O_NONBLOCK and the fstat check
        os.makedirs(self.rdir)
        self.put_rf(b"")
        real_lstat = os.lstat

        def lstat(p, *a, **k):
            st = real_lstat(p, *a, **k)
            if p == self.rf and stat.S_ISREG(st.st_mode):
                os.unlink(self.rf)
                os.mkfifo(self.rf)
            return st
        res = []

        def go():
            with mock.patch.object(receipts.os, "lstat", lstat):
                res.append(self.msg())
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertRegex(res[0], "is not a regular file; receipt files must be regular files; " + REMEDY)

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


if __name__ == "__main__":
    unittest.main()
