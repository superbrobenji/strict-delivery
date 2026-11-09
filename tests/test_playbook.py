"""Tests for playbook/rules.md (Task B2.1) and its table helpers in tests/prose_check.py.
Oracle: the real file is read from the repository root and parsed by the production helpers (table_rows,
first_table_header, rules_problems). Every expected value below (header, ids, spec section 8 keys, phrases, the
derivation table of `profiles` and `enforced by`, `source`, the fixed set) is a literal from the plan and spec, never
read back from the file or the helpers. Bad samples are built from GOOD, a well-formed sample written here, by one
change each, and assert their exact problem kinds."""
import os
import re
import tempfile
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
    "SD-R15": ["`mktemp -d`", "`git stash`", "heredoc", "discloses a slip"]}
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
    "SD-R3": (["Owner-only", "halts"], ["never assumes"]),
    "SD-R4": (["Report before plan", "planned in full", "stream breakdown", "dependency edges",
               "superpowers:brainstorming", "dispatches no writer", "`program create`"], ["nobody approved"]),
    "SD-R5": (["Zero bugs", "cosmetic item", "marks it cosmetic", "unrelated bug"], ["defect shipped"]),
    "SD-R6": (["deleted test"], ["hides the failure"]),
    "SD-R7": (["epic"], ["siblings"]),
    "SD-R8": (["process defect"], ["lets the defects in"]),
    "SD-R9": (["re-run every gate", "`git merge-tree`", "polluted"], ["author's checkout"]),
    "SD-R10": (["mutation transcript", "one mutant per changed condition", "surviving mutant"], ["no mutant fails"]),
    "SD-R11": (["One block per agent context", "`gate_checkpoint` counts", "Continuation is automatic",
                "inherited memory", "rewrites the handoff", "handoff is complete", "safe to clear"], ["written handoff"]),
    "SD-R12": (["base branch is protected", "owner's approval", "`MERGED`", "`checkpoint.pushed`", "need no approval",
                "conflicts"], ["lost machine"]),
    "SD-R13": (["cleanup"], ["pile up"]),
    "SD-R14": (["background jobs", "completion record", "waiting on its own background work"], ["orphaned job"]),
    "SD-R15": (["`set -eu`", "`mktemp -d`", "heredoc", "discloses a slip"], ["another agent's work"]),
    "SD-R16": (["agent memory"], ["decision log"]),
    "SD-R17": (["role/model map"], ["quality or cost", "whatever the profile"]),
    "SD-R18": (["bypass block"], ["can skip"]),
    "SD-R19": (["production-path"], ["proves the mock"]),
}


# Clauses of spec section 8 that the review found dropped or blurred (F-B21R-4), and those found by the re-check of
# every row against its bullet; each must stay in its rule cell, case-sensitive.
RESTORED = {
    "SD-R4": ["dependency edges", "unblock condition", "parallel groups", "`breakdown/1`", "`max_concurrent`",
              "`streams.yml`", "a pointer to a section that does not exist or holds none"],
    "SD-R5": ["the reviewer marks it cosmetic", "folded into the next real edit"],
    "SD-R11": ["the handoff fields of spec §9", "`Task <block>.<n>` headings", "`<block>.<n>` task tokens", "`/clear`"],
}


def read(rel):
    """UTF-8 text of a repository file, from the repository root whatever the working directory (Q-B21-6 (a))."""
    with open(os.path.join(pc.REPO_ROOT, rel), "rb") as f:
        return f.read().decode("utf-8")


def sentences(cell):
    """Sentences of a cell: split at spaces after `.`, `!` or `?`, or after one of them and a closing bracket or quote."""
    return [s for s in re.split(r"(?<=[.!?]) +|(?<=[.!?][)\]\"']) +", cell) if s]


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
                self.assertEqual(kinds(read(RULES)), {"line-ending"})


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
    ("title bom", "\ufeff" + GOOD_TEXT, {"first-line"}),
    # F2 bytes
    ("cr in a line", with_line(2, "Rules\rfollow."), {"line-ending"}),
    ("crlf", GOOD_TEXT.replace("\n", "\r\n"), {"line-ending"}),
    ("tab", with_line(2, "Rules\tfollow."), {"control"}),
    ("nul", with_line(2, "Rules\x00follow."), {"control"}),
    ("esc", with_line(2, "Rules\x1bfollow."), {"control"}),
    ("del", with_line(2, "Rules\x7ffollow."), {"control"}),
    # F-B21R-2: every Unicode Cc, Zl and Zp character but the newline
    ("c1 first", with_line(2, "Rules" + chr(0x80) + "follow."), {"control"}),
    ("c1 nel", with_line(2, "Rules" + chr(0x85) + "follow."), {"control"}),
    ("c1 csi", with_line(2, "Rules" + chr(0x9b) + "follow."), {"control"}),
    ("c1 last", with_line(2, "Rules" + chr(0x9f) + "follow."), {"control"}),
    ("line separator", with_line(2, "Rules" + chr(0x2028) + "follow."), {"control"}),
    ("paragraph separator", with_cell(1, 2, "Rows" + chr(0x2029) + "give owners."), {"control"}),
    ("vertical tab", with_line(2, "Rules\x0bfollow."), {"control"}),
    ("trailing space", with_line(2, GOOD_LINES[2] + " "), {"trailing-ws"}),
    ("trailing tab", with_line(2, GOOD_LINES[2] + "\t"), {"trailing-ws", "control"}),
    ("no final newline", GOOD_TEXT[:-1], {"final-newline"}),
    ("two final newlines", GOOD_TEXT + "\n", {"final-newline", "trailing"}),
    ("lone surrogate", with_cell(1, 1, "Every \ud800 change."), {"encoding"}),
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
    ("arabic digit", with_cell(1, 0, "SD-R\u0661"), {"id"}),
    ("arabic second digit", with_cell(1, 0, "SD-R1\u0661"), {"id"}),
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
    ("source arabic digit", with_cell(1, 6, "spec §\u0668"), {"source"}),
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
        t = self.with_cell("SD-R7", 2, "Mending only one member " + why[why.index("of a class"):])
        self.assertNotEqual(t, self.text)
        self.assertEqual(rules_problems(t), [])
        self.assertEqual(all_content_problems(t), [])

    def test_real_file_has_no_content_problems(self):
        self.assertEqual(all_content_problems(self.text), [])


if __name__ == "__main__":
    unittest.main()
