"""Tests for playbook/rules.md (Task B2.1) and its table helpers in tests/prose_check.py.
Oracle: the real file is read from the repository root and parsed by the production helpers (table_rows,
first_table_header, rules_problems). Every expected value below (header, ids, spec section 8 keys, phrases, the
derivation table of `profiles` and `enforced by`, `source`, the fixed set) is a literal from the plan and spec, never
read back from the file or the helpers. Bad samples are built from GOOD, a well-formed sample written here, by one
change each, and assert their exact problem kinds."""
import os
import random
import re
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

from tests import prose_check as pc
from tests.prose_check import first_table_header, forbidden_hits, rules_problems, table_rows

RULES = "playbook/rules.md"
TITLE = "# Base playbook: rules"
HEADER = "| id | rule | why | enforced by | profiles | fixed | source |"
SEPARATOR = "|---|---|---|---|---|---|---|"
GATES = {"gate_schema", "gate_register", "gate_claims", "gate_decisions", "gate_dispatch", "gate_streams", "gate_context",
         "gate_cites", "gate_drift", "gate_index", "gate_checkpoint", "gate_cleanup", "gate_evidence", "run_all", "hook",
         "judgment"}
SD_R4_ENFORCER = "program create (programs); judgment"     # spec section 8; owner Q-PL-1 (a), Q-B2R-1 (a)
SPEC8_KEYS = {1: "register row", 2: "by contradiction", 3: "Owner-only", 4: "Report before plan", 5: "Zero bugs",
              6: "deleted test", 7: "epic", 8: "process defect", 9: "re-run every gate", 10: "mutation transcript",
              11: "One block per agent context", 12: "owner's approval", 13: "cleanup", 14: "background jobs",
              15: "set -eu", 16: "decisions", 17: "role/model map", 18: "bypass", 19: "production-path"}
RULE_PHRASES = {   # spec section 8 bullets 9, 10, 12, 15 as extended by the spec catch-up; case-insensitive
    "SD-R9": ["clean copy", "`git merge-tree`"], "SD-R10": ["one mutant per changed condition", "never the checkout"],
    "SD-R12": ["pull request", "owner's approval", "`checkpoint.pushed`"],
    "SD-R15": ["`mktemp -d`", "`git stash`", "heredoc", "discloses a slip"],
    "SD-R5": ["fixed in the fix round, or registered as a LOW under LOW_PLATEAU, or registered against a named task "
              "when the binding verdict (STOP_NARROW, ESCALATE) stops the loop, and otherwise never deferred"]}  # F-B2F-1, D4
RESUME_PHRASES = {   # session-resume design 3.3-3.5
    "SD-R4": ["superpowers:brainstorming", "superpowers:executing-plans"],
    "SD-R11": ["handoff is complete", "porcelain"],
    "SD-R14": ["taskstop", "completion record"]}
ALL3 = "light, standard, strict"
STD = "standard, strict"
# DB-7 derivation table (plan Task B2.1), fixed set (spec section 8), source (DB-8, Q-B21-4 (a)):
# id -> (enforced by, profiles, fixed, source)
EXPECTED = {
    "SD-R1": ("gate_register", ALL3, "no", "spec §8"),
    "SD-R2": ("gate_claims", STD, "no", "spec §8"),
    "SD-R3": ("gate_decisions", ALL3, "yes", "spec §8"),
    "SD-R4": (SD_R4_ENFORCER, ALL3, "no", "spec §8"),
    "SD-R5": ("judgment", ALL3, "no", "spec §8"),
    "SD-R6": ("judgment", ALL3, "no", "spec §8"),
    "SD-R7": ("judgment", ALL3, "no", "spec §8"),
    "SD-R8": ("judgment", ALL3, "no", "spec §8"),
    "SD-R9": ("judgment", ALL3, "no", "spec §8"),
    "SD-R10": ("gate_evidence", STD, "no", "spec §8"),
    "SD-R11": ("gate_checkpoint", STD, "no", "spec §8"),
    "SD-R12": ("hook", ALL3, "yes", "spec §8"),
    "SD-R13": ("gate_cleanup", ALL3, "no", "spec §8"),
    "SD-R14": ("judgment", ALL3, "no", "spec §8"),
    "SD-R15": ("judgment", ALL3, "no", "spec §8"),
    "SD-R16": ("judgment", ALL3, "no", "spec §8"),
    "SD-R17": ("gate_dispatch", STD, "no", "spec §8"),
    "SD-R18": ("hook", ALL3, "yes", "spec §4"),
    "SD-R19": ("judgment", ALL3, "no", "spec §13a"),
}
INTRO_REQUIRED = ["`overrides: SD-R<n>`", "`rule-override`", "decision/2", "`fixed: yes`", "never overridden"]
SD_R17_WHY = "whatever the profile"     # Q-B21-5 (a)

# Every sentence of the intro and of each rule and why cell holds at least one pinned phrase (stream rule: every
# content sentence has an executable check); an unpinned word may be reworded freely.
INTRO_PINS = ["what enforces it", "never overridden", "`rule-override`", "lists the active overrides"]
PINS = {
    "SD-R1": (["register row", "before work starts"], ["no owner"]),
    "SD-R2": (["by contradiction", "both commands"], ["checked one way"]),
    "SD-R3": (["Owner-only", "halts", "only the work that depends on the answer"], ["never assumes"]),
    "SD-R4": (["Report before plan", "planned in full", "stream breakdown", "dependency edges",
               "superpowers:brainstorming", "dispatches no writer", "`program create`"], ["nobody approved"]),
    "SD-R5": (["Zero bugs", "cosmetic item", "marks it cosmetic", "unrelated bug"],
              ["defect shipped", "only a LOW registered under LOW_PLATEAU, or a finding registered against a named "
                                 "task when a binding verdict stops the loop, may wait"]),     # F-B2F1RR-1, D4
    "SD-R6": (["deleted test"], ["hides the failure"]),
    "SD-R7": (["epic"], ["siblings"]),
    "SD-R8": (["process defect"], ["lets the defects in"]),
    "SD-R9": (["re-run every gate", "`git merge-tree`", "polluted"], ["author's checkout"]),
    "SD-R10": (["mutation transcript", "one mutant per changed condition", "surviving mutant"], ["no mutant fails"]),
    "SD-R11": (["One block per agent context", "`gate_checkpoint` counts", "Continuation is automatic",
                "inherited memory", "rewrites the handoff", "handoff is complete", "safe to clear",
                "usage-limit stop (a 429 or a limit message) is the exception", "the resume command"], ["written handoff"]),
    "SD-R12": (["base branch is protected", "owner's approval", "`MERGED`", "`checkpoint.pushed`", "need no approval",
                "conflicts"], ["lost machine"]),
    "SD-R13": (["cleanup"], ["pile up"]),
    "SD-R14": (["background jobs", "completion record", "waiting on its own background work"], ["orphaned job"]),
    "SD-R15": (["`set -eu`", "`mktemp -d`", "heredoc", "around `mktemp`", "discloses a slip"], ["another agent's work"]),
    "SD-R16": (["agent memory"], ["decision log"]),
    "SD-R17": (["role/model map"], ["quality or cost", "whatever the profile"]),
    "SD-R18": (["bypass block"], ["can skip"]),
    "SD-R19": (["production-path"], ["proves the mock"]),
}


# Clauses of spec section 8 that the review found dropped or blurred (F-B21R-4), and those found by the re-check of
# every row against its bullet; each must stay in its rule cell, case-sensitive.
RESTORED = {
    "SD-R4": ["dependency edges", "unblock condition", "parallel groups", "`breakdown/1`", "`max_concurrent`",
              "`streams.yml`", "a pointer to a section that does not exist or holds none",
              "(kind `breakdown/1`, spec appendix A)", "Claude Code limits, spec §10)", "(programs and streams design §5)"],
    "SD-R5": ["the reviewer marks it cosmetic", "folded into the next real edit"],
    "SD-R11": ["the handoff fields of spec §9", "`Task <block>.<n>` headings", "`<block>.<n>` task tokens", "`/clear`",
               "background-job check below"],
    # F-B21RR-2: cross-references and gate attributions of spec section 8, written as plain references
    "SD-R8": ["process changes"],
    "SD-R12": ["`gate_checkpoint`'s `checkpoint.pushed`"],
    "SD-R13": ["(spec §5)"],
}


def read(rel):
    """UTF-8 text of a repository file, from the repository root whatever the working directory (Q-B21-6 (a))."""
    with open(os.path.join(pc.REPO_ROOT, rel), "rb") as f:
        return f.read().decode("utf-8")


# A boundary is a stop (`.`, `!` or `?`), then a closer run of ASCII punctuation (closing brackets, quotes, backticks,
# emphasis markers, `_`, further stops). It ends a sentence when anything but an ASCII lowercase letter or digit
# follows the run: a gap (space or LF, dropped), a capital, other text, or the end. The input is restricted to the
# rules.md character set (prose_check.RULES_CHARS: LF, U+0020-U+007E, U+00A7; owner Q-B2FX2-1 (a)), and any other
# character raises ValueError naming its code point, so no Unicode database decides a boundary. It oversplits
# rather than undersplits, so no sentence hides behind its pinned neighbour (F-B21RR-1, F-B21RR2-1, F-B2FX2RR-2).
_STOPS = frozenset(".!?")
_CLOSERS = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_GAPS = frozenset(" \n")
_NO_BREAK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def _is_gap(ch):
    return ch in _GAPS


def _is_closer(ch):
    return ch in _CLOSERS


def sentences(cell):
    bad = next((ch for ch in cell if ch not in pc.RULES_CHARS), None)
    if bad is not None:
        raise ValueError("sentences: U+%04X is outside the rules.md character set" % ord(bad))
    out, start, i, n = [], 0, 0, len(cell)
    while i < n:
        if cell[i] not in _STOPS:
            i += 1
            continue
        j = i + 1
        while j < n and _is_closer(cell[j]):
            j += 1
        k = j
        while k < n and _is_gap(cell[k]):
            k += 1
        if k > j or k == n or cell[k] not in _NO_BREAK:
            out.append(cell[start:j])
            start = k
        i = k if k > j else j
    out.append(cell[start:])
    return [s for s in out if s]


def intro(text):
    return text.split(HEADER)[0]


# Content checks, each returning problem strings; run on the real file (expect []) and on changed copies of it.
def key_problems(rows):
    out = []
    for i, key in SPEC8_KEYS.items():
        if i > len(rows) or key.lower() not in rows[i - 1]["rule"].lower():
            out.append("key %d %r" % (i, key))
    return out


def phrase_problems(rows):
    rule = {r["id"]: r["rule"].lower() for r in rows}
    out = []
    for table in (RULE_PHRASES, RESUME_PHRASES):
        for rid, phrases in table.items():
            for s in phrases:
                if s.lower() not in rule.get(rid, ""):
                    out.append("phrase %s %r" % (rid, s))
    return out


def column_problems(rows):
    got = {r["id"]: (r["enforced by"], r["profiles"], r["fixed"], r["source"]) for r in rows}
    out = []
    if [r["id"] for r in rows] != ["SD-R%d" % i for i in range(1, 20)]:
        out.append("ids %r" % [r["id"] for r in rows])
    for rid, want in EXPECTED.items():
        if got.get(rid) != want:
            out.append("columns %s %r" % (rid, got.get(rid)))
    return out


def intro_problems(text):
    return ["intro %r" % s for s in INTRO_REQUIRED if s not in intro(text)]


def pin_problems(text, rows):
    out = []
    cells = [("intro", intro(text).split("\n\n")[1].strip("\n"), INTRO_PINS)]
    for r in rows:
        rule_pins, why_pins = PINS.get(r["id"], ([], []))
        cells += [(r["id"] + " rule", r["rule"], rule_pins), (r["id"] + " why", r["why"], why_pins)]
    for name, cell, pins in cells:
        low = cell.lower()
        for p in pins:
            if p.lower() not in low:
                out.append("pin missing %s %r" % (name, p))
        for s in sentences(cell):
            if not any(p.lower() in s.lower() for p in pins):
                out.append("unpinned sentence %s %r" % (name, s[:40]))
    return out


def why17_problems(rows):
    why = {r["id"]: r["why"] for r in rows}.get("SD-R17", "")
    return [] if SD_R17_WHY in why and "gate_dispatch" in why and "program is live" in why else ["why SD-R17"]


def restored_problems(rows):
    rule = {r["id"]: r["rule"] for r in rows}
    return ["restored %s %r" % (rid, p) for rid, ps in RESTORED.items() for p in ps if p not in rule.get(rid, "")]


def fixed_split(text):
    """(the ids of the rows whose `fixed` cell is `yes`, as a tuple in table order; the (id, cell) pairs whose `fixed`
    cell is neither `yes` nor `no`, None for a missing column), from prose_check.table_rows (padding stripped)."""
    ids, bad = [], []
    for r in table_rows(text):
        cell = r.get("fixed")
        if cell == "yes":
            ids.append(r.get("id"))
        elif cell != "no":
            bad.append((r.get("id"), cell))
    return tuple(ids), bad


def all_content_problems(text):
    rows = table_rows(text)
    return (key_problems(rows) + phrase_problems(rows) + column_problems(rows) + intro_problems(text)
            + pin_problems(text, rows) + why17_problems(rows) + restored_problems(rows))


class RealFileTest(unittest.TestCase):
    def setUp(self):
        self.text = read(RULES)
        self.rows = table_rows(self.text)

    def test_rules_problems_empty(self):                       # F1-F11, I1, I2, E1, P1, X0, S1, W1 on the real file
        self.assertEqual(rules_problems(self.text), [])
        self.assertEqual(self.text.split("\n")[0], TITLE)

    def test_header_and_ids(self):                             # F6, I1 (plan)
        self.assertEqual(first_table_header(self.text), HEADER)
        self.assertEqual([r["id"] for r in self.rows], ["SD-R%d" % i for i in range(1, len(self.rows) + 1)])

    def test_exactly_nineteen_rules(self):                     # I3, C3
        self.assertEqual(len(self.rows), 19)
        self.assertEqual(set(re.findall(r"SD-R[0-9]+", self.text)), {"SD-R%d" % i for i in range(1, 20)})

    def test_every_spec8_rule_present(self):                   # K1, K2, K12, K16, K18 (plan)
        self.assertEqual(key_problems(self.rows), [])

    def test_resume_rules_in_their_rows(self):                 # K4 (plan)
        r = {x["id"]: x["rule"].lower() for x in self.rows}
        self.assertTrue("superpowers:brainstorming" in r["SD-R4"] and "superpowers:executing-plans" in r["SD-R4"])
        self.assertTrue("handoff is complete" in r["SD-R11"] and "porcelain" in r["SD-R11"])
        self.assertTrue("taskstop" in r["SD-R14"] and "completion record" in r["SD-R14"])

    def test_extended_rule_phrases(self):                      # K3 (plan)
        self.assertEqual(phrase_problems(self.rows), [])

    def test_profiles_from_spec12(self):                       # P2 (plan, six rows)
        p = {r["id"]: r["profiles"] for r in self.rows}
        for i in ("SD-R1", "SD-R3", "SD-R18"):
            self.assertEqual(p[i], "light, standard, strict")
        for i in ("SD-R2", "SD-R11", "SD-R17"):
            self.assertEqual(p[i], "standard, strict")

    def test_sd_r12_enforced_by_hook(self):                    # E3, Q-B21-1 (a)
        self.assertEqual({r["id"]: r["enforced by"] for r in self.rows}["SD-R12"], "hook")

    def test_sd_r4_enforced_by_program_create(self):           # E4, Q-PL-1 (a), Q-B2R-1 (a)
        enf = {r["id"]: r["enforced by"] for r in self.rows}
        self.assertEqual(enf["SD-R4"], SD_R4_ENFORCER)
        self.assertEqual([i for i, e in enf.items() if e == SD_R4_ENFORCER], ["SD-R4"])

    def test_every_row_matches_derivation_table(self):         # E2, P2, X2, S2, I3: all 19 rows, every column
        self.assertEqual(column_problems(self.rows), [])

    def test_override_form_named(self):                        # F4, DB-9 (plan)
        i = intro(self.text)
        self.assertTrue("`overrides: SD-R<n>`" in i and "`rule-override`" in i and "decision/2" in i)
        self.assertEqual(intro_problems(self.text), [])

    def test_fixed_set_exact(self):                            # X0, X2 (plan)
        self.assertEqual({r["id"] for r in self.rows if r["fixed"] == "yes"}, {"SD-R3", "SD-R12", "SD-R18"})
        self.assertTrue(all(r["fixed"] in ("yes", "no") for r in self.rows))

    def test_fixed_rules_match_decisions_constant(self):       # FR-a..FR-e, PC1-a; F-2, "Cross-stream order"
        from gates.lib.decisions import FIXED_RULES             # A's constant; literal pinned in test_decisions_lib
        ids, bad = fixed_split(self.text)
        self.assertEqual(bad, [])                               # FR-d, FR-e: every fixed cell is exactly yes or no
        self.assertEqual(sorted(ids), sorted(FIXED_RULES))      # FR-a..FR-c: plan:6700, sorted lists: order-free, count-sensitive
        cases = [   # (name, fixture, expected (ids, bad)) through the same helper, on GOOD_TEXT (fixed: SD-R2 only)
            ("good", GOOD_TEXT, (("SD-R2",), [])),
            ("padded yes", with_cell(2, 5, "yes "), (("SD-R2",), [])),       # the checker strips cell padding
            ("Yes", with_cell(2, 5, "Yes"), ((), [("SD-R2", "Yes")])),
            ("y", with_cell(2, 5, "y"), ((), [("SD-R2", "y")])),
            ("empty", with_cell(2, 5, ""), ((), [("SD-R2", "")])),
            ("second yes", with_cell(1, 5, "yes"), (("SD-R1", "SD-R2"), [])),
            ("no fixed column", with_line(4, HEADER.replace("| fixed |", "| fix |")),
             ((), [("SD-R1", None), ("SD-R2", None), ("SD-R3", None), ("SD-R4", None)])),
        ]
        for name, text, want in cases:
            with self.subTest(name):
                self.assertEqual(fixed_split(text), want)
        with self.subTest("4301-digit id"):                     # PC1-a: compared as text, never converted to int
            long_id = "SD-R" + "1" * 4301
            ids, bad = fixed_split(with_cell(2, 0, long_id))
            self.assertEqual((ids, bad), ((long_id,), []))
            self.assertNotEqual(ids, FIXED_RULES)
        with self.subTest("rules.md absent"), tempfile.TemporaryDirectory() as td:      # FR-e: fails, never skips
            with mock.patch.object(pc, "REPO_ROOT", td):
                with self.assertRaises(FileNotFoundError):
                    read(RULES)

    def test_columns_valid(self):                              # E1, P1, S1 (plan)
        for r in self.rows:
            self.assertTrue(r["enforced by"] in GATES or (r["id"], r["enforced by"]) == ("SD-R4", SD_R4_ENFORCER))
            ps = r["profiles"].split(", ")
            self.assertTrue(ps and ps == [p for p in ("light", "standard", "strict") if p in ps])
            self.assertTrue(re.fullmatch(r"spec §[0-9]+[a-z]?", r["source"]), r["source"])
            self.assertTrue(r["why"].strip(), r["id"])                                  # W1

    def test_sd_r17_states_live_program_exception(self):       # K21, Q-B21-5 (a)
        self.assertEqual(why17_problems(self.rows), [])

    def test_every_sentence_pinned(self):                      # stream rule: every content sentence has a check
        self.assertEqual(sorted(PINS), sorted(EXPECTED))
        self.assertEqual(pin_problems(self.text, self.rows), [])

    def test_no_forbidden_strings_in_playbook(self):           # C1 (plan)
        self.assertEqual(forbidden_hits(read(RULES)), [])

    def test_no_angle_placeholder_outside_code(self):          # Q-B22v2-3 (a), as it reaches this file
        prose = re.sub(r"`[^`\n]*`", "", self.text)
        self.assertNotIn("<", prose)
        self.assertNotIn(">", prose)

    def test_constants_match_plan(self):                       # E1: the checker's whitelists equal the plan literals
        self.assertEqual(pc.RULES_HEADER, HEADER)
        self.assertEqual(pc.RULES_TITLE, TITLE)
        self.assertEqual(pc.RULES_SEPARATOR, SEPARATOR)
        self.assertEqual(set(pc.RULES_ENFORCERS), GATES)
        self.assertEqual(pc.SD_R4_ENFORCER, SD_R4_ENFORCER)


class ReadTest(unittest.TestCase):
    def test_read_from_another_cwd(self):                      # F12
        before = os.getcwd()
        with open(os.path.join(pc.REPO_ROOT, "playbook", "rules.md"), "rb") as f:
            want = f.read().decode("utf-8")
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                self.assertEqual(read(RULES), want)
            finally:
                os.chdir(before)

    def test_read_is_strict_utf8_and_keeps_cr(self):           # F2: not UTF-8; CR reaches the checker
        with tempfile.TemporaryDirectory() as td:
            os.mkdir(os.path.join(td, "playbook"))
            p = os.path.join(td, "playbook", "rules.md")
            with mock.patch.object(pc, "REPO_ROOT", td):
                with open(p, "wb") as f:
                    f.write(b"# Base playbook: rules\n\xff\n")
                with self.assertRaises(UnicodeDecodeError):
                    read(RULES)
                with open(p, "wb") as f:
                    f.write(GOOD_TEXT.replace("\n", "\r\n").encode("utf-8"))
                self.assertEqual(kinds(read(RULES)), {"line-ending", "char"})       # CR: outside the set too


GOOD_LINES = [
    TITLE,
    "",
    "Rules follow; a `fixed: yes` rule is never overridden, others by `overrides: SD-R<n>`.",
    "",
    HEADER,
    SEPARATOR,
    "| SD-R1 | Every change is a row. | Rows give owners. | gate_register | light, standard, strict | no | spec §8 |",
    "| SD-R2 | Dispatch by the map. | Tiers matter. | gate_dispatch | standard, strict | yes | spec §13a |",
    "| SD-R3 | Use `a` and `b`. | It holds. | hook | strict | no | spec §4 |",
    "| SD-R4 | Plan first. | Plans hold. | program create (programs); judgment | light | no | spec §12 |",
]
GOOD_TEXT = "\n".join(GOOD_LINES) + "\n"
ROW = {1: 6, 2: 7, 3: 8, 4: 9}     # rule number -> index in GOOD_LINES


def kinds(text):
    return {p.split(":")[0] for p in rules_problems(text)}


def with_line(i, new):
    lines = list(GOOD_LINES)
    lines[i] = new
    return "\n".join(lines) + "\n"


def with_cell(n, col, value):
    cells = [c.strip(" ") for c in GOOD_LINES[ROW[n]][1:-1].split("|")]
    cells[col] = value
    return with_line(ROW[n], "| " + " | ".join(cells) + " |")


def without_line(i):
    return "\n".join(GOOD_LINES[:i] + GOOD_LINES[i + 1:]) + "\n"


def inserted(i, new):
    return "\n".join(GOOD_LINES[:i] + [new] + GOOD_LINES[i:]) + "\n"


class GoodSampleTest(unittest.TestCase):
    def test_good_sample_passes(self):                         # C5, F2 (§ accepted), E4 (SD-R4 exception accepted)
        self.assertEqual(rules_problems(GOOD_TEXT), [])
        self.assertIn("§", GOOD_TEXT)

    def test_padding_and_multiline_intro_accepted(self):       # I2 (padding stripped), F3 (a wrapped paragraph)
        self.assertEqual(rules_problems(with_cell(1, 0, " SD-R1 ")), [])
        self.assertEqual(rules_problems(inserted(3, "A second line of the same paragraph.")), [])


BAD = [   # (name, text, exact problem kinds); each differs from GOOD_TEXT in one dimension
    # F1 line 1
    ("title case", with_line(0, "# Base Playbook: rules"), {"first-line"}),
    ("title spaces", with_line(0, "#  Base playbook: rules"), {"first-line"}),
    ("title missing", without_line(0), {"first-line", "layout"}),
    ("title bom", "\ufeff" + GOOD_TEXT, {"first-line", "char"}),
    # F2 bytes
    ("cr in a line", with_line(2, "Rules\rfollow."), {"line-ending", "char"}),
    ("crlf", GOOD_TEXT.replace("\n", "\r\n"), {"line-ending", "char"}),
    ("tab", with_line(2, "Rules\tfollow."), {"control", "char"}),
    ("nul", with_line(2, "Rules\x00follow."), {"control", "char"}),
    ("esc", with_line(2, "Rules\x1bfollow."), {"control", "char"}),
    ("del", with_line(2, "Rules\x7ffollow."), {"control", "char"}),
    # F-B21R-2: every Unicode Cc, Zl and Zp character but the newline
    ("c1 first", with_line(2, "Rules" + chr(0x80) + "follow."), {"control", "char"}),
    ("c1 nel", with_line(2, "Rules" + chr(0x85) + "follow."), {"control", "char"}),
    ("c1 csi", with_line(2, "Rules" + chr(0x9b) + "follow."), {"control", "char"}),
    ("c1 last", with_line(2, "Rules" + chr(0x9f) + "follow."), {"control", "char"}),
    ("line separator", with_line(2, "Rules" + chr(0x2028) + "follow."), {"control", "char"}),
    ("paragraph separator", with_cell(1, 2, "Rows" + chr(0x2029) + "give owners."), {"control", "char"}),
    ("vertical tab", with_line(2, "Rules\x0bfollow."), {"control", "char"}),
    ("trailing space", with_line(2, GOOD_LINES[2] + " "), {"trailing-ws"}),
    ("trailing tab", with_line(2, GOOD_LINES[2] + "\t"), {"trailing-ws", "control", "char"}),
    ("no final newline", GOOD_TEXT[:-1], {"final-newline"}),
    ("two final newlines", GOOD_TEXT + "\n", {"final-newline", "trailing"}),
    ("lone surrogate", with_cell(1, 1, "Every \ud800 change."), {"encoding", "char"}),
    # F3 intro paragraph
    ("no intro", without_line(2), {"intro"}),
    ("two intro paragraphs", "\n".join(GOOD_LINES[:3] + ["", "Another paragraph."] + GOOD_LINES[3:]) + "\n",
     {"intro"}),
    ("line 2 not empty", without_line(1), {"layout"}),
    ("two empty lines before the table", inserted(4, ""), {"layout"}),
    ("two empty lines after the title", inserted(1, ""), {"layout"}),
    ("no empty line before the table", without_line(3), {"layout"}),
    # F5 SD-R tokens outside the id column (Q-B21-3 (a))
    ("id in intro", with_line(2, "Rules follow, as SD-R3 says."), {"stray-id"}),
    ("id in why", with_cell(1, 2, "See SD-R20."), {"stray-id"}),
    ("id in rule, joined", with_cell(1, 1, "See XSD-R2x."), {"stray-id"}),
    ("id after the table", GOOD_TEXT + "SD-R5\n", {"trailing", "stray-id"}),
    # F6 header
    ("header renamed", with_line(4, HEADER.replace("| why |", "| reason |")), {"header"}),
    ("header reordered", with_line(4, "| id | why | rule | enforced by | profiles | fixed | source |"), {"header"}),
    ("header extra", with_line(4, HEADER + " notes |"), {"header"}),
    ("header missing cell", with_line(4, HEADER.replace(" source |", "")), {"header"}),
    ("header doubled space", with_line(4, HEADER.replace("| rule", "|  rule")), {"header"}),
    ("header trailing space", with_line(4, HEADER + " "), {"header", "trailing-ws"}),
    # F7 separator
    ("separator six cells", with_line(5, "|---|---|---|---|---|---|"), {"separator"}),
    ("separator aligned", with_line(5, "|:---:|---|---|---|---|---|---|"), {"separator"}),
    ("separator absent", without_line(5), {"separator", "stray-id", "id-sequence"}),
    # F8 tables
    ("second table", GOOD_TEXT + "\n" + HEADER + "\n" + SEPARATOR + "\n", {"tables", "trailing"}),
    ("second header row", inserted(8, HEADER), {"tables"}),
    # F9 cells
    ("six cells", with_line(6, GOOD_LINES[6].replace(" spec §8 |", "")), {"cells"}),
    ("eight cells", with_line(6, GOOD_LINES[6] + " x |"), {"cells"}),
    ("row without closing pipe", with_line(6, GOOD_LINES[6][:-2]), {"row"}),
    ("row indented", with_line(6, "  " + GOOD_LINES[6]), {"row"}),
    # F10 pipes in a cell
    ("pipe in cell", with_cell(1, 1, "a | b"), {"cells"}),
    ("escaped pipe", with_cell(1, 1, "a \\| b"), {"pipe", "cells"}),
    ("pipe in code span", with_cell(1, 1, "`a|b`"), {"pipe", "cells"}),
    # F11 text after the table
    ("paragraph after", GOOD_TEXT + "\nA note.\n", {"trailing"}),
    ("line right after", GOOD_TEXT + "A note.\n", {"trailing"}),
    ("blank lines after", GOOD_TEXT + "\n\n", {"final-newline", "trailing"}),
    # I1 sequence, I2 spelling
    ("gap", with_cell(2, 0, "SD-R3"), {"id-sequence"}),
    ("duplicate", with_cell(2, 0, "SD-R1"), {"id-sequence"}),
    ("not from one", with_cell(1, 0, "SD-R5"), {"id-sequence"}),
    ("SD-R0", with_cell(1, 0, "SD-R0"), {"id"}),
    ("SD-R01", with_cell(1, 0, "SD-R01"), {"id"}),
    ("lowercase", with_cell(1, 0, "sd-r1"), {"id"}),
    ("lower r", with_cell(1, 0, "SD-r1"), {"id"}),
    ("no dash", with_cell(1, 0, "SDR1"), {"id"}),
    ("suffix", with_cell(1, 0, "SD-R1a"), {"id"}),
    ("arabic digit", with_cell(1, 0, "SD-R\u0661"), {"id", "char"}),
    ("arabic second digit", with_cell(1, 0, "SD-R1\u0661"), {"id", "char"}),
    # W1 and empty cells
    ("empty why", with_cell(1, 2, ""), {"empty"}),
    ("empty rule", with_cell(1, 1, ""), {"empty"}),
    # E1 enforced by
    ("unknown gate", with_cell(1, 3, "gate_foo"), {"enforced-by"}),
    ("gate case", with_cell(1, 3, "Gate_claims"), {"enforced-by"}),
    ("empty enforced by", with_cell(1, 3, ""), {"empty", "enforced-by"}),
    ("exception on another row", with_cell(1, 3, SD_R4_ENFORCER), {"enforced-by"}),
    # P1 profiles
    ("empty profiles", with_cell(1, 4, ""), {"empty", "profiles"}),
    ("unknown profile", with_cell(1, 4, "heavy"), {"profiles"}),
    ("profiles order", with_cell(1, 4, "strict, light"), {"profiles"}),
    ("profiles duplicate", with_cell(1, 4, "light, light"), {"profiles"}),
    ("profiles no space", with_cell(1, 4, "light,standard"), {"profiles"}),
    # X0 fixed
    ("fixed Yes", with_cell(1, 5, "Yes"), {"fixed"}),
    ("fixed y", with_cell(1, 5, "y"), {"fixed"}),
    ("fixed empty", with_cell(1, 5, ""), {"empty", "fixed"}),
    # S1 source
    ("source no section sign", with_cell(1, 6, "spec 8"), {"source"}),
    ("source anchor", with_cell(1, 6, "spec §8#x"), {"source"}),
    ("source path", with_cell(1, 6, "docs/spec.md"), {"source"}),
    ("source empty", with_cell(1, 6, ""), {"empty", "source"}),
    ("source arabic digit", with_cell(1, 6, "spec §\u0668"), {"source", "char"}),
    # table presence
    ("no table", "\n".join(GOOD_LINES[:3]) + "\n", {"table"}),
    ("no rows", "\n".join(GOOD_LINES[:6]) + "\n", {"rows"}),
]


class BadSamplesTest(unittest.TestCase):
    def test_table_parser_rejects_bad_samples(self):           # C4 (plan's four included: reordered, gap, SD-R01, two)
        names = [b[0] for b in BAD]
        self.assertEqual(len(names), len(set(names)))
        for name, text, want in BAD:
            with self.subTest(sample=name):
                self.assertNotEqual(text, GOOD_TEXT)
                self.assertEqual(kinds(text), want, rules_problems(text))

    def test_problem_format(self):                             # T2: each problem is 'kind: detail'
        for name, text, _ in BAD:
            for p in rules_problems(text):
                self.assertRegex(p, r"^[a-z-]+: \S", (name, p))

    def test_helpers_take_str(self):                           # T2
        for f in (rules_problems, table_rows, first_table_header):
            for bad in (GOOD_TEXT.encode("utf-8"), 5, None):
                with self.subTest(f=f.__name__, arg=type(bad).__name__):
                    with self.assertRaisesRegex(TypeError, "^%s takes str, not " % f.__name__):
                        f(bad)

    def test_gap_reported_once(self):                          # I1: the sequence resyncs after a gap
        text = "\n".join(GOOD_LINES[:6] + [GOOD_LINES[6], GOOD_LINES[7].replace("SD-R2", "SD-R3"),
                                           GOOD_LINES[8].replace("SD-R3", "SD-R4")]) + "\n"
        self.assertEqual(rules_problems(text), ["id-sequence: line 8, expected SD-R2, got SD-R3"])


class TableHelpersTest(unittest.TestCase):
    def test_table_rows_generic(self):                         # T1: any one-table file, keyed by its own header
        text = "# Other\n\nIntro.\n\n| role | tier |\n|---|---|\n| implementer | tier2 |\n|  reviewer  | tier3 |\n"
        self.assertEqual(table_rows(text), [{"role": "implementer", "tier": "tier2"},
                                            {"role": "reviewer", "tier": "tier3"}])
        self.assertEqual(first_table_header(text), "| role | tier |")

    def test_table_rows_stops_at_the_first_non_table_line(self):     # invariant: prose after the table is ignored
        rows = table_rows(GOOD_TEXT + "\nAfter.\n")
        self.assertEqual([r["id"] for r in rows], ["SD-R1", "SD-R2", "SD-R3", "SD-R4"])
        self.assertEqual(rows[0]["source"], "spec §8")

    def test_table_line_after_the_table_raises(self):          # F-B21R-1: rows after a non-table line
        for text in (GOOD_TEXT + "\nAfter.\n| SD-R9 | x | y | hook | strict | no | spec §8 |\n",
                     "| a |\n|---|\n| 1 |\n\n| b |\n|---|\n", "| a |\n|---|\nfoo\n| x |\n"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "after the table"):
                    table_rows(text)

    def test_separator_shape_raises(self):                     # F-B21R-1: separator missing, count, cells
        for text in ("| a |\n", "| a |\nfoo\n| x |\n", "| a | b |\n| 1 | 2 |\n| 3 | 4 |\n",
                     "| a | b |\n|---|\n| 1 | 2 |\n", "| a | b |\n|---|---|---|\n| 1 | 2 |\n",
                     "| a | b |\n|---|-x-|\n| 1 | 2 |\n", "| a | b |\n|---||\n| 1 | 2 |\n",
                     "| a | b |\n|---|:-:-|\n| 1 | 2 |\n", "| a | b |\n|---|::|\n| 1 | 2 |\n",
                     "| a |\n|---\n| 1 |\n", "| a |"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "separator"):
                    table_rows(text)

    def test_separator_forms_accepted(self):                   # alignment colons and padding
        self.assertEqual(table_rows("| a | b |\n|:---|---:|\n| 1 | 2 |\n"), [{"a": "1", "b": "2"}])
        self.assertEqual(table_rows("| a |\n| :-: |\n| 1 |\n"), [{"a": "1"}])
        self.assertEqual(table_rows("| a |\n|-|\n"), [])         # invariant: a header with no rows gives []

    def test_duplicate_header_raises(self):                    # F-B21R-1: duplicate header names
        for text in ("| a | a |\n|---|---|\n| 1 | 2 |\n", "| a | b | a |\n|---|---|---|\n"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    table_rows(text)

    def test_indented_table_lines(self):                       # invariant: an indented table line is a table line
        self.assertEqual(table_rows("Intro.\n\n  | a |\n  |---|\n  | 1 |\n"), [{"a": "1"}])

    def test_no_table(self):
        self.assertIsNone(first_table_header("# T\n\nNo table.\n"))
        with self.assertRaises(ValueError):
            table_rows("# T\n\nNo table.\n")

    def test_cell_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            table_rows("| a | b |\n|---|---|\n| 1 | 2 | 3 |\n")

    def test_unclosed_row_raises(self):
        for bad in ("| a | b |\n|---|---|\n| 1 | 2\n", "| a | b |\n|---|---|\n|\n", "| a | b\n|---|---|\n"):
            with self.subTest(text=bad):
                with self.assertRaises(ValueError):
                    table_rows(bad)


def erase(cell, s):
    """cell with every case-insensitive occurrence of s replaced by 'zz'."""
    while s.lower() in cell.lower():
        at = cell.lower().index(s.lower())
        cell = cell[:at] + "zz" + cell[at + len(s):]
    return cell


def changed(text, old, new):
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1)


class ContentChecksRefuseTest(unittest.TestCase):
    """The content checks above are not vacuous: each refuses a copy of the real file with one change."""

    def setUp(self):
        self.text = read(RULES)

    def row_line(self, rid):
        return [l for l in self.text.split("\n") if l.startswith("| %s |" % rid)][0]

    def with_cell(self, rid, col, value):
        line = self.row_line(rid)
        cells = [c.strip(" ") for c in line[1:-1].split("|")]
        cells[col] = value
        return changed(self.text, line, "| " + " | ".join(cells) + " |")

    def cell(self, rid, col):
        return [c.strip(" ") for c in self.row_line(rid)[1:-1].split("|")][col]

    def test_key_only_in_another_row(self):                    # K1
        rule7 = self.cell("SD-R7", 1)
        t = self.with_cell("SD-R7", 1, rule7.replace("epic", "set"))
        t = changed(t, self.cell("SD-R8", 1), self.cell("SD-R8", 1) + " An epic too.")
        self.assertEqual(key_problems(table_rows(t)), ["key 7 'epic'"])

    def test_key_inside_longer_word_accepted(self):            # K1: substring, so 'epics' satisfies 'epic'
        rows = table_rows(self.with_cell("SD-R7", 1, self.cell("SD-R7", 1).replace("an epic", "epics")))
        self.assertEqual(key_problems(rows), [])

    def test_each_key_missing(self):                           # K2, K12, K16, K18
        for i, key in SPEC8_KEYS.items():
            rid = "SD-R%d" % i
            rule = self.cell(rid, 1)
            with self.subTest(key=key):
                self.assertIn(key.lower(), rule.lower())
                t = self.with_cell(rid, 1, erase(rule, key))
                self.assertIn("key %d %r" % (i, key), key_problems(table_rows(t)))

    def test_each_phrase_missing(self):                        # K3, K4
        for table in (RULE_PHRASES, RESUME_PHRASES):
            for rid, phrases in table.items():
                for s in phrases:
                    t = self.with_cell(rid, 1, erase(self.cell(rid, 1), s))
                    with self.subTest(rid=rid, phrase=s):
                        self.assertIn("phrase %s %r" % (rid, s), phrase_problems(table_rows(t)))

    def test_each_column_changed(self):                        # E2, E3, E4, P2, X2, S2
        for rid in EXPECTED:
            for col, value in ((3, "judgment" if EXPECTED[rid][0] != "judgment" else "hook"),
                               (4, "strict"), (5, "no" if EXPECTED[rid][2] == "yes" else "yes"),
                               (6, "spec §9")):
                with self.subTest(rid=rid, col=col):
                    self.assertTrue(column_problems(table_rows(self.with_cell(rid, col, value))))

    def test_row_count_changed(self):                          # I3: 18 or 20 rows
        last = self.row_line("SD-R19")
        self.assertTrue(column_problems(table_rows(changed(self.text, "\n" + last, ""))))
        extra = last.replace("SD-R19", "SD-R20")
        self.assertTrue(column_problems(table_rows(changed(self.text, last, last + "\n" + extra))))

    def test_intro_strings_missing(self):                      # F4
        for s in INTRO_REQUIRED:
            with self.subTest(s=s):
                self.assertIn("intro %r" % s, intro_problems(changed(self.text, s, "zz")))

    def test_sd_r17_why_without_exception(self):               # K21
        t = self.with_cell("SD-R17", 2, self.cell("SD-R17", 2).replace(SD_R17_WHY, "in any setup"))
        self.assertEqual(why17_problems(table_rows(t)), ["why SD-R17"])

    def test_unpinned_sentence_and_missing_pin(self):          # stream rule P:6303
        rule = self.cell("SD-R6", 1)
        t = self.with_cell("SD-R6", 1, rule + " Also do something else.")
        self.assertEqual(pin_problems(t, table_rows(t)), ["unpinned sentence SD-R6 rule 'Also do something else.'"])
        t = self.with_cell("SD-R13", 2, "Files are kept tidy.")
        self.assertIn("pin missing SD-R13 why 'pile up'", pin_problems(t, table_rows(t)))
        t = changed(self.text, "lists the active overrides", "shows them")
        self.assertIn("pin missing intro 'lists the active overrides'", pin_problems(t, table_rows(t)))

    def test_unpinned_sentence_any_start_or_end(self):         # F-B21R-3: sentence boundaries
        rule = self.cell("SD-R6", 1)
        for added, sentence in ((rule + " (Also do something else.)", "(Also do something else.)"),
                                (rule + " also do something else.", "also do something else."),
                                (rule + " 2 agents may skip it.", "2 agents may skip it."),
                                (rule + " `x` is skipped.", "`x` is skipped."),
                                (rule[:-1] + "? And skip it.", "And skip it."),
                                (rule[:-1] + "! and skip it.", "and skip it."),
                                (rule + "  Two spaces before.", "Two spaces before.")):
            with self.subTest(sentence=sentence):
                t = self.with_cell("SD-R6", 1, added)
                self.assertEqual(rules_problems(t), [])
                self.assertEqual(pin_problems(t, table_rows(t)),
                                 ["unpinned sentence SD-R6 rule %r" % sentence[:40]])

    def test_sentences_split(self):                            # F-B21R-3: the splitter itself
        self.assertEqual(sentences("A b. (C d.) e f? G! 2 h.  `i` j."),
                         ["A b.", "(C d.)", "e f?", "G!", "2 h.", "`i` j."])
        self.assertEqual(sentences("Use `a.b` and 80 % of it."), ["Use `a.b` and 80 % of it."])

    def assert_split_or_refused(self, text, want):
        """Q-B2FX2-1 (a): an all-whitelist text splits as want; any other raises ValueError naming its first code point
        outside the set."""
        bad = first_refused(text)
        if bad is None:
            self.assertEqual(sentences(text), want)
        else:
            with self.assertRaisesRegex(ValueError, re.escape(bad)):
                sentences(text)

    def assert_char_refused(self, t):
        """Through the real file: a cell holding a character outside the set gives a 'char' problem naming it."""
        bad = first_refused(t)
        self.assertIsNotNone(bad)
        self.assertTrue(any(p.startswith("char: ") and bad in p for p in rules_problems(t)), bad)

    def test_sentences_split_after_closers_and_any_space(self):     # F-B21RR-1: the whole boundary dimension
        closers = ["`", "*", "_", ")", "]", "\"", "'", "**", "`)", chr(0x201d), chr(0x2019), chr(0xbb), chr(0x300d)]
        spaces = [" ", "  ", "\t", chr(0xa0), chr(0x2003), chr(0x3000), " " + chr(0xa0)]
        for stop in ".!?":
            for c in [""] + closers:
                for sp in spaces:
                    with self.subTest(stop=stop, closer=c, space=sp):
                        self.assert_split_or_refused("A b" + stop + c + sp + "C d.", ["A b" + stop + c, "C d."])
        self.assertEqual(sentences("A b.cd e."), ["A b.cd e."])               # no space: no boundary
        self.assertEqual(sentences("A b. "), ["A b."])                        # no empty sentence after the last
        self.assertEqual(sentences(""), [])
        self.assertEqual(sentences("Use `$(...)` here."), ["Use `$(...)`", "here."])   # fail closed: oversplit

    def test_unpinned_sentence_behind_closers(self):          # F-B21RR-1, on the real file
        rule = self.cell("SD-R6", 1)
        for tail in (" `x.` ", "* ", "_ ", chr(0x201d) + " ", chr(0x2019) + " ", chr(0xbb) + " ", chr(0xa0),
                     chr(0x2003), "\t", "!" + chr(0x201d) + " "):
            with self.subTest(tail=tail):
                t = self.with_cell("SD-R6", 1, rule + tail + "Agents may skip it.")
                if first_refused(tail) is None:
                    self.assertIn("unpinned sentence SD-R6 rule 'Agents may skip it.'", pin_problems(t, table_rows(t)))
                else:
                    self.assert_char_refused(t)

    def test_restored_spec_clauses(self):                      # F-B21R-4: clauses of spec section 8 kept
        rule = {r["id"]: r["rule"] for r in table_rows(self.text)}
        for rid, phrases in RESTORED.items():
            for p in phrases:
                with self.subTest(rid=rid, phrase=p):
                    self.assertIn(p, rule[rid])
                    t = self.with_cell(rid, 1, erase(rule[rid], p))
                    self.assertTrue(restored_problems(table_rows(t)))

    def test_harmless_rewording_passes(self):                  # K20: verbatim spec bullet, unpinned rewording
        t = self.with_cell("SD-R6", 1, "A deleted test is restored and fixed; dropping a test is never offered as a fix.")
        self.assertEqual(rules_problems(t), [])
        self.assertEqual(all_content_problems(t), [])
        why = self.cell("SD-R7", 2)
        with self.subTest(part="SD-R7 why"):                   # FR-1 (B4): "of a class" is unpinned; absent = visible skip
            self.harmless_phrase_skipped_if_absent(why)
            t = self.with_cell("SD-R7", 2, "Mending only one member " + why[why.index("of a class"):])
            self.assertNotEqual(t, self.text)
            self.assertEqual(rules_problems(t), [])
            self.assertEqual(all_content_problems(t), [])

    def harmless_phrase_skipped_if_absent(self, why):
        if "of a class" not in why:
            self.skipTest("FR-1: 'of a class' is reworded on disk; unpinned, so never a failure")

    def test_k20_absent_phrase_is_skipped_not_failed(self):    # B4 rows 2, 3 (FR-1)
        case = type(self)("test_harmless_rewording_passes")
        orig = case.cell
        self.harmless_phrase_skipped_if_absent(self.cell("SD-R7", 2))    # already reworded on disk: skipped as well

        def cell(rid, col):
            got = orig(rid, col)
            return got.replace("of a class", "of the class", 1) if (rid, col) == ("SD-R7", 2) else got
        case.cell = cell
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.skipped), 1, result.skipped)

    def test_real_file_has_no_content_problems(self):
        self.assertEqual(all_content_problems(self.text), [])

    def test_unpinned_sentence_with_no_space(self):          # F-B21RR2-1: every member, through the real pin check
        rule = self.cell("SD-R6", 1)
        self.assertTrue(rule.endswith("fix."))
        for stop in ".!?" + CJK_STOPS:
            for closer in NO_SPACE_CLOSERS:
                for sep, nxt in NO_SPACE_JOINS:
                    added = rule[:-1] + stop + closer + sep + nxt
                    with self.subTest(stop=stop, closer=closer, sep=sep, nxt=nxt[:2]):
                        t = self.with_cell("SD-R6", 1, added)
                        if first_refused(added) is None:
                            self.assertEqual(rules_problems(t), [])
                            self.assertEqual(pin_problems(t, table_rows(t)),
                                             ["unpinned sentence SD-R6 rule %r" % nxt[:40]])
                        else:                                   # Q-B2FX2-1 (a): non-ASCII members refused
                            self.assert_char_refused(t)

    def test_cjk_stop_splits_before_lowercase(self):          # F-B21RR2-1; Q-B2FX2-1 (a): every CJK stop now refused
        rule = self.cell("SD-R6", 1)
        for stop in CJK_STOPS:
            with self.subTest(stop=stop):
                for added in (rule[:-1] + "." + stop + "agents may skip it.", rule[:-1] + stop + "agents may skip it."):
                    self.assert_char_refused(self.with_cell("SD-R6", 1, added))
                    with self.assertRaisesRegex(ValueError, re.escape("U+%04X" % ord(stop))):
                        sentences(added)

    def test_no_false_split_without_space(self):              # F-B21RR2-1: lowercase, digits and code stay one sentence
        rule = self.cell("SD-R6", 1)
        for tail in ("e.g.the fix", "v3.12 fix", "spec §8.x", "`gates.lib.config` fix", "a.b fix"):
            with self.subTest(tail=tail):
                t = self.with_cell("SD-R6", 1, rule[:-1] + " via " + tail + ".")
                self.assertEqual(pin_problems(t, table_rows(t)), [])


# F-B21RR2-1 members: stops, closer runs and what follows the run with no whitespace (expected sentence = the text after
# the separator, built here, never read from the splitter).
CJK_STOPS = chr(0x3002) + chr(0xff0e) + chr(0xff01) + chr(0xff1f) + chr(0xff61)


def in_charset(cp):
    """The rules.md character set, written by hand from controller D4: LF, U+0020-U+007E, U+00A7."""
    return cp == 0x0a or 0x20 <= cp <= 0x7e or cp == 0xa7


def first_refused(text):
    """'U+XXXX' of the first character of text outside the rules.md character set, or None."""
    bad = next((ch for ch in text if not in_charset(ord(ch))), None)
    return None if bad is None else "U+%04X" % ord(bad)
NO_SPACE_CLOSERS = ["", ")", "``", "**", "\"", chr(0x201d), "``)", "_", chr(0x300d)]  # backticks paired: one cell
NO_SPACE_JOINS = [("", "Agents may skip it."), ("", chr(0xc9) + "tapes may skip it."), ("", chr(0x1c5) + "x may skip it.")]
NO_SPACE_JOINS += [(sep, nxt) for sep in (chr(0x200b), chr(0x200d), chr(0x2060), chr(0xfeff), chr(0x200b) * 2)
                   for nxt in ("Agents may skip it.", "agents may skip it.")]
NO_SPACE_JOINS += [(stop, nxt) for stop in CJK_STOPS for nxt in ("Agents may skip it.", "agents may skip it.")]


class SentenceSplitTest(unittest.TestCase):
    def test_no_space_boundaries(self):                       # F-B21RR2-1: the splitter on each member
        self.assertEqual(sentences("A fix.Agents b."), ["A fix.", "Agents b."])
        self.assertEqual(sentences("A fix.)Agents b."), ["A fix.)", "Agents b."])
        for text, cp in (("A fix." + chr(0x200b) + "agents b.", "U+200B"), ("A fix." + chr(0x3002) + "agents b.", "U+3002"),
                         ("A fix" + chr(0x3002) + "agents b.", "U+3002"), ("A fix." + chr(0x200b), "U+200B"),
                         ("A fix." + chr(0x3002), "U+3002")):    # Q-B2FX2-1 (a): non-ASCII members now refused
            with self.subTest(cp=cp):
                with self.assertRaisesRegex(ValueError, re.escape(cp)):
                    sentences(text)
        self.assertEqual(sentences("e.g.the v3.12 a.b `x.Y` end."), ["e.g.the v3.12 a.b `x.", "Y` end."])


# ---- Task B2.2 part 1: section, forbidden additions, placeholders, front matter ----

class SectionHelperTest(unittest.TestCase):
    def raises_naming(self, text, heading):
        with self.assertRaises(AssertionError) as cm:
            pc.section(text, heading)
        self.assertIn(repr(heading), str(cm.exception))

    def test_section_helper_edges(self):              # plan; H1, H2: absent and repeated fail; the last runs to the end
        t = "# x\n\n## A\na1\n## B\nb1\n"
        self.assertEqual(pc.section(t, "A"), "a1\n")
        self.assertEqual(pc.section(t, "B"), "b1\n")
        for text, heading in ((t, "C"), (t + "## A\n", "A")):
            with self.subTest(heading=heading):
                self.raises_naming(text, heading)

    def test_section_multiline_bodies(self):          # H1
        t = "# x\n\n## A\na1\n\na2\n## B\nb1\nb2\n"
        self.assertEqual(pc.section(t, "A"), "a1\n\na2\n")
        self.assertEqual(pc.section(t, "B"), "b1\nb2\n")
        self.assertEqual(pc.section("## A\n## B\n", "A"), "\n")

    def test_section_near_misses_are_absent(self):    # H3: only the exact line `## <heading>` counts
        for near in ("## A ", "##A", "### A", "## a", " ## A", "##  A"):
            with self.subTest(near=near):
                self.raises_naming("# x\n" + near + "\nbody\n", "A")
        self.assertEqual(pc.section("## A \nx\n## A\ny\n### A\nz\n", "A"), "y\n### A\nz\n")

    def test_section_subheading_in_body(self):        # H4
        self.assertEqual(pc.section("## A\na\n### Sub\ns\n## B\n", "A"), "a\n### Sub\ns\n")

    def test_section_heading_inside_fence(self):      # H5: a fenced `## ` line is a heading line
        t = "## A\n```\n## X\n```\n## B\nb\n"
        self.assertEqual(pc.section(t, "A"), "```\n")
        self.assertEqual(pc.section(t, "X"), "```\n")

    def test_section_crlf_and_no_final_newline(self):     # H6
        self.raises_naming("## A\r\nx\r\n", "A")
        self.assertEqual(pc.section("## A\nx", "A"), "x")
        self.assertEqual(pc.section("## A", "A"), "")


NEW_FORBIDDEN = [("absolute-path", "/Users/alice/repo/x.md"), ("absolute-path", "see /home/alice/x"),
                 ("test-filename", "test_*.py"), ("test-filename", "*_test.go"), ("test-filename", "*.spec.ts")]
# Row F6 edges, owner Q-B22v2-4 (a): (sample, expected names in order)
F6_EDGES = [
    ("/Users/<name>/", []), ("/home/<name>/x", []), ("/home/alice", []), ("~/x", []), ("$HOME/x", []),
    ("/Users/Shared/x", ["absolute-path"]), ("/users/alice/x", []), ("/HOME/alice/x", []), ("C:\\Users\\alice\\", []),
    ("test_*.c", ["test-filename"]), ("*.test.js", ["test-filename"]), ("tests/test_playbook.py", []),
    ("https://x.org/home/alice/y", []), ("~/Users/alice/x", []), ("./home/alice/x", []), ("a-/home/alice/x", []),
    ("x/home/alice/y", []), ("_/home/alice/y", []), ("(/home/alice/x)", ["absolute-path"]),
    ("`/Users/alice/x`", ["absolute-path"]), ("\"/home/alice/x\"", ["absolute-path"]), ("/home/a b/x", []),
    ("/home/\"a\"/x", []), ("/home/'a'/x", []), ("/home/a>/x", []), ("/home//x", []), ("/home/alice/", ["absolute-path"]),
    ("*_test.<ext>", []), ("test_*.<ext>", []), ("src/**/*.spec.ts", ["test-filename"]), ("test_x.py", []),
    ("*.test", []), ("the test_* files", []),
]


class ForbiddenAdditionsTest(unittest.TestCase):
    def test_new_forbidden_patterns_seeded(self):          # F2, F3 (plan); Q-RB-1 (a)
        for name, sample in NEW_FORBIDDEN:
            with self.subTest(sample=sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], [name])
        for clean in ("/strict-delivery:init", "/usr/bin/python3", "/bin/sh", "test filename patterns"):
            with self.subTest(clean=clean):
                self.assertEqual(forbidden_hits(clean), [])

    def test_new_forbidden_names_follow_old_steps(self):   # F1 (plan); Q-RB-1 (a)
        names = [n for n, _ in pc.FORBIDDEN]
        i = names.index("old-steps")
        self.assertEqual(names[i + 1:i + 3], ["absolute-path", "test-filename"])
        self.assertEqual(len(names), 11)

    def test_f6_edges(self):                                # F6, owner Q-B22v2-4 (a)
        for sample, names in F6_EDGES:
            with self.subTest(sample=sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], names)
                self.assertEqual([h[0] for h in forbidden_hits("prose " + sample + " prose")], names)

    def test_overlap_with_owner_handle(self):               # F4
        self.assertEqual(forbidden_hits("/Users/benji/x"),
                         [("absolute-path", 1, "/Users/benji/"), ("owner-handle", 1, "benji")])

    def test_joined_scan_adds_no_second_hit(self):          # F5
        self.assertEqual(forbidden_hits("see /Users/alice/\nmore text"), [("absolute-path", 1, "/Users/alice/")])
        self.assertEqual(forbidden_hits("a\nrun test_*.py\nb"), [("test-filename", 2, "test_*.py")])
        self.assertEqual(forbidden_hits("see /home/\nalice/x"), [])

    def test_b_owned_markdown_clean(self):                  # F7, A3 for the files that exist; F9 reads the same list
        files = b_owned_markdown()
        self.assertIn(RULES, files)
        for rel in files:
            with self.subTest(rel=rel):
                self.assertEqual(forbidden_hits(read(rel)), [])


def b_owned_markdown():
    """Every B-owned markdown file present: the ten prompt blocks, playbook/*.md (glob), the skill once it lands."""
    out = ["%s/%s.md" % (pc.PROMPTS_DIR, r) for r in pc.B_ROLES]
    pb = os.path.join(pc.REPO_ROOT, "playbook")
    out += sorted("playbook/" + n for n in os.listdir(pb) if n.endswith(".md"))
    if os.path.exists(os.path.join(pc.REPO_ROOT, "skills", "strict-delivery", "SKILL.md")):
        out.append("skills/strict-delivery/SKILL.md")
    return out


# Row P1-P10 samples: (text, expected [(line, match)]); every expected value is written here by hand.
R1, R3 = "refused: multi-line code span", "refused: pipe in table-row code span"   # owner Q-B2FX2-1 (a), D1
RA, RB, RL, RI, RQ = ("refused: angle bracket outside code span", "refused: backslash outside code span",
                      "refused: link syntax", "refused: indented line", "refused: block quote")   # W1 (fix round 4)
RC, RX = "refused: character outside whitelist", "refused: extended autolink"           # fix round 5 (D1, D6)
RN = "refused: block start in list item"                                       # fix round 7 (Q-B2Z1-1 (a), D1)
PLACEHOLDER_REFUSED = [   # fix round 4 (W1): every '<' outside a code span is also refused (RA), after the line's hits
    ("G<n> the same", [(1, "<n>"), (1, RA)]), ("Owner answers (<date>), binding", [(1, "<date>"), (1, RA)]),
    ("<program>/integration", [(1, "<program>"), (1, RA)]),
    ("class: <dimension>: <members>", [(1, "<dimension>"), (1, "<members>"), (1, RA)]),
    ("<role>.md", [(1, "<role>"), (1, RA)]), ("<Rq-n>", [(1, "<Rq-n>"), (1, RA)]),                      # P1
    ("<the slugs in order>", [(1, "<the slugs in order>"), (1, RA)]),
    ("<a href=\"x\">", [(1, "<a href=\"x\">"), (1, RA)]),
    ("<a b='x y' c=d e>", [(1, "<a b='x y' c=d e>"), (1, RA)]), ("<br/>", [(1, "<br/>"), (1, RA)]),
    ("<n />", [(1, "<n />"), (1, RA)]),
    ("<the slugs\nin order>", [(1, "<the slugs\nin order>"), (1, RA)]),                                  # P5
    ("</n>", [(1, "</n>"), (1, RA)]), ("</n >", [(1, "</n >"), (1, RA)]),
    ("<!-- x -->", [(1, "<!-- x -->"), (1, RA)]),
    ("a <!-- open", [(1, "<!--"), (1, RA)]), ("<!--\nx -->", [(1, "<!--\nx -->"), (1, RA)]),            # P7
    ("\\<n>", [(1, "<n>"), (1, RA), (1, RB)]),                                                           # P8
    ("a ` b <n>", [(1, "<n>"), (1, R1), (1, RA)]), ("`a`` <n>", [(1, "<n>"), (1, R1), (1, RA)]),       # P9 + R1
    ("\\`a <n> `", [(1, "<n>"), (1, R1), (1, RA), (1, RB)]),
    ("` <n> ``", [(1, "<n>"), (1, R1), (1, RA)]), ("`` <n> `", [(1, "<n>"), (1, R1), (1, RA)]),   # unequal runs
    ("`a\n<n>`", [(1, R1), (2, "<n>"), (2, R1), (2, RA)]),                                             # P10 + R1
    ("x\n```\ny\n```\n<n>", [(5, "<n>"), (5, RA)]), ("~~~\n```\n<n>\n~~~\n<m>", [(5, "<m>"), (5, RA)]),
    ("    ```\n<n>\n    ```", [(1, R1), (1, RI), (2, "<n>"), (2, RA), (3, R1), (3, RI)]),
    ("``` a`b\n<n>", [(1, R1), (2, "<n>"), (2, RA)]),                                                    # P3 edges
    ("<a `x`>", [(1, RA)]),                                    # was R2 (round 3); RA from round 4
    ("# `a\n`<x>`\n", [(1, R1)]),                              # was accepted (heading ends a paragraph): R1
    ("  ```py\n<n>\n  ```", [(1, RI), (3, RI)]),               # was accepted (indented fence): RI from round 4
    ("a < b", [(1, RA)]), ("x<y", [(1, RA)]), ("<1-4>", [(1, RA)]), ("< n>", [(1, RA)]), ("a <", [(1, RA)]),
    ("<>", [(1, RA)]), ("<-n>", [(1, RA)]), ("<_n>", [(1, RA)]),          # P4: were accepted; RA from round 4
    ("<https://example.org/x>", [(1, RA), (1, RX)]), ("<mailto:a@b.c>", [(1, RA)]), ("<a@b.c>", [(1, RA)]),   # P6
    ("<`n`>", [(1, RA)]),                                      # was accepted (no R2 opener); RA from round 4
]
PLACEHOLDER_ACCEPTED = [
    "`G<n>`", "`<date>`", "``a `<n>` b``", "`` <n> ``", "``x` <n> `y``",                                # P2
    "```\n<n>\n```", "~~~\n<n>\n~~~", "````\n```\n<n>\n````", "```\n<n>\n",
    "~~~~\n<n>\n~~~~~", "```\n<n>\n```  ",                                                               # P3
]


class PlaceholderTest(unittest.TestCase):
    def test_refused_samples(self):                    # P1, P5, P7, P8, P9, P10, P3 edges
        for text, want in PLACEHOLDER_REFUSED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_accepted_samples(self):                   # P2, P3, P4, P6
        for text in PLACEHOLDER_ACCEPTED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])

    def test_generated_inputs(self):                   # PC2 oracle: the verdict comes from the construction
        tags = {"<n>": "<n>", "<date>": "<date>", "<program>/integration": "<program>",
                "<the slugs in order>": "<the slugs in order>"}
        plain = ["a < b", "<1-4>", "<https://x.org>"]
        rng = random.Random(20261109)
        words = ["alpha", "beta", "x", "run", "(see)", "1", "e.g."]
        for _ in range(300):
            lines, want = [], []
            for _ in range(rng.randint(1, 6)):
                ph = rng.choice(list(tags) + plain)
                wrap = rng.choice(["none", "span1", "span2", "fence", "unpaired"])
                pre = " ".join(rng.choice(words) for _ in range(rng.randint(0, 3)))
                post = " ".join(rng.choice(words) for _ in range(rng.randint(0, 3)))
                pre = pre + " " if pre else ""
                post = " " + post if post else ""
                if wrap == "fence":
                    fence = rng.choice(["```", "~~~", "````"])
                    lines += [fence, pre + ph + post, fence]
                    continue
                body = {"none": ph, "span1": "`" + ph + "`", "span2": "`` " + ph + " ``", "unpaired": "` " + ph}[wrap]
                lines.append(pre + body + post)
                if ph in tags and wrap in ("none", "unpaired"):
                    want.append((len(lines), tags[ph]))
                if wrap == "unpaired":       # Q-B2FX2-1 (a): an unpaired run is refused (R1), after the line's hit
                    want.append((len(lines), "refused: multi-line code span"))
                if wrap in ("none", "unpaired"):     # W1 (round 4): every '<' outside a span is refused, after R1
                    want.append((len(lines), "refused: angle bracket outside code span"))
                if wrap in ("none", "unpaired") and "://" in ph:      # round 5 (D6): '://' outside a span
                    want.append((len(lines), "refused: extended autolink"))
                if wrap == "unpaired":
                    lines.append("")
            with self.subTest(doc=lines):
                self.assertEqual(pc.placeholder_hits("\n".join(lines) + "\n"), want)

    def test_b_owned_markdown_has_no_placeholder(self):     # A6, Q-B22v2-3 (a): every B-owned markdown file
        files = b_owned_markdown()
        self.assertEqual(files[:13], ["%s/%s.md" % (pc.PROMPTS_DIR, r) for r in pc.B_ROLES])   # Task 2c.3: 13
        self.assertIn(RULES, files)
        for rel in files:
            with self.subTest(rel=rel):
                self.assertEqual(pc.placeholder_hits(read(rel)), [])

    def test_seeded_hit_in_a_real_file_is_found(self):      # A6: the file check is not vacuous
        text = read(RULES)
        t = changed(text, "the active overrides", "the <n> active overrides")
        n = text[:text.index("the active overrides")].count("\n") + 1
        self.assertEqual(pc.placeholder_hits(t), [(n, "<n>"), (n, RA)])          # W2: the hit and its refusal

    def test_takes_str(self):
        with self.assertRaises(TypeError):
            pc.placeholder_hits(b"<n>")


class SpanPositionTest(unittest.TestCase):                   # verifier v11 F-1, F-2: rows S-a..S-e, PC1-a, PC1-b
    """Every per-span loop must see every code span, not only the first (prose_check.py _mask_spans,
    _info_refusals, _unpaired_runs and the table-row loop). Expected values are written by hand."""
    def check(self, cases):
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_table_row_pipe_span_after_the_first(self):      # S-a (F-1)
        self.check([
            ("| a | b |\n|---|---|\n| `x` | `<b>|` |", [(3, R3)]),                  # the reproducer: 2nd span, body row
            ("| a | `x` | `a|b` |\n|---|---|---|\n", [(1, R3)]),                     # header row, 3rd (last) span
            ("| `x` | `y` | `a|b` |\n|---|---|---|\n", [(1, R3)]),                   # 3rd of three
            ("| `x` | `a|b` | `y` |\n|---|---|---|\n", [(1, R3)]),                   # middle of three
            ("| `x` | `y` |\n|---|---|\n| `x` | `a|b` | `y` | `z` |", [(3, R3)]),    # body row, 2nd of four
            ("a | `x` | `a|b`\n---|---|---\n", [(1, R3)]),                           # no leading pipe, header
            ("a | b\n---|---\n`x` | `<b>|`", [(3, R3)]),                             # no leading pipe, body, last span
            ("a | b\n---|---\n`x` | `y` | `z` | `a|b`", [(3, R3)]),                  # no leading pipe, 4th
            ("| a |\n| `x` `|` |\n|---|", [(2, R3)]),                                # pipe span right after a span
            ("| a |\n|---|\n| `x` | `a|b` |\n| `y` | `c|d` |", [(3, R3), (4, R3)]),   # two rows
        ])

    def test_tilde_info_string_pipe_span_after_the_first(self):    # S-b (F-2)
        self.check([
            ("~~~ `x` `a|b`\ny\n~~~\n", [(1, R3)]),
            ("~~~ `x` `y` `a|b`\ny\n~~~\n", [(1, R3)]),
            ("~~~ `x` `a|b` `y`\ny\n~~~\n", [(1, R3)]),
            ("~~~~ a `x` b `c` d `e|f` g\ny\n~~~~\n", [(1, R3)]),
        ])

    def test_unpaired_run_after_spans(self):                  # S-c (R1)
        self.check([
            ("`a` `b` `\n", [(1, R1)]),
            ("`a` x ``\n", [(1, R1)]),
            ("`a` `b` `c` `\n", [(1, R1)]),
            ("~~~ `a` `b` `\ny\n~~~\n", [(1, R1)]),
            ("`a` `b`\n", []),            # controls: every run paired, no refusal for a span after the first
            ("`a` `b` `c`\n", []),
            ("`a` x ``b`` y\n", []),
        ])

    def test_mask_covers_every_span(self):                    # S-d
        self.check([
            ("`a` `<b>`\n", []),
            ("`a` `b` `<c>`\n", []),
            ("`a` `b` `c` `<d>`\n", []),
            ("`a` `www.x` `b` `\\c`\n", []),
            ("`a` <b>\n", [(1, "<b>"), (1, RA)]),     # control: the '<' outside a span is still found
        ])

    def test_controls_without_the_pipe_in_a_span(self):      # S-e
        self.check([
            ("| a | b |\n|---|---|\n| `x` | `y` |", []),
            ("| `x` | `y` | `z` |\n|---|---|---|\n", []),
            ("`x` `y` a|b\n", []),                                  # pipe outside every span, not a table row
            ("`x` | `y` | `z`\n", []),                              # no delimiter run, no leading pipe: not a row
            ("~~~ `x` `y` a|b\ny\n~~~\n", []),                      # pipe outside the spans
            ("`x` `a|b`\n", []),                                    # pipe span on a non-table line
        ])

    def test_long_digit_run_in_a_later_span(self):           # PC1-a: 4301 digits, same on 3.9 and 3.13
        digits = "1" * 4301
        self.check([
            ("| `x` | `%s|` |\n" % digits, [(1, R3)]),
            ("~~~ `x` `%s|`\ny\n~~~\n" % digits, [(1, R3)]),
        ])

    def test_non_ascii_gives_only_the_character_refusal(self):    # PC1-b
        self.check([("| `x` | `a|b%s` |\n" % chr(0xe9), [(1, RC)])])


# Row Y samples. GOOD_FM's expected dict is written here, not parsed back.
GOOD_FM = "---\nname: strict-delivery\ndescription: \"Use at the start: paths \\\"q\\\" and \\\\ b\"\n---\n# Body\n"
GOOD_FM_DICT = {"name": "strict-delivery", "description": "Use at the start: paths \"q\" and \\ b"}
FM_ACCEPTED = [   # (front matter lines between the --- lines, expected dict)
    (["name: strict-delivery"], {"name": "strict-delivery"}),                                            # Y3
    (["description: \"Use at the start: paths\""], {"description": "Use at the start: paths"}),          # Y2
    (["a-b_1: x"], {"a-b_1": "x"}), (["a: a#b"], {"a": "a#b"}), (["a: a:b"], {"a": "a:b"}),            # Y9, Y5
    (["a: \"\""], {"a": ""}), (["a: \"'x' #y: z\""], {"a": "'x' #y: z"}), (["a: x", "b: y"], {"a": "x", "b": "y"}),
    (["a: caf§"], {"a": "caf§"}), ([], {}),                     # round 5: the café row moved to FM_REFUSED (D8)
]
FM_REFUSED = [   # (front matter lines, line number named): line 1 is the opening ---
    (["description: Use at the start: paths"], 2),                                                       # Y1
    (["a: a #b"], 2), (["a: x:"], 2),                                                                     # Y5
    (["a:"], 2), (["a: "], 2), (["a: x", "a: y"], 3), (["a:\tx"], 2), (["a: x\ty"], 2), ([" a: x"], 2),
    (["a: |", "  more"], 2), (["- x"], 2), (["a:", "  - x"], 2), ([""], 2), (["# c"], 2), (["a: x "], 2),
    (["a:  x"], 2), (["a: x\r"], 2),                                                                      # Y6
    (["a: 'x: y'"], 2), (["a: 'x'"], 2),                                                                  # Y7
    (["Name: x"], 2), (["1a: x"], 2), (["a.b: x"], 2), (["a b: x"], 2), ([": x"], 2), (["-a: x"], 2),     # Y9
    (["a: \"\\n\""], 2), (["a: \"\\t\""], 2), (["a: \"\\x41\""], 2), (["a: \"\\" + chr(0xe9) + "\""], 2),
    (["a: \"x\\\""], 2),                                                                                  # Y10
    (["a: \"abc"], 2), (["a: \"a\" b"], 2), (["a: \"a\" # c"], 2), (["a: \"a\"b\""], 2),                  # Y11
    (["a: caf" + chr(0xe9)], 2),                       # round 5 (D8): was FM_ACCEPTED; outside the character whitelist
]
YAML_INDICATORS = "-?:,[]{}#&*!|>'\"%@`"


class FrontMatterTest(unittest.TestCase):
    def refused_at(self, text, line):
        with self.assertRaises(AssertionError) as cm:
            pc.front_matter(text)
        self.assertIn("line %d:" % line, str(cm.exception))

    def test_good_sample(self):                       # Y2, Y3, Y13
        got = pc.front_matter(GOOD_FM)
        self.assertEqual(got, GOOD_FM_DICT)
        self.assertEqual(list(got), ["name", "description"])

    def test_accepted(self):                          # Y2, Y3, Y5, Y9
        for lines, want in FM_ACCEPTED:
            with self.subTest(lines=lines):
                self.assertEqual(pc.front_matter("\n".join(["---"] + lines + ["---", "body"]) + "\n"), want)

    def test_refused(self):                           # Y1, Y5-Y7, Y9-Y11, Y15
        for lines, line in FM_REFUSED:
            with self.subTest(lines=lines):
                self.refused_at("\n".join(["---"] + lines + ["---", "body"]) + "\n", line)

    def test_indicator_first(self):                   # Y4
        for ch in YAML_INDICATORS:
            with self.subTest(ch=ch):
                self.refused_at("---\nname: ok\nv: " + ch + "x\n---\n", 3)

    def test_opening_and_closing_lines(self):         # Y12, Y6 no closer, Y15 short inputs
        for text, line in (("--- \na: x\n---\n", 1), ("----\na: x\n---\n", 1), ("x\n---\na: x\n---\n", 1),
                           ("---\na: x\n--- \n", 1), ("---\na: x\n...\n", 1), ("---\na: x\n", 1), ("---", 1),
                           ("---\n", 1), ("", 1), ("\n---\na: x\n---\n", 1), ("---\r\na: x\r\n---\r\n", 1)):
            with self.subTest(text=text):
                self.refused_at(text, line)
        self.assertEqual(pc.front_matter("---\na: x\n---"), {"a": "x"})
        self.assertEqual(pc.front_matter("---\na: x\n---\n---\nb: y\n"), {"a": "x"})

    def test_takes_str(self):
        with self.assertRaises(TypeError):
            pc.front_matter(b"---\n---\n")

    def test_messages_name_the_rule(self):            # Y15: the message names the line and the broken rule
        for line, part in (("abc", "not 'key: value'"), ("a:x", "not 'key: value'"), ("a: ", "empty value"),
                           ("a: -x", "starts with '-'"), ("a: \"\\n\"", "double-quoted"), ("a: x y:", "trailing ':'")):
            with self.subTest(line=line):
                with self.assertRaises(AssertionError) as cm:
                    pc.front_matter("---\n%s\n---\n" % line)
                self.assertIn("line 2: ", str(cm.exception))
                self.assertIn(part, str(cm.exception))

    def test_generated_inputs(self):                  # Y14: fixed seed; expected dict and verdict from the construction
        rng = random.Random(20261109)
        low = "abcdefghijklmnopqrstuvwxyz"
        for _ in range(400):
            keys, entries = [], []
            for _ in range(rng.randint(1, 5)):
                key = rng.choice(low) + "".join(rng.choice(low + "0123456789_-") for _ in range(rng.randint(0, 6)))
                if key in keys:
                    continue
                keys.append(key)
                if rng.random() < 0.5:
                    words = []
                    for _ in range(rng.randint(1, 4)):
                        w = "".join(rng.choice(low + "ABC019") for _ in range(rng.randint(1, 5)))
                        if rng.random() < 0.3:
                            w = w + rng.choice("#:./") + rng.choice(low)
                        words.append(w)
                    value = rng.choice(low) + " ".join(words)
                    entries.append((key, value, value))
                else:
                    raw, dec = "", ""
                    for _ in range(rng.randint(0, 6)):
                        piece = rng.choice([("ab", "ab"), (": ", ": "), (" #", " #"), ("\\\"", "\""), ("\\\\", "\\"),
                                            ("'", "'"), ("- ", "- "), ("§", "§")])  # fix round 5: § in the set
                        raw, dec = raw + piece[0], dec + piece[1]
                    entries.append((key, "\"" + raw + "\"", dec))
            lines = ["%s: %s" % (k, v) for k, v, _ in entries]
            want = {k: d for k, _, d in entries}
            with self.subTest(lines=lines):
                self.assertEqual(pc.front_matter("\n".join(["---"] + lines + ["---", "# x"]) + "\n"), want)
            bad = rng.choice(["indicator", "colon", "hash", "trailing", "empty", "single", "escape", "unterminated",
                              "after", "key", "duplicate", "tab", "indent", "noclose"])
            i = rng.randrange(len(lines))
            k = entries[i][0]
            mutated = list(lines)
            mutated[i] = {"indicator": "%s: %sv" % (k, rng.choice(YAML_INDICATORS)), "colon": "%s: a: b" % k,
                          "hash": "%s: a #b" % k, "trailing": "%s: ab:" % k, "empty": "%s: " % k,
                          "single": "%s: 'a'" % k, "escape": "%s: \"a\\%s\"" % (k, rng.choice("ntx0/u")),
                          "unterminated": "%s: \"ab" % k, "after": "%s: \"a\" b" % k, "key": "%s%s: x" % (
                              rng.choice("A1._ "), k), "duplicate": "%s: x\n%s: y" % (k, k), "tab": "%s: a\tb" % k,
                          "indent": " %s: x" % k, "noclose": lines[i]}[bad]
            text = "\n".join(["---"] + mutated + ([] if bad == "noclose" else ["---"]) + ["# x"]) + "\n"
            line = 1 if bad == "noclose" else i + 2 + (1 if bad == "duplicate" else 0)
            with self.subTest(bad=bad, mutated=mutated):
                self.refused_at(text, line)

    def test_b_owned_front_matter_files(self):        # Y8: the files the check runs on; not vacuous
        with_fm = [rel for rel in b_owned_markdown() if read(rel).split("\n", 1)[0] == "---"]
        self.assertEqual(with_fm, ["skills/strict-delivery/SKILL.md"])   # Task B2.3
        for rel in with_fm:
            pc.front_matter(read(rel))


# ---- Task B2.2 part 2: roles, decisions, sessions, streams, review ----
# Every expected value below is a literal from the plan (Task B2.2 Step 1) or the brief's input-domain rows; the
# production path is table_rows and section over the real files.

CTRL = "open, planned, in-progress, deferred, closed"
STATES = {"controller": CTRL, "program_controller": CTRL, "stream_controller": CTRL,
          "implementer": "fixed-unpinned, pinned", "implementer_transcription": "fixed-unpinned, pinned",
          "task_reviewer": "open", "final_reviewer": "open", "final_verifier": "open",
          "audit_reviewer": "open", "audit_verifier": "open", "investigator": "none", "exception_reviewer": "none",
          "plan_writer": "none", "plan_reviewer": "open", "drafter": "none"}  # fifteen: DB-2's twelve plus Task 2c.3's three
TIERS = {"implementer_transcription": "tier1", "implementer": "tier2",
         "controller": "tier3", "program_controller": "tier3", "stream_controller": "tier3", "task_reviewer": "tier2",
         "final_reviewer": "tier3", "audit_reviewer": "tier3", "audit_verifier": "tier3", "investigator": "tier3",
         "final_verifier": "tier4", "exception_reviewer": "tier4",
         "plan_writer": "tier3", "plan_reviewer": "tier3", "drafter": "tier2"}
ROLES_HEADER = "| role | prompt block | minimum tier | needs brief | finding states |"
ROLES_SECTIONS = ["Model tiers", "Budget cap", "Dispatch contract", "Report contract"]     # layout proposed (PC3)
OWNER_ONLY = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close",
              "rule-override", "profile-override", "program-create", "stream-ownership", "stream-merge",
              "request-dispute", "program-close"]    # row D8: hand-written, the 13 of gates/lib/config.py DEFAULTS on main
NEW_PLAYBOOKS = ("roles", "decisions", "sessions", "streams", "review")
PLAYBOOK_SECTIONS = {   # file stem -> [(heading, key phrases)]; each phrase is quoted from the source cited on its line
    "decisions": [("Asking", ["`decisions ask`", "decisions find", "search before asking", "`decisions batch --since`",
                              "Also open", "`source`", "recommended option", "`model-policy`", "`batch_cut`",
                              "corrected to the spec", "only the work that depends on its answer halts",
                              "nothing independent of them waits on the batch",
                              "until the binding Rules N and T verdict stops the loop"]),   # spec §7.4, §7.1; Q-LT-1 (a); design 5.4, 5.6
                  ("Answering", ["`decisions decide`", "`decisions withdraw`", "human"]),       # spec §7.1
                  ("Lasting decisions", ["`landed_in`", "never a spec"]),                       # spec §7.2, §7.4
                  ("Owner-only classes", ["`decision_classes.owner_only`", "`Decision (controller): class -- action -- "
                                          "cost if wrong`", "a controller ruling under the fix rule"])],   # Q-B22v2-5 (a); design 5.5
    "sessions": [("Session kinds", ["`program`", "`program-controller`", "`sync`"]),             # design §10
                 ("Start order", ["`in-force.md`", "`python3 -m gates context", "`required_reads`", "`ledger_from`",
                                  "investigator", "Q9", "G4", "Resume check", "before any edit or dispatch"]),
                 ("Blocks and checkpoints", ["`block.max_tasks`", "`CHECKPOINT`",
                                             "the full suite on the pull request's head"]),       # spec §8, §9; design 5.1
                 ("Handoffs and continuation", ["handoff", "80 %", "Nothing continues from inherited memory",
                                                "`live_subagents`", "`worktrees`", "handoff is complete", "TaskStop",
                                                "re-dispatches at the reset", "schedules a wake-up",
                                                "the handoff names the resume command"]),            # design 5.7, D6
                 ("Agent tree", ["program controller", "workers never dispatch", "configured depth"]),
                 ("Plan format", ["fail closed", "seeded generated-input test", "expected verdict",
                                  "a row with no test is a finding",
                                  "`what -- why -- cost if wrong -- spec cite`", "both quotes"]),       # spec §8a
                 ("Agent rules", ["background shell jobs", "DENIED", "does not re-run the denied action",
                                  "external code"]),                                                   # spec §10
                 ("Commits", ["assume-unchanged", "by name", "never amends", "`Co-Authored-By:`",
                           "every test module that imports a changed module", "is not a per-commit gate"]),     # spec §8a
                 ("Planning", ["planned in full before", "stream breakdown", "as they unblock",
                               "superpowers:brainstorming", "superpowers:writing-plans",
                               "superpowers:subagent-driven-development", "superpowers:executing-plans",
                               "input-domain dimensions", "assertions as code"])],                    # spec §8, Q-PL-1 (a)
    "streams": [("Programs and streams", ["program_controller", "stream_controller", "disjoint set of files",
                                          "never pauses a whole stream on a question",
                                          "when nothing independent is left the stream checkpoints and waits"]),  # 5.6
                ("Cross-stream requests", ["never edits", "request", "not on this branch", "before the final review"]),
                ("Syncs", ["`sync`", "integration branch"]),                                           # design §10
                ("Status page", ["status page"]),                                                     # design §11
                ("Pull-request flow", ["`gh pr merge --merge --match-head-commit`", "head sha", "`MERGED`",
                                       "as soon as it is ready", "`Consumes:`", "the stream-end adversarial review",
                                       "consumer streams do not stop",
                                       "blocks only that pull request"])],                      # design 5.2, D7
    "review": [("Task review", ["re-run every gate", "every test module that imports a changed module",
                                "the head of each pull request", "fix commit's parent"]),              # spec §8; design 5.1, 5.3
               ("Final review", ["whole branch", "as soon as it is ready", "goes out with the stream's final pull request"]),
               ("Verifier", ["`final_verifier`", "tier4", "Once per stream", "the parts it already merged included",
                             "not re-run after the fixes its findings cause"]),                        # DB-2; design 5.2
               ("Fix loop", ["rounds 1-3", "rounds 4-5", "owner question", "cosmetic", "never deferred",
                             "LOW_PLATEAU", "narrow", "fails closed", "parent", "Fix rule.", "new modelled behaviour",
                             "Blame is tested", "`Decision (controller)`", "STOP_NARROW", "review 6"]),  # spec §10; §8; DN-4; 5.3, 5.4
               ("Input domains", ["input-domain table", "independent expected value", "NEEDS_DECISION",
                                  "class-narrowing question", "class: <dimension>: <members>"]),      # spec §8, Q-SDDT-5
               ("Small re-review", ["`reviews.small`", "round 5", "escalate", "Rule N", "Rule T"]),
               ("Process-defect stop", ["process defect", "stop fixing"]),                            # spec §8
               ("Rules N and T", ["Rule N", "Rule T", "`python3 -m gates loopstats`", "The verdict is binding",
                                  "STOP_NARROW and ESCALATE stop the loop"]),                        # design 5.4
               ("Review methods", ["watched red", "behaviour stub", "pre-change commit", "pasted result"]),  # spec §8a
               ("Plan review", ["verbatim", "occurs once", "`Consumes`", "pairwise disjoint", "omission",
                                "reads the whole document", "adds no new design", "one final edit pass",
                                "one adversarial review runs at the end of planning",
                                "never reopens the planning loop"])],                             # spec §8a; design 5.9
}
RESTART_END = ("Only the session writes decision records; workers never do, and never change anything for a question. "
               "Fix and re-review rounds run until the binding Rules N and T verdict stops the loop.")   # row D9, design 5.4


def headings(text):
    return [line[3:] for line in text.split("\n") if line.startswith("## ")]


def in_order(body, items):
    """True when every item occurs in body, each after the previous one."""
    at = -1
    for s in items:
        at = body.find(s, at + 1)
        if at < 0:
            return False
    return True


class PlaybookFilesTest(unittest.TestCase):
    def test_roles_table_covers_spec_roles(self):                 # plan; RO2-RO6, RO11, RO12
        rows = table_rows(read("playbook/roles.md"))
        self.assertEqual([r["role"] for r in rows], list(pc.SPEC_ROLES))
        for r in rows:
            self.assertEqual(r["prompt block"], "skills/strict-delivery/prompts/%s.md" % r["role"])
            self.assertIn(r["minimum tier"], ("tier1", "tier2", "tier3", "tier4"))
            if r["role"] in pc.B_ROLES:
                self.assertTrue(os.path.isfile(os.path.join(pc.REPO_ROOT, r["prompt block"])), r["role"])
        self.assertEqual({r["role"]: r["minimum tier"] for r in rows}, TIERS)       # DB-2, all twelve
        self.assertTrue(all(r["needs brief"] == "yes" for r in rows))               # Q-B22-1 (a)
        self.assertTrue(len(STATES) == 15 and set(TIERS) <= set(STATES))
        self.assertEqual({r["role"]: r["finding states"] for r in rows}, {k: STATES[k] for k in TIERS})

    def test_roles_header_and_top_tier(self):                     # RO1, RO6, RO13: exact header; tier4 rows
        text = read("playbook/roles.md")
        self.assertEqual(pc.first_table_header(text), ROLES_HEADER)
        rows = table_rows(text)
        self.assertEqual([r["role"] for r in rows if r["minimum tier"] == "tier4"], ["final_verifier", "exception_reviewer"])
        self.assertNotIn("merged", text)                              # RO12: no role sets merged

    def test_roles_contract_sections(self):                       # RO7-RO10 (rulings R-v2-1, R-v2-2; Q-B2R-1 (a))
        text = read("playbook/roles.md")
        self.assertEqual(headings(text), ROLES_SECTIONS)
        tiers = pc.section(text, "Model tiers")
        for s in ("`top_tier_roles`", "`top_tier_fallback`", "`tier3`", "`tier4`"):
            self.assertIn(s, tiers)                                   # RO7
        budget = pc.section(text, "Budget cap")
        self.assertIn("`budgets.<role>`", budget)                     # RO10: the key, not a number
        self.assertIsNone(re.search(r"\d", budget.replace("`budgets.<role>`", "")))
        dispatch = pc.section(text, "Dispatch contract")
        self.assertTrue(in_order(dispatch, ["`%s`" % h for h in pc.DISPATCH_HEADINGS]))     # RO8
        self.assertIn("fork dispatch is refused", dispatch)
        self.assertIn("`%s`" % pc.STATUS_LINE, pc.section(text, "Report contract"))          # RO9

    def test_playbook_files_first_line_and_clean(self):           # plan; A1, A3
        for stem in ("rules",) + NEW_PLAYBOOKS:
            with self.subTest(stem=stem):
                t = read("playbook/%s.md" % stem)
                self.assertEqual(t.split("\n", 1)[0], "# Base playbook: " + stem)
                self.assertEqual(forbidden_hits(t), [])

    def test_playbook_bytes(self):                                # A2: as rules.md (UTF-8, LF, no control, no trailing ws)
        for stem in NEW_PLAYBOOKS:
            with self.subTest(stem=stem):
                with open(os.path.join(pc.REPO_ROOT, "playbook", stem + ".md"), "rb") as f:
                    raw = f.read()
                text = raw.decode("utf-8")
                self.assertEqual([c for c in text if c != "\n" and unicodedata.category(c) in ("Cc", "Zl", "Zp", "Cf")], [])
                self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))
                self.assertEqual([n for n, line in enumerate(text.split("\n"), 1) if line != line.rstrip()], [])

    def test_tiers_never_models(self):                            # A4: tier names only tier1-tier4
        for stem in NEW_PLAYBOOKS:
            with self.subTest(stem=stem):
                t = read("playbook/%s.md" % stem)
                self.assertEqual(set(re.findall(r"\btier\d+\b", t)) - {"tier1", "tier2", "tier3", "tier4"}, set())
                self.assertEqual([h for h in forbidden_hits(t) if h[0] == "model-name"], [])

    def test_decisions_playbook_human_only(self):                 # plan
        self.assertIn("decisions decide", read("playbook/decisions.md"))
        self.assertIn("human", read("playbook/decisions.md"))

    def test_sessions_names_default_tree(self):                   # plan; Q-BD-5 (a); SS3
        self.assertIn("workers never dispatch", pc.section(read("playbook/sessions.md"), "Agent tree"))

    def test_streams_names_pr_flow(self):                         # plan; Q-BD-5 (a); ST2
        self.assertIn("--match-head-commit", pc.section(read("playbook/streams.md"), "Pull-request flow"))

    def test_playbook_sections_and_key_phrases(self):             # plan; A5, D1-D4, SS1, SS2, ST1, R1, R2, DN4-2
        for stem, secs in PLAYBOOK_SECTIONS.items():
            t = read("playbook/%s.md" % stem)
            self.assertEqual(headings(t), [h for h, _ in secs], stem)
            for h, phrases in secs:
                body = pc.section(t, h)
                for s in phrases:
                    self.assertIn(s.lower(), body.lower(), (stem, h, s))

    def test_key_phrase_only_in_another_section_fails(self):      # A5: the check reads the named section only
        t = read("playbook/review.md")
        self.assertNotIn("stop fixing", pc.section(t, "Task review").lower())
        moved = t.replace("## Task review\n", "## Task review\nstop fixing\n", 1)
        self.assertIn("stop fixing", pc.section(moved, "Task review").lower())

    def test_plan_fix_loop_line_names_low_plateau(self):          # DN4-2: the plan line of B2.2's own section
        plan = read("docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md")
        line = [ln for ln in plan.split("\n") if ln.lstrip().startswith('("Fix loop", [')]
        self.assertEqual(len(line), 1)
        self.assertIn('"never deferred", "LOW_PLATEAU"]', line[0])

    def test_decisions_answering_routes(self):                    # D5, D6, D7 (ruling R-v2-3)
        body = pc.section(read("playbook/decisions.md"), "Answering")
        for s in ("from any subagent", "the owner's exact words", "`!` prefix",                 # D5
                  "refuses any agent Edit or Write under `paths.decisions`",                    # D6
                  "not a decision record", "`MERGED`", "head sha"):                             # D7
            self.assertIn(s, body)

    def test_decisions_asking_by_hand_and_printed_form(self):     # D2: the plan's "Asking" content (design §3.6, §3.7)
        body = pc.section(read("playbook/decisions.md"), "Asking")
        for s in ("words of at least 4 characters", "`git log -S`", "A question found answered is cited, not asked",
                  "the recommended option with its cost, every alternative with its cost",
                  "are not printed", "one header per `source`", "Printing writes nothing"):
            self.assertIn(s, body)

    def test_decisions_owner_only_classes(self):                  # D8 (owner Q-B22v2-5 (a))
        text = read("playbook/decisions.md")
        body = pc.section(text, "Owner-only classes")
        rows = table_rows(body)
        self.assertEqual([r["slug"] for r in rows], OWNER_ONLY)
        self.assertEqual(len(set(r["slug"] for r in rows)), len(rows))
        self.assertIn("`decision_classes.owner_only`", body)
        self.assertIn("a project may add", body.lower())
        self.assertEqual(headings(text).index("Owner-only classes"), headings(text).index("Lasting decisions") + 1)

    def test_decisions_owner_only_table_refuses_changes(self):    # D8: missing, extra, reordered, duplicated
        body = pc.section(read("playbook/decisions.md"), "Owner-only classes")
        lines = body.split("\n")
        first = next(i for i, ln in enumerate(lines) if ln.startswith("| triage |"))
        variants = [lines[:first] + lines[first + 1:],                                            # missing
                    lines[:first] + ["| extra-class | x |"] + lines[first:],                      # extra
                    lines[:first] + [lines[first + 1], lines[first]] + lines[first + 2:],          # reordered
                    lines[:first] + [lines[first]] + lines[first:]]                                # duplicated
        for v in variants:
            self.assertNotEqual([r["slug"] for r in table_rows("\n".join(v))], OWNER_ONLY)

    def test_decisions_restart_end_and_no_ledger_cite(self):      # D9, D10
        text = read("playbook/decisions.md")
        asking = pc.section(text, "Asking")
        self.assertTrue(asking.rstrip("\n").endswith(RESTART_END))
        self.assertIn("Owner answers (date), binding", asking)
        self.assertIsNone(re.search(r"\bL:\d|\bX-\d", text))
        self.assertEqual(pc.placeholder_hits(text), [])

    def test_sessions_kinds_and_continuation(self):               # SS4, SS5 (ruling R-v2-4)
        t = read("playbook/sessions.md")
        self.assertIn("`plan`", pc.section(t, "Session kinds"))
        hc = pc.section(t, "Handoffs and continuation")
        for s in ("usage-limit stop", "fresh agent of the same role", "`BLOCKED: budget`"):
            self.assertIn(s, hc)

    def test_sessions_start_order_questions(self):                # SS6, SS7; F-RDV2-1 copy with code-span placeholders
        t = read("playbook/sessions.md")
        body = pc.section(t, "Start order")
        for q in ["Q%d" % n for n in range(1, 10)] + ["G%d" % n for n in range(1, 5)]:
            self.assertIsNotNone(re.search(r"(?m)^- %s " % q, body), q)
        for s in ("`Q<n> <fact>: match`", "`G<n>`", "`ledger_from - 1`", "`<program>/integration`",
                  "`git -C <path> merge-base --is-ancestor <head> HEAD`", "`git -C <root> show <branch>:<path>`"):
            self.assertIn(s, body)
        self.assertEqual(pc.placeholder_hits(t), [])
        self.assertTrue(in_order(body, ["Resume check", "before any edit or dispatch"]))

    def test_streams_rules(self):                                 # ST3-ST6 (rulings R-v2-5, R-v2-6)
        t = read("playbook/streams.md")
        pr = pc.section(t, "Pull-request flow")
        for s in ("pushed or merged to the base branch directly", "Bash hook", "one pull request"):
            self.assertIn(s, pr)                                      # ST3, ST2
        self.assertIn("`Rq-<n> not on this branch`", pc.section(t, "Cross-stream requests"))     # ST4
        self.assertIn("never a rebase", pc.section(t, "Syncs"))                                    # ST5
        ps = pc.section(t, "Programs and streams")
        self.assertIn("each stream owns a set of files disjoint from the other streams'", ps)   # ST6, spec §11

    def test_review_fix_loop_zero_bugs(self):                     # DN4-1 (owner DN-4 (a), Q-CONV-1 (a), DN-1 (b))
        body = pc.section(read("playbook/review.md"), "Fix loop")
        for s in ("a minor is a real defect", "fixed, or registered as a LOW under LOW_PLATEAU, or registered against a "
                  "named task when the binding verdict (STOP_NARROW, ESCALATE) stops the loop, and otherwise never deferred",
                  "two consecutive reviews", "a review with no change-caused finding counts as all-LOW",
                  "the loop ends", "registered", "always fixed"):
            self.assertIn(s.lower(), body.lower())

    def test_review_rule_t_weighted_tally(self):                  # owner Q-CONV-1 (a): Rule T on the weighted tally
        body = pc.section(read("playbook/review.md"), "Rules N and T")
        for s in ("weighs 8 (CRITICAL), 4 (HIGH), 2 (MEDIUM) or 1 (LOW)", "`N = sum W_i`", "`S = sum (i-1) W_i`",
                  "the LOW run", "is at least 2", "`E_next` and `N` are the weighted tally's"):
            self.assertIn(s, body)
        for s in ("`N = sum X_i`", "`S = sum (i-1) X_i`"):
            self.assertNotIn(s, body)                                 # the plain-count text is refused

    def test_rule_row_references_pair_each_method_with_its_row(self):   # F-B22R2-1, whole class: every SD-R ref
        rows = table_rows(read(RULES))
        clean = [r["id"] for r in rows if "clean copy" in r["rule"]]
        mut = [r["id"] for r in rows if "mutation review" in r["rule"]]
        self.assertEqual((len(clean), len(mut)), (1, 1))
        contexts = {"the mutation review": mut[0], "the clean-copy review": clean[0],
                    "a clean copy of the reviewed head": clean[0]}       # method named just before its row
        found = 0
        for stem in NEW_PLAYBOOKS:
            t = read("playbook/%s.md" % stem)
            refs = re.findall(r"SD-R\d+", t)
            pinned = list(re.finditer(r"(?i)(the mutation review|the clean-copy review|a clean copy of the reviewed head)"
                                      r" \(row `(SD-R\d+)`\)", t))
            self.assertEqual(len(refs), len(pinned), stem)               # no reference outside a pinned pairing
            for m in pinned:
                self.assertEqual(m.group(2), contexts[m.group(1).lower()], (stem, m.group(0)))
            found += len(pinned)
        self.assertGreaterEqual(found, 4)                                # review.md: intro, Task review, methods (2)

    def test_signals_keep_the_low_plateau_exception(self):       # F-B22R2-2, whole class: what the signals decide
        hits = []
        for stem in NEW_PLAYBOOKS:
            for line in read("playbook/%s.md" % stem).split("\n"):
                if "The verdict is binding" in line:
                    hits.append(stem)
                    self.assertIn(VERDICT_INVARIANT, line, stem)
        self.assertEqual(hits, ["review"])
        body = pc.section(read("playbook/review.md"), "Rules N and T")
        self.assertIn(VERDICT_INVARIANT, body)                    # invariant: a change-caused CRITICAL/HIGH is fixed
        self.assertNotIn("advisory", body)                        # design 5.4: the verdict is binding, not advisory
        self.assertNotIn("never block a fix", body)

    def test_finding_records_for_loopstats_and_plan_3d1_alignment(self):   # program controller input; design 5.4
        rec = ("After each review, before `loopstats` runs, a finding record (schema `finding`) is written for each "
               "finding of that review, with `python3 -m gates findings new --review-round <k> --caused-by-change yes|no --dimension <dimension>` (plus its required flags), under config "
               "`paths.findings` on the task's branch, by the controller, which mints each id with `findings new` "
               "(owner answer Q-PV2-3 (a), 2026-11-17). The records stay on "
               "that branch while its pull request is open and merge with it, and `loopstats` counts only findings "
               "that have a record.")
        spec = " ".join(read("docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md").split())
        self.assertEqual(spec.count(rec), 1)
        self.assertEqual(" ".join(pc.section(read("playbook/review.md"), "Rules N and T").split()).count(rec), 1)
        self.assertIn("A finding carries `review_round`, `caused_by_change` and `dimension`. " + rec, spec)
        plan = read(PLAN_DOC)
        self.assertIn("`json.loads` refusing duplicate keys, keeping each JSON integer as a `str` subclass "
                      "(PC1 S1: no `int()` runs)", plan)
        self.assertEqual(plan.count("`plugin.repository`"), 1)      # only the sentence that says it is satisfied

    def test_review_rules_n_t_and_methods(self):                  # R3, R4, R6
        t = read("playbook/review.md")
        self.assertIn("`class: <dimension>: <members>`", pc.section(t, "Input domains"))          # R3
        self.assertIn("`Loopstats:`", pc.section(t, "Rules N and T"))                             # R4
        methods = pc.section(t, "Review methods")
        self.assertIn("`SD-R9`", methods)                                                          # R6
        self.assertIn("`SD-R10`", methods)
        for s in ("one mutant per changed condition", "git merge-tree", "git archive"):
            self.assertNotIn(s, t)                                    # not restated: they are rules.md rows


# F-B23R-1, class "profile: light, standard; final verifier stated as unconditional". Every expected string is written
# here by hand from design spec section 12 ("| top-tier final verifier | no | no | yes |"), the programs spec :140 and
# the controller's decisions D1-D3; none is read back from the files.
BLOCK_END_ORDER = ("A branch ends in this order: final review, the full suite on the pull request's head, the "
                   "top-tier verifier and the review of its fix diffs (at a stream's end only), the owner's approval, "
                   "merge, post-merge gates, checkpoint.")              # design 5.1, 5.2 (process v2), plan B1 (D2)
VERDICT_INVARIANT = "it never stops a change-caused CRITICAL or HIGH finding from being fixed"   # design 5.4
VERIFIER_PROFILE = ("The top-tier verifier runs only where the profile enables it, the strict profile (design spec "
                    "section 12); the light and standard profiles skip that step.")                            # D2
VERIFIER_OPENING = ("Once per stream, at its end, after a clean final review and where the profile enables it "
                    "(strict), the `final_verifier` tries to break everything the stream delivered, the parts it "
                    "already merged included; a plain plan counts as one stream.")                  # D3; design 5.2, D2
PROFILE_CONDITION = "where the profile enables it"
# F-B23RR1-1: a verifier term is `final_verifier` or the word "verifier" (so "final verifier", "top-tier verifier" and
# a bare "the verifier"); `audit_verifier` is another role and does not match. Every prose unit naming one is a member
# unless it is hand-listed below as a non-step unit, with its reason.
_VERIFIER = re.compile(r"final_verifier|\bverifier\b", re.I)
VERIFIER_NON_STEPS = [   # (file, the whole unit verbatim, why it states no block-end step); D6, F-B2FX2RR-3
    ("playbook/roles.md",
     "| final_verifier | skills/strict-delivery/prompts/final_verifier.md | tier4 | yes | open |",
     "role table row: prompt block, minimum tier, finding states"),
    ("playbook/roles.md",
     "A role runs at its minimum tier or above. A dispatch chooses a tier, and config `models.tiers` maps each tier to "
     "the model the project uses: the dispatch's `## Model` names that model, and every other line of a brief or "
     "report names tiers, never a model. The top tier, `tier4`, is allowed only for the roles in "
     "`top_tier_roles`, by default `final_verifier` and `exception_reviewer`. `tier4` has no default model; while it "
     "is unset, the `top_tier_roles` run at the tier `top_tier_fallback` names, default `tier3`. A small re-review "
     "that the dispatch check admits may run below the reviewer's minimum tier (`playbook/review.md`, \"Small "
     "re-review\").",
     "tier rule: `final_verifier` is one of `top_tier_roles`"),
    ("skills/strict-delivery/SKILL.md",
     "The roles, with their prompt blocks, minimum tiers and finding states, are in `playbook/roles.md`: "
     "`program_controller`, `stream_controller`, `controller`, `implementer`, `implementer_transcription`, "
     "`task_reviewer`, `final_reviewer`, `final_verifier`, `exception_reviewer`, `audit_reviewer`, `audit_verifier`, "
     "`investigator`, `plan_writer`, `plan_reviewer` and `drafter`.",
     "the role list"),
]   # a unit is exempt only verbatim: any edit in place or any added text makes it a member
# The class members, hand-listed: (file, the start of the paragraph that states the verifier as a block-end step).
VERIFIER_STEP_MEMBERS = [
    ("playbook/review.md", "Before a pull request opens, a `final_reviewer`"),
    ("playbook/review.md", "Once per stream, at its end, after a clean final review"),
    ("playbook/rules.md", "| SD-R9 | Reviewers execute every claim"),    # R1-4: no longer exempt, it names the condition
    ("playbook/sessions.md", "One block per agent context"),
    ("skills/strict-delivery/SKILL.md", "Each task runs an implementer"),
]
LOW_PLATEAU_BY_HAND = "the controller applies the verdict and the weighted tally by hand and ledgers the verdict."   # F-B22RR1-1, Q-CONV-1 (a), design 5.4


def verifier_class_files():
    """The B2-owned SKILL.md and playbook files (the prompt blocks are outside the F-B23R-1 class)."""
    return [p for p in b_owned_markdown() if not p.startswith(pc.PROMPTS_DIR + "/")]


def prose_units(text, cells=False):
    """The prose units of a markdown text: each blank-line paragraph, headings dropped; in a table each row is a unit,
    or with cells=True each cell of a row."""
    out = []
    for para in re.split(r"\n[ \t]*\n", text):
        para = para.strip("\n")
        if not para.strip() or para.startswith("#"):
            continue
        if para.startswith("|"):
            for row in para.split("\n"):
                if cells:
                    out += [c.strip() for c in row.strip().strip("|").split(" | ") if c.strip()]
                else:
                    out.append(row)
        else:
            out.append(para)
    return out


def verifier_step_paragraphs(text, rel=None):
    """The prose units that name a verifier term and are not hand-listed for rel as non-step units: the units that
    state the verifier as a block-end step (F-B23RR1-1)."""
    exempt = [unit for f, unit, _ in VERIFIER_NON_STEPS if f == rel]
    return [u for u in prose_units(text) if _VERIFIER.search(u) and u not in exempt]


def verifier_step_problems(text, rel=None):
    """F-B23R-1 class check: each block-end verifier paragraph states the profile condition and the strict profile."""
    return [p[:60] for p in verifier_step_paragraphs(text, rel)
            if PROFILE_CONDITION not in p.lower() or "strict" not in p.lower()]


# F-B2F-1, class "zero-bugs deferral statements in B2-owned files". A unit that states a minor is never deferred, or
# names a minor with a deferral or a follow-up, also names LOW_PLATEAU (DN-4 (a); docs-owed spec section 8 wording).
_DEFERRAL = re.compile(r"never deferred|\bminors?\b.*(?:defer|follow-up)|\bdeferred defect", re.I | re.S)
# F-B2F1RR-1: a why cell that argues against deferral is a member too ("A deferred defect is a defect shipped").
SD_R5_LOW_PLATEAU = ("fixed in the fix round, or registered as a LOW under LOW_PLATEAU, or registered against a named "
                     "task when the binding verdict (STOP_NARROW, ESCALATE) stops the loop, and otherwise never deferred")
DEFERRAL_MEMBERS = [   # (file, the start of the unit), in b_owned_markdown() order; written by hand
    ("skills/strict-delivery/prompts/controller.md", "Zero bugs. A change's own bug makes its task incomplete"),
    ("playbook/review.md", "Zero bugs: a change's own bug makes it incomplete. A minor is a real defect"),
    ("playbook/rules.md", "Zero bugs: a change's own bug makes it incomplete, and a minor is a real defect"),
    ("playbook/rules.md", "A deferred defect is a defect shipped, so only a LOW registered"),
]
_IMPLEMENTER_ZERO_BUGS = (
    "Zero bugs. A defect your own change introduces makes the work incomplete; there is no minor defect and no "
    "follow-up. A defect you find that your change did not cause is not fixed in passing: record file:line, a "
    "reproducer and the class statement under Unrelated findings, so the controller registers it with an owner.")
DEFERRAL_NON_MEMBERS = [   # (file, the whole unit, why it is not a statement of the deferral rule for minors)
    ("skills/strict-delivery/prompts/implementer.md", _IMPLEMENTER_ZERO_BUGS,
     "the implementer's own change: no defect of it may be called minor; LOW_PLATEAU is the controller's act"),
    ("skills/strict-delivery/prompts/implementer_transcription.md", _IMPLEMENTER_ZERO_BUGS, "as implementer.md"),
]   # F-B2F1RR-2, whole class: an exemption holds only for the unit verbatim, so any added text makes it a member


def deferral_units(text, rel=None):
    """The prose units and table cells that state the deferral rule for minors, less the hand-listed non-members."""
    exempt = [unit for f, unit, _ in DEFERRAL_NON_MEMBERS if f == rel]
    return [u for u in prose_units(text, cells=True) if _DEFERRAL.search(u) and u not in exempt]


def deferral_problems(text, rel=None):
    return [u[:60] for u in deferral_units(text, rel) if "LOW_PLATEAU" not in u]


def non_ascii_lines(raw):
    """Line numbers (1-based) of the lines holding a byte above 0x7f."""
    return [n for n, ln in enumerate(raw.split(b"\n"), 1) if any(b >= 0x80 for b in ln)]


class VerifierProfileTest(unittest.TestCase):                    # F-B23R-1 (FX1-FX5, FX7), F-B22RR1-1 (FX6)
    def test_block_end_order_kept_and_qualified(self):            # FX2, FX4: spec sentence verbatim, then the qualifier
        for rel, heading in (("playbook/review.md", "Final review"), ("playbook/sessions.md", "Blocks and checkpoints")):
            with self.subTest(rel=rel):
                body = pc.section(read(rel), heading)
                self.assertEqual(body.count(BLOCK_END_ORDER), 1)
                self.assertIn(BLOCK_END_ORDER + " " + VERIFIER_PROFILE, body)

    def test_verifier_paragraph_conditioned(self):                # FX3
        self.assertIn(VERIFIER_OPENING, pc.section(read("playbook/review.md"), "Verifier"))

    def test_fix_loop_low_plateau_and_tally_by_hand(self):        # FX6, F-B22RR1-1
        body = pc.section(read("playbook/review.md"), "Fix loop")
        self.assertIn(LOW_PLATEAU_BY_HAND, body)
        self.assertNotIn("applies LOW_PLATEAU by hand", body)
        self.assertNotIn("applies LOW_PLATEAU and the weighted tally by hand", body)   # the pre-v2 sentence is gone

    def test_class_every_block_end_verifier_paragraph_conditioned(self):   # FX5, whole class, through the real files
        files = verifier_class_files()
        for rel in ("skills/strict-delivery/SKILL.md", "playbook/review.md", "playbook/sessions.md", "playbook/roles.md",
                    "playbook/rules.md", "playbook/decisions.md", "playbook/streams.md"):
            self.assertIn(rel, files)
        found = []
        for rel in files:
            text = read(rel)
            with self.subTest(rel=rel):
                self.assertEqual(verifier_step_problems(text, rel), [])
            found += [(rel, p) for p in verifier_step_paragraphs(text, rel)]
        self.assertEqual([(rel, p[:60]) for rel, p in found],
                         [(rel, p[:60]) for rel, p in found if any(rel == r and p.startswith(s)
                                                                   for r, s in VERIFIER_STEP_MEMBERS)])
        self.assertEqual(len(found), len(VERIFIER_STEP_MEMBERS))
        for (rel, para), (want_rel, start) in zip(found, VERIFIER_STEP_MEMBERS):
            self.assertEqual(rel, want_rel)
            self.assertTrue(para.startswith(start), (rel, para[:60]))

    def test_verifier_non_steps_each_exempt_one_unit(self):      # F-B23RR1-1: every exemption names one real unit
        for rel, unit, why in VERIFIER_NON_STEPS:
            with self.subTest(rel=rel, unit=unit[:30]):
                self.assertEqual(prose_units(read(rel)).count(unit), 1)
                self.assertTrue(why and _VERIFIER.search(unit))

    def test_exempt_unit_with_an_added_step_fails(self):          # F-B2F1RR-2, V5, M8: E2, a word changed, row text
        step = "At a block's end the verifier runs."
        for rel, unit, _ in VERIFIER_NON_STEPS:
            text = read(rel)
            words = unit.split(" ")
            mid = len(words) // 2
            changed = " ".join(words[:mid] + [words[mid] + "x"] + words[mid + 1:])      # one word changed in place
            grown = unit[:-2] + " " + step + " |" if unit.endswith(" |") else unit + " " + step
            variants = [grown, changed]
            if unit.startswith("| "):
                first = unit.index(" | ", 2)
                variants.append(unit[:first] + " x" + unit[first:])                   # text after a table row start
            for v in variants:
                with self.subTest(rel=rel, v=v[:40]):
                    self.assertEqual(text.count(unit), 1)
                    self.assertEqual(verifier_step_problems(text.replace(unit, v), rel), [v[:60]])

    def test_class_refuses_an_unconditioned_paragraph(self):     # FX5, F-B23RR1-1: a new member without the condition
        added = ["Each block ends with a final review and a final verifier.",
                 "After the final review the top-tier verifier runs.",
                 "After a clean final review the `final_verifier` tries to break the branch; strict reviewers agree.",
                 "At a block's end the top-tier verifier runs.",                     # M9 of the B2.3 re-review
                 "Then the verifier tries to break the branch."]                     # a bare "verifier"
        for rel in verifier_class_files():
            for s in added:
                with self.subTest(rel=rel, s=s):
                    self.assertEqual(verifier_step_problems(read(rel) + "\n" + s + "\n", rel), [s[:60]])
        self.assertEqual(verifier_step_problems("The final review checks `final_reviewer` output.\n"), [])
        self.assertEqual(verifier_step_problems("The `audit_verifier` re-runs the audit.\n"), [])

    def test_deferral_class_every_unit_names_low_plateau(self):   # F-B2F-1 (FR2), whole class, through the real files
        found = []
        for rel in b_owned_markdown():
            text = read(rel)
            with self.subTest(rel=rel):
                self.assertEqual(deferral_problems(text, rel), [])
            found += [(rel, u[:80]) for u in deferral_units(text, rel)]
        self.assertEqual(len(found), len(DEFERRAL_MEMBERS), found)
        for (rel, unit), (want_rel, start) in zip(found, DEFERRAL_MEMBERS):
            self.assertEqual(rel, want_rel)
            self.assertTrue(unit.startswith(start), (rel, unit))
        for rel, unit, why in DEFERRAL_NON_MEMBERS:           # each exemption names one real unit, verbatim
            self.assertEqual(prose_units(read(rel), cells=True).count(unit), 1, rel)
            grown = read(rel).replace(unit, unit + " A review minor may wait for a follow-up.")
            self.assertEqual(len(deferral_problems(grown, rel)), 1, rel)          # F-B2F1RR-2, whole class
            changed = read(rel).replace(unit, unit.replace("no follow-up", "a follow-up"))   # M8: edited in place
            self.assertEqual(len(deferral_problems(changed, rel)), 1, rel)

    def test_sd_r5_why_cell_names_low_plateau(self):              # F-B2F1RR-1, V4
        row = [r for r in table_rows(read(RULES)) if r["id"] == "SD-R5"][0]
        self.assertEqual(row["why"], "A deferred defect is a defect shipped, so only a LOW registered under LOW_PLATEAU, "
                                     "or a finding registered against a named task when a binding verdict stops the "
                                     "loop, may wait.")
        bare = read(RULES).replace(row["why"], "A deferred defect is a defect shipped.")
        self.assertEqual(deferral_problems(bare, RULES), ["A deferred defect is a defect shipped."])

    def test_deferral_class_refuses_a_statement_without_low_plateau(self):   # F-B2F-1 (FR2): a new member fails
        added = ["A minor is a real defect and is never deferred.",
                 "Review minors are fixed and never deferred to a follow-up.",
                 "| X | a minor is fixed, never deferred | why |"]
        for rel in b_owned_markdown():
            for s in added:
                with self.subTest(rel=rel, s=s):
                    self.assertEqual(len(deferral_problems(read(rel) + "\n" + s + "\n", rel)), 1)
        self.assertEqual(deferral_problems("A minor is fixed, or registered under LOW_PLATEAU, never deferred.\n"), [])

    def test_sd_r5_low_plateau_exception(self):                   # F-B2F-1 (FR1), DN-4 (a)
        row = [r for r in table_rows(read(RULES)) if r["id"] == "SD-R5"][0]
        self.assertIn(SD_R5_LOW_PLATEAU, row["rule"])
        self.assertNotIn("fixed in the fix round and never deferred", row["rule"])
        self.assertNotIn("until a clean pass", row["rule"])           # design 5.9: the document re-review is bounded
        self.assertIn("is stopped by the same binding verdict", row["rule"])
        self.assertNotIn("under LOW_PLATEAU, and otherwise never deferred", row["rule"])   # the pre-v2 sentence is gone
        self.assertEqual(row["source"], "spec §8")

    def test_edited_playbook_files_ascii(self):                   # FX7 (D2): review.md and sessions.md stay ASCII
        for rel in ("playbook/review.md", "playbook/sessions.md"):
            with open(os.path.join(pc.REPO_ROOT, rel), "rb") as f:
                raw = f.read()
            with self.subTest(rel=rel):
                self.assertEqual(non_ascii_lines(raw), [])
                for ch in ("§", "—"):
                    self.assertEqual(non_ascii_lines(raw + ch.encode("utf-8") + b"\n"), [raw.count(b"\n") + 1])


# Block B2 verifier round (F-B2V3-1..3), converted in fix round 3 to the input restriction (owner Q-B2FX2-1 (a),
# controller D1-D5). Every expected value is written here by hand.
SPAN_HTML_REFUSED = [   # V1: (text, result)
    ('x <a title="`"> y ` z\n', [(1, RA)]),                                 # reproducer 1: backtick inside a tag
    ("`a\nb` <x> `c`\n", [(1, R1), (2, R1)]),                               # reproducer 2: span over a line break
    ('see <n title="`"> and ` here\n', [(1, RA)]),
    ("`a b` <x> `c`\n", [(1, "<x>"), (1, RA)]),                              # control of reproducer 2, one line
    ('x <a title="q"> y\n', [(1, '<a title="q">'), (1, RA)]),                # control of reproducer 1, no backtick
    ("`a\n<n>`\n", [(1, R1), (2, "<n>"), (2, R1), (2, RA)]),                 # P10: fail closed
    ("- `a\n  b` <x> `c`\n", [(1, R1), (2, R1), (2, RI)]),                   # a list item's continuation line
    ("# `a\n`<x>`\n", [(1, R1)]),                                            # was accepted: a heading's unpaired run
]
SPAN_HTML_ACCEPTED = ["`<x>`\n", "a `<x>` b\nc `d`\n", "`a`\n\n`<x>`\n", "``a ` <x> ` b``\n"]
# M1-M5 (fix round 3). F-B2FX2RR-1 reproducers, the class members and controls.
RESTRICT_SAMPLES = [
    ("e `\n- a `b\nc` <x> `d\n", [(1, R1), (2, R1)]),                       # F-B2FX2RR-1: bullet list item
    ("e `\n> a `b\nc` <x> `d\n", [(1, R1), (2, R1), (2, RQ)]),              # block quote, then a lazy line
    ("e `\n***\na `b\nc` <x> `d\n", [(1, R1), (3, R1)]),                    # thematic break
    ("a `b\n| c` <x> `d\n", [(1, R1)]),                                     # a `|` line inside a paragraph
    ("| `a | <x> | b` |\n|---|---|---|\n", [(1, R3)]),                       # GFM cell split on pipes in a span
    ("<http://a`b> <x> `c\n", [(1, RA), (1, RX)]), ("<a`b@c.de> <x> `c\n", [(1, RA)]),   # autolinks holding a backtick
    ("x \\` y\n", [(1, RB)]), ("```\n` a\n```\n", []),                       # M1: escaped run (RB, round 4); fence
    ("- ` a\n", [(1, R1)]), ("> ` a\n", [(1, R1), (1, RQ)]), ("# ` a\n", [(1, R1)]), ("| ` a |\n", [(1, R1)]),
    ("<a href=`x`>\n", [(1, "<a href=\0\0\0>"), (1, RA)]), ("<a\ntitle=`x`>\n", [(1, "<a\ntitle=\0\0\0>"), (1, RA)]),
    ("</a`>\n", [(1, R1), (1, RA)]),            # M2; a hit is matched on the masked text (NUL per span char)
    ("<!-- ` -->\n", [(1, "<!-- ` -->"), (1, R1), (1, RA)]), ("<?x `?>\n", [(1, R1), (1, RA)]),
    ("`<a>` `b`\n", []), ("<1 `x` >\n", [(1, RA)]), ("< a `x` >\n", [(1, RA)]), ("<a `x`\n", [(1, RA)]),
    ("| `a|b` |\n", [(1, R3)]), ("a | `b|c`\n--|--\n", [(1, R3)]), ("a | `b|c`\n:-|-:\n", [(1, R3)]),   # M3
    ("see `a|b` here\n", []), ("| `a\\|b` |\n", [(1, R3)]), ("x\n\na | `b|c`\n", []),
    ("a `<!-- ` b\n", []), ("(`<!-- ` or `# `)\n", []), ("`a` <x> `b`\n", [(1, "<x>"), (1, RA)]),   # M4, FX2RR-4
    ("a `\n<b `x`>\n| `c|d` |\n", [(1, R1), (2, RA), (3, R3)]),                                  # M5: each kind
    ("| `a|b` ` |\n", [(1, R1), (1, R3)]), ("<x> `\n", [(1, "<x>"), (1, R1), (1, RA)]),          # two; mixed
]
# W1-W5 (fix round 4, owner Q-B2FX2-1 (a) as a whitelist). The refused forms, enumerated: two characters, two
# sequences and three line starts outside every per-line code span and fenced block, with R1 and R3.
W_CHARS = [("<", RA), ("\\", RB), ("](", RL), ("]:", RL)]
W_POSITIONS = ["%s x", "x %s y", "x y %s", "`a`%s b", "b %s`a`", "# x %s y", "- x %s y", "1. x %s y", "| x %s y |"]
W_STARTS = [(" x", RI), ("\tx", RC), ("  x", RI), ("    x", RI), ("> x", RQ), (">x", RQ)]
W_REPRODUCERS = [   # F-B2FX2RR5-1, F-B2FX2RR5-2: each refused by name (they were [] at 66b494c)
    ('<a t=">" u="`"> <x> `\n', [(1, RA)]), ("y <a t='>' u='`'> <x> `\n", [(1, RA)]),          # F-B2FX2RR5-1
    ("see [a](`) <x> ` here\n", [(1, RL)]), ("see [a](<`>) <x> ` here\n", [(1, RA), (1, RL)]),    # RR5-2 member 1
    ('see [a](/u "`") <x> ` here\n', [(1, RL)]), ("see ![a](`) <x> ` here\n", [(1, RL)]),
    ("- a\n  ```\n<x>\n```\n", [(2, RI)]), ("1. a\n   ~~~\n<x>\n~~~\n", [(2, RI)]),                # member 2
    ("<div\n```\n<x>\n```\n", [(1, RA)]), ("</div\n```\n<x>\n```\n", [(1, RA)]),                  # member 3
    ("> | h |\n> | - |\n> | `a | <z> b` |\n", [(1, RQ), (2, RQ), (3, RQ)]),                       # member 4
    ("- > | h |\n  > | - |\n  > | `a | <z> b` |\n", [(1, RN), (2, RI), (3, RI)]),       # round 7: line 1 RN too
]
W_FAIL_CLOSED = [   # the round 3 fail-closed notes: each is now a named refusal
    ("para\n\n    <x>\n", [(3, "<x>"), (3, RA), (3, RI)]),                           # indented code
    ("    ```\nx\n    ```\n", [(1, R1), (1, RI), (3, R1), (3, RI)]),                 # an indented fence under no list
    ("| `a` |\n|---|\nprose `b|c`\n", [(3, R3)]),                                    # R3 past a table's end: kept
]
W_ADMITTED = [   # W-h: the block forms the whitelist leaves, each with a code span holding '<'
    "a `<x>` b\n", "# h `<x>`\n", "## h\n", "a\n---\n", "a\n===\n", "***\n", "---\n", "- a `<x>`\n", "1. a `<x>`\n",
    "| a | `<x>` |\n|---|---|\n| b | c |\n", "```\n<x>\n```\n", "~~~\n<x>\n~~~\n",
    "---\nname: x\ndescription: y `<z>`\n---\n# Body\n", "a > b\n", "a ] (b)\n", "a ]x( b\n", "x [a] (b)\n",   # round 8: was "[a] (b)"
    "a\n   \nb\n",
]
W_BLANK_AND_FENCED = ["```\n x\n```\n", "```\n> x\n```\n", "~~~\n    <x> \\ ](a) ]: b\n~~~\n"]
W_TAB_CONVERTED = [   # fix round 5 (D8): tab rows of W_ADMITTED, W_BLANK_AND_FENCED and test_line_starts, converted
    ("a\tb\n", [(1, RC)]), ("a\n\t\nb\n", [(2, RC)]), ("a\n \t \nb\n", [(2, RC)]),           # were W_ADMITTED
    ("```\n\tx\n```\n", [(2, RC)]),                                                       # was W_BLANK_AND_FENCED
    ("a\n   \t\nb\n", [(2, RC)]),                                                         # was in test_line_starts
]
STERM_26 = [0x0701, 0x0702, 0x07F9, 0x1367, 0x166E, 0x1803, 0x1809, 0x1944, 0x1945, 0x2E3C, 0x2E53, 0x2E54, 0xA4FF,
            0xA60E, 0xA60F, 0xA6F3, 0xA6F7, 0xFE12, 0xFE15, 0xFE16, 0x11143, 0x16AF5, 0x16E98, 0x1BC9F, 0x1DA88,
            0x1E95E]                                                    # F-B2FX2RR-2, named by the re-review


class VerifierRoundTest(unittest.TestCase):
    def test_placeholder_span_html_class(self):                   # F-B2V3-1, V1 (converted, D5)
        for text, want in SPAN_HTML_REFUSED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)
        for text in SPAN_HTML_ACCEPTED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])

    def test_input_restriction_samples(self):                     # F-B2FX2RR-1, -4; M1-M5
        self.assertEqual(pc.REFUSED_KINDS, ("multi-line code span", "angle bracket outside code span",
                                            "backslash outside code span", "link syntax", "indented line",
                                            "block quote", "pipe in table-row code span",
                                            "character outside whitelist", "extended autolink",    # round 5: 8th, 9th
                                            "block start in list item"))                           # round 7: 10th
        for text, want in RESTRICT_SAMPLES:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_backtick_runs_one_to_four(self):                     # M1: every run length, paired and unpaired
        for n in range(1, 5):
            run = "`" * n
            with self.subTest(n=n):
                self.assertEqual(pc.placeholder_hits("x %sa%s y\n" % (run, run)), [])
                self.assertEqual(pc.placeholder_hits("x %sa y\n" % run), [(1, R1)])
                self.assertEqual(pc.placeholder_hits("x %sa%s y\n" % (run, "`" * (n + 1))), [(1, R1)])

    def test_rule_id_digit_count_same_on_every_interpreter(self):   # F-B2V3-2, V2, PC1-a 4300/4301 row
        text = read(RULES)
        rng = random.Random(20261109)
        for digits in (4300, 4301, 9):
            num = str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(digits - 1))
            t = text.replace("| SD-R5 |", "| SD-R%s |" % num)
            with self.subTest(digits=digits):
                self.assertEqual(rules_problems(t), ["id: line 11, SD-R%s... is out of range (more than 8 digits)"
                                                     % num[:8]])
        t = text.replace("| SD-R5 |", "| SD-R99999999 |")              # 8 digits: still parsed
        self.assertEqual(rules_problems(t)[:1], ["id-sequence: line 11, expected SD-R5, got SD-R99999999"])

    def test_sentence_stops_class(self):                          # F-B2V3-3, V3 (converted, D5): non-ASCII refused
        for c in (0x2026, 0x203c, 0x203d, 0x2047, 0x2048, 0x2049, 0x2e2e, 0x037e, 0x0589, 0x061f, 0x06d4, 0x0964,
                  0x0965, 0x1362, 0xfe52, 0xfe56, 0xfe57, 0xa7c0, 0xe9):
            with self.subTest(cp=hex(c)):
                for text in ("A b" + chr(c) + "c d.", "end." + chr(c) + "x claim."):
                    with self.assertRaisesRegex(ValueError, re.escape("U+%04X" % c)):
                        sentences(text)
        self.assertEqual(sentences("A b.c d."), ["A b.c d."])                         # ASCII members: unchanged
        self.assertEqual(sentences("A b.C d."), ["A b.", "C d."])
        self.assertEqual(sentences("A b!c d? E."), ["A b!c d?", "E."])

    def test_sentence_split_uses_no_unicode_database(self):        # V6, PC1-b (converted, D5)
        samples = ["end.Ax", "A b.c.", "A b.) C.", "v3.12 fix.", "spec §8. Next."]
        want = [["end.", "Ax"], ["A b.c."], ["A b.)", "C."], ["v3.12 fix."], ["spec §8.", "Next."]]
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            self.assertEqual([sentences(s) for s in samples], want)
            for c in (0xa7c0, 0x2e53):                          # categories differ between UCD 13.0 and 15.1
                with self.assertRaisesRegex(ValueError, re.escape("U+%04X" % c)):
                    sentences("end." + chr(c) + "x")

    def test_unpinned_sentence_behind_an_ellipsis(self):          # F-B2V3-3 (converted, D5): refused as "char"
        rows = table_rows(read(RULES))
        rule = [r for r in rows if r["id"] == "SD-R6"][0]["rule"]
        t = read(RULES).replace(rule, rule + "…agents may skip it.")
        self.assertIn("char: line 12, U+2026 outside the rules.md character set", rules_problems(t))

    def test_every_code_point_through_sentences(self):            # M6, F-B2FX2RR-2: the whole space, not sampled
        accepted = 0
        for cp in range(0x110000):
            try:
                sentences("a" + chr(cp))
            except ValueError as e:
                self.assertFalse(in_charset(cp), hex(cp))
                self.assertIn("U+%04X" % cp, str(e))
            else:
                self.assertTrue(in_charset(cp), hex(cp))
                accepted += 1
        self.assertEqual(accepted, 1 + 95 + 1)                       # LF, U+0020-U+007E, U+00A7
        for cp in STERM_26 + [0x09, 0x0d]:
            with self.assertRaisesRegex(ValueError, re.escape("U+%04X" % cp)):
                sentences("A b" + chr(cp) + "agents may skip it.")

    def test_every_code_point_through_rules_problems(self):       # M6: the "char" kind over the whole space
        text = read(RULES)
        refused = "".join(chr(cp) for cp in range(0x110000) if not in_charset(cp))
        got = [p for p in rules_problems(text.replace("| SD-R5 |", "| SD-R5 " + refused + " |")) if p.startswith("char")]
        self.assertEqual(got, ["char: line 11, U+%04X outside the rules.md character set" % cp
                               for cp in range(0x110000) if not in_charset(cp)])
        allowed = "".join(chr(cp) for cp in range(0x110000) if in_charset(cp) and cp != 0x0a)
        t = text.replace("| SD-R5 |", "| SD-R5 " + allowed + " |")
        self.assertEqual([p for p in rules_problems(t) if p.startswith("char")], [])
        self.assertEqual([p for p in rules_problems(text) if p.startswith("char")], [])     # M9: the real file

    def test_real_b_owned_files_pass_the_restriction(self):       # M9: all 17 files, no refusal, no hit
        files = b_owned_markdown()
        self.assertEqual(len(files), 20)     # Task 2c.3: the three plan-role and drafter prompt blocks
        for rel in files:
            with self.subTest(rel=rel):
                self.assertEqual(pc.placeholder_hits(read(rel)), [])

    def test_changed_helpers_use_no_exception_group(self):        # PC1-c: the changed helpers run on 3.9 as on 3.13
        import inspect
        for fn in (pc.placeholder_hits, pc._unpaired_runs, pc._table_row_lines, pc.rules_problems, sentences,
                   pc.char_refusals, pc._refuse_chars, pc.forbidden_hits, pc.labels, pc.paragraph, pc.section,
                   pc.first_table_header, pc.table_rows, pc.front_matter, pc.block_problems,    # + round 5's helpers
                   pc._info_refusals, pc._list_block_start,                     # + round 6's and round 7's helpers
                   pc._bracket_start):                                          # + round 8's helper
            self.assertNotIn("ExceptionGroup", inspect.getsource(fn))
            self.assertNotIn("except*", inspect.getsource(fn))


class WhitelistTest(unittest.TestCase):                             # W1-W5, fix round 4; rows W-a..W-h, PC1-b
    def _form(self, form, kind):
        """A refused character or sequence: refused at each position outside spans, accepted in a span or fence."""
        for pos in W_POSITIONS:
            text = pos % form + "\n"
            want = [(1, R1), (1, kind)] if form == "\\" and pos.endswith("%s`a`") else [(1, kind)]   # '\`' escapes
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)
            for fenced in ("```\n%s```\n", "~~~~\n%s~~~~\n"):
                with self.subTest(fenced=fenced % text):
                    self.assertEqual(pc.placeholder_hits(fenced % text), [])
        for span in ("`%s`", "x `a %s b` y", "``%s``", "| `%s` |", "- `%s`", "# `%s` h"):
            text = span % form + "\n"
            with self.subTest(span=text):   # round 8 (Q-B2F1-1 (a), D-i): '](' and ']:' are checked raw, spans too
                self.assertEqual(pc.placeholder_hits(text), [(1, kind)] if kind == RL else [])
        with self.subTest(second_line=form):
            self.assertEqual(pc.placeholder_hits("a\nb %s c\n" % form), [(2, kind)])

    def test_angle_bracket(self):                                  # W-a
        self._form("<", RA)

    def test_backslash(self):                                      # W-a
        self._form("\\", RB)

    def test_link_paren(self):                                     # W-b
        self._form("](", RL)

    def test_link_colon(self):                                     # W-b
        self._form("]:", RL)

    def test_link_parts_apart_accepted(self):                      # W-b: ']' and '(' or ':' separated
        for text in ("a ] (b)\n", "a ]x( b\n", "x [a] (b)\n", "a ] : b\n", "a ]\n(b)\n", "a ]\n: b\n", "`a]`(b)\n"):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])

    def test_line_starts(self):                                    # W-c
        for start, kind in W_STARTS:
            for text, line in ((start + "\n", 1), ("a\n" + start + "\n", 2), ("```\nc\n```\n" + start + "\n", 4),
                               ("- a\n" + start + " `b`\n", 2)):
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(line, kind)])
            with self.subTest(fenced=start):        # round 5: a tab is refused inside a fence too (before the parse)
                self.assertEqual(pc.placeholder_hits("```\n" + start + "\n```\n"), [(2, RC)] if kind == RC else [])
        for text in W_BLANK_AND_FENCED + ["a\n \nb\n", "a > b\n"]:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        self.assertEqual(pc.placeholder_hits("a\n- > b\n"), [(2, RN)])         # round 7 (D3): was [] at dfb6667
        for text, want in W_TAB_CONVERTED:           # round 5 (D8): were accepted blank or fenced tab lines
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_indented_fence_lines(self):                           # W-c: an indented opener or closer is refused
        for text, want in (("  ```\nx\n```\n", [(1, RI)]), ("```\nx\n  ```\n", [(3, RI)]),
                           (" ~~~\n<x>\n ~~~\n", [(1, RI), (3, RI)]), ("```\nx\n    ```\n", [])):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_round3_rereview_reproducers(self):                    # W-e: F-B2FX2RR5-1, F-B2FX2RR5-2
        for text, want in W_REPRODUCERS:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_round3_fail_closed_notes(self):                       # W4: named refusals now (R3 note: stays fail closed)
        for text, want in W_FAIL_CLOSED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_output_shape(self):                                   # W-f: kinds, order, several on a line, with hits
        text = "<x> ` \\ ](a\n  b\n> c\n| `d|e` |\n  | `f|g` |\n> <y> `\nwww.a\n"
        want = [(1, "<x>"), (1, R1), (1, RA), (1, RB), (1, RL), (2, RI), (3, RQ), (4, R3), (5, RI), (5, R3),
                (6, "<y>"), (6, R1), (6, RA), (6, RQ), (7, RX)]
        got = pc.placeholder_hits(text)
        self.assertEqual(got, want)
        kinds = [k[len("refused: "):] for _, k in got if k.startswith("refused: ")]
        self.assertEqual(sorted(set(kinds), key=kinds.index), [k for k in pc.REFUSED_KINDS[:9] if k != pc.CHAR_KIND])
        self.assertEqual(len(pc.REFUSED_KINDS), 10)                # round 5: the char kind 8th (D1), autolink 9th
        self.assertEqual(pc.placeholder_hits(text + "- # <z>\n"), want + [(8, "<z>"), (8, RA), (8, RN)])   # round 7
        self.assertEqual(pc.placeholder_hits(text + "\t" + text), [(8, RC)])       # D1: only the char kind, no hit
        for n, kind in enumerate(pc.REFUSED_KINDS):                # each kind alone, once
            sample = ["a `\n", "a < b\n", "a \\ b\n", "a ](b\n", " a\n", "> a\n", "| `a|b` |\n", "a\tb\n", "www.a\n",
                      "- # a\n"][n]
            with self.subTest(kind=kind):
                self.assertEqual(pc.placeholder_hits(sample), [(1, "refused: " + kind)])

    def test_hit_has_its_refusal(self):                            # W2: every hit's line carries the RA refusal
        for text, _ in PLACEHOLDER_REFUSED + SPAN_HTML_REFUSED + RESTRICT_SAMPLES + W_FAIL_CLOSED:
            got = pc.placeholder_hits(text)
            for n, m in got:
                if not m.startswith("refused: "):
                    with self.subTest(text=text, hit=m):
                        self.assertIn((n, RA), got)

    def test_admitted_forms(self):                                 # W-h
        for text in W_ADMITTED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        for text, want in W_TAB_CONVERTED[:3]:       # round 5 (D8): the converted W_ADMITTED rows
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_unicode_version_independent(self):                    # PC1-b: U+A7C0 (category differs 13.0/15.1)
        c = chr(0xA7C0)
        rows = [("x %s y\n" % c, [(1, RC)]), ("`%s<x>`\n" % c, [(1, RC)]), ("%s <x>\n" % c, [(1, RC)]),   # round 5:
                (" %s\n" % c, [(1, RC)]), ("%s\n%s\n" % (c, c), [(1, RC), (2, RC)])]       # converted to the char kind
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            for text, want in rows:
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), want)


# ---- Fix round 5 (owner Q-B2FX2-1 (a); F-B2FX2RR5v6-1, F-B2FX2RR5v6-2; rows X-a..X-h, PC1) ----
X_CR = [   # X-a: (text, LF-counted lines refused); every expected value written here by hand
    ("\rx\n", [1]), ("a\rb\n", [1]), ("a\r\n", [1]), ("`a\rb`\n", [1]), ("```\na\r\n```\n", [2]),
    ("```py\r\nx\n```\n", [1]), ("~~~ <x>\r\n<y>\n~~~\n", [1]), ("a\nb\r", [2]), ("a\rb\rc\r", [1]),
    ("a\r\nb\r\nc\r\n", [1, 2, 3]), ("a\r", [1]), ("\r", [1]), ("\r\n", [1]),
    ("```\r\ncode\r\n```\r\n<name>\r\n", [1, 2, 3, 4]),          # F-B2FX2RR5v6-1 reproducers ([] at 9be350a)
    ("`\r\r<name>\r\r`\n", [1]), ("a `x\r# <name>\r` y\n", [1]),
]
X_OUTSIDE = (list(range(0x00, 0x0a)) + list(range(0x0b, 0x20)) + [0x7f] + list(range(0x80, 0xa0))
             + [0xa0, 0xa6, 0xa8, 0x2028, 0x2029, 0x3000, 0xfeff, 0x1f600, 0xa7c0])           # X-b, PC1-b
X_EDGES = [0x20, 0x7e, 0xa7, 0x0a]                                                          # X-c
X_BLANK_CLASS = ["\f", "\v", "\r", "\t", chr(0xa0), chr(0x3000)]                            # X-e (D5)
X_AUTOLINK_REFUSED = [   # X-f (D6): (text, lines refused "extended autolink"); a placeholder after, inside, beside
    "www.example.com/`<name>`\n", "http://example.com/`<name>`\n", "https://e.com/`<n>`\n", "WWW.E.COM/`<n>`\n",
    "ftp://x/`<n>`\n", "x www.a.b `<n>`\n", "(www.a.b/`<n>`)\n", "*www.a.b/`<n>`*\n", "www.a.b/` x <n>`\n",
    "a `<n>` www.a.b\n", "- www.a.b/`<n>`\n", "# http://a.b/`<n>`\n", "| www.a.b/`<n>` |\n|---|\n",
]
X_AUTOLINK_ACCEPTED = [   # inside a span or a fence, or an email form (its characters exclude the backtick)
    "`www.a.b/<n>`\n", "`http://a/<n>`\n", "```\nwww.a.b/`<n>`\n```\n", "a@b.co`<n>`\n", "mailto:a@b.co `<n>`\n",
    "xmpp:a@b.co `<n>`\n", "a.b@c.de `<n>`\n", "www `<n>`\n", "http:/ `<n>`\n",
]
CHECKERS = [   # X-d: (name, call on str, exception or None when the checker returns its refusal)
    ("forbidden_hits", lambda t: pc.forbidden_hits(t), None),
    ("labels", lambda t: pc.labels(t), ValueError),
    ("paragraph", lambda t: pc.paragraph(t, "Build."), ValueError),
    ("section", lambda t: pc.section(t, "A"), AssertionError),
    ("first_table_header", lambda t: pc.first_table_header(t), ValueError),
    ("table_rows", lambda t: pc.table_rows(t), ValueError),
    ("front_matter", lambda t: pc.front_matter(t), AssertionError),
]
X_GOOD = "---\na: x\n---\n# t\n\nintro\n\nBuild. a\n\n## A\nb\n\n| h |\n|---|\n| c |\n"    # every checker accepts it


class CharWhitelistTest(unittest.TestCase):                          # X-a..X-h, PC1-a..c (fix round 5)
    def test_cr_and_crlf_refused(self):                              # X-a, F-B2FX2RR5v6-1
        for text, lines in X_CR:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [(n, RC) for n in lines])
                self.assertEqual([n for n, _ in pc.char_refusals(text)], lines)

    def test_every_class_outside_refused_before_parse(self):         # X-b: one per line, no hit, LF-counted
        for cp in X_OUTSIDE:
            c = chr(cp)
            for text, want in (("a%s<n>\n" % c, [(1, RC)]), ("<n>\n`%s`\n<m>\n" % c, [(2, RC)]),
                               ("%s\n<n>\n%s%s\n" % (c, c, c), [(1, RC), (3, RC)]), ("```\n%s\n" % c, [(2, RC)])):
                with self.subTest(cp="U+%04X" % cp, text=text):
                    self.assertEqual(pc.placeholder_hits(text), want)

    def test_exhaustive_code_points(self):                           # X-b, X-c: U+0000-U+10FFFF vs the hand set
        cps = [c for c in range(0x110000) if c != 0x0a]                # one code point per line; LF separates
        got = pc.char_refusals("\n".join(chr(c) for c in cps))
        want = [(i + 1, c) for i, c in enumerate(cps) if not in_charset(c)]
        self.assertEqual(got[:3], [(1, 0), (2, 1), (3, 2)])
        self.assertEqual(len(got), len(want))
        diff = [(g, w) for g, w in zip(got, want) if g != w][:1]
        self.assertEqual(diff, [])
        self.assertEqual(len(got), 0x110000 - 1 - 96)                  # 96 code points in the set besides LF

    def test_set_edges_accepted(self):                               # X-c
        text = "a" + "".join(chr(c) for c in X_EDGES) + "a b ~ §\n"
        self.assertEqual(pc.char_refusals(text), [])
        self.assertEqual(pc.placeholder_hits(text), [])
        self.assertEqual(pc.forbidden_hits(text), [])
        for c in X_EDGES:
            with self.subTest(cp="U+%04X" % c):
                self.assertTrue(in_charset(c))
                self.assertIn(chr(c), pc.RULES_CHARS)

    def test_other_checkers_refuse_by_name_before_the_split(self):   # X-d (D3)
        for name, call, exc in CHECKERS:
            with self.subTest(name=name, good=True):
                call(X_GOOD)                                          # in-set input: the checker runs as before
            for cp in X_OUTSIDE + [0x0d]:
                bad = X_GOOD.replace("Build. a", "Build. a" + chr(cp))           # line 8
                with self.subTest(name=name, cp="U+%04X" % cp):
                    if exc is None:
                        self.assertEqual(call(bad), [(pc.CHAR_KIND, 8, "U+%04X" % cp)])
                    else:
                        with self.assertRaises(exc) as cm:
                            call(bad)
                        self.assertIn("line 8: U+%04X, character outside whitelist" % cp, str(cm.exception))
        # before the split: each input below gave a result through the split at 9be350a
        self.assertEqual(pc.forbidden_hits("lap\rtimer\nOpus\n"), [(pc.CHAR_KIND, 1, "U+000D")])
        self.assertEqual(pc.forbidden_hits("a lap timer\n"), [(pc.CHAR_KIND, 1, "U+2028")])
        for text, call in (("## A\r\nx\r\n", lambda t: pc.section(t, "A")),
                           ("## A\nx\rb\n", lambda t: pc.section(t, "A")),
                           ("| h |\n|---|\n| a\x0bb |\n", pc.table_rows), ("| h\t|\n", pc.first_table_header),
                           ("---\na: x\n---\r\n", pc.front_matter), ("a\nb\nc\nd\nBuild. x\x85\n", pc.labels)):
            with self.subTest(text=text):
                with self.assertRaises((ValueError, AssertionError)) as cm:
                    call(text)
                self.assertIn(pc.CHAR_KIND, str(cm.exception))

    def test_kept_forms(self):                                       # X-d: the checkers that already refused
        self.assertIn("char: line 1, U+000D outside the rules.md character set", rules_problems("a\r\n"))
        with self.assertRaisesRegex(ValueError, "U\\+000D"):
            sentences("a.\rB.")
        for raw, kind in ((b"a\rb\n", "line-ending"), (b"a\tb\n", "control"), (b"a\xc2\xa7\n", "encoding"),
                          (b"a\x7f\n", "control"), (b"a\xe2\x80\xa8\n", "encoding")):
            with self.subTest(raw=raw):
                self.assertIn(kind, {p.split(":")[0] for p in pc.block_problems(raw, "implementer")})

    def test_blank_line_rule_equivalence_and_class(self):            # X-e (D5 (ii)), F-B2FX2RR5v6-2
        self.assertEqual(sorted(c for c in pc.RULES_CHARS if c.isspace()), ["\n", " "])   # so strip() == strip(" ")
        for c in X_BLANK_CLASS:
            for text in (" %s\n" % c, "a\n %s\nb\n" % c, " %s %s\n" % (c, c)):
                with self.subTest(cp="U+%04X" % ord(c), text=text):
                    want = [(1, RC)] if text.startswith(" ") else [(2, RC)]
                    self.assertEqual(pc.placeholder_hits(text), want)
        for text in ("a\n \nb\n", "a\n    \nb\n", " \n"):               # a line of only spaces is blank
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        for text, line in ((" x\n", 1), ("a\n  §\n", 2), ("a\n   ~\n", 2)):    # a space and anything else
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [(line, RI)])

    def test_extended_autolinks(self):                               # X-f (D6)
        for text in X_AUTOLINK_REFUSED:
            with self.subTest(text=text):
                got = pc.placeholder_hits(text)
                self.assertIn((1, RX), got)
                self.assertEqual([k for k in got if k[1] == RX], [(1, RX)])
        for text in X_AUTOLINK_ACCEPTED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        self.assertEqual(pc.placeholder_hits("www.example.com/`<name>`\n"), [(1, RX)])   # the lead, exact
        self.assertEqual(pc.placeholder_hits("---\nd: www.x\n---\n"), [(2, RX)])          # front matter counts

    def test_real_inputs_unchanged(self):                            # X-g, D4: every real checker input
        rels = sorted("%s/%s" % (pc.PROMPTS_DIR, n) for n in os.listdir(pc.prompts_dir()))
        rels += sorted("playbook/" + n for n in os.listdir(os.path.join(pc.REPO_ROOT, "playbook")))
        rels.append("skills/strict-delivery/SKILL.md")
        self.assertEqual(len(rels), 22)     # Task 2c.3: the three plan-role and drafter prompt blocks; Task P4.3: the two program blocks
        for rel in rels:
            with self.subTest(rel=rel):
                t = read(rel)
                self.assertEqual(pc.char_refusals(t), [])
                self.assertEqual(pc.placeholder_hits(t), [])
                self.assertEqual(pc.forbidden_hits(t), [])
                self.assertNotIn(pc.CHAR_KIND, repr(pc.placeholder_hits(t)))
        self.assertEqual(pc.front_matter(read("skills/strict-delivery/SKILL.md"))["name"], "strict-delivery")
        self.assertEqual(rules_problems(read(RULES)), [])

    def test_plan_sentence(self):                                    # X-h (D7)
        plan = read("docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md")
        para = [ln for ln in plan.split("\n") if ln.startswith("**Input restriction (owner answer Q-B2FX2-1 (a), "
                                                                "2026-11-09; it narrows Q-B22v2-3 (a)):**")]
        self.assertEqual(len(para), 1)
        p = para[0]
        self.assertIn("before any line split or markdown parse, the whole text is held to the character whitelist "
                      "LF, U+0020-U+007E and U+00A7", p)
        self.assertLess(p.index("character whitelist LF"), p.index("Then the markdown whitelist"))
        self.assertNotIn("whatever CommonMark or GFM would do", p)        # the round 4 claim the re-review refuted
        self.assertNotIn("a space or a tab", p)
        for s in ("or, from fix round 6, only space, `-` and `:`, with at least one `-` and one `:` and no `|`",   # Z-f
                  "Other GFM table forms are not modeled by this predicate (residual accepted by the owner, 2026-11-10)",
                  "A fence opener's info string (the text after the fence marker on the opener line) is checked raw, "
                  "with no code-span masking", "each refusal is reported on the opener's line",
                  "for backtick and tilde fences alike; in a tilde fence also a backtick run the per-line pairing "
                  "leaves unpaired (`multi-line code span`) and a code span holding `|` (`pipe in table-row code span`)",
                  "The fence still opens and its content stays masked.",
                  # round 7 (N-h): the rule (D2, D3, D4, D5) and the corrected "block forms left" sentence
                  "any block start inside a list item is refused as `block start in list item`, reported on the "
                  "list item's line, so nested positions are closed as a whole class by construction",
                  "a run of one or more ASCII digits (any length, read as text, never converted to a number) "
                  "followed by `.` or `)`; the marker is followed by a space or the end of the line",
                  "so markers are at column 0 only",
                  "The content is the text after the marker and all the spaces that follow it. It is refused when "
                  "it begins with a backtick run of 3 or more, a tilde run of 3 or more, `#`, `>`, `|`, `<`, or "
                  "another list marker of the same form; when 5 or more spaces stand between the marker and "
                  "non-blank content (an indented code block inside the item); and when it is a thematic break "
                  "(3 or more of one of `-`, `*` and `_`, with spaces between and nothing else)",
                  "the checker opens no fence on a list item line",
                  # round 8 (D-h, E4): D5's definition claim corrected, the rule, and the closed dimension
                  "a block quote is refused as a line start (`block quote`), and footnote definitions and "
                  "reference definitions are refused by `link syntax`, because `](` and `]:` are checked on the raw "
                  "line and a `[` content start is refused",
                  "fix round 8, owner answer Q-B2F1-1 (a), 2026-11-10: `](` and `]:` checked on the raw line and a "
                  "`[` content start refused",
                  "`link syntax` is checked on the raw line, before code-span masking: a line holding `](` or `]:` "
                  "anywhere, code spans included, is refused, and so is a line whose content starts with `[`",
                  "at every nesting depth, or the whole line when it has no marker; `link syntax` is reported once "
                  "per line",
                  "content beginning `[` is refused as `link syntax` from fix round 8",
                  "The dimension closed is the block-level constructs whose marker a per-line code span could mask: "
                  "the fence info string (fix round 6), the table row (R3, raw spans), the list item (fix round 7) "
                  "and the definition (fix round 8)",
                  "column-0 list items whose content holds no block start, tables and column-0 fences, none whose "
                  "content starts with `[`"):
            self.assertIn(s, p)
        self.assertNotIn("thematic breaks, column-0 list items, tables", p)          # round 7: the old sentence
        self.assertNotIn("are refused by `link syntax` (`]:`)", p)                   # round 8: the false claim
        self.assertNotIn("code span are `](` and `]:` (`link syntax`)", p)           # round 8: masked check gone
        self.assertNotIn("backticks, `[`, a letter", p)                              # round 8: `[` no longer accepted
        doc = " ".join(pc.placeholder_hits.__doc__.split())                          # round 8 (E4): the docstring
        for s in ("code spans included (checked on the raw line)", "starts with '[' (_bracket_start)",
                  "definitions by \"link syntax\", because '](' and ']:' are checked on the raw line and a '[' "
                  "content start is refused", "the definition (round 8)"):
            self.assertIn(s, doc)
        self.assertNotIn("outside every per-line code span, a '<' (\"angle bracket outside code span\"), a '\\' "
                         "(\"backslash outside code span\"), the sequence", doc)
        self.assertIn(", ".join("`%s`" % k for k in pc.REFUSED_KINDS), p)
        # UR-1 (owner Q-B2UR1-1 (a)): the masking claim names its one exception, the excess table cells
        self.assertNotIn("or hide text the masking keeps.", p)
        self.assertNotIn("or hide text the per-line masking keeps", doc)
        self.assertIn("can take a backtick from a per-line span, and none of them hides text the masking keeps. "
                      "One construct does hide text the masking keeps: a GFM table body row's cells beyond the "
                      "header row's cell count are dropped by the renderer", p)
        self.assertIn("this is part of the accepted residual (other GFM table forms are not modeled; owner "
                      "2026-11-10, Q-B2UR1-1 (a))", p)
        self.assertIn("no construct can take a backtick from a per-line span, and no construct but one hides text "
                      "the per-line masking keeps: a GFM table body row's cells beyond the header row's cell count "
                      "are dropped by the renderer", doc)
        self.assertIn("This is part of the accepted residual (other GFM table forms are not modeled; owner "
                      "2026-11-10, Q-B2UR1-1 (a))", doc)
        # fix round 1 (F-1): exact residual wording; a code span there gives no hit, raw HTML there is still caught
        self.assertNotIn("is hidden while placeholder_hits returns no hit", doc)
        self.assertNotIn("is not rendered while `placeholder_hits` returns no hit; this", p)
        self.assertIn("so a code span there is hidden and gives no hit and no refusal (raw HTML there is still "
                      "caught: a hit plus an \"angle bracket outside code span\" refusal). This is part of", doc)
        self.assertIn("so a code span there is not rendered and `placeholder_hits` gives no hit and no refusal for "
                      "it (raw HTML there is still caught: a hit plus an `angle bracket outside code span` "
                      "refusal); this is part of", p)

    def test_excess_table_cell_raw_html_is_still_caught(self):       # UR-1 review F-1
        # Raw HTML (outside a code span) in an excess cell is not hidden from the checker: a hit plus the
        # angle-bracket refusal, both on line 3. Only the code span case is the residual.
        self.assertEqual(pc.placeholder_hits("| a |\n| - |\n| x | <b> |"),
                         [(3, "<b>"), (3, "refused: angle bracket outside code span")])

    def test_excess_table_cell_is_the_documented_residual(self):     # UR-1
        # Owner Q-B2UR1-1 (a), 2026-11-10: GFM drops a table body row's cells beyond the header's count, so the
        # code span below is not rendered, yet placeholder_hits gives []. It is inside the accepted table residual
        # ("other GFM table forms are not modeled"); if this changes, the residual sentences must change with it.
        self.assertEqual(pc.placeholder_hits("| a |\n| - |\n| x | `<role>` |"), [])

    def test_numeric_text_same_on_every_interpreter(self):          # PC1-a: a placeholder_hits row
        for digits in (4300, 4301):
            with self.subTest(digits=digits):
                self.assertEqual(pc.placeholder_hits("1" * digits + "\n"), [])
                self.assertEqual(pc.placeholder_hits("<" + "1" * digits + ">\n"), [(1, RA)])
                self.assertEqual(pc.char_refusals("\t" + "1" * digits), [(1, 9)])

    def test_no_unicode_database_read(self):                         # PC1-b: the char refusal and the in-set path
        c = chr(0xA7C0)
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            self.assertEqual(pc.placeholder_hits("a %s <x>\n" % c), [(1, RC)])
            self.assertEqual(pc.forbidden_hits("a %s\n" % c), [(pc.CHAR_KIND, 1, "U+A7C0")])
            self.assertEqual(pc.front_matter(GOOD_FM), GOOD_FM_DICT)          # no lookup left in front_matter
            for name, call, exc in CHECKERS:
                with self.subTest(name=name):
                    call(X_GOOD)
                    if exc is not None:
                        with self.assertRaisesRegex(exc, "U\\+A7C0, character outside whitelist"):
                            call(X_GOOD.replace("Build. a", "Build. a" + c))


# Fix round 6 (owner 2026-11-10; D-v8-1, U-v7-1, F-B2V8-1, F-B2V8-2). Rows Z-a..Z-g, PC1-a..c.
Z_INFO_FORMS = [("<", RA), ("\\", RB), ("](", RL), ("]:", RL), ("www.", RX), ("WWW.", RX), ("wWw.", RX), ("://", RX)]
Z_INFO_TILDE_FORMS = [("`", R1), ("```", R1), ("`a|b`", R3), ("``a|b``", R3), ("`|`", R3)]
Z_INFO_POSITIONS = ["%s a", "a %s b", "a %s", "%s"]
Z_INFO_CONTROLS = ["```python\n<x>\n```\n", "``` text x-y\n<x>\n```\n", "~~~ a b\n<x>\n~~~\n", "```\n<x>\n```\n",
                   "~~~\n<x>\n~~~\n", "~~~ `a` b\n<x>\n~~~\n", "``` a|b c:d [e] (f) ]x(\n<x>\n```\n",
                   "~~~ a|b\n<x>\n~~~\n"]
Z_DELIMS = [":-", "-:", ":-:", ":--", "--:", " :- ", "::-", "-:-", ":---:", ": - :"]
Z_DELIM_CONTROLS = ["---", "-", "- - -", ":", "::", "a : b", "x", "-- a", ":-x"]


def _kind_order(refusals):
    return sorted(refusals, key=lambda r: (r[0], pc.REFUSED_KINDS.index(r[1][len("refused: "):])))


class InfoStringTableTest(unittest.TestCase):                       # fix round 6, rows Z-a..Z-d, Z-g, PC1-a, PC1-b
    def test_info_string_refused(self):                              # Z-a, D-v8-1 (D1)
        for marker in ("```", "````", "~~~", "~~~~~"):
            forms = Z_INFO_FORMS + (Z_INFO_TILDE_FORMS if marker[0] == "~" else [])
            for indent in ("", " ", "  ", "   "):
                for form, kind in forms:
                    for pos in Z_INFO_POSITIONS:
                        text = "%s%s%s\n<x> ` \\ ](a) www.b `c|d`\n%s%s\n" % (indent, marker, pos % form, indent, marker)
                        want = [(1, kind)] + ([(1, RI), (3, RI)] if indent else [])
                        with self.subTest(text=text):
                            self.assertEqual(pc.placeholder_hits(text), _kind_order(want))
        self.assertEqual(pc.placeholder_hits("``` <role>\nx\n```\n"), [(1, RA)])                 # the reproducer
        self.assertEqual(pc.placeholder_hits("a\n\n~~~ `<x>`\n~~~\n"), [(3, RA)])                # RAW: no masking
        self.assertEqual(pc.placeholder_hits("~~~ ` <x> ` www.a\n~~~\n"), [(1, RA), (1, RX)])
        self.assertEqual(pc.placeholder_hits("~~~ \\` <a>](b) `|`\n~~~\n"), [(1, RA), (1, RB), (1, RL), (1, R3)])
        self.assertEqual(pc.placeholder_hits("~~~ a `b|c` ` d\n~~~\n"), [(1, R1), (1, R3)])
        self.assertEqual(pc.placeholder_hits("x\n```\ny\n```\n```http://a\n<b>\n```\n"), [(5, RX)])  # opener line no.

    def test_info_string_fence_still_opens(self):                    # Z-a: the content stays masked
        for opener in ("``` <x>", "~~~ <x>", "~~~ `", "~~~ `a|b`", "```` ://", "~~~ \\"):
            close = opener.split(" ")[0]
            text = "%s\n<y> `\n%s\n<z>\n" % (opener, close)
            with self.subTest(text=text):
                got = pc.placeholder_hits(text)
                self.assertEqual([r for r in got if r[0] != 1], [(4, "<z>"), (4, RA)])
                self.assertEqual(len([r for r in got if r[0] == 1]), 1)

    def test_info_string_controls(self):                             # Z-a2
        for text in Z_INFO_CONTROLS:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])

    def test_pipe_less_delimiter_rows(self):                         # Z-b, U-v7-1 (D2)
        for d in Z_DELIMS:
            for text, want, at in (("h `a|b`\n%s\n`c|d`\nx `e|f` y\n" % d, [(1, R3), (3, R3), (4, R3)], 2),
                                   ("h\n%s\n`c|d`\n" % d, [(3, R3)], 2), ("h\n%s\n`c|d`\n\n`e|f`\n" % d, [(3, R3)], 2),
                                   ("h\n%s\nb\nc `c|d`\n" % d, [(4, R3)], 2), ("p `a|b`\n\nh\n%s\n" % d, [], 4)):
                ri = [(at, RI)] if d.startswith(" ") else []
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), _kind_order(want + ri))
        self.assertEqual(pc.placeholder_hits("a\n:-\n`<name>|`\n"), [(3, R3)])                  # the reproducer

    def test_widening_controls(self):                                # Z-b2: unchanged from d013b15
        for d in Z_DELIM_CONTROLS:
            for text in ("h\n%s\n`c|d`\n" % d, "h `a|b`\n%s\n" % d):
                with self.subTest(text=text):     # round 7 (D3): "- - -" is a thematic break in a list item
                    self.assertEqual(pc.placeholder_hits(text), [(2, RN)] if d == "- - -" else [])
        self.assertEqual(pc.placeholder_hits("h\nx\n`c|d`\ny `e|f`\n"), [])
        self.assertEqual(pc.placeholder_hits("a | `b|c`\n--|--\n"), [(1, R3)])                  # the old form, kept

    def test_delimiter_row_space_member(self):                       # Z-c, F-B2V8-1 (mutant V29)
        for text in ("a | `b|c`\n- | - | -\n", "a | `b|c`\n--- | ---\n", "a | `b|c`\n:- | -:\n", "`b|c`\n-- |\n"):
            with self.subTest(text=text):     # round 7 (D3): "- | - | -" is a list item whose content starts '|'
                self.assertEqual(pc.placeholder_hits(text), [(1, R3)] + ([(2, RN)] if "\n- | " in text else []))
        self.assertEqual(pc.placeholder_hits("a | `b|c`\n- |\t-\n"), [(2, RC)])               # tab: char refusal

    def test_run_predicate_dash_and_blank_boundary(self):            # Z-d, F-B2V8-2 (mutants V17, V30)
        for text in ("a `b|c`\n|\n", "a `b|c`\n| : |\n", "a `b|c`\n \n-|-\n", "a `b|c`\n   \n-|-\n",
                     "a `b|c`\n \n:-\n", "-|-\n \nx `b|c`\n"):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        self.assertEqual(pc.placeholder_hits("a `b|c`\n-|-\n"), [(1, R3)])                     # one run: refused

    def test_whitelist_first(self):                                  # Z-g
        for text, want in (("``` a\t<\n```\n", [(1, RC)]), ("~~~ \x0b`\n~~~\n", [(1, RC)]),
                           ("~~~ `a|\xa0`\n<x>\n~~~\n", [(1, RC)]), ("h\n:-\t\n`a|b`\n", [(2, RC)]),
                           ("h\n:-\xa0\n`a|b`\n", [(2, RC)]), ("h\n:-\n`a|b`\r\n", [(3, RC)])):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_numeric_text_same_on_every_interpreter(self):           # PC1-a
        for digits in (4300, 4301):
            num = "1" * digits
            for text, want in (("```%s\n```\n" % num, []), ("``` <%s\n```\n" % num, [(1, RA)]),
                               ("~~~ `%s\n~~~\n" % num, [(1, R1)]), ("~~~ `%s|`\n~~~\n" % num, [(1, R3)]),
                               ("h\n:-\n`a|b` %s\n" % num, [(3, R3)]), ("h\n:-\n%s\n" % num, []),
                               ("h\n:-%s\n`a|b`\n" % ("-" * digits), [(3, R3)])):
                with self.subTest(digits=digits, text=text[:12]):
                    self.assertEqual(pc.placeholder_hits(text), want)

    def test_no_unicode_database_read(self):                         # PC1-b: U+A7C0 is Cn on 3.9, Lu on 3.13
        c = chr(0xA7C0)
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            for text in ("``` %s <x>\n```\n" % c, "~~~ `a|%s`\n~~~\n" % c, "h\n:-%s\n`a|b`\n" % c):
                with self.subTest(text=text):
                    got = pc.placeholder_hits(text)
                    self.assertEqual(len(got), 1)
                    self.assertEqual(got[0][1], RC)
            self.assertEqual(pc.placeholder_hits("``` <x>\n```\n"), [(1, RA)])


# Fix round 7 (owner Q-B2Z1-1 (a), 2026-11-10; Z-1; controller D1-D5). Rows N-a..N-k, PC1-a..c. Every expected
# value is written here by hand from the round 7 table, never read back from the code. RN is defined beside RC, RX.
N_MARKERS = ["-", "*", "+", "1.", "1)", "10.", "123456789)"]
N_STARTS = [   # (block start, hits on the line, refusals the line earns besides RN, in REFUSED_KINDS order)
    ("```", [], [R1]), ("````", [], [R1]), ("```python", [], [R1]),     # the fence is not opened (D4): R1 stays
    ("~~~", [], []), ("~~~~", [], []), ("~~~ x", [], []),
    ("#", [], []), ("# h", [], []), ("######", [], []), (">", [], []), ("> q", [], []), ("|", [], []),
    ("| a |", [], []), ("<", [], [RA]), ("<b>", ["<b>"], [RA]),
    ("- x", [], []), ("* x", [], []), ("+ x", [], []), ("1. x", [], []), ("2) x", [], []), ("-", [], []),
]
N_NESTED = [("- - ~~~ x", []), ("* 1. # h", []), ("1) + > q", []), ("- - - |", []), ("1. 2. 3. <b>", ["<b>", RA])]
N_Z1 = ["- ~~~ `<role>`", "1. ~~~ `www.x`", "- ~~~ `a|b`", "* ~~~ `<role>`", "+ ~~~ `a\\b`", "1) ~~~ `a](b`",
        "- - ~~~ `<role>`"]
N_CODE_AND_BREAK = ["-     code", "1.      x", "- ---", "- * * *", "* ___", "- - -", "+ _ _ _", "1. ***",
                    "- *  *  * ", "-      ~~~", "10)     x"]
N_ACCEPTED = ["- plain", "- **bold** x", "- *em*", "- _em_", "- `code` x", "- ``a`` x", "1. 2026 text",
              "1.5 x", "-x", "---", "--- ", "***", "12345678901234567890. x\nplain", "- a # b", "- a | b",
              "- a ~~~ b", "-    code", "- --", "- ~~ x", "- ~~x~~", "- *x y", "- _x_", "- 1.5 x", "- 2026 text",
              "-", "- ", "-     ", "1.", "1)", "* x", "+ x", "1) x", "a - # b", "x\n- a\n- b\n\n1. c\n2. d"]
N_TOP_LEVEL = [("```\nx\n```\n", []), ("~~~\nx\n~~~\n", []), ("# h\n", []), ("| a |\n|---|\n| b |\n", []),
               ("> q\n", [(1, RQ)]), ("~~~ `<role>`\n", [(1, RA)]), ("~~~ `<role>`\nx\n~~~\n", [(1, RA)])]


class ListItemBlockStartTest(unittest.TestCase):                    # fix round 7, rows N-a..N-k, PC1-a..c
    def test_block_start_after_every_marker(self):                   # N-a: the class, one subTest per cell
        for marker in N_MARKERS:
            for start, hits, kinds in N_STARTS:
                for gap in (" ", "  ", "    "):
                    text = "%s%s%s\n" % (marker, gap, start)
                    want = [(1, h) for h in hits] + [(1, k) for k in kinds] + [(1, RN)]
                    with self.subTest(text=text):
                        self.assertEqual(pc.placeholder_hits(text), want)
                    with self.subTest(second_line=text):
                        self.assertEqual(pc.placeholder_hits("a\n\n" + text), [(n + 2, k) for n, k in want])

    def test_nested_depth(self):                                     # N-b
        for line, before in N_NESTED:
            want = [(1, "<b>"), (1, RA), (1, RN)] if before else [(1, RN)]
            with self.subTest(text=line):
                self.assertEqual(pc.placeholder_hits(line + "\n"), want)

    def test_z1_reproducers(self):                                   # N-c: each was [] at dfb6667
        for line in N_Z1:   # round 8 (D-i): '](' in a span is now checked raw, so "1) ~~~ `a](b`" also earns RL
            with self.subTest(text=line):
                self.assertEqual(pc.placeholder_hits(line + "\n"), [(1, RL), (1, RN)] if "](" in line else [(1, RN)])
        self.assertEqual(pc.placeholder_hits("~~~ `<role>`\n~~~\n"), [(1, RA)])                 # the control
        self.assertEqual(pc.placeholder_hits("- ~~~ x\n<y>\n~~~\n"), [(1, RN), (2, "<y>"), (2, RA)])  # D4: no fence
        self.assertEqual(pc.placeholder_hits("- ``` x\n<y> `\n```\n"), [(1, R1), (1, RN), (2, "<y>"), (2, R1),
                                                                       (2, RA)])

    def test_indented_code_and_thematic_break_in_item(self):         # N-d
        for line in N_CODE_AND_BREAK:
            with self.subTest(text=line):
                self.assertEqual(pc.placeholder_hits(line + "\n"), [(1, RN)])

    def test_accepted_controls(self):                                # N-e: [] as at dfb6667
        for text in N_ACCEPTED:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text + "\n"), [])

    def test_top_level_controls(self):                               # N-f: no new kind
        for text, want in N_TOP_LEVEL:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_old_kinds_kept_in_list_item(self):                      # invariants: each old kind, inside an item
        for content, kind in (("a `", R1), ("a < b", RA), ("a \\ b", RB), ("a ](b", RL), ("a `x|y` | b |", None),
                              ("www.a", RX)):
            for marker in ("-", "1."):
                text = "%s %s\n" % (marker, content)
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(1, kind)] if kind else [])
        self.assertEqual(pc.placeholder_hits("- a\n  b\n> c\n"), [(2, RI), (3, RQ)])
        self.assertEqual(pc.placeholder_hits("- a `x|y`\n-|-\n"), [(1, R3)])
        self.assertEqual(pc.placeholder_hits("- a <b>\n"), [(1, "<b>"), (1, RA)])
        self.assertEqual(pc.placeholder_hits("- <b> a\n"), [(1, "<b>"), (1, RA), (1, RN)])         # D4's example
        self.assertEqual(pc.placeholder_hits("- `a` <b> # c `\n"), [(1, "<b>"), (1, R1), (1, RA)])

    def test_whitelist_first(self):                                  # N-j: only the char kind, as today
        for text, want in (("-\tx\n", [(1, RC)]), ("- \t~~~\n", [(1, RC)]), ("-\xa0~~~ x\n", [(1, RC)]),
                           ("- \xa0# h\n", [(1, RC)]), ("- # h\n-\t> q\n", [(2, RC)]), ("1.\t<b>\n", [(1, RC)])):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_inside_fences_masked(self):                             # N-k
        for text in ("```\n- ~~~ x\n- # h\n1. 2. y\n- > q\n- | a |\n-     code\n- ---\n```\n",
                     "~~~\n- > q\n* ```\n~~~\n", "````\n- ```\n```\n````\n", "```python\n1) # x\n```\n"):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), [])
        self.assertEqual(pc.placeholder_hits("```\n- # h\n```\n- # h\n"), [(4, RN)])            # after the close

    def test_numeric_text_same_on_every_interpreter(self):           # PC1-a: 4300 / 4301 digits, no int()
        for digits in (4300, 4301):
            num = "1" * digits
            for text, want in (("%s. ~~~ x\n" % num, [(1, RN)]), ("%s) # h\n" % num, [(1, RN)]),
                               ("- %s\n" % num, []), ("%s. x\n" % num, []), ("- %s. # h\n" % num, [(1, RN)]),
                               ("- %s.5 x\n" % num, [])):
                with self.subTest(digits=digits, text=text[-8:]):
                    self.assertEqual(pc.placeholder_hits(text), want)

    def test_no_unicode_database_read(self):                         # PC1-b: U+A7C0 is Cn on 3.9, Lu on 3.13
        c = chr(0xA7C0)
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            for text in ("- %s ~~~\n" % c, "- # %s\n" % c, "%s. # h\n" % c, "- %s\n" % c):
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(1, RC)])
            self.assertEqual(pc.placeholder_hits("- # h\n"), [(1, RN)])


# Fix round 8 (owner Q-B2F1-1 (a), 2026-11-10; F-1 / F-B2R7-1, U-1; controller E1-E4). Rows D-a..D-i, PC1-a..c.
# Every expected value is written here by hand from the round 8 table, never read back from the code.
D_RAW_IN_SPAN = ["x `a]:b` y", "x `a](b` y", "`]:`", "`](`", "`a]:b` x", "x `a]:b`", "`a](b` x", "x `a](b`",
                 "``a]:b``", "x ``a](b`` y", "x ``]:`` y", "- `a]:b`", "# h `a](b`", "| `a]:b` |"]
D_REPRODUCERS = [   # F-1 (list item) and U-1 (top level): each was [] at 01cc2bd, or lacked RL
    ("- [a`]: x '<role>`'", [RL]), ("- [a`]:` x", [RL]), ("[a`]: x '<role>`'", [RL]), ("[^a`]: x", [R1, RL]),
    ("1. [a`]: y", [R1, RL]), ("- - [a`]: y", [R1, RL, RN]), ("1) [^a`]: y", [R1, RL]),
]
D_BRACKETS = ["[a]", "[x] y", "[^1] z", "[", "[[a]]"]
D_MARKERS = ["-", "*", "+", "1.", "1)", "10."]
D_CONTROLS = ["a [b] c", "`[a]`", "x ] y", "a]b", "```\n[\n```", "```\n]:\n```", "- a [b] c", "~~~\n[a]: x\n~~~",
              "x [a] (b)", "a ]\n: b", "-[a]", "`a]`(b)", "a\n\n- b [c]\n"]


class RawLinkSyntaxTest(unittest.TestCase):                         # fix round 8, rows D-a..D-i, PC1-a..c
    def test_raw_link_syntax_in_span(self):                          # D-a
        for line in D_RAW_IN_SPAN:
            with self.subTest(text=line):
                self.assertEqual(pc.placeholder_hits(line + "\n"), [(1, RL)])
            with self.subTest(second_line=line):
                self.assertEqual(pc.placeholder_hits("a\n" + line + "\n"), [(2, RL)])

    def test_f1_u1_reproducers(self):                                # D-b
        for line, kinds in D_REPRODUCERS:
            with self.subTest(text=line):
                self.assertEqual(pc.placeholder_hits(line + "\n"), [(1, k) for k in kinds])

    def test_bracket_content_start(self):                            # D-c: column 0, each marker, depth 2
        for b in D_BRACKETS:
            with self.subTest(text=b):
                self.assertEqual(pc.placeholder_hits(b + "\n"), [(1, RL)])
            for marker in D_MARKERS:
                for gap in (" ", "    "):
                    text = "%s%s%s\n" % (marker, gap, b)
                    with self.subTest(text=text):
                        self.assertEqual(pc.placeholder_hits(text), [(1, RL)])
                text = "%s      %s\n" % (marker, b)          # 6 spaces: round 7's indented code in the item too
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(1, RL), (1, RN)])
                text = "- %s %s\n" % (marker, b)             # depth 2: round 7 gives RN for the inner marker (E2)
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(1, RL), (1, RN)])
        self.assertEqual(pc.placeholder_hits("- - [a]\n"), [(1, RL), (1, RN)])
        self.assertEqual(pc.placeholder_hits("1. * 2) [a]\n"), [(1, RL), (1, RN)])
        self.assertEqual(pc.placeholder_hits("a\n[b]: x\nc\n"), [(2, RL)])
        self.assertEqual(pc.placeholder_hits("- [x] <b>\n"), [(1, "<b>"), (1, RA), (1, RL)])   # was N_ACCEPTED's "- [x] y"

    def test_multi_line_label(self):                                 # D-d
        self.assertEqual(pc.placeholder_hits("[a\nb`]: x\n"), [(1, RL), (2, R1), (2, RL)])
        self.assertEqual(pc.placeholder_hits("- [a\n  b]: x\n"), [(1, RL), (2, RL), (2, RI)])
        self.assertEqual(pc.placeholder_hits("x [a\nb]: c\n"), [(2, RL)])

    def test_controls(self):                                         # D-e: [] as at 01cc2bd
        for text in D_CONTROLS:
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text + "\n"), [])

    def test_whitelist_first(self):                                  # D-f: only the char kind
        for text, want in (("[\tx\n", [(1, RC)]), ("]:\xa0\n", [(1, RC)]), ("- [a]:\xa0x\n", [(1, RC)]),
                           ("a\n`]:`\xa0\n", [(2, RC)]), ("[a]\n\tb\n", [(2, RC)])):
            with self.subTest(text=text):
                self.assertEqual(pc.placeholder_hits(text), want)

    def test_fence_opener_unchanged(self):                           # E1: the info string stays checked raw
        self.assertEqual(pc.placeholder_hits("~~~ `a]:b`\n[x]\n~~~\n"), [(1, RL)])
        self.assertEqual(pc.placeholder_hits("```\nx\n```\n[a]: y\n"), [(4, RL)])

    def test_numeric_text_same_on_every_interpreter(self):           # PC1-a
        for digits in (4300, 4301):
            num = "1" * digits
            for text, want in (("%s. [a]\n" % num, [(1, RL)]), ("[%s]: x\n" % num, [(1, RL)]),
                               ("- %s. [a]\n" % num, [(1, RL), (1, RN)]), ("%s) `a](b`\n" % num, [(1, RL)])):
                with self.subTest(digits=digits, text=text[-8:]):
                    self.assertEqual(pc.placeholder_hits(text), want)

    def test_no_unicode_database_read(self):                         # PC1-b: U+A7C0 is Cn on 3.9, Lu on 3.13
        c = chr(0xA7C0)
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("UCD lookup")):
            for text in ("[%s\n" % c, "- [%s]: x\n" % c, "`a]:%s`\n" % c):
                with self.subTest(text=text):
                    self.assertEqual(pc.placeholder_hits(text), [(1, RC)])
            self.assertEqual(pc.placeholder_hits("- [a]\n"), [(1, RL)])


# Task B3: the owner directives of 2026-11-09/10 in the base playbook, written out (spec section 7.1, 8, 10;
# Q-VER-DO-1 (a): the version-rows rule is stack-neutral). Each sentence is pinned with its place.
B3_VERSION_ROWS = ("Every table carries rows for the known version differences of the project's own stack and "
                   "runtime, each run on every runtime the project supports.")
B3_ASKING_ANCHOR = ("Any other open point, and every point in an owner-only class, is an owner question, and only the "
                    "work that depends on its answer halts until it is answered; a controller never pauses a whole "
                    "stream on a question, and when nothing independent is left the stream checkpoints and waits.")
B3_SMALL_POINT = ("The one exception is a small point inside the plan's intent: a question of format, syntax, bytes or "
                  "whitespace, wording, layout, naming, test detail, a test-helper contract or an error-return shape "
                  "is not asked; the controller decides it, taking the option it would recommend, and ledgers it as "
                  "`Decision (owner delegation): what -- why -- cost if wrong`, outside `rulings.max_per_block`.")
B3_OWNER_KEEPS = ("The owner keeps work added or removed, plan and spec changes, architecture choices, framework or "
                  "process changes, agent models and costs, merge-blocking risk, and anything irreversible or "
                  "otherwise important; a question in an owner-only class is always asked, and when unsure, the "
                  "controller asks.")
B3_ROLES_MODEL = "The dispatch's model equals `## Model` and meets the role's minimum tier."
B3_ROLES_EXPLICIT = ("The dispatch call passes that model explicitly, the one `models.tiers` maps the chosen tier to; "
                     "a dispatch never inherits its dispatcher's model.")
B3_ROLES_AFTER = "A worker role dispatches no agent, and a dispatch whose dispatcher is a worker role is refused (`gate_dispatch`)."
B3_ROLES_RETURN = ("A controller never returns while its children run: questions and progress go up to its parent as "
                   "messages, and answers come down as decision records.")
B3_NO_LIVE_CHILD = ("A controller never ends its turn while a child or a background job it started still runs: it "
                    "waits inside its turn, in the foreground, and returns only after every child has handed back.")
B3_FINISHED = ("A child has finished only when its handback arrives, never because its report file already holds a "
               "status line.")
B3_ITEM1_ANCHOR = ("A missing table blocks dispatch; a row with no test is a finding, and its fix re-checks the whole "
                   "dimension without widening the behaviour (\"Fix rule\").")
# Task B4: U-2 (tier against model), U-4 (open grammar), U-5 (no handback with live children), playbook form.
B4_ROLES_MIN = "A role runs at its minimum tier or above."
B4_ROLES_TIER = ("A dispatch chooses a tier, and config `models.tiers` maps each tier to the model the project uses: "
                 "the dispatch's `## Model` names that model, and every other line of a brief or report names tiers, "
                 "never a model.")
B4_ROLES_FOLLOW = "The top tier, `tier4`, is allowed only for the roles in `top_tier_roles`"
B4_OPEN_GRAMMAR = ("A table enumerates the full input class or restricts the input, so the code refuses what lies "
                   "outside the enumerated class, and never samples an open grammar.")
B4_CONT_FIRST = ("Continuation is automatic, at every agent level: an agent that reaches a checkpoint, 80 % of its "
                 "token or time budget, or a usage-limit stop writes its handoff and returns `status: DONE` with "
                 "`next:` (or `BLOCKED: budget`).")
B4_LIVE_CHILDREN = ("Before it writes that handoff, a controller dispatches nothing new and waits, inside its turn, "
                    "for the handback of every child still running; a child that a usage-limit stop cuts off before "
                    "its handback is listed in the handoff's `live_subagents`.")
B4_CONT_NEXT = "Its dispatcher at once dispatches a fresh agent"
B3_MISMATCH_ANCHOR = "any other mismatch, plan-vs-code included, is an owner question"
B3_MISMATCH_TAIL = ", except a small point that `playbook/decisions.md` (\"Asking\") lets the controller decide."


# B3 review R1-1: the Plan format paragraph of playbook/sessions.md states the same input-domain table rule.
B3_PLAN_ANCHOR = "The implementer fills `test`, and a row with no test is a finding."
B3_PLAN_VERDICT = ("Each verdict is marked as settled by the spec or plan, as an owner question, as a controller "
                   "ruling, or as a small point the controller decided under `playbook/decisions.md` (\"Asking\"); a "
                   "controller row goes to the reviewer as a ruling with one line of why.")
B3_PLAN_VERDICT_KEEPS = (   # the invariants of the replaced sentence, plus the new kind
    "Each verdict is marked as", "settled by the spec or plan", "as an owner question", "as a controller ruling",
    "as a small point the controller decided under `playbook/decisions.md` (\"Asking\")",
    "a controller row goes to the reviewer as a ruling with one line of why.")
B3_PLAN_NEXT = "The table's sections are: Oracle,"


def b3_unit(body, start):
    """The one non-empty line of a section body that starts with `start`; ValueError unless exactly one."""
    found = [l for l in body.split("\n") if l.startswith(start)]
    if len(found) != 1:
        raise ValueError("%d lines start with %r" % (len(found), start))
    return found[0]


B3_ENTRIES = (   # (id, file, section, the line the sentences sit in (its start), sentences, anchor, separator, follow)
    ("C1", "playbook/review.md", "Input domains", "1. Every task whose interface", (B3_VERSION_ROWS,),
     B4_OPEN_GRAMMAR, " ", None),                                     # B4: the U-4 sentence now stands before it
    ("C2", "playbook/review.md", "Input domains", "A mismatch a table finds", (B3_MISMATCH_TAIL,),
     B3_MISMATCH_ANCHOR, "", None),
    ("D", "playbook/decisions.md", "Asking", "A point the spec, the plan", (B3_SMALL_POINT, B3_OWNER_KEEPS),
     B3_ASKING_ANCHOR, " ", None),
    ("E1", "playbook/roles.md", "Dispatch contract", "A dispatch prompt carries", (B3_ROLES_EXPLICIT,),
     B3_ROLES_MODEL, " ", B3_ROLES_AFTER),
    ("E2", "playbook/roles.md", "Report contract", "Every report starts with", (B3_NO_LIVE_CHILD, B3_FINISHED),
     B3_ROLES_RETURN, " ", None),
    ("R1a", "playbook/sessions.md", "Plan format", "Every task whose interface takes", (B3_VERSION_ROWS,),
     B4_OPEN_GRAMMAR, " ", "Each verdict is marked as settled by the spec or plan,"),   # B4: U-4 stands before it
    ("R1b", "playbook/sessions.md", "Plan format", "Every task whose interface takes", (B3_PLAN_VERDICT,),
     B3_VERSION_ROWS, " ", B3_PLAN_NEXT),
    ("U2", "playbook/roles.md", "Model tiers", "A role runs at its minimum tier", (B4_ROLES_TIER,),
     B4_ROLES_MIN, " ", B4_ROLES_FOLLOW),                                                 # U-2 (B4)
    ("U4a", "playbook/review.md", "Input domains", "1. Every task whose interface", (B4_OPEN_GRAMMAR,),
     B3_ITEM1_ANCHOR, " ", B3_VERSION_ROWS),                                              # U-4 (B4)
    ("U4b", "playbook/sessions.md", "Plan format", "Every task whose interface takes", (B4_OPEN_GRAMMAR,),
     B3_PLAN_ANCHOR, " ", B3_VERSION_ROWS),                                               # U-4 (B4)
    ("U5", "playbook/sessions.md", "Handoffs and continuation", "Continuation is automatic, at every agent level",
     (B4_LIVE_CHILDREN,), B4_CONT_FIRST, " ", B4_CONT_NEXT),                              # U-5 (B4)
)
B3_BY_ID = {e[0]: e for e in B3_ENTRIES}
B3_TOKENS = (   # (file, section, line start, whole token): case-sensitive
    ("playbook/review.md", "Input domains", "1. Every task whose interface", "version differences"),
    ("playbook/decisions.md", "Asking", "A point the spec, the plan",
     "Decision (owner delegation): what -- why -- cost if wrong"),
    ("playbook/roles.md", "Dispatch contract", "A dispatch prompt carries", "never inherits"),
    ("playbook/roles.md", "Report contract", "Every report starts with", "handed back"),
    ("playbook/roles.md", "Report contract", "Every report starts with", "handback"),
    ("playbook/sessions.md", "Plan format", "Every task whose interface takes", "version differences"),
    ("playbook/sessions.md", "Plan format", "Every task whose interface takes", "small point"),
    ("playbook/review.md", "Input domains", "1. Every task whose interface", "open grammar"),                   # B4 U-4
    ("playbook/sessions.md", "Plan format", "Every task whose interface takes", "open grammar"),              # B4 U-4
    ("playbook/roles.md", "Model tiers", "A role runs at its minimum tier", "never a model"),                 # B4 U-2
    ("playbook/sessions.md", "Handoffs and continuation", "Continuation is automatic, at every agent level",
     "live_subagents"),                                                                                       # B4 U-5
)
B3_HARMLESS = (   # (file, section, line start, old, new): an unpinned phrase elsewhere in the unit
    ("playbook/review.md", "Input domains", "1. Every task whose interface", "sections per producer",
     "one section per producer"),
    ("playbook/decisions.md", "Asking", "A point the spec, the plan", "is applied as written", "is applied as stated"),
    ("playbook/roles.md", "Dispatch contract", "A dispatch prompt carries", "A fork dispatch is refused.",
     "A fork dispatch is rejected."),
    ("playbook/roles.md", "Report contract", "Every report starts with", "the first of DENIED",
     "the first value of DENIED"),
    ("playbook/sessions.md", "Plan format", "Every task whose interface takes", "one row per parameter",
     "one row for each parameter"),
)


def b3_chain(sentences, sep):
    return sep.join(sentences) if sep == "" else " ".join(sentences)


def b3_problems(text, entry):
    """Problems of one entry in the text of its file: the sentences stand once, in order, right after the anchor
    (with its separator), before `follow`, or last when nothing follows; a section or line problem is one problem."""
    ident, _, heading, start, sentences, anchor, sep, follow = entry
    try:
        unit = b3_unit(pc.section(text, heading), start)
    except (ValueError, AssertionError) as e:
        return ["%s: %s" % (ident, e)]
    chain = b3_chain(sentences, sep)
    want = anchor + sep + chain + ((" " + follow) if follow else "")
    out = []
    if want not in unit:
        out.append("%s: not in place" % ident)
    if any(text.count(s) != 1 for s in sentences):          # FV-1 (B4): counted over the whole file, not the unit
        out.append("%s: not once" % ident)
    if follow is None and not unit.endswith(chain):
        out.append("%s: not last" % ident)
    return out


def b3_token_problems(text, token_row):
    _, heading, start, token = token_row
    try:
        return [] if pc.whole_token(token, b3_unit(pc.section(text, heading), start)) else ["lacks %r" % token]
    except (ValueError, AssertionError) as e:
        return [str(e)]


def b3_in_section(text, heading, fn):
    body = pc.section(text, heading)
    new = fn(body)
    assert new != body, (heading, "mutation changed nothing")
    return text.replace(body, new, 1)


def b3_key_phrase_problems(stem, text):
    out = []
    for h, phrases in PLAYBOOK_SECTIONS.get(stem, []):
        body = pc.section(text, h).lower()
        out += ["%s %r" % (h, s) for s in phrases if s.lower() not in body]
    return out


class OwnerDirectivePlaybookTest(unittest.TestCase):
    def test_new_sentences_in_place_on_disk(self):                # rows 1, 3, 4, 5, 9
        for entry in B3_ENTRIES:
            with self.subTest(id=entry[0]):
                self.assertEqual(b3_problems(read(entry[1]), entry), [])
                self.assertEqual(forbidden_hits(read(entry[1])), [])
        for row in B3_TOKENS:
            with self.subTest(token=row[3]):
                self.assertEqual(b3_token_problems(read(row[0]), row), [])

    def test_deleted_sentence_refused_naming_the_unit(self):      # row 1, per sentence
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            for s in sentences:
                with self.subTest(id=ident, sentence=s[:30]):
                    bad = b3_in_section(read(rel), heading, lambda b: b.replace((" " if sep else "") + s, "", 1))
                    got = b3_problems(bad, entry)
                    self.assertTrue(got and got[0].startswith(ident + ":"), got)

    def test_moved_to_another_section_refused(self):              # row 2
        other = {"playbook/review.md": "Small re-review", "playbook/decisions.md": "Answering",
                 "playbook/roles.md": "Budget cap", "playbook/sessions.md": "Commits"}
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            for s in sentences:
                with self.subTest(id=ident, sentence=s[:30]):
                    t = read(rel)
                    gone = b3_in_section(t, heading, lambda b: b.replace(s, "zzz", 1))
                    moved = b3_in_section(gone, other[rel], lambda b: b.rstrip("\n") + " " + s + "\n")
                    self.assertTrue(b3_problems(moved, entry))

    def test_misplaced_refused(self):                             # row 3: first, before the anchor, glued, reordered
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            t = read(rel)
            chain = b3_chain(sentences, sep)
            with self.subTest(id=ident, case="first"):
                bad = b3_in_section(t, heading, lambda b: b.replace(sep + chain, "", 1).replace(start, chain + " " + start, 1))
                self.assertTrue(b3_problems(bad, entry))
            with self.subTest(id=ident, case="before the anchor"):
                bad = b3_in_section(t, heading, lambda b: b.replace(anchor + sep + chain, chain + " " + anchor, 1))
                self.assertTrue(b3_problems(bad, entry))
            if sep:
                with self.subTest(id=ident, case="glued"):
                    bad = b3_in_section(t, heading, lambda b: b.replace(anchor + sep + chain, anchor + chain, 1))
                    self.assertTrue(b3_problems(bad, entry))
            else:
                with self.subTest(id=ident, case="spaced"):
                    bad = b3_in_section(t, heading, lambda b: b.replace(anchor + chain, anchor + " " + chain, 1))
                    self.assertTrue(b3_problems(bad, entry))
            if len(sentences) == 2:
                with self.subTest(id=ident, case="reordered"):
                    bad = b3_in_section(t, heading, lambda b: b.replace(chain, sentences[1] + " " + sentences[0], 1))
                    self.assertTrue(b3_problems(bad, entry))
                with self.subTest(id=ident, case="glued between"):
                    bad = b3_in_section(t, heading, lambda b: b.replace(sentences[0] + " " + sentences[1],
                                                                        sentences[0] + sentences[1], 1))
                    self.assertTrue(b3_problems(bad, entry))
            if follow is None:
                with self.subTest(id=ident, case="not last"):
                    bad = b3_in_section(t, heading, lambda b: b.replace(chain, chain + " Zzz.", 1))
                    self.assertTrue(b3_problems(bad, entry))

    def test_twice_refused(self):                                 # row 4
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            for s in sentences:
                with self.subTest(id=ident, sentence=s[:30]):
                    bad = b3_in_section(read(rel), heading, lambda b: b.replace(s, s + " " + s, 1))
                    self.assertTrue(b3_problems(bad, entry))

    def test_copied_into_another_unit_of_the_file_refused(self):  # B4 row 4, FV-1: counted over the whole file
        other = {"playbook/review.md": "Small re-review", "playbook/decisions.md": "Answering",
                 "playbook/roles.md": "Budget cap", "playbook/sessions.md": "Commits"}
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            for s in sentences:
                with self.subTest(id=ident, sentence=s[:30]):
                    t = read(rel)
                    self.assertEqual(b3_problems(t, entry), [])
                    bad = b3_in_section(t, other[rel], lambda b: b.rstrip("\n") + " " + s + "\n")
                    got = b3_problems(bad, entry)
                    self.assertEqual(got, ["%s: not once" % ident], got)

    def test_same_sentence_in_different_files_accepted(self):     # B4 row 6: the count is per file
        self.assertEqual(read("playbook/review.md").count(B3_VERSION_ROWS), 1)
        self.assertEqual(read("playbook/sessions.md").count(B3_VERSION_ROWS), 1)
        self.assertEqual(read("playbook/review.md").count(B4_OPEN_GRAMMAR), 1)
        self.assertEqual(read("playbook/sessions.md").count(B4_OPEN_GRAMMAR), 1)
        for entry in B3_ENTRIES:
            self.assertEqual(b3_problems(read(entry[1]), entry), [])

    def test_roles_model_clause_dropped_refused(self):            # B4 row 8 (U-2): a mutant dropping the `## Model` clause
        entry = B3_BY_ID["U2"]
        for name, old, new in (("clause dropped", ": the dispatch's `## Model` names that model, and every other line",
                                ", and every other line"),
                               ("tier unqualified", "A dispatch chooses a tier", "A dispatch names a tier")):
            with self.subTest(case=name):
                bad = b3_in_section(read("playbook/roles.md"), "Model tiers", lambda b: b.replace(old, new, 1))
                self.assertTrue(b3_problems(bad, entry))
        self.assertIsNone(re.search(r"names a tier, never a model[;.:]", read("playbook/roles.md")))   # row 9

    def test_b4_digit_runs_glued_to_each_new_sentence_refused_the_same(self):   # B4 row 13 (no int() on text)
        for ident in ("U2", "U4a", "U4b", "U5"):
            entry = B3_BY_ID[ident]
            rel, heading, sentences = entry[1], entry[2], entry[4]
            got = []
            for n in (4300, 4301):
                with self.subTest(id=ident, digits=n):
                    s = sentences[-1]
                    bad = b3_in_section(read(rel), heading, lambda b: b.replace(s, s + "9" * n, 1))
                    got.append(b3_problems(bad, entry))
                    self.assertTrue(got[-1])
                    self.assertEqual(pc.char_refusals(bad), [])
            self.assertEqual(got[0], got[1])

    def test_whole_tokens_joined_or_recased_refused(self):        # row 5
        for row in B3_TOKENS:
            rel, heading, start, token = row
            for name, new in (("joined before", "x" + token), ("joined after", token + "x"),
                              ("case", token.upper()), ("absent", "zzz")):
                with self.subTest(token=token, case=name):
                    bad = b3_in_section(read(rel), heading, lambda b: b.replace(token, new))
                    self.assertTrue(b3_token_problems(bad, row))

    def text_of(self, rel):
        """The text the harmless rows run on; the row-2 test replaces it with a reworded copy (FR-1)."""
        return read(rel)

    def test_harmless_row_absent_on_disk_is_skipped_not_failed(self):   # B4 rows 2, 3 (FR-1)
        def absent(rel, heading, start, old):
            return old not in b3_unit(pc.section(read(rel), heading), start)
        gone0 = [row[3] for row in B3_HARMLESS if absent(*row[:4])]
        for i, (rel, heading, start, old, new) in enumerate(B3_HARMLESS):
            with self.subTest(reworded=old):
                case = OwnerDirectivePlaybookTest("test_harmless_rewording_passes")
                case.text_of = lambda r, i=i: (b3_in_section(read(r), B3_HARMLESS[i][1],
                                                             lambda b: b.replace(B3_HARMLESS[i][3], B3_HARMLESS[i][4], 1))
                                               if r == B3_HARMLESS[i][0] and not absent(*B3_HARMLESS[i][:4])
                                               else read(r))
                result = unittest.TestResult()
                case.run(result)
                gone = gone0 + ([old] if old not in gone0 else [])
                self.assertEqual((result.failures, result.errors), ([], []))
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(len(result.skipped), len(gone), result.skipped)
                self.assertEqual(case.harmless_ran, [row[3] for row in B3_HARMLESS if row[3] not in gone])

    def test_harmless_rewording_passes(self):                     # row 6 (spec section 14); FR-1 (B4): absent = visible skip
        self.harmless_ran = []
        for rel, heading, start, old, new in B3_HARMLESS:
            with self.subTest(rel=rel, new=new):
                t = self.text_of(rel)
                if old not in b3_unit(pc.section(t, heading), start):
                    self.skipTest("FR-1: %r is reworded on disk; unpinned, so never a failure" % old)
                self.harmless_ran.append(old)
                bad = b3_in_section(t, heading, lambda b: b.replace(old, new, 1))
                for entry in B3_ENTRIES:
                    if entry[1] == rel:
                        self.assertEqual(b3_problems(bad, entry), [])
                for row in B3_TOKENS:
                    if row[0] == rel:
                        self.assertEqual(b3_token_problems(bad, row), [])
                self.assertEqual(b3_key_phrase_problems(os.path.basename(rel)[:-3], bad), [])
                self.assertEqual(forbidden_hits(bad), [])

    def test_new_sentences_join_no_class_and_are_clean(self):     # rows 9, 10: no verifier-step, no deferral member
        for entry in B3_ENTRIES:
            for s in entry[4]:
                with self.subTest(id=entry[0]):
                    s.encode("ascii")
                    self.assertEqual(pc.char_refusals(s), [])
                    self.assertIsNone(_VERIFIER.search(s), s)
                    self.assertIsNone(_DEFERRAL.search(s), s)
        for rel in {e[1] for e in B3_ENTRIES}:                    # the files' class members are the hand-listed ones
            self.assertEqual(verifier_step_problems(read(rel), rel), [])

    def test_plan_format_verdict_sentence_keeps_its_invariants(self):   # R1-1: the replaced sentence's invariants
        t = read("playbook/sessions.md")
        unit = b3_unit(pc.section(t, "Plan format"), "Every task whose interface takes")
        self.assertEqual(unit.count(B3_PLAN_VERDICT), 1)
        self.assertNotIn("as an owner question, or as a controller ruling;", unit)    # the old wording is gone
        for phrase in B3_PLAN_VERDICT_KEEPS:                       # three verdict kinds, the new kind, the ruling line
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, B3_PLAN_VERDICT)
                bad = b3_in_section(t, "Plan format", lambda b: b.replace(phrase, "zzz", 1))
                self.assertTrue(b3_problems(bad, B3_BY_ID["R1b"]))

    def test_plan_format_digit_runs_refused_the_same(self):        # row 13 (no int() on text), R1 sentences
        for entry in (B3_BY_ID["R1a"], B3_BY_ID["R1b"]):
            for n in (4300, 4301):
                with self.subTest(id=entry[0], digits=n):
                    s = entry[4][-1]
                    bad = b3_in_section(read("playbook/sessions.md"), "Plan format",
                                        lambda b: b.replace(s, s + "9" * n, 1))
                    self.assertTrue(b3_problems(bad, entry))
                    self.assertEqual(pc.char_refusals(bad), [])

    def test_forbidden_strings_in_new_sentence_refused(self):     # row 9
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            for name, sample in (("model-name", "use Opus"), ("owner-handle", "ask superbrobenji"),
                                 ("row-id", "row X9-ABC-1")):
                with self.subTest(id=ident, sample=sample):
                    bad = read(rel).replace(sentences[0], sentences[0] + " " + sample, 1)
                    self.assertIn(name, [h[0] for h in forbidden_hits(bad)])

    def test_digit_runs_after_a_new_sentence_refused_the_same(self):   # row 13 (no int() on text)
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            if follow is not None:
                continue
            for n in (4300, 4301):
                with self.subTest(id=ident, digits=n):
                    bad = b3_in_section(read(rel), heading, lambda b: b.replace(sentences[-1], sentences[-1] + " " + "9" * n, 1))
                    self.assertEqual(len(b3_problems(bad, entry)), 1)

    def test_version_dependent_code_point_refused_by_the_character_check(self):   # row 14 (U+2C2F: Cn on 3.9, Lu on 3.13)
        c = chr(0x2C2F)
        for entry in B3_ENTRIES:
            ident, rel, heading, start, sentences, anchor, sep, follow = entry
            with self.subTest(id=ident):
                bad = read(rel).replace(sentences[0], sentences[0].replace("e", c, 1), 1)
                self.assertTrue(pc.char_refusals(bad))
                self.assertEqual([h[0] for h in forbidden_hits(bad)][:1], [pc.CHAR_KIND])
                self.assertTrue(b3_problems(bad, entry)[0].startswith(ident + ":"))
                with self.assertRaises(AssertionError):
                    pc.section(bad, heading)


# Process v2 (design 5.1-5.9): the superseded sentences are gone from every playbook file, and a file restored to
# one of them fails the pin that now holds the new sentence (a broken variant of each new text).
SUPERSEDED = (
    "until a clean pass", "after round 5 the controller stops and raises an owner question", "advisory signals",
    "never block a fix", "the path halts until the owner answers", "the path that needs it halts",
    "runs the full suite on the merged tree", "A block ends in this order: final review, top-tier verifier",
    "class-narrowing question for the owner", "its fix covers the whole dimension", "stop and wait for the owner (an",
    "the controller applies LOW_PLATEAU and the weighted tally by hand")
BROKEN_VARIANTS = (   # (file, new text, old text it must not be restored to)
    ("playbook/review.md", "it never stops a change-caused CRITICAL or HIGH finding from being fixed",
     "never decides whether a found defect is fixed"),
    ("playbook/review.md", "Once per stream, at its end, after a clean final review",
     "After a clean final review"),
    ("playbook/decisions.md", "until the binding Rules N and T verdict stops the loop", "until a clean pass"),
    ("playbook/rules.md", "only the work that depends on the answer halts", "the path halts"),
)


def runs_clean(case, name, files):
    """Run the one existing test method `name` of `case` with `read` serving `files` (rel -> text) in place of the
    repository files, and say whether it passed: the production pin checker on a replaced file."""
    real = read

    def fake(rel):
        return files[rel] if rel in files else real(rel)
    with mock.patch.object(sys.modules[__name__], "read", fake):
        result = unittest.TestResult()
        case(name).run(result)
    return result.wasSuccessful()


VARIANT_PINS = {   # (file, new text) -> the existing tests (class, method) that pin it; written by hand (R1-12)
    BROKEN_VARIANTS[0][:2]: [(PlaybookFilesTest, "test_signals_keep_the_low_plateau_exception")],
    BROKEN_VARIANTS[1][:2]: [(VerifierProfileTest, "test_verifier_paragraph_conditioned")],
    BROKEN_VARIANTS[2][:2]: [(PlaybookFilesTest, "test_playbook_sections_and_key_phrases")],
    BROKEN_VARIANTS[3][:2]: [(RealFileTest, "test_every_sentence_pinned")],
}


class ProcessV2PlaybookTest(unittest.TestCase):
    def test_superseded_sentences_are_gone(self):
        for stem in NEW_PLAYBOOKS + ("rules",):
            text = read("playbook/%s.md" % stem)
            for old in SUPERSEDED:
                with self.subTest(stem=stem, old=old):
                    self.assertNotIn(old, text)

    def test_broken_variant_of_each_new_text_is_caught(self):
        # R1-12: the pin that holds each new text is run, unchanged, on the file restored to the old text, and must
        # fail there; on the real file it passes (the control), so a failure is the broken text and not the harness.
        for rel, new, old in BROKEN_VARIANTS:
            text = read(rel)
            with self.subTest(rel=rel, new=new[:40]):
                self.assertEqual(text.count(new), 1)
                broken = text.replace(new, old)
                self.assertNotIn(new, broken)
                self.assertIn(old, broken)
                pins = VARIANT_PINS[(rel, new)]
                self.assertTrue(pins)
                for case, name in pins:
                    self.assertTrue(runs_clean(case, name, {}), (case.__name__, name))             # control
                    self.assertFalse(runs_clean(case, name, {rel: broken}), (case.__name__, name))

    def test_verifier_opening_restored_to_the_old_wording_fails_the_class_check(self):
        text = read("playbook/review.md")
        broken = text.replace(VERIFIER_OPENING, "After a clean final review, the `final_verifier` tries to break "
                                                "the finished branch.")
        self.assertNotIn(VERIFIER_OPENING, pc.section(broken, "Verifier"))
        self.assertTrue(verifier_step_problems(broken, "playbook/review.md"))   # no profile condition any more

    def test_fix_rule_paragraph_states_its_pass_and_fail_test(self):
        body = pc.section(read("playbook/review.md"), "Fix loop")
        for s in ("refuses input with a named error", "newly accepts input the code used to refuse",
                  "passes on the fix commit's parent and fails on the fix commit", "a violation is itself a finding",
                  "needs new behaviour is first narrowed in the fix round"):
            self.assertIn(s, body)

# Fix round 1 of the process-v2 roll-in (plan review 1, R1-1..R1-13; design 5.9): each corrected text is pinned
# as (id, file, new text, the flagged old text, how often the new text occurs); the old text must be gone.
MS_DOC = "docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md"
SR_DOC = "docs/strict-delivery/specs/2026-11-02-session-resume-and-questions-design.md"
PD_DOC = "docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md"
PLAN_DOC = "docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md"
BLOCK_END_GATE = ("The commit gate is the test modules of the changed files plus every test module that imports a "
                  "changed module, on every supported runtime, every enabled gate check, and a clean tree; the full "
                  "suite is not a per-commit gate (design 5.1).")
ADVERSARIAL_COND = "(where the profile enables it, strict)"
BD_DOC = ".strict-delivery/state/plans/2026-10-31-strict-delivery-framework/breakdown.md"
README_DOC = "README.md"
ONE_PR_DECISION = ("Decision (owner delegation 2026-11-09): each program stream keeps its one pull request (revision "
                   "6's folding, Q-SPD-1 (a), Q-SPD-2 (a)), opened on demand when a task of another stream consumes "
                   "one of its sub-blocks; a consumed sub-block does not open a PR of its own, since every such "
                   "consumer has slack (R2 0.75 h; release waits for PR-config) -- cost if wrong: one more PR per "
                   "consumed sub-block, no critical-path change")
CONFIG_V_DECISION = ("Decision (owner delegation 2026-11-09): stream `config`'s V runs after PR-config, beside "
                     "`release`")
FIX1_PINS = [
    ("R1-1", MS_DOC, "with any difference it stops only the work the difference affects, waits for the owner on it, "
     "and takes over the rest at once.", "with any difference it stops and waits for the owner.", 1),
    ("R1-1", SR_DOC, "With any difference, it stops only the work the difference affects and waits for the owner on "
     "it, and takes over the rest at once (skill text", "With any difference, it stops and waits for the owner (skill "
     "text", 1),
    ("R1-1", PLAN_DOC, "with any difference stops only the work the difference affects and waits for the owner on "
     "it, and takes over the rest at once (an agent", "with any difference stops and waits for the owner (an agent", 1),
    ("R1-3", "playbook/sessions.md", BLOCK_END_GATE, None, 1),
    ("R1-4", "playbook/rules.md", "in the stream-end adversarial review " + ADVERSARIAL_COND + ".",
     "in the stream-end adversarial review.", 1),
    ("R1-4", "playbook/streams.md", "the stream-end adversarial review (where the profile enables it, strict; "
     "`playbook/review.md`)", "the stream-end adversarial review (`playbook/review.md`)", 1),
    ("R1-4", "playbook/review.md", "before its adversarial review " + ADVERSARIAL_COND + ", and in that review",
     "before its adversarial review, and in that review", 1),
    ("R1-4", "skills/strict-delivery/SKILL.md", "before its adversarial review " + ADVERSARIAL_COND +
     ", and in that review", "before its adversarial review, and in that review", 1),
    ("R1-4", MS_DOC, "at a stream's end before the verifier " + ADVERSARIAL_COND + ", and in the verifier",
     "at a stream's end before the verifier, and in the verifier", 2),
    ("R1-5", "playbook/review.md", "A block ends with this review on its stream branch.", None, 1),
    ("R1-5", PD_DOC, "after the touched-area tests, in this order: the final branch review (a `final_reviewer`), one "
     "full suite on the pull request head, the owner's approval", "in this order: touched-area tests, one full suite "
     "on the pull request head, the final branch review (a `final_reviewer`)", 1),
    ("R1-5", "skills/strict-delivery/SKILL.md", "after touched-area tests, a final branch review and one full suite "
     "on the pull request head;", "after touched-area tests, one full suite on the pull request head and a final "
     "branch review;", 1),
    # The five R1-6 pins that stood here (one PR per program stream) were withdrawn by the controller in fix round 2
    # (plan review 2, R2-2: they contradicted design 5.2); FIX2_PINS below holds their corrected form.
    ("R1-7", BD_DOC, CONFIG_V_DECISION, None, 1),
    ("R1-7", BD_DOC, "= 60.0 working hours from t = 0.**", "= 61.5 working hours from t = 0.**", 1),
    ("R1-7", BD_DOC, "-> the Rq commits (49.25) -> PR-config (52.0) -> 6R.1, 6R.2 (56.25) -> PR-release's final review "
     "(57.25) -> stream `release`'s V (58.75) -> PR-release (59.25) -> 6R.3, the tag (60.0)", "-> the Rq commits (49.25) -> stream `config`'s V (50.75) -> "
     "PR-config (53.5)", 1),
    ("R1-7", BD_DOC, "PR-config 52.0, PR-release 59.25", "PR-config 53.5, PR-release 60.75", 2),
    ("R1-7", BD_DOC, "| **v0.1.0 tag (6R.3)** | **60.0** | 59.25 + 0.75 | **Fri 20 Nov 02:00** | **Fri 27 Nov 10:00** |",
     "| **v0.1.0 tag (6R.3)** | **61.5** | 60.75 + 0.75 |", 1),
    ("R1-7", README_DOC, "Target: about 60.0 hours of work", "Target: about 61.5 hours of work", 1),
    ("R1-8", PLAN_DOC, "`FIX_ROUND_CAP = 5` (spec §10: \"rounds 4-5 a fresh agent one tier up, then the Rules N and T "
     "verdict\")", "`FIX_ROUND_CAP = 5` (spec §10: \"rounds 4-5 a fresh agent one tier up, then an owner question\")", 1),
    ("R1-8", PLAN_DOC, "PC3's \"The full suites run once per commit\" (as on origin/main)",
     "PC3's \"The full suites run once per commit\")", 1),
    ("R1-8", PLAN_DOC, "\"dispatch waits for the answers\" (as on origin/main) in \"Owner questions are batched\"",
     "\"dispatch waits for the answers\" in \"Owner questions are batched\"", 1),
    ("R1-9", PLAN_DOC, "(P:50: the test command on both interpreters plus every enabled `python3 -m gates check <gate>`, "
     "with a clean tree; P:1134)", "(P:39: the test command on both interpreters plus every enabled `python3 -m gates "
     "check <gate>`, with a clean tree; P:1123)", 1),
    ("R1-10", SR_DOC, "Rules N and T: advisory until 2026-11-17, binding on the controller from design 5.4",
     "Rules N and T: advisory (binding on the controller from design 5.4; owner 2026-11-17)", 1),
    ("R1-11", "playbook/streams.md", "an edge in the breakdown goes from one of its tasks",
     "an edge in the breakdown (section 3.2 or 6) goes from one of its tasks", 1),
]


def fix1_problems(text, new, old, n):
    """The new text occurs n times and the flagged old text (when there is one) is gone."""
    out = []
    if text.count(new) != n:
        out.append("new text %d times, not %d" % (text.count(new), n))
    if old is not None and old in text:
        out.append("flagged old text present")
    return out


class FixRound1Test(unittest.TestCase):
    def test_every_corrected_text_is_in_place_and_the_flagged_text_gone(self):
        for fid, rel, new, old, n in FIX1_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertEqual(fix1_problems(read(rel), new, old, n), [])

    def test_each_pin_fails_on_the_file_restored_to_the_flagged_text(self):
        for fid, rel, new, old, n in FIX1_PINS:
            if old is None:
                continue
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                broken = read(rel).replace(new, old)
                self.assertTrue(fix1_problems(broken, new, old, n))

    def test_each_pin_fails_on_the_file_without_the_new_text(self):
        for fid, rel, new, old, n in FIX1_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, ""), new, old, n))

    def test_the_old_resume_wording_is_gone_from_every_document(self):          # R1-1: the whole class
        for rel in (MS_DOC, SR_DOC, PLAN_DOC, "playbook/sessions.md", "skills/strict-delivery/SKILL.md"):
            with self.subTest(rel=rel):
                self.assertNotIn("stops and waits for the owner", read(rel))
                self.assertNotIn("stop and wait for the owner (an", read(rel))

    def test_config_v_placement_figures_re_add_forward_and_backward(self):       # R1-7
        # The chain's steps, written by hand from the unit costs (breakdown section 1); the documents are compared
        # with the sums, which the test computes both ways.
        steps = [("PR-unicode", 1.5), ("PR-2b1", 1.75), ("PR-2b-rest", 2.25), ("PR-2c3", 2.25), ("cut", 0.25),
                 ("P1", 6.0), ("PR-P1", 1.75), ("cut", 0.25), ("P2", 7.0), ("PR-P2", 1.5), ("cut", 0.25),
                 ("P3 tasks", 6.5), ("PR-P3", 1.75), ("cut", 0.25), ("4d", 7.0), ("4d end", 1.0), ("4e", 7.0),
                 ("Rq", 1.0), ("PR-config", 2.75), ("cut", 0.25), ("6R.1-6R.2", 4.0), ("PR-release R", 1.0),
                 ("V release", 1.5), ("PR-release", 0.5), ("6R.3", 0.75)]       # V-4: final review, V, then T
        # the on-path steps before the 4d end re-add as 41.25 (section 7), the P3 tasks tie with PR-runtime
        forward, at = {}, 0.0
        for name, cost in steps:
            at += cost
            forward[name] = at
        backward, back = [], at
        for name, cost in reversed(steps):
            back -= cost
            backward.append(back)
        self.assertEqual(at, 60.0)
        self.assertEqual(back, 0.0)
        self.assertEqual(backward[-1], 0.0)
        self.assertEqual(forward["Rq"], 49.25)
        self.assertEqual(forward["PR-config"], 52.0)
        self.assertEqual(forward["6R.1-6R.2"], 56.25)
        self.assertEqual(forward["PR-release"], 59.25)
        self.assertEqual((forward["PR-release R"], forward["V release"]), (57.25, 58.75))        # V-4
        self.assertNotIn("V config", forward)                                # config's V is not a path step
        kinds = 38.5 + 1.0 + 17.0 + 1.5 + 1.25 + 0.75                           # tasks, end, PR ends, V, cuts, tag
        self.assertEqual(kinds, 60.0)
        bd = read(BD_DOC)
        sec7 = bd[bd.index("## 7. Critical path"):]
        for fig in ("= 49.25; + 2.75 (PR-config U 0.25 + R 2.0 + T 0.5) = 52.0", "= 56.25;", "= 59.25;", "= 60.0.",
                    "- 4.0 (6R.1, 6R.2) = 52.25; - 0.25 (cut) = 52.0; - 2.75 (PR-config) = 49.25",
                    "38.5 + 1.0 + 17.0 + 1.5 + 1.25 + 0.75 = 60.0"):
            self.assertIn(fig, sec7, fig)
        for stale in ("= 61.5.", "= 50.75; + 2.75", "= 53.75;", "= 53.5;"):
            self.assertNotIn(stale, sec7, stale)

    def test_streams_md_carries_no_section_number_of_this_repository_breakdown(self):     # R1-11
        self.assertNotIn("section 3.2 or 6", read("playbook/streams.md"))

    def test_every_stream_end_adversarial_review_sentence_names_the_condition(self):      # R1-4, whole class
        for rel in ("playbook/rules.md", "playbook/streams.md", "playbook/review.md", "skills/strict-delivery/SKILL.md"):
            with self.subTest(rel=rel):
                for unit in prose_units(read(rel)):
                    if "counts as review 1" in unit:      # review.md "Fix loop": applies only when that review runs
                        continue
                    for m in re.finditer(r"(?:stream-end|its) adversarial review", unit):
                        self.assertIn("where the profile enables it", unit[m.start():m.start() + 120], (rel, unit[:60]))


# Fix round 2 of the process-v2 roll-in (plan review 2, R2-1..R2-7; design 5.2, 5.9; controller rulings of
# 2026-11-17). The same pin form as FIX1_PINS: (id, file, new text, the flagged old text, how often the new text occurs).
PROMPTS = "skills/strict-delivery/prompts/"
V_RULE_PLAN = ("the stream-end verifier (once per stream, after its last block; no on-demand pull request waits for "
               "it, and its fixes go in the stream's final pull request or, when every block already merged on "
               "demand, in a small follow-up pull request, which is then the final one; design 5.2; owner 2026-11-17)")
R3_END_NEW = ("the block opens its own pull request on demand, D7, because Task 6R.1 consumes it (PR-R3, breakdown "
              "revision 7)")
R4_END_NEW = ("the block opens its own pull request on demand, D7, because Task 6R.1 consumes it (PR-R4, breakdown "
              "revision 7)")
FIX2_PINS = [
    ("R2-1", PROMPTS + "controller.md", "the final verifier (where the profile enables it, strict) runs once per "
     "stream, at its end,", "the final verifier runs once per stream, at its end,", 1),
    ("R2-1", PROMPTS + "final_reviewer.md", "go to the final verifier where the profile enables it, strict).",
     "go to the final verifier).", 1),
    ("R2-1", MS_DOC, "The final verifier (where the profile enables it, strict) runs once per stream, at its end, over "
     "everything the stream delivered, including what it already merged", "The final verifier runs once per stream, "
     "at its end, over everything the stream delivered, including what it already merged", 1),
    ("R2-1", MS_DOC, "after the stream-end final verifier (where the profile enables it, strict) has run",
     "after the stream-end final verifier has run", 1),
    ("R2-1", SR_DOC, "and in the verifier (where the profile enables it, strict; design 5.1; owner 2026-11-17)",
     "and in the verifier (design 5.1; owner 2026-11-17)", 1),
    ("R2-2", BD_DOC, "- Withdrawn 2026-11-17 by the controller: it contradicted design 5.2 (plan review 2, R2-2)",
     ONE_PR_DECISION, 1),
    ("R2-2", BD_DOC, "opens its own on-demand PR as soon as it is ready when a task of another stream consumes it",
     "a consumed sub-block does not open a PR of its own", 1),
    ("R2-2", PLAN_DOC, "recorded in the breakdown's revision 7 (section 6.1): a sub-block that another stream consumes "
     "opens its own pull request as soon as it is ready, and the other sub-blocks ride their stream's final pull "
     "request.", "each program stream keeps its one pull request, opened on demand when a task of another stream "
     "consumes one of its sub-blocks, and a consumed sub-block does not open a pull request of its own", 1),
    ("R2-3", PD_DOC, "runs once at the stream's end, after its last block, over everything the stream delivered; no "
     "on-demand pull request waits for it, and its fixes go in the stream's final pull request or, when every block "
     "already merged on demand, in a small follow-up pull request, which is then the final one (design 5.2; owner "
     "2026-11-17).", "runs once at the stream's end, before the stream's final pull request, over everything the "
     "stream delivered (design 5.2; owner 2026-11-17).", 1),
    ("R2-3", "playbook/streams.md", "(where the profile enables it, strict; `playbook/review.md`), which runs after "
     "the stream's last block and which no on-demand pull request waits for. A defect that review finds in "
     "already-merged code is fixed in that pull request or, when every block of the stream already merged on demand, "
     "in a small follow-up pull request, which is then the final one, and a consumer stream takes the fix",
     "`playbook/review.md`). A defect that review finds in already-merged code is fixed in that pull request or in a "
     "small follow-up pull request, and a consumer stream takes the fix", 1),
    ("R2-3", MS_DOC, "has run, which it does after the stream's last block, no on-demand pull request waiting for it, "
     "and a stream whose every block already merged on demand opens a small follow-up pull request for the "
     "verifier's fixes, which is then its final one; a block another stream consumes", "(where the profile enables "
     "it, strict) has run; a block another stream consumes", 1),
    ("R2-3", BD_DOC, "It runs after the stream's last block (after that block's merge when it merged on demand); no "
     "on-demand PR waits for it, and its fixes go in the stream's final PR or, when every block already merged on "
     "demand, in a small follow-up PR (opened only if V finds a defect), which is then the final PR.",
     "It sits before the stream's final PR, or, when the stream's last part already merged on demand, before a small "
     "final PR.", 1),
    ("R2-3", PLAN_DOC, V_RULE_PLAN, "the stream-end verifier (once per stream, before its final pull request; design "
     "5.2; owner 2026-11-17)", 1),
    ("R2-3", PLAN_DOC, "Then final review and the PR flow, which is on demand because Task 6R.1 consumes 4e "
     "(breakdown revision 7); the stream-end verifier (design 5.2; owner 2026-11-17) runs after it and does not "
     "delay it.", "Then final review, the stream-end verifier (design 5.2; owner 2026-11-17) and the PR flow.", 1),
    ("R2-3", BD_DOC, "on demand (consumer: `release` 6R.1, edge 4e.3 -> 6R.1); it carries what no earlier PR carried "
     "(4e and R2), so every block of `config` has merged on demand once it merges and V's fixes go in a small "
     "follow-up PR, which is then the stream's final PR", "R4.1 -> 6R.1) and the stream's final PR", 1),
    ("R2-4", BD_DOC, "-- why: V runs after the stream's last block and no on-demand PR waits for it, for every "
     "stream alike", "-- why: PR-config is on demand (consumer `release` 6R.1), its gate holds no verifier", 1),
    ("R2-5", BD_DOC, "6R.1 waits for PR-config's merge (P:4799)", "6R.1 waits for PR-config's merge (P:5537)", 1),
    ("R2-6", PLAN_DOC, "**Block R1 end:** final review on the stream branch (no per-block verifier, it runs once at "
     "the stream's end: design 5.2; the block rides PR-5b, breakdown revision 7 (the R1 end is on the stream branch "
     "before the 5b group is cut), and has no PR of its own, since "
     "only stream `records` consumes it; owner 2026-11-17); stream `docs`'s 5c end waits for it.",
     "**Block R1 end:** final review, PR to `main` (`MERGED ... stream=residual block=R1`", 1),
    ("R2-6", PLAN_DOC, R3_END_NEW, "the block rides PR-hooks, breakdown revision 7;", 1),
    ("R2-6", PLAN_DOC, R4_END_NEW, "the block rides PR-config, breakdown revision 7;", 1),
    ("R2-7", README_DOC, "Merged pull requests: #1-#24.", "(#17, `run_all`, is open)", 1),
]
SUB_BLOCK_PR = {"3a": "PR-runtime", "3d": "PR-package", "5a": "PR-5a", "5b": "PR-5b", "5c": "PR-5c", "6E": "PR-6E",
                "6K": "PR-6K", "R3": "PR-R3", "R4": "PR-R4", "4e": "PR-config", "4c": "PR-4c",
                "4d": "PR-4d"}   # D7: the breakdown's edges, and for 4c and 4d the `Consumes:` lines of Tasks 6R.1-6R.2
CONSUMES_ONLY = {"4c", "4d"}      # consumed through D7's `Consumes:` clause, with no edge in the breakdown's YAML (R3-4)
# what each on-demand PR carries besides the sub-block it is named for (a work branch is never rebased; R3-3)
CARRIES = {"PR-R3": ("3b", "3c"), "PR-R4": ("4b",), "PR-4d": ("4a",), "PR-5b": ("R1",), "PR-5a": ("3b.1",),
           "PR-6E": ("6E.3b",)}      # V-6: 3b.1 is on hooks/main before the 5a cut, R1 before the 5b cut


def bd_yaml():
    text = read(BD_DOC)
    start = text.index("schema: breakdown/1")                 # section 6's block, not the max_concurrent one of section 1
    return text[start:text.index("```", start)]


def bd_streams_and_edges():
    """(task -> stream, [(from, to)]) of the breakdown's section 6 YAML, read with a regex (the production reader,
    P2.2's breakdown loader, does not exist yet)."""
    y = bd_yaml()
    owner = {}
    for m in re.finditer(r"\{id: (\w+),.*?tasks: \[([^\]]*)\]", y, re.S):
        for t in m.group(2).split(","):
            owner[t.strip()] = m.group(1)
    edges = re.findall(r"\{from: ([\w.]+), to: ([\w.]+)\}", y)
    return owner, edges


def bd_rev7_rows():
    """name -> merge figure of every PR row of the revision 7 tables (section 4 and section 6.1)."""
    bd = read(BD_DOC)
    a = bd[bd.index("### Revision 7 per-PR table"):bd.index("**Revision 6 table (history")]
    b = bd[bd.index("### 6.1 Program PRs"):bd.index("Revision 6 (history): one row per program PR")]
    out = {}
    for line in (a + "\n" + b).split("\n"):
        if line.startswith("| PR-"):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            out[cells[0].split(" ")[0]] = (float(re.findall(r"\*\*([0-9.]+)\*\*", cells[-1])[0]), line)
    return out


def bd_queue():
    bd = read(BD_DOC)
    s = bd.index("The merge-queue order, with the merge times of this section and of section 4: ")
    e = bd.index(". The streams still run unregistered", s)
    items = bd[s:e].split(": ", 1)[1].split(", ")
    return [(i.rsplit(" ", 1)[0], float(i.rsplit(" ", 1)[1])) for i in items]


class FixRound2Test(unittest.TestCase):
    def test_every_corrected_text_is_in_place_and_the_flagged_text_gone(self):
        for fid, rel, new, old, n in FIX2_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertEqual(fix1_problems(read(rel), new, old, n), [])

    def test_each_pin_fails_on_the_file_restored_to_the_flagged_text(self):
        for fid, rel, new, old, n in FIX2_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, old), new, old, n))

    def test_each_pin_fails_on_the_file_without_the_new_text(self):
        for fid, rel, new, old, n in FIX2_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, ""), new, old, n))

    def test_the_old_one_pr_per_stream_rule_is_gone_from_every_document(self):          # R2-2, whole class
        for rel in (BD_DOC, PLAN_DOC, "playbook/streams.md", MS_DOC, PD_DOC):
            with self.subTest(rel=rel):
                text = read(rel)
                self.assertNotIn("does not open a PR of its own", text)
                self.assertNotIn("does not open a pull request of its own", text)
                self.assertNotIn("keeps its one pull request", text)
                self.assertNotIn("and is the stream's final PR in every case", text)

    def test_every_consumed_sub_block_has_its_own_on_demand_row(self):                  # R2-2, direct and by edges
        owner, edges = bd_streams_and_edges()
        consumed = {a.split(".")[0] for a, b in edges if owner[a] != owner[b]}
        self.assertEqual(consumed | CONSUMES_ONLY, set(SUB_BLOCK_PR))       # no sub-block outside the list is consumed
        self.assertFalse(consumed & CONSUMES_ONLY)                          # the two lists do not overlap
        plan = read(PLAN_DOC)
        for needle in ("`templates.render` and `managed.put_block` (Tasks 4c.1-4c.2)",     # R3-4: the Consumes lines
                       "- Consumes: `plugin.version` (block 3); `managed.put_block`, `templates.render` (block 4)",
                       "- block 4: `init` (non-interactive, answers file, profile)"):
            self.assertIn(needle, plan, needle)
        rows = bd_rev7_rows()
        for pr, subs in CARRIES.items():                                    # R3-3: each PR names what it carries
            for sub in subs:
                with self.subTest(pr=pr, sub=sub):
                    self.assertIn(sub, rows[pr][1].split(" | ")[0] + rows[pr][1].split(" | ")[1])
        for sub, pr in SUB_BLOCK_PR.items():
            with self.subTest(sub=sub):
                self.assertIn(pr, rows)
                self.assertIn("on demand", rows[pr][1].split(" | ")[1])
        for riding in ("R1", "3b", "3c"):                                   # consumed only inside their own stream
            self.assertNotIn(riding, consumed)
        for pr in ("PR-hooks", "PR-records", "PR-residual/R5"):
            self.assertIn("stream final PR", rows[pr][1].split(" | ")[1])

    def test_the_merge_queue_figures_re_add(self):                                         # R2-2, R2-3
        rows = bd_rev7_rows()
        queue = bd_queue()
        self.assertEqual([n for n, _ in queue], sorted(rows, key=lambda n: rows[n][0]))
        for (n, t) in queue:
            self.assertEqual(rows[n][0], t, n)
        for (_, a), (_, b) in zip(queue, queue[1:]):
            self.assertGreaterEqual(b - a, 0.75)          # one merge at a time, each at least U + T after the one before
        sec4 = read(BD_DOC)
        s4 = sec4.index("The program's PRs and their V are in section 6.1 (")
        listed = [(i.rsplit(" ", 1)[0], float(i.rsplit(" ", 1)[1])) for i in
                  sec4[s4:sec4.index(").", s4)].split("(", 1)[1].split(", ")]
        self.assertEqual(listed, [q for q in queue if q[1] > 33.0 and q[0] != "PR-a-final"])    # the program's PRs, as in section 6.1
        at = dict(queue)
        prev = {n: queue[i - 1][1] for i, (n, _) in enumerate(queue) if i}
        m = lambda tasks_end, r, n: max(tasks_end + 0.25 + r + 0.5, prev[n] + 0.75)    # clean U + T after the queue
        v_hooks, v_records = at["PR-R3"] + 1.5, at["PR-6K"] + 1.5
        # R is 1.0 for a PR with one sub-block or V's fixes only, the stream's larger figure when it carries earlier
        # sub-blocks (section 1; R3-3; V-6): PR-6E carries 6E.3b, PR-5a 3b.1, PR-5b R1, PR-R3 3b and 3c, PR-4d 4a,
        # PR-R4 4b; 6K.2 is held to 38.25 (V-5: the end of PR-5c's R, 37.25 + 1.0 = 38.25)
        want = {"PR-runtime": m(27.75, 1.0, "PR-runtime"), "PR-6E": m(20.0, 1.5, "PR-6E"),
                "PR-5a": m(30.75, 1.25, "PR-5a"), "PR-4c": m(16.0, 1.0, "PR-4c"), "PR-5b": m(37.25, 1.5, "PR-5b"),
                "PR-5c": m(37.25, 1.0, "PR-5c"), "PR-6K": m(38.25 + 2.0, 1.0, "PR-6K"), "PR-R3": m(39.5, 1.25, "PR-R3"),
                "PR-4d": m(40.25, 2.0, "PR-4d"),
                "PR-records": m(v_records, 1.0, "PR-records"), "PR-hooks": m(v_hooks, 1.0, "PR-hooks"),
                "PR-residual/R5": prev["PR-residual/R5"] + 0.75, "PR-R4": m(46.5, 2.0, "PR-R4"),
                "PR-config": m(49.25, 2.0, "PR-config")}
        for n, t in want.items():
            self.assertEqual(at[n], t, n)
        self.assertEqual(at["PR-hooks"], 47.0)
        self.assertEqual((at["PR-5b"], at["PR-5c"], at["PR-6K"]), (39.5, 40.25, 42.0))      # V-6, V-5
        self.assertEqual(at["PR-4c"], at["PR-5a"] + 0.75)                  # R3-4: in the gap after PR-P3, with PR-6E, PR-5a
        self.assertEqual(at["PR-R4"], at["PR-config"] - 2.75)               # R3-3: PR-R4 merges as PR-config's U starts
        self.assertEqual(prev["PR-hooks"], at["PR-records"])
        self.assertEqual(prev["PR-residual/R5"], at["PR-hooks"])        # the enablement follows the hooks stream's last PR

    def test_every_wave_is_at_or_under_the_cap_of_25(self):                                # R2-2, section 6.2
        bd = read(BD_DOC)
        sec = bd[bd.index("**Revision 7 waves"):bd.index("**Revision 6 waves (history).**")]
        peaks = [int(m.group(1)) for m in re.finditer(r"^\| PW\d \|.*\| \*\*(\d+)\*\*", sec, re.M)]
        self.assertEqual(len(peaks), 8)
        self.assertTrue(all(p <= 25 for p in peaks), peaks)

    def test_every_stream_end_verifier_sentence_names_the_condition(self):                   # R2-1, whole class
        # the cadence sentences; "A defect the stream-end verifier finds ..." (MS "Verifier and merges") states no cadence
        stream_end = re.compile(r"stream-end final verifier|final verifier(?: \(where[^)]*\))? runs once per stream|go "
                                r"to the final verifier|in the verifier \(")
        for rel in (MS_DOC, SR_DOC, PROMPTS + "controller.md", PROMPTS + "final_reviewer.md"):
            found = 0
            for unit in prose_units(read(rel)):
                for sentence in re.split(r"(?<=\.) (?=[A-Z`(])", unit):
                    if stream_end.search(sentence):
                        found += 1
                        self.assertIn("where the profile enables it", sentence, (rel, sentence[:80]))
            with self.subTest(rel=rel):
                self.assertGreaterEqual(found, 1)


R3_PLAN_START_NEW = ("R2.1 starts after `merged:hooks/5a` and `merged:package`, R2.2 after `merged:records/5b` and "
                     "`merged:records/5c`, R2.3 after `merged:records/6E`")
R3_BD_UNBLOCK_NEW = ("R2.1 after merged:hooks/5a and merged:package, then R2.2 after merged:records/5b and "
                     "merged:records/5c and R2.3 after merged:records/6E, serially")
R3_6E3_DONE = "merged as #22 (`a128a39`, 2026-11-17, observed; the schedule keeps its figure, t = 0 does not move): **9.5** |"
FIX3_PINS = [
    ("R3-2", PLAN_DOC, R3_PLAN_START_NEW, "R2 starts after `merged:hooks` and `merged:records`; R4 after the 4b end and "
     "`merged:records`", 1),
    ("R3-2", PLAN_DOC, "R4 after the 4b end and PR-loopstats (Task 6E.3; Task R4.1)", "R4 after the 4b end and "
     "`merged:records`", 1),
    ("R3-2", BD_DOC, R3_BD_UNBLOCK_NEW, "R2.1 after merged:hooks and merged:package, then R2.2 and R2.3 serially after "
     "merged:records", 1),
    ("R3-2", BD_DOC, "R4.1 after the 4b end and PR-loopstats, the 6E.3 merge (P078:5329);", "R4.1 after the 4b end and "
     "merged:records (P078:5329);", 1),
    ("R3-2", BD_DOC, "The `unblock` strings of the YAML for R2.1, R2.2, R2.3 and R4.1, rewritten by revision 7, name "
     "the consumed sub-block's merge", "(4) the `unblock` strings that wait for a stream's merge", 1),
    ("R3-3", BD_DOC, "| PR-R3 (3b, 3c, R3.1, R3.2) |", "| PR-R3 (R3.1, R3.2) |", 1),
    ("R3-3", BD_DOC, "| PR-R4 (4b, R4.1) |", "| PR-R4 (R4.1) |", 1),
    ("R3-3", BD_DOC, "| PR-5b (R1, 5b.1, 5b.2) |", "| PR-5b (5b.1, 5b.2) |", 1),     # V-6: R1 rides PR-5b
    ("R3-3", BD_DOC, "| PR-hooks (V's fixes) |", "| PR-hooks (3b, 3c) |", 1),
    ("R3-3", BD_DOC, "| PR-records (V's fixes) |", "| PR-records (R1, 6E.3b) |", 1),
    ("R3-3", BD_DOC, "| PR-config (4e, R2) |", "| PR-config (4a-4e, R2) |", 1),
    ("R3-3", BD_DOC, "R 1.25 (3b, 3c and R3) -> 40.75", "R 1.0 -> 40.5; clean U 0.25 + T 0.5 after PR-6K", 1),
    ("R3-3", BD_DOC, "PR-R4 merges 49.25, as PR-config's update starts (49.25), so it has no slack",
     "PR-R4 merges 48.25, 1.0 h before PR-config's update (49.25)", 1),
    ("R3-4", BD_DOC, "| PR-4c (4c.1, 4c.2) |", "also name 4c and 4d modules, which go out in PR-config", 1),
    ("R3-4", BD_DOC, "| PR-4d (4a, 4d) |", "also name 4c and 4d modules, which go out in PR-config", 1),
    ("R3-4", BD_DOC, "which D7's `Consumes:` clause counts (plan review 3, R3-4): 4d (`init`, Task 4d.1; PR-4d) and 4c "
     "(`managed.put_block`, `templates.render`, Tasks 4c.1-4c.2; PR-4c); twelve in all", "The edges of the YAML above give "
     "ten consumed sub-blocks: 3a (PR-runtime), 3d (PR-package), 5a (PR-5a), 5b (PR-5b), 5c (PR-5c), 6E (6E.3 in "
     "PR-loopstats, 6E.1-6E.2 in PR-6E), 6K (PR-6K), R3 (PR-R3), R4 (PR-R4) and 4e (PR-config, which carries 4a-4d", 1),
    ("R3-5", PLAN_DOC, "**Block 6E end:** final review, PR to `main` (the verifier runs once at the end of the stream "
     "that carries 6E,", "(`final=yes`; the verifier runs once at the end of the stream that carries 6E,", 1),
    ("R3-5", PLAN_DOC, "**Block 6K end:** final review, PR to `main` (the verifier runs once at the end of the stream "
     "that carries 6K,", "(`final=yes`; the verifier runs once at the end of the stream that carries 6K,", 1),
    ("R3-6", PLAN_DOC, "`package` merges first among them, after PR-loopstats (design 5.4; breakdown revision 7).",
     "each its own pull request; `package` merges first.", 1),
    ("R3-7", PLAN_DOC, "**Block R2 end:** final review on the stream branch (no per-block verifier, it runs once at the "
     "stream's end: design 5.2; the block rides PR-config, breakdown revision 7, and has no PR of its own, since no "
     "other stream consumes it; owner 2026-11-17).", "**Block R2 end:** final review, PR to `main` (`MERGED ... "
     "stream=residual block=R2`", 1),
    ("R3-6E3", PLAN_DOC, "### Task 6E.3: `loopstats` (group branch `<program>/evidence/loopstats`, PARALLEL with "
     "6E.1-6E.2, starts now) — COMPLETE", "PARALLEL with 6E.1-6E.2, starts now)\n", 1),
    ("R3-6E3", PLAN_DOC, "Complete: merged into `main` as PR #22 (`a128a39`, 2026-11-17; breakdown revision 7, "
     "PR-loopstats).", None, 1),
    ("R3-6E3", BD_DOC, R3_6E3_DONE, "rides PR-6E | **9.5** |", 2),
    ("R3-6E3", PLAN_DOC, "itertools.product over each half of the N draws, the halves convolved (meet in the middle;",
     "sum over product(range(k), repeat=N), N <= 17", 1),
]


class FixRound3Test(unittest.TestCase):
    def test_every_corrected_text_is_in_place_and_the_flagged_text_gone(self):
        for fid, rel, new, old, n in FIX3_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertEqual(fix1_problems(read(rel), new, old, n), [])

    def test_each_pin_fails_on_the_file_restored_to_the_flagged_text(self):
        for fid, rel, new, old, n in FIX3_PINS:
            if old is None:
                continue
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, old), new, old, n))

    def test_each_pin_fails_on_the_file_without_the_new_text(self):
        for fid, rel, new, old, n in FIX3_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, ""), new, old, n))

    def test_no_final_yes_on_an_on_demand_block_end(self):                                 # R3-5, whole class
        plan = read(PLAN_DOC)
        for line in plan.split("\n"):
            if "**Block 6E end:**" in line or "**Block 6K end:**" in line:
                self.assertNotIn("final=yes", line)
        self.assertIn("`final=yes` marks the plan's last PR and is not used", read(BD_DOC))

    def test_the_merged_loopstats_test_has_the_meet_in_the_middle_reference(self):         # relayed item 2
        src = read("tests/test_loopstats.py")
        self.assertIn("def brute_p(counts):", src)
        self.assertIn("each half of the N draws separately", src)
        self.assertIn("dist(half), dist(n - half)", src)

    def test_the_plan_names_the_merged_task_where_the_breakdown_does(self):                # relayed item 1
        plan = read(PLAN_DOC)
        head = plan.index("### Task 6E.3: `loopstats`")
        self.assertIn("COMPLETE", plan[head:plan.index("\n", head)])
        self.assertIn("PR #22", plan[head:head + 600])


DESIGN_DOC = "docs/strict-delivery/specs/2026-11-17-delivery-process-changes-design.md"
FIXV_PINS = [   # the final verifier's findings V-3..V-7 (V-1: tests.test_skill.RepoSkillTest; V-3's record sentence: its own tests)
    ("V-4", BD_DOC, "6R.2 54.25 + 2.0 = 56.25; final review R 1.0 -> 57.25; V 1.5 -> 58.75; T 0.5 -> 59.25",
     "6R.2 54.25 + 2.0 = 56.25; V 1.5 -> 57.75; R 1.0 + T 0.5 = 1.5 -> 59.25", 1),
    ("V-4", BD_DOC, "after PR-P3 33.0: R 1.0 -> 34.0; V 1.5 -> 35.5; U 0.25 + T 0.5 = 0.75 -> 36.25",
     "after V 34.5: U 0.25 + R 1.0 + T 0.5 = 1.75 -> 36.25", 1),
    ("V-4", BD_DOC, "PR-release's final review (57.25) -> stream `release`'s V (58.75) -> PR-release (59.25)",
     "-> stream `release`'s V (57.75) -> PR-release (59.25)", 1),
    ("V-4", BD_DOC, "+ 1.0 (R) + 1.5 (V) + 0.5 (T) = 59.25; + 0.75 (6R.3) = 60.0.",
     "+ 1.5 (V) + 1.5 (R 1.0 + T 0.5) = 59.25", 1),
    ("V-4", BD_DOC, "- 0.5 (PR-release T) = 58.75; - 1.5 (V release) = 57.25; - 1.0 (PR-release R) = 56.25;",
     "- 1.5 (PR-release R + T) = 57.75; - 1.5 (V release) = 56.25;", 1),
    ("V-5", BD_DOC, "6K.2 38.25 + 2.0 = 40.25; R 1.0 -> 41.25; after PR-5c (40.25): clean U 0.25 + T 0.5 = 0.75 -> 42.0",
     "6K.2 37.25 + 2.0 = 39.25; R 1.0 -> 40.25; after PR-5c (39.75)", 1),
    ("V-5", BD_DOC, "the other windows have at most 3, `a` at 1.75-2.75 among them: F1b group 1 and PR-2b1's end 2)",
     "the 4e and R2 groups with PR-R4's end; the other windows have at most 3).", 1),
    ("V-5", BD_DOC, "at 38.5: hooks 6, records 6 (controller 1, the 6K.2 group 3, PR-5b's end 2), residual 3, config 4)",
     "at 38.5: hooks 6, records 6 with PR-5b's end, residual 3, config 4)", 1),
    ("V-6", BD_DOC, "PR-5a carries 3b.1 (merged into `20261110-v01/hooks/main` as `3194b4f`, not on `main`, before the "
     "5a group is cut at 24.75)", "PR-5c carries R1 (on the stream branch before 5c", 1),
    ("V-6", BD_DOC, "PR-5b carries R1 (the R1 end, 32.5, is on the stream branch before the 5b group is cut at 33.25;",
     "PR-5c carries R1", 1),
    ("V-6", BD_DOC, "R 1.5 (R1 and 5b) -> 38.75; after PR-a-final (36.25): clean U 0.25 + T 0.5 = 0.75 -> 39.5 | **39.5** |",
     "R 1.0 -> 38.25; after PR-a-final (36.25): clean U 0.25 + T 0.5 = 0.75 -> 39.0 | **39.0** |", 1),
    ("V-6", BD_DOC, "5c 33.25 + 4.0 = 37.25; R 1.0 -> 38.25; after PR-5b (39.5): clean U 0.25 + T 0.5 = 0.75 -> 40.25 | "
     "**40.25** |", "R 1.5 (R1 and 5c) -> 38.75", 1),
    ("V-6", BD_DOC, "R 1.25 (5a and 3b.1) -> 32.0;", "5a.1-5a.3 24.75 + 6.0 = 30.75; R 1.0 -> 31.75;", 1),
    ("V-7", BD_DOC, "The section 6 YAML is changed by revision 7 only in the `unblock` strings of R2.1, R2.2, R2.3 and "
     "R4.1 (below):", "The section 6 YAML is not rewritten by revision 7", 1),
    ("V-7", BD_DOC, "R5.1 (S) 38.25 + 1.0 = 39.25; R 1.0 -> 40.25; V 1.5 -> 41.75;", "V 1.5 -> 40.75", 1),
    ("V-7", DESIGN_DOC, "Status: approved by the owner, 2026-11-17 (\"approved, roll it in\").",
     "Status: draft for owner approval", 1),
]


class FixRoundVTest(unittest.TestCase):
    def test_every_corrected_text_is_in_place_and_the_flagged_text_gone(self):
        for fid, rel, new, old, n in FIXV_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertEqual(fix1_problems(read(rel), new, old, n), [])

    def test_each_pin_fails_on_the_file_restored_to_the_flagged_text(self):
        for fid, rel, new, old, n in FIXV_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, old), new, old, n))

    def test_each_pin_fails_on_the_file_without_the_new_text(self):
        for fid, rel, new, old, n in FIXV_PINS:
            with self.subTest(fid=fid, rel=rel, new=new[:40]):
                self.assertTrue(fix1_problems(read(rel).replace(new, ""), new, old, n))

    def test_the_final_review_comes_before_the_verifier_at_a_stream_final_pr(self):       # V-4, whole class
        for name, rest in bd_rev7_rows().items():
            if name not in ("PR-a-final", "PR-residual/R5", "PR-release"):
                continue
            cell = rest[1].split(" | ")[3]
            r, v = re.search(r"\bR 1\.0\b", cell), re.search(r"\bV 1\.5\b", cell)
            with self.subTest(pr=name):
                self.assertTrue(r and v and r.start() < v.start(), cell)
        self.assertNotIn("after V 34.5", read(BD_DOC))

    def test_the_sums_of_the_reordered_cells_re_add(self):                                  # V-4: the totals do not move
        rows = bd_rev7_rows()
        self.assertEqual(33.0 + 1.0 + 1.5 + 0.25 + 0.5, rows["PR-a-final"][0])
        self.assertEqual(56.25 + 1.0 + 1.5 + 0.5, rows["PR-release"][0])
        self.assertEqual(rows["PR-5b"][0], 37.25 + 1.5 + 0.25 + 0.5)                       # V-6
        self.assertEqual(rows["PR-5c"][0], rows["PR-5b"][0] + 0.75)
        self.assertEqual(rows["PR-6K"][0], 38.25 + 2.0 + 1.0 + 0.75)                       # V-5
        self.assertEqual(rows["PR-R3"][0], rows["PR-4d"][0] + 0.75)

    def test_no_stream_exceeds_four_children_in_the_window_the_verifier_found(self):       # V-5: records 37.25-38.75
        rows = bd_rev7_rows()
        r_5c_end = 37.25 + 1.0                       # PR-5c's R ends (the PR-5c cell: R 1.0 -> 38.25)
        self.assertIn("R 1.0 -> 38.25", rows["PR-5c"][1])
        k2_start = float(re.search(r"6K\.2 ([0-9.]+) \+ 2\.0", rows["PR-6K"][1]).group(1))
        # 1 (6K.2 group) + 2 (PR-5b's end) + 2 (PR-5c's R) is 5 while the three overlap; the group starts when R ends
        self.assertGreaterEqual(k2_start, r_5c_end)


if __name__ == "__main__":
    unittest.main()
