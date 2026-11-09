"""Drift tests (plan Task 2a.1 "Drift tests", F-B2p-5): code constants against the base playbook's tables.

Stream D's file while D is live, then stream A's (DS-3). It reads ``playbook/rules.md`` and never edits it. The
only skip is an absent file; a present file that cannot be read, or has no rule table, fails. Each constant is
also asserted against its literal owner value in ``tests/test_decisions_lib.py`` (F-B2p-4)."""
import os
import stat
import tempfile
import unittest
from unittest import mock

from gates.lib.decisions import KNOWN_RULES

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(REPO, "playbook", "rules.md")
ALL = tuple("SD-R%d" % n for n in range(1, 20))


def _cells(line: str) -> list:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def rule_ids(text: str):
    """The first-column cells of the first markdown table whose header's first cell is ``id``, as a set; ``None``
    when the text holds no such table. A cell not of the ``SD-R`` form is kept, so it shows as a mismatch."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and lines[i + 1].lstrip().startswith("|"):
            head = _cells(lines[i])
            sep = _cells(lines[i + 1])
            if all(c != "" and set(c) <= set("-:") for c in sep):
                j = i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    j += 1
                if head[0] == "id":
                    return {_cells(line)[0] for line in lines[i + 2:j]}
                i = j  # another table: skip its rows
                continue
        i += 1
    return None


def compare(known, path: str) -> None:
    """Assert that ``set(known)`` equals the rule ids of the table in ``path``. An absent path (``lexists`` false)
    skips with the named reason; anything else that is not a readable UTF-8 regular file with a rule table fails."""
    shown = "playbook/" + os.path.basename(path)
    if not os.path.lexists(path):
        raise unittest.SkipTest("%s absent on this branch: block B2 not merged" % shown)
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode):
        raise AssertionError("%s is present but not a regular file (a directory, symlink or other entry is never "
                             "followed)" % shown)
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise AssertionError("%s is present but cannot be read as UTF-8 (%s)" % (shown, type(e).__name__)) from None
    ids = rule_ids(text)
    if ids is None:
        raise AssertionError("%s is present but has no table whose first column is id" % shown)
    if set(known) != ids:
        raise AssertionError("%s drifts: KNOWN_RULES %s, table %s" % (shown, sorted(set(known)), sorted(ids)))


def table(ids) -> str:
    rows = "".join("| %s | r | w | judgment | strict | no | spec 8 |\n" % i for i in ids)
    return ("# Base playbook: rules\n\nA paragraph.\n\n| id | rule | why | enforced by | profiles | fixed | source |\n"
            "|---|---|---|---|---|---|---|\n" + rows)


class KnownRulesDriftTest(unittest.TestCase):
    def test_known_rules_match_rules_md(self):  # D1 on this branch; strict on presence
        compare(KNOWN_RULES, RULES)


class DriftHelperTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = os.path.realpath(td.name)
        self.path = os.path.join(self.dir, "rules.md")

    def put(self, data) -> str:
        with open(self.path, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        return self.path

    def test_drift_helper_skips_only_when_absent(self):  # D1, D3
        with self.assertRaises(unittest.SkipTest) as cm:
            compare(KNOWN_RULES, self.path)
        self.assertEqual(str(cm.exception), "playbook/rules.md absent on this branch: block B2 not merged")
        for text in ("", "Prose only.\nNo table here.\n", "| a | b |\n|---|---|\n| SD-R1 | x |\n",
                     "| id | rule |\n| SD-R1 | x |\n"):  # the last: pipe lines without a separator row are no table
            with self.subTest(repr(text)):
                self.put(text)
                self.assertEqual(self.failure(self.path), "playbook/rules.md is present but has no table whose first "
                                                          "column is id")

    def failure(self, path: str) -> str:
        """The message of the AssertionError ``compare`` raises on ``path``; a skip or a pass fails the test."""
        try:
            compare(KNOWN_RULES, path)
        except AssertionError as e:
            return str(e)
        except unittest.SkipTest as e:
            self.fail("skipped, but a present file never skips: %s" % e)
        self.fail("passed, but %s must fail" % path)

    def fresh(self, name: str) -> str:
        """``rules.md`` inside a new sub-directory ``name`` (each case its own entry; nothing is deleted)."""
        os.mkdir(os.path.join(self.dir, name))
        return os.path.join(self.dir, name, "rules.md")

    def test_drift_helper_fails_when_unreadable(self):  # D2: fails, never skips, never blocks
        not_regular = "playbook/rules.md is present but not a regular file (a directory, symlink or other entry " \
                      "is never followed)"
        good = os.path.join(self.dir, "good.md")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write(table(ALL))
        a = self.fresh("dir")
        os.mkdir(a)
        b = self.fresh("dangling")
        os.symlink(os.path.join(self.dir, "nowhere"), b)
        c = self.fresh("link")
        os.symlink(good, c)  # a symlink is never followed, even to a good table
        d = self.fresh("fifo")
        os.mkfifo(d)  # never opened, so it cannot block
        # compare refuses each entry before any open (review 1 F3): with ``open`` replaced in the helper's module, a
        # lost guard fails by name instead of blocking on the FIFO
        def refuse_open(*args, **kwargs):
            raise AssertionError("opened %s" % (args[0] if args else kwargs))

        with mock.patch.dict(compare.__globals__, {"open": refuse_open}):
            for p in (a, b, c, d):
                with self.subTest(p):
                    self.assertEqual(self.failure(p), not_regular)
            self.assertEqual(self.failure(good), "opened %s" % good)  # the replacement is live
        self.put(b"| id |\n|---|\n| SD-R1 \xff |\n")
        with self.assertRaises(AssertionError) as cm:
            compare(KNOWN_RULES, self.path)
        self.assertEqual(str(cm.exception), "playbook/rules.md is present but cannot be read as UTF-8 "
                                            "(UnicodeDecodeError)")

    def test_drift_helper_fails_on_mismatch(self):  # D4: names both sets
        self.put(table(ALL[:-1]))
        with self.assertRaises(AssertionError) as cm:
            compare(KNOWN_RULES, self.path)
        msg = str(cm.exception)
        self.assertIn("KNOWN_RULES %s" % sorted(ALL), msg)
        self.assertIn("table %s" % sorted(ALL[:-1]), msg)
        self.put(table(ALL + ("SD-R20",)))
        with self.assertRaises(AssertionError) as cm:
            compare(KNOWN_RULES, self.path)
        self.assertIn("table %s" % sorted(ALL + ("SD-R20",)), str(cm.exception))

    def test_drift_helper_passes_on_equal_sets(self):  # D5
        self.put(table(ALL))
        self.assertIsNone(compare(KNOWN_RULES, self.path))
        self.put(table(reversed(ALL)))
        self.assertIsNone(compare(KNOWN_RULES, self.path))

    def test_first_table_with_id_header(self):  # D7
        prose = "| name | value |\n|---|---|\n| SD-R99 | x |\n\n"
        self.assertEqual(rule_ids(prose + table(ALL)), set(ALL))
        self.assertEqual(rule_ids(table(("SD-R1", "`SD-R2`", "X"))), {"SD-R1", "`SD-R2`", "X"})
        self.put(table(ALL[:-1] + ("sd-r19",)))
        with self.assertRaises(AssertionError):
            compare(KNOWN_RULES, self.path)

    def test_path_from_the_repository_root(self):  # D8: never the cwd
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        self.assertTrue(os.path.isabs(RULES))
        self.assertEqual(RULES, os.path.join(REPO, "playbook", "rules.md"))
        self.assertTrue(os.path.isfile(os.path.join(REPO, "gates", "lib", "decisions.py")))
        self.put(table(ALL[:-1]))  # a drifting rules.md in the cwd is never read
        os.mkdir(os.path.join(self.dir, "playbook"))
        with open(os.path.join(self.dir, "playbook", "rules.md"), "w", encoding="utf-8") as fh:
            fh.write(table(ALL[:-1]))
        test = KnownRulesDriftTest("test_known_rules_match_rules_md")
        if os.path.lexists(RULES):
            test.test_known_rules_match_rules_md()  # the repository's file decides
        else:
            with self.assertRaises(unittest.SkipTest) as cm:
                test.test_known_rules_match_rules_md()
            self.assertEqual(str(cm.exception), "playbook/rules.md absent on this branch: block B2 not merged")


if __name__ == "__main__":
    unittest.main()
