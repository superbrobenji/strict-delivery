"""Tests of gates.lib.transcript (Task 3a.2 input-domain rows T1-T10, V1, V2; measured shape M3).

Fixtures are real JSONL files in a temporary directory, with the measured field names and synthetic values. Expected
values are written by hand from the plan (P:3487, P:3906-3907) and the table, never read back from the code."""
import json
import os
import sys
import tempfile
import unittest

from gates.lib import transcript
from gates.lib.hookio import HookContext
from tests.helpers import int_limit

DIGIT_LIMITS = (None, 0) if hasattr(sys, "set_int_max_str_digits") else (None,)


def user(content, **extra):
    row = {"type": "user", "message": {"role": "user", "content": content}, "uuid": "u-1"}
    row.update(extra)
    return json.dumps(row)


def other(kind):
    return json.dumps({"type": kind, "uuid": "x-" + kind, "message": {"role": kind, "content": "ignored"}})


def ctx(agent_id=None, transcript_path=None, session_id="s1"):
    return HookContext(event="PreToolUse", tool_name="Bash", tool_input={}, session_id=session_id, agent_id=agent_id,
                       transcript_path=transcript_path, cwd="/", root="/", cfg=None, cfg_error=None,
                       framework_dir="/", env={}, raw={})


class TmpCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        self.count = 0

    def write(self, data, name=None):
        self.count += 1
        path = os.path.join(self.tmp, name or ("t%d.jsonl" % self.count))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class FirstPromptShapes(TmpCase):
    def test_first_prompt_shapes(self):   # T1, T2, T3, T4, T8, T10
        text_block = lambda t: {"type": "text", "text": t}
        cases = [
            # T1 content shapes
            ("T1 str", user("hello"), "hello"),
            ("T1 text blocks joined with empty string", user([text_block("ab"), text_block("cd")]), "abcd"),
            ("T1 text and image", user([text_block("a"), {"type": "image", "source": {"type": "base64"}}, text_block("b")]), "ab"),
            ("T1 text and tool_result", user([{"type": "tool_result", "tool_use_id": "t", "content": "zz"}, text_block("q")]), "q"),
            ("T1 no text block", user([{"type": "image", "source": {}}]), None),
            ("T1 empty list", user([]), None),
            ("T1 str empty", user(""), ""),
            ("T1 no message", json.dumps({"type": "user"}), None),
            ("T1 message not an object", json.dumps({"type": "user", "message": "s"}), None),
            ("T1 content a number", user(5), None),
            ("T1 content null", user(None), None),
            ("T1 text block with a non-str text", user([{"type": "text", "text": 5}, text_block("k")]), "k"),
            # T2 entries before it
            ("T2 summary system assistant first",
             "\n".join([other("summary"), other("system"), other("assistant"), user("real")]), "real"),
            ("T2 only non-user entries", "\n".join([other("summary"), other("assistant")]), None),
            ("T2 empty file", "", None),
            # T3 malformed line before it
            ("T3 not json", "{\n" + user("late"), None),
            ("T3 bare word", "x\n" + user("late"), None),
            ("T3 array", "[1]\n" + user("late"), None),
            ("T3 string", '"s"\n' + user("late"), None),
            ("T3 null", "null\n" + user("late"), None),
            ("T3 blank line", "\n" + user("late"), None),
            ("T3 duplicate keys", '{"type": "summary", "type": "summary"}\n' + user("late"), None),
            ("T3 NaN", '{"type": "summary", "n": NaN}\n' + user("late"), None),
            ("T3 Infinity", '{"type": "summary", "n": Infinity}\n' + user("late"), None),
            ("T3 -Infinity", '{"type": "summary", "n": -Infinity}\n' + user("late"), None),
            ("T3 not utf-8", b'\xff{"type": "summary"}\n' + user("late").encode("utf-8"), None),
            ("T3 lone surrogate bytes", b'\xed\xa0\x80\n' + user("late").encode("utf-8"), None),
            ("T3 duplicate keys nested", '{"type": "summary", "m": {"a": 1, "a": 2}}\n' + user("late"), None),
            # T4 malformed line after it
            ("T4 not json after", user("first") + "\n{", "first"),
            ("T4 not utf-8 after", user("first").encode("utf-8") + b"\n\xff\xfe\n", "first"),
            ("T4 blank after", user("first") + "\n\n", "first"),
            ("T4 second user entry ignored", user("first") + "\n" + user("second"), "first"),
            # T8 Unicode version
            ("T8 U+1FAE0 and U+2C2F raw", user("a\U0001fae0bⰯc"), "a\U0001fae0bⰯc"),
            # T10 fork transcript
            ("T10 fork boilerplate unchanged", user("<fork-boilerplate> You are a fork. Do X."),
             "<fork-boilerplate> You are a fork. Do X."),
            # not representable as UTF-8 (prompt_sha would raise): refused, decision
            ("lone surrogate in the text", '{"type": "user", "message": {"content": "a\\ud800b"}}', None),
            ("CRLF line ends", user("crlf") + "\r\n", "crlf"),
        ]
        for name, data, expected in cases:
            with self.subTest(name):
                self.assertEqual(transcript.first_prompt(self.write(data)), expected)

    def test_t8_escaped_form(self):   # T8: the escaped spelling returns the same text
        path = self.write('{"type": "user", "message": {"content": "a\\ud83e\\udee0b\\u2c2f"}}')
        self.assertEqual(transcript.first_prompt(path), "a\U0001fae0bⰯ")

    def test_first_prompt_digit_limit(self):   # T7, V1
        for limit in DIGIT_LIMITS:
            for digits, expected in ((4300, "found"), (4301, None), (4299, "found"), (5000, None)):
                for sign in ("", "-"):
                    with self.subTest(limit=limit, digits=digits, sign=sign):
                        line = '{"type": "summary", "n": %s%s}' % (sign, "1" * digits)
                        path = self.write(line + "\n" + user("found"))
                        with int_limit(limit):
                            self.assertEqual(transcript.first_prompt(path), expected)

    def test_first_prompt_digit_limit_after_entry(self):   # T4 with T7: a long number after the entry is never read
        path = self.write(user("found") + '\n{"n": %s}' % ("1" * 5000))
        self.assertEqual(transcript.first_prompt(path), "found")

    def test_deeply_nested_line_is_malformed(self):   # fail closed: a recursion error is a malformed line
        path = self.write("[" * 100000 + "]" * 100000 + "\n" + user("late"))
        self.assertEqual(transcript.first_prompt(path), None)


class FirstPromptMaxBytes(TmpCase):
    def test_first_prompt_max_bytes(self):   # T5
        entry = user("0123456789")
        n = len(entry.encode("utf-8"))
        path = self.write(entry)                       # the entry ends at byte n
        with self.subTest("ends at max_bytes"):
            self.assertEqual(transcript.first_prompt(path, n), "0123456789")
        with self.subTest("ends at max_bytes + 1"):
            self.assertEqual(transcript.first_prompt(path, n - 1), None)
        path2 = self.write(entry + "\n")               # with its line end the entry holds n + 1 bytes
        with self.subTest("newline counted, fits"):
            self.assertEqual(transcript.first_prompt(path2, n + 1), "0123456789")
        with self.subTest("newline counted, over"):
            self.assertEqual(transcript.first_prompt(path2, n), None)
        path3 = self.write(other("summary") + "\n" + entry)     # earlier lines count
        m = len(other("summary")) + 1 + n
        with self.subTest("earlier lines count, fits"):
            self.assertEqual(transcript.first_prompt(path3, m), "0123456789")
        with self.subTest("earlier lines count, over"):
            self.assertEqual(transcript.first_prompt(path3, m - 1), None)
        path4 = self.write(entry + "\n" + "x" * 50)      # bytes after the entry are not needed
        with self.subTest("bytes after the entry"):
            self.assertEqual(transcript.first_prompt(path4, n + 1), "0123456789")
        with self.subTest("max_bytes 0"):
            self.assertEqual(transcript.first_prompt(path, 0), None)
        with self.subTest("max_bytes 0 empty file"):
            self.assertEqual(transcript.first_prompt(self.write(""), 0), None)
        for bad in (-1, -4194304, True, False, 1.0, 5.5, "5", None, b"5", [5]):
            with self.subTest("ValueError", max_bytes=bad):
                with self.assertRaises(ValueError):
                    transcript.first_prompt(path, bad)

    def test_default_max_bytes_is_4_mib(self):   # signature: max_bytes = 4194304
        fits = self.write(user("ok") + "\n")
        self.assertEqual(transcript.first_prompt(fits), "ok")
        pad = '{"type": "summary", "pad": "%s"}' % ("p" * 4194304)
        late = self.write(pad + "\n" + user("late"))
        self.assertEqual(transcript.first_prompt(late), None)
        self.assertEqual(transcript.first_prompt(late, 4194304 + 4096), "late")
        import inspect
        self.assertEqual(inspect.signature(transcript.first_prompt).parameters["max_bytes"].default, 4194304)

    def test_max_bytes_checked_before_the_path(self):   # a bad max_bytes is a ValueError whatever the path
        for p in (None, os.path.join(self.tmp, "absent")):
            with self.subTest(path=p):
                with self.assertRaises(ValueError):
                    transcript.first_prompt(p, -1)


class FirstPromptPathKinds(TmpCase):
    def test_first_prompt_path_kinds(self):   # T6
        good = self.write(user("viaLink"))
        directory = os.path.join(self.tmp, "adir")
        os.mkdir(directory)
        fifo = os.path.join(self.tmp, "afifo")
        os.mkfifo(fifo)
        link = os.path.join(self.tmp, "alink")
        os.symlink(good, link)
        fifo_link = os.path.join(self.tmp, "fifolink")
        os.symlink(fifo, fifo_link)
        dangling = os.path.join(self.tmp, "dangling")
        os.symlink(os.path.join(self.tmp, "nowhere"), dangling)
        for name, path, expected in (
                ("absent", os.path.join(self.tmp, "absent.jsonl"), None),
                ("directory", directory, None),
                ("fifo, no writer", fifo, None),
                ("symlink to a regular file", link, "viaLink"),
                ("symlink to a fifo", fifo_link, None),
                ("dangling symlink", dangling, None),
                ("None", None, None),
                ("int", 5, None),
                ("bytes", good.encode("utf-8"), None),
                ("empty string", "", None),
                ("NUL in the path", good + "\0x", None),
                ("regular file", good, "viaLink")):
            with self.subTest(name):
                self.assertEqual(transcript.first_prompt(path), expected)

    def test_unreadable_file(self):   # an open failure is None, not an exception
        path = self.write(user("x"))
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.assertEqual(transcript.first_prompt(path), None)


class OwnTranscript(TmpCase):
    def test_own_transcript(self):   # T9, T9b
        d = os.path.join(self.tmp, "proj")
        main = os.path.join(d, "s1.jsonl")
        expected = os.path.join(d, "s1", "subagents", "agent-a1.jsonl")
        self.assertEqual(transcript.own_transcript(ctx(None, main)), None)               # no agent_id
        self.assertEqual(transcript.own_transcript(ctx(None, None)), None)
        self.assertEqual(transcript.own_transcript(ctx("a1", main)), expected)
        self.assertFalse(os.path.exists(expected))                                         # returned though absent
        with self.subTest("another id pair"):
            self.assertEqual(transcript.own_transcript(ctx("a-2_x", main, session_id="S_9")),
                             os.path.join(d, "S_9", "subagents", "agent-a-2_x.jsonl"))
        for name, c in (
                ("transcript_path None", ctx("a1", None)),
                ("transcript_path relative", ctx("a1", "proj/s1.jsonl")),
                ("transcript_path bare name", ctx("a1", "s1.jsonl")),
                ("transcript_path empty", ctx("a1", "")),
                ("transcript_path not a str", ctx("a1", 5)),
                ("agent_id with a slash", ctx("a/b", main)),
                ("agent_id dotdot", ctx("..", main)),
                ("agent_id empty", ctx("", main)),
                ("agent_id with a space", ctx("a b", main)),
                ("agent_id with a newline", ctx("a1\n", main)),
                ("agent_id not a str", ctx(1, main)),
                ("agent_id 129 characters", ctx("a" * 129, main)),
                ("session_id with a slash", ctx("a1", main, session_id="s/1")),
                ("session_id dotdot", ctx("a1", main, session_id="..")),
                ("session_id empty", ctx("a1", main, session_id="")),
                ("session_id not a str", ctx("a1", main, session_id=None))):
            with self.subTest(name):
                self.assertEqual(transcript.own_transcript(c), None)
        with self.subTest("128 characters accepted"):
            self.assertEqual(transcript.own_transcript(ctx("a" * 128, main)),
                             os.path.join(d, "s1", "subagents", "agent-" + "a" * 128 + ".jsonl"))

    def test_own_transcript_end_to_end(self):   # T9c (M3)
        d = os.path.join(self.tmp, "proj")
        main = self.write(user("MAIN"), "proj/s1.jsonl")
        self.write(user("P the dispatch prompt"), "proj/s1/subagents/agent-a1.jsonl")
        c = ctx("a1", main)
        self.assertEqual(transcript.first_prompt(transcript.own_transcript(c)), "P the dispatch prompt")
        self.assertNotEqual(transcript.first_prompt(transcript.own_transcript(c)), "MAIN")
        self.assertEqual(transcript.first_prompt(main), "MAIN")
        with self.subTest("absent subagent file"):
            self.assertEqual(transcript.first_prompt(transcript.own_transcript(ctx("a2", main))), None)
        with self.subTest("no agent_id gives None, first_prompt(None) None"):
            self.assertEqual(transcript.first_prompt(transcript.own_transcript(ctx(None, main))), None)


if __name__ == "__main__":
    unittest.main()
