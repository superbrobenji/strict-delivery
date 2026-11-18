"""Task P2.2 part c: the rows of task-P2.2-domain.md for ``program status``, ``request new``, ``request set``,
``sync-log`` and ``merged`` that parts a and b left without a test (row ids in the comments), and the version rows
V1-V3. Expected values are written by hand; every git fixture is a ``make_repo`` repository."""
import ast
import builtins
import datetime
import os
import sys
import unittest
from unittest import mock

from gates.tools import program_cli
from tests.helpers import commit_all, git
from tests.test_program_cli import DEC, NAME, Fx, load_yaml, run
from tests.test_program_merged import RecFx, merged_line

REQ = ("--from", "a", "--to", "b", "--file", "b/x.py", "--interface", "spec.md:1", "--need", "x", "--by", "a")


class AfterC(Fx):
    """A created and committed program (the setUp of ``After``, without its tests)."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.create()[0], 0)
        self.commit_iw()

    def cli(self, sub, *argv):
        return run("program", *sub.split(" "), NAME, *argv, "--root", self.iw)

    def page(self):
        return os.path.join(self.folder(), "status.md")

    def new_request(self, *argv):
        code, out, err = self.cli("request new", *(argv or REQ))
        self.assertEqual(code, 0, err)
        return out.splitlines()[-1]

    def request_file(self, rid):
        return os.path.join(self.folder(), "requests", rid + ".yml")

    def unchanged(self, path, *cmds):
        with open(path, "rb") as fh:
            before = fh.read()
        for sub, argv in cmds:
            with self.subTest(argv):
                code, out, err = self.cli(sub, *argv)
                self.assertEqual((code, out), (1, ""), err)
                self.assertNotIn("Traceback", err)
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(), before)


class StatusC(AfterC):
    def test_status_unknown_stream(self):  # ST2, ST13: the row is selected by exact string equality
        self.unchanged(self.page(), *[("status", (s, "--used", "1")) for s in ("A", "a ", "a" * 4301, "ab", "")])

    def test_status_text_forms(self):  # ST6
        bad = ("x|y", "x\\|y", "x\ny", "x\ry", "x\0y", "x\ty", " x", "x ", "", "café", "ࡰ")
        for flag in ("--block", "--next-task", "--delivers"):
            self.unchanged(self.page(), *[("status", ("a", flag, v)) for v in bad])
        code, out, err = self.cli("status", "a", "--block", "A1", "--next-task", "A1.1", "--delivers", "one: two #3")
        self.assertEqual(code, 0, err)

    def test_status_blockers_and_pending(self):  # ST7, ST8
        rid = self.new_request()
        self.commit_iw()
        self.unchanged(self.page(), *[("status", ("a", "--blockers", v)) for v in
                                      ("R-20261101-aaaa", DEC, "NONE", "", rid + ", " + rid, "x")] +
                       [("status", ("a", "--pending", v)) for v in ("nope", rid, "NONE", "")] +
                       [("status", ("a", "--status", "ready", "--status", "running")),
                        ("status", ("a", "--blockers", "none", "--blockers", "none"))])
        self.assertEqual(self.cli("status", "a", "--blockers", rid, "--pending", DEC)[0], 0)
        self.assertEqual(self.cli("status", "a", "--blockers", "none", "--pending", "none")[0], 0)

    def test_status_refuses_invalid_page(self):  # ST9
        with open(self.page(), encoding="utf-8") as fh:
            good = fh.read()
        lines = good.split("\n")
        for name, text in (("header", good.replace("| stream |", "|  stream |", 1)), ("missing row", "\n".join(lines[:3] + lines[4:])),
                           ("extra row", good.replace("\n", "\n", 1).rstrip("\n") + "\n" + lines[4] + "\n"),
                           ("ten cells", good.replace("| does a |", "|", 1)), ("blank", "")):
            with self.subTest(name):
                with open(self.page(), "w", encoding="utf-8") as fh:
                    fh.write(text)
                self.unchanged(self.page(), ("status", ("a", "--used", "1")))

    def test_status_file_kinds(self):  # ST11
        with open(self.page(), "rb") as fh:
            good = fh.read()
        for name, data in (("bom", b"\xef\xbb\xbf" + good), ("crlf", good.replace(b"\n", b"\r\n")), ("utf8", b"\xff\xfe")):
            with self.subTest(name):
                with open(self.page(), "wb") as fh:
                    fh.write(data)
                self.unchanged(self.page(), ("status", ("a", "--used", "1")))
        os.unlink(self.page())
        self.assertEqual(self.cli("status", "a", "--used", "1")[0], 1)            # absent
        os.mkdir(self.page())
        self.assertEqual(self.cli("status", "a", "--used", "1")[0], 1)            # a directory
        os.rmdir(self.page())
        os.symlink(os.path.join(self.tmp, "elsewhere.md"), self.page())
        self.assertEqual(self.cli("status", "a", "--used", "1")[0], 1)            # a symlink is never followed

    def test_status_final_newline_and_prose(self):  # ST12, ST14
        with open(self.page(), encoding="utf-8") as fh:
            good = fh.read()
        with open(self.page(), "w", encoding="utf-8") as fh:
            fh.write(good + "\nNotes follow here.\n")
        self.assertEqual(self.cli("status", "a", "--used", "2")[0], 0)
        with open(self.page(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.endswith("\nNotes follow here.\n"))
        self.assertEqual(text.count("| 2 |"), 1)
        with open(self.page(), "w", encoding="utf-8") as fh:
            fh.write(good.rstrip("\n"))
        self.assertEqual(self.cli("status", "a", "--used", "2")[0], 0)
        with open(self.page(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), good.rstrip("\n").replace("| 0 | ready | none | none | does a |",
                                                                  "| 2 | ready | none | none | does a |"))


class RequestC(AfterC):
    def test_request_id_date_from_utc_today(self):  # RN2: the date is ids.utc_today, never the clock read here
        with mock.patch.object(program_cli.ids, "utc_today", return_value=datetime.date(2026, 11, 2)):
            rid = self.new_request()
        self.assertTrue(rid.startswith("R-20261102-"), rid)
        self.assertTrue(os.path.isfile(self.request_file(rid)))

    def test_request_new_interface_cite(self):  # RN6
        for v in ("../spec.md", "/spec.md", "spec.md#", "spec.md#a#b", "caf\u00e9", "a//b", "a/./b"):
            with self.subTest(v):
                code, out, err = self.cli("request new", *REQ[:6], "--interface", v, "--need", "x", "--by", "a")
                self.assertEqual((code, out), (1, ""), err)
        self.assertFalse(os.path.exists(os.path.join(self.folder(), "requests")))

    def test_request_need_roundtrip(self):  # RN8: load(emit(row)) == row for texts that need quoting
        for need in ("a: b", "- x", "|", ">", '"', "&x", "#c", "a #b", "x:", "[a]", "{a}", "true", "null", "123", "~",
                     "'q'", "%x", "a\\b", "a|b", "*x", "!t", "@x", "`x", "1e3", "0x1f", "- x", "x" * 4301):
            with self.subTest(need[:20]):
                rid = self.new_request(*REQ[:-4], "--need", need, "--by", "a")
                self.assertEqual(load_yaml(self.request_file(rid))["need"], need)
        for need in ("", " x", "x ", "a\nb", "a\0b", "a\tb", "café", "ࡰ"):
            with self.subTest(repr(need)[:20]):
                self.assertEqual(self.cli("request new", *REQ[:-4], "--need", need, "--by", "a")[0], 1)

    def test_request_new_by(self):  # RN9, RS10
        for by in ("b", "program"):
            self.new_request(*REQ[:-1], by)
        for by in ("zz", "", "A", "a ", "café"):
            self.assertEqual(self.cli("request new", *REQ[:-1], by)[0], 1, by)
        rid = self.new_request()
        for by in ("zz", "", "A"):
            self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", by)[0], 1, by)
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "program")[0], 0)

    def test_request_ids_unique_across_registers(self):  # RN11: the mint is given every id of the registers
        rid = self.new_request()
        self.commit_iw()
        seen = []
        real = program_cli.ids.mint

        def spy(fmt, existing, today, rng):
            seen.append(set(existing))
            return real(fmt, existing, today, rng)

        with mock.patch.object(program_cli.ids, "mint", spy):
            self.new_request()
        self.assertLessEqual({DEC, rid}, seen[0])

    def test_request_new_twice_and_single_flags(self):  # RN16, RN17
        self.assertNotEqual(self.new_request(), self.new_request())
        self.assertEqual(len(os.listdir(os.path.join(self.folder(), "requests"))), 2)
        for flag, val in (("--from", "a"), ("--need", "y"), ("--by", "a"), ("--interface", "spec.md:2"), ("--to", "b")):
            with self.subTest(flag):
                self.assertEqual(self.cli("request new", *REQ, flag, val)[0], 1)

    def test_request_set_unknown_id(self):  # RS7
        before = os.listdir(self.folder())
        for rid in ("R-20261101-aaaa", "x", "R-20261101-AAAA", ".." + os.sep + "streams", "R-" + "9" * 4301):
            with self.subTest(rid[:20]):
                code, out, err = self.cli("request set", rid, "--status", "accepted", "--by", "b")
                self.assertEqual((code, out), (1, ""))
                self.assertNotIn("Traceback", err)
        self.assertEqual(os.listdir(self.folder()), before)

    def test_request_set_changes_only_status_fields(self):  # RS8, RS9
        rid = self.new_request()
        old = load_yaml(self.request_file(rid))
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 0)
        new = load_yaml(self.request_file(rid))
        self.assertEqual({k: v for k, v in new.items() if k != "status"}, {k: v for k, v in old.items() if k != "status"})
        self.assertEqual(new["status"], "accepted")
        self.assertEqual(self.cli("request set", rid, "--status", "withdrawn", "--by", "a")[0], 0)
        self.assertIn("PASS schema.request", run("check", "schema", "--root", self.iw)[1])

    def test_request_set_status_forms(self):  # RS11
        rid = self.new_request()
        self.unchanged(self.request_file(rid), *[("request set", (rid, "--status", s, "--by", "b")) for s in
                                                 ("Accepted", "accepted ", "", "5", "open", "done", "x" * 4301)] +
                       [("request set", (rid, "--by", "b")), ("request set", (rid, "--status", "accepted", "--by", "b",
                                                                              "--status", "accepted"))])

    def test_request_set_file_kinds(self):  # RS12
        rid = self.new_request()
        path = self.request_file(rid)
        for name, data in (("yaml error", b"a: [\n"), ("other schema", b"schema: finding/1\n"), ("empty", b"")):
            with self.subTest(name):
                with open(path, "wb") as fh:
                    fh.write(data)
                self.unchanged(path, ("request set", (rid, "--status", "accepted", "--by", "b")))
        os.unlink(path)
        os.mkdir(path)
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 1)

    def test_request_set_many_commits(self):  # RS14: resolution.commits holds every --commit, in the order given
        rid = self.new_request()
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 0)
        git(self.work, "checkout", "-q", "-b", NAME + "/b/main", "main")
        shas = []
        for i in range(3):
            self.write_main("b/x.py", "x = %d\n" % i)
            shas.append(commit_all(self.work, "b work %d" % i))
        git(self.work, "checkout", "-q", "main")
        argv = ["request set", rid, "--status", "done", "--by", "b"]
        flags = [a for s in shas for a in ("--commit", s)]
        code, out, err = self.cli(*argv, *flags)
        self.assertEqual(code, 0, err)
        self.assertEqual(load_yaml(self.request_file(rid))["resolution"]["commits"], shas)


class SyncC(AfterC):
    def line(self, **kw):
        main = git(self.work, "rev-parse", "main")
        argv = ["--main", kw.get("main", main), "--merged-main", "no", "--tests", "PASS"]
        for flag in ("--updated", "--combined", "--question"):
            for v in kw.get(flag, ()):
                argv += [flag, v]
        return self.cli("sync-log", *argv)

    def log(self):
        return os.path.join(self.folder(), "sync-log.md")

    def test_sync_main_forms(self):  # SL2, SL10
        main = git(self.work, "rev-parse", "main")
        for v in (main.upper(), "HEAD", "main", "", main + "0", "f" * 4301, main[:12]):
            with self.subTest(v[:12]):
                self.unchanged(self.log(), ("sync-log", ("--main", v, "--merged-main", "no", "--tests", "PASS")))
        self.unchanged(self.log(), ("sync-log", ("--main", main, "--main", main, "--merged-main", "no", "--tests", "PASS")))

    def test_sync_updated_combined_and_questions(self):  # SL5, SL6, SL7, SL12
        for kw in ({"--updated": ["none"]}, {"--updated": ["a,b"]}, {"--combined": ["A"]}, {"--updated": ["a", "a"]},
                   {"--question": ["DEC-1"]}, {"--question": [DEC, DEC]}, {"--question": ["none"]}):
            with self.subTest(kw):
                self.unchanged(self.log(), ("sync-log", ("--main", git(self.work, "rev-parse", "main"), "--merged-main",
                                                         "no", "--tests", "PASS", *[x for f, vs in kw.items() for v in vs
                                                                                   for x in (f, v)])))
        self.assertEqual(self.line(**{"--combined": ["b"]})[0], 0)                  # combined without updated
        self.assertEqual(self.line(**{"--combined": ["b", "a"], "--updated": ["a"]})[0], 0)
        self.assertEqual(self.line(**{"--updated": ["a"], "--combined": ["a", "b"]})[0], 0)
        with open(self.log(), encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        self.assertIn("updated=none combined=b ", lines[1])
        self.assertEqual(lines[2].split(" updated=")[1], lines[3].split(" updated=")[1])   # flag order: the same line

    def test_sync_appends_to_valid_log(self):  # SL8, SL9, SL11
        with open(self.log(), "w", encoding="utf-8") as fh:
            fh.write("<!-- schema: sync-log/1 -->")                              # no final newline
        self.unchanged(self.log(), ("sync-log", ("--main", git(self.work, "rev-parse", "main"), "--merged-main", "no",
                                                 "--tests", "PASS")))
        with open(self.log(), "w", encoding="utf-8") as fh:
            fh.write("<!-- schema: sync-log/1 -->\nSYNC bogus\n")                # a malformed earlier line
        self.unchanged(self.log(), ("sync-log", ("--main", git(self.work, "rev-parse", "main"), "--merged-main", "no",
                                                 "--tests", "PASS")))
        with open(self.log(), "w", encoding="utf-8") as fh:
            fh.write("<!-- schema: sync-log/1 -->\n")
        gitdir = git(self.iw, "rev-parse", "--absolute-git-dir")
        with open(os.path.join(gitdir, "MERGE_HEAD"), "w", encoding="utf-8") as fh:
            fh.write(git(self.iw, "rev-parse", "HEAD") + "\n")                     # a sync may be written mid-merge
        self.assertEqual(self.line()[0], 0)
        self.assertEqual(self.line()[0], 0)
        with open(self.log(), encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().split("\n")), 4)


class MergedC(RecFx):
    def new(self, line):
        code, out, err = self.merged(line)
        return code, err

    def test_merged_earlier_lines_not_revalidated(self):  # MG10, D-Q4
        head, m = self.pr("release", [("6R", "6R.1")])
        with open(os.path.join(self.folder(), "merged.md"), "a", encoding="utf-8") as fh:
            fh.write(merged_line(90, "1" * 40, "2" * 40, "release", "6R") + "\n")      # unknown objects: fails merged_errors
        self.commit_iw()
        self.assertEqual(self.new(merged_line(91, head, m, "release", "6R")), (0, ""))

    def test_merged_at_forms(self):  # MG15
        head, m = self.pr("release", [("6R", "6R.1")])
        base = merged_line(1, head, m, "release", "6R")
        for at in ("2026-13-01T10:00:00Z", "2026-11-01T25:00:00Z", "2026-11-01", "2026-11-01T10:00:00", "x"):
            with self.subTest(at):
                code, err = self.new(base.replace("2026-11-01T10:00:00Z", at))
                self.assertEqual(code, 1)
                self.assertNotIn("Traceback", err)
        self.assertEqual(self.new(base.replace("2026-11-01T10:00:00Z", "2099-01-01T00:00:00Z")), (0, ""))   # a future time

    def test_merged_pr_digits(self):  # MG14, V1
        head, m = self.pr("release", [("6R", "6R.1")])
        for n in (601, 4300, 4301):
            with self.subTest(n):
                code, err = self.new(merged_line(int("9" * n) if n < 4301 else 0, head, m, "release", "6R")
                                     .replace("pr=0 ", "pr=" + "9" * n + " "))
                self.assertEqual(code, 1)
                self.assertNotIn("Traceback", err)


class VersionRows(unittest.TestCase):
    def test_no_int_of_text_and_no_exception_groups(self):  # V1, V3
        for rel in ("gates/tools/program_cli.py", "gates/lib/breakdown.py"):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *rel.split("/"))
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src)
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "int"]
            self.assertEqual(calls, [], rel)                                  # V1: no int() of text anywhere
            self.assertNotIn("except*", src)                                  # V3: 3.9 cannot parse it
            self.assertNotIn("ExceptionGroup", src)
            self.assertNotIn("TryStar", src)

    @unittest.skipUnless(hasattr(builtins, "ExceptionGroup"), "ExceptionGroup exists from 3.11")
    def test_exception_group_is_not_swallowed(self):  # V3: main catches GateError only
        with mock.patch.object(program_cli.gitinfo, "current_branch", side_effect=builtins.ExceptionGroup(
                "x", [ValueError()])), mock.patch.object(program_cli.index, "_root", return_value="/nonexistent"), \
                mock.patch.object(program_cli.config, "load", return_value={}):
            with self.assertRaises(builtins.ExceptionGroup):
                program_cli.main(["status", NAME, "a", "--used", "1"])

    def test_non_ascii_refused_alike(self):  # V2: U+0870, U+2C2F, U+1FAE8 are refused by ordinal on every interpreter
        for ch in ("ࡰ", "Ⱟ", "\U0001fae8"):
            code, out, err = run("program", "status", NAME, "a", "--delivers", "x" + ch)
            self.assertEqual((code, out), (1, ""))
            self.assertIn("U+%04X is not allowed" % ord(ch), err)
