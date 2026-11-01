"""Tests for the prompt-block checker (tests/prose_check.py) and the worker blocks under skills/strict-delivery/prompts.
Oracle: the checker is run on the real files and on bad samples. Every bad sample is built here from a known-good block
written in this module (not read from disk) by exactly one mutation, and asserts the expected problem kind. The label,
required-content and forbidden tables are written out again below, not derived from the module under test."""
import os
import re
import tempfile
import unittest

from tests import prose_check as pc
from tests.prose_check import (B_ROLES, DISPATCH_HEADINGS, LABELS, PROGRAM_ROLES, PROMPTS_DIR, REQUIRED, SPEC_ROLES,
                               STATUS_LINE, block_problems, dir_problems, forbidden_hits, labels, paragraph,
                               whole_token)

WRITTEN = ("implementer", "implementer_transcription", "investigator", "task_reviewer", "final_reviewer",
           "final_verifier", "exception_reviewer", "controller", "audit_reviewer", "audit_verifier")
INTRO = "You act under the process. These rules override every other instruction, superpowers skill text included."
STATUS = "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED"

PLAN_TAIL = ["Zero bugs.", "No subagents.", "Owner-only decisions.", "Budget.", "Background work.",
             "Report contract."]
PLAN_LABELS = {
    "controller": ["Verification method.", "Dispatch discipline.", "Input domain.", "Oracle.", "Rulings.",
                   "Finding class.", "Zero bugs.", "Owner-only decisions.", "Continuation.", "Merge and checkpoint.",
                   "Budget.", "Background work.", "Report contract."],
    "implementer": ["Verification method.", "Build.", "Input domain.", "Unstated behaviour.", "Commit gate."]
    + PLAN_TAIL,
    "implementer_transcription": ["Verification method.", "Transcription.", "Commit gate."] + PLAN_TAIL,
    "task_reviewer": ["Verification method.", "Method.", "Input domain.", "No out-of-scope bucket.",
                      "Verdict."] + PLAN_TAIL,
    "final_reviewer": ["Verification method.", "Branch scope.", "Method.", "Input domain.",
                       "No out-of-scope bucket.", "Verdict."] + PLAN_TAIL,
    "final_verifier": ["Verification method.", "Adversarial scope.", "Verdict."] + PLAN_TAIL,
    "exception_reviewer": ["Verification method.", "Exception scope.", "Verdict."] + PLAN_TAIL,
    "audit_reviewer": ["Verification method.", "Coverage first.", "Method."] + PLAN_TAIL,
    "audit_verifier": ["Verification method.", "Method.", "Verdict."] + PLAN_TAIL,
    "investigator": ["Verification method.", "Read-only."] + PLAN_TAIL,
}
PLAN_REQUIRED = {
    "Verification method.": ["directly", "by contradiction", "Record both commands"],
    "Owner-only decisions.": ["decision_classes.owner_only", "NEEDS_DECISION", "at least two options"],
    "Report contract.": [STATUS],
    "Budget.": ["80 %"],
    "Background work.": ["reaps", "killed"],        # any one
    "Commit gate.": ["python3 -m gates run_all"],
    "Input domain.": ["input-domain table"],
    "Unstated behaviour.": ["NEEDS_DECISION", "mutant"],
    "No out-of-scope bucket.": ["class-narrowing question for the owner", "missing input-domain table is a finding"],
    "Oracle.": ["production path", "independent expected value"],
    "Finding class.": ["class: <dimension>: <members>"],
    "Continuation.": ["handoff", "BLOCKED: budget", "Nothing continues from inherited memory"],
    "Dispatch discipline.": ["`## Role`", "`## Brief`", "`## Findings`", "`## Claims`",
                             "`## Budget: tokens=<n> minutes=<n>`", "`## Model`", "`## Report`", "`## Strict block`",
                             "`## Task`", "fork"],
    "Read-only.": ["no tracked file"],
}
PLAN_HEADINGS = ["## Role", "## Brief", "## Findings", "## Claims", "## Budget: tokens=<n> minutes=<n>", "## Model",
                 "## Report", "## Strict block", "## Task"]

ALL_HEADINGS_TICKED = " ".join("`%s`" % h for h in PLAN_HEADINGS)
GOOD = {
    "Verification method.": "Verification method. Check each statement directly, then by contradiction. "
                            "Record both commands and their output.",
    "Dispatch discipline.": "Dispatch discipline. Send " + ALL_HEADINGS_TICKED + " in that order; a fork inherits.",
    "Build.": "Build. Write the test first and watch it fail.",
    "Transcription.": "Transcription. Copy the code the brief carries.",
    "Method.": "Method. Read the diff.",
    "Branch scope.": "Branch scope. Read the whole branch.",
    "Adversarial scope.": "Adversarial scope. Try to break it.",
    "Exception scope.": "Exception scope. Judge the exception.",
    "Coverage first.": "Coverage first. Count what was read.",
    "Read-only.": "Read-only. Leave no tracked file changed.",
    "Input domain.": "Input domain. Every row of the input-domain table has a test.",
    "Unstated behaviour.": "Unstated behaviour. Stop NEEDS_DECISION; write one mutant per condition.",
    "No out-of-scope bucket.": "No out-of-scope bucket. A seeming exclusion is a class-narrowing question for the "
                               "owner; a missing input-domain table is a finding.",
    "Oracle.": "Oracle. Run the production path and compare an independent expected value.",
    "Rulings.": "Rulings. Quote each ruling.",
    "Finding class.": "Finding class. Write class: <dimension>: <members> for each finding.",
    "Verdict.": "Verdict. Say approved or not.",
    "Commit gate.": "Commit gate. Run python3 -m gates run_all before each commit.",
    "Continuation.": "Continuation. Write the handoff, report BLOCKED: budget. Nothing continues from inherited memory.",
    "Merge and checkpoint.": "Merge and checkpoint. Merge only on a grant.",
    "Zero bugs.": "Zero bugs. None.",
    "No subagents.": "No subagents. None.",
    "Owner-only decisions.": "Owner-only decisions. For decision_classes.owner_only, stop NEEDS_DECISION with at least "
                             "two options.",
    "Budget.": "Budget. Stop at 80 % of a limit.",
    "Background work.": "Background work. Each job reaps or is killed.",
    "Report contract.": "Report contract. Start with " + STATUS + " as the first line.",
}


def good_lines(role):
    lines = ["# Strict block: " + role, "", INTRO]
    for lab in PLAN_LABELS[role]:
        lines += ["", GOOD[lab]]
    return lines


def join(lines):
    return "\n".join(lines) + "\n"


def good_text(role):
    return join(good_lines(role))


def good(role):
    return good_text(role).encode("ascii")


def kinds(raw, role="implementer"):
    return {p.split(":")[0] for p in block_problems(raw, role)}


def at(role, label):
    return good_lines(role).index(GOOD[label])


def make_dir(root, files):
    d = os.path.join(root, "prompts")
    os.mkdir(d)
    for name, raw in files.items():
        with open(os.path.join(d, name), "wb") as f:
            f.write(raw)
    return d


class ConstantsTest(unittest.TestCase):
    def test_role_sets_partition_spec_roles(self):          # K1
        self.assertEqual(SPEC_ROLES, (
            "program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
            "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer",
            "audit_verifier", "investigator"))
        self.assertEqual(len(SPEC_ROLES), 12)
        self.assertEqual(B_ROLES, SPEC_ROLES[2:])
        self.assertEqual(PROGRAM_ROLES, ("program_controller", "stream_controller"))
        self.assertTrue(set(B_ROLES) | set(PROGRAM_ROLES) == set(SPEC_ROLES) and not set(B_ROLES) & set(PROGRAM_ROLES))

    def test_labels_table(self):                              # K2
        self.assertEqual(set(LABELS), set(B_ROLES))
        self.assertEqual({k: list(v) for k, v in LABELS.items()}, PLAN_LABELS)

    def test_required_table(self):                            # K3
        got = {}
        for label, items in REQUIRED.items():
            flat = []
            for item in items:
                flat.extend(item if isinstance(item, tuple) else [item])
            got[label] = flat
        self.assertEqual(got, PLAN_REQUIRED)
        self.assertEqual(REQUIRED["Background work."], (("reaps", "killed"),))
        carried = {lab for row in LABELS.values() for lab in row}
        self.assertTrue(set(REQUIRED) <= carried, set(REQUIRED) - carried)

    def test_fixed_strings(self):                             # K4
        self.assertEqual(list(DISPATCH_HEADINGS), PLAN_HEADINGS)
        self.assertEqual(STATUS_LINE, STATUS)
        self.assertEqual(PROMPTS_DIR, "skills/strict-delivery/prompts")

    def test_real_dir_resolves_from_another_cwd(self):       # K4
        before = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                self.assertEqual(dir_problems(pc.prompts_dir(), WRITTEN), [])
                self.assertTrue(os.path.isabs(pc.prompts_dir()))
                self.assertTrue(pc.prompts_dir().endswith(PROMPTS_DIR.replace("/", os.sep)))
            finally:
                os.chdir(before)


class RealFilesTest(unittest.TestCase):
    def path(self, role):
        return os.path.join(pc.prompts_dir(), role + ".md")

    def test_written_roles_have_files(self):                  # S4
        for r in WRITTEN:
            self.assertTrue(os.path.isfile(self.path(r)) and not os.path.islink(self.path(r)), r)

    def test_no_stray_files(self):                            # S1
        names = os.listdir(pc.prompts_dir())
        self.assertTrue({n[:-3] for n in names} <= set(SPEC_ROLES), names)
        self.assertTrue(all(n.endswith(".md") for n in names), names)

    def test_dir_problems_empty(self):
        self.assertEqual(dir_problems(pc.prompts_dir(), WRITTEN), [])

    def test_format_every_present_block(self):                # W1, plan test_format_every_present_block
        for name in sorted(os.listdir(pc.prompts_dir())):
            role = name[:-3]
            with self.subTest(role=role):
                with open(self.path(role), "rb") as f:
                    raw = f.read()
                self.assertEqual(block_problems(raw, role), [])

    def test_labels_exact_and_ordered(self):
        for role in WRITTEN:
            with self.subTest(role=role):
                with open(self.path(role), "rb") as f:
                    text = f.read().decode("ascii")
                self.assertEqual(labels(text), PLAN_LABELS[role])

    def test_required_content(self):
        for role in WRITTEN:
            with open(self.path(role), "rb") as f:
                text = f.read().decode("ascii")
            for lab in PLAN_LABELS[role]:
                body = paragraph(text, lab)
                for s in PLAN_REQUIRED.get(lab, ()):
                    if lab == "Background work.":
                        continue
                    self.assertTrue(whole_token(s, body), (role, lab, s))
                if lab == "Background work.":
                    self.assertTrue(whole_token("reaps", body) or whole_token("killed", body), role)

    def test_no_forbidden_strings_in_blocks(self):
        for role in WRITTEN:
            with open(self.path(role), "rb") as f:
                self.assertEqual(forbidden_hits(f.read().decode("ascii")), [], role)

    def test_implementer_commit_gate_names_the_test_command(self):            # W2
        with open(self.path("implementer"), "rb") as f:
            body = paragraph(f.read().decode("ascii"), "Commit gate.")
        self.assertIn("`commands.test`", body)
        self.assertIn("`python3 -m gates run_all`", body)

    def test_transcription_stops_on_any_gap(self):            # W3
        with open(self.path("implementer_transcription"), "rb") as f:
            body = paragraph(f.read().decode("ascii"), "Transcription.")
        self.assertIn("Any gap", body)
        self.assertIn("stop with status NEEDS_DECISION", body)

    def test_investigator_cites_file_line(self):              # W4
        with open(self.path("investigator"), "rb") as f:
            body = paragraph(f.read().decode("ascii"), "Read-only.")
        self.assertIn("file:line", body)
        self.assertIn("no tracked file", body)


class GoodSampleTest(unittest.TestCase):
    def test_every_b_role_good_sample_passes(self):           # the oracle itself is satisfiable
        for role in B_ROLES:
            with self.subTest(role=role):
                self.assertEqual(block_problems(good(role), role), [])
                self.assertEqual(forbidden_hits(good_text(role)), [])

    def test_clean_lines_that_look_a_little_like_headings(self):   # P11, an empty line is not an underline
        lines = good_lines("implementer")
        i = at("implementer", "Build.")
        lines[i + 1:i + 1] = ["- item", "a=b", "--- x", "C# is fine here", "```"]
        self.assertEqual(block_problems(join(lines).encode("ascii"), "implementer"), [])


class FormatSamplesTest(unittest.TestCase):
    def expect(self, raw, expected, role="implementer"):
        got = kinds(raw, role)
        self.assertEqual(got, set(expected), block_problems(raw, role))

    # P1
    def test_encoding_cases(self):
        for name, ch in [("en dash", "\u2013"), ("curly quote", "\u2019"), ("nbsp", "\u00a0")]:
            with self.subTest(name):
                raw = good_text("implementer").replace("Write the test", "Write " + ch + " the test").encode("utf-8")
                self.expect(raw, {"encoding"})
        self.expect(b"\xef\xbb\xbf" + good("implementer"), {"encoding", "first-line"})
        raw = good("implementer").replace(b"Write the test", b"Write \xff the test")
        self.expect(raw, {"encoding"})
        self.assertIn("line 7", [p for p in block_problems(raw, "implementer") if "0xff" in p][0])

    # P2
    def test_control_characters(self):
        for name, ch in [("tab", "\t"), ("vt", "\x0b"), ("ff", "\x0c"), ("nul", "\x00"), ("esc", "\x1b"),
                         ("del", "\x7f")]:
            with self.subTest(name):
                raw = good_text("implementer").replace("Write the test", "Write" + ch + "the test").encode("latin-1")
                self.expect(raw, {"control"})

    # P3
    def test_line_endings(self):
        text = good_text("implementer")
        self.expect(text.replace("\n", "\r\n").encode("ascii"), {"line-ending"})
        self.expect(text.replace("Write the test", "Write\rthe test").encode("ascii"), {"line-ending"})
        self.expect(text.replace("\n", "\r\n", 1).encode("ascii"), {"line-ending"})
        self.assertIn("line-ending", kinds(text.replace("\n", "\r").encode("ascii")))

    # P4
    def test_final_newline(self):
        raw = good("implementer")
        self.expect(raw[:-1], {"final-newline"})
        self.expect(raw + b"\n", {"final-newline"})
        self.expect(raw + b"\n\n\n", {"final-newline"})
        self.assertIn("final-newline", kinds(b""))
        self.assertIn("first-line", kinds(b""))
        self.assertIn("first-line", kinds(b"\n"))

    # P5
    def test_truncated_files_return_problems(self):
        lines = good_lines("implementer")
        for n in (1, 2):
            with self.subTest(n):
                got = kinds(join(lines[:n]).encode("ascii"))
                self.assertIn("truncated", got)
                self.assertIn("labels", got)
        self.expect(join(lines[:3]).encode("ascii"), {"labels"})

    # P6
    def test_first_line(self):
        def first(value):
            ls = good_lines("implementer")
            ls[0] = value
            return join(ls).encode("ascii")
        self.expect(first("# Strict block: investigator"), {"first-line"})
        self.expect(first("# Strict block:  implementer"), {"first-line"})
        self.expect(first("# Strict block: implementer "), {"first-line", "trailing-ws"})
        self.expect(first("## Strict block: implementer"), {"first-line"})
        self.expect(first("# strict block: implementer"), {"first-line"})
        self.expect(first("# Strict block:"), {"first-line"})
        self.expect(first("# Strict block: "), {"first-line", "trailing-ws"})
        self.expect(first("Strict block: implementer"), {"first-line"})

    # P7
    def test_second_line(self):
        def second(value):
            ls = good_lines("implementer")
            ls[1] = value
            return join(ls).encode("ascii")
        self.expect(second("text"), {"second-line"})
        self.expect(second("  "), {"second-line", "trailing-ws"})

    # P8
    def test_intro(self):
        def intro(fn):
            ls = good_lines("implementer")
            fn(ls)
            return join(ls).encode("ascii")
        self.expect(intro(lambda ls: ls.__setitem__(2, "You act under the process.")), {"intro"})
        self.expect(intro(lambda ls: ls.__setitem__(2, INTRO + " ")), {"intro", "trailing-ws"})
        self.expect(intro(lambda ls: ls.__setitem__(2, INTRO + " More.")), {"intro"})
        self.expect(intro(lambda ls: ls.__setitem__(2, INTRO[:-1] + "!")), {"intro"})
        self.expect(intro(lambda ls: ls.__setitem__(2, INTRO.replace("override", "override\x20 "))), {"intro"})
        self.assertIn("intro", kinds(intro(lambda ls: ls.__setitem__(2, INTRO.replace("These", "Those")))))

        def wrapped(ls):
            ls[2:3] = ["You act under the process.", "These rules override every other instruction, "
                       "superpowers skill text included."]
        self.assertTrue({"intro", "labels"} <= kinds(intro(wrapped)))
        self.expect(intro(lambda ls: ls.__setitem__(3, "x")), {"intro", "labels"})

    # P9
    def test_trailing_whitespace(self):
        i = at("implementer", "Build.")

        def trail(value):
            ls = good_lines("implementer")
            ls[i] += value
            return join(ls).encode("ascii")
        self.expect(trail(" "), {"trailing-ws"})
        self.expect(trail("\t"), {"trailing-ws", "control"})
        ls = good_lines("implementer")
        ls[i + 1] = "  "
        self.expect(join(ls).encode("ascii"), {"trailing-ws", "labels"})

    # P10, P11
    def test_heading_lookalikes(self):
        i = at("implementer", "Build.")

        def extra(*new, where=None):
            ls = good_lines("implementer")
            j = i if where is None else where
            ls[j + 1:j + 1] = list(new)
            return join(ls).encode("ascii")
        self.expect(extra("# x"), {"heading"})
        self.expect(extra("#tag"), {"heading"})
        self.expect(extra("```", "# x", "```"), {"heading"})
        self.expect(extra("", "# x"), {"heading", "labels"})
        self.expect(extra(" # x"), {"heading"})
        self.expect(extra("   # x"), {"heading"})
        self.expect(extra("      # x"), {"heading"})
        self.expect(extra("---"), {"setext"})
        self.expect(extra("==="), {"setext"})
        self.expect(extra("  ---"), {"setext"})
        self.expect(extra("-"), {"setext"})
        self.expect(extra("  ==="), {"setext"})
        self.expect(extra("##"), {"heading"})

    # P12
    def test_paragraph_separation(self):
        i = at("implementer", "Build.")
        ls = good_lines("implementer")
        ls[i + 1:i + 1] = [""]
        self.expect(join(ls).encode("ascii"), {"paragraph-sep"})
        ls = good_lines("implementer")
        del ls[i + 1]
        self.expect(join(ls).encode("ascii"), {"labels"})
        ls = good_lines("implementer")
        ls[3:3] = [""]
        self.expect(join(ls).encode("ascii"), {"paragraph-sep"})

    # L1
    def test_label_list(self):
        i = at("implementer", "Build.")
        ls = good_lines("implementer")
        del ls[i - 1:i + 1]
        self.expect(join(ls).encode("ascii"), {"labels"})                       # one missing
        ls = good_lines("implementer")
        j = at("implementer", "Input domain.")
        ls[i], ls[j] = ls[j], ls[i]
        self.expect(join(ls).encode("ascii"), {"labels"})                       # two swapped
        ls = good_lines("implementer")
        ls[i + 1:i + 1] = ["", "Extra label. Text."]
        self.expect(join(ls).encode("ascii"), {"labels"})                       # one extra
        ls = good_lines("implementer")
        ls[i + 1:i + 1] = ["", GOOD["Build."]]
        self.expect(join(ls).encode("ascii"), {"labels"})                       # one duplicated

    # L2, L3
    def test_label_text(self):
        i = at("implementer", "Zero bugs.")
        for new in ["Zero bugs: None.", "zero bugs. None.", "Zero bugs.None.", "Zero bugs now. None."]:
            with self.subTest(new):
                ls = good_lines("implementer")
                ls[i] = new
                self.expect(join(ls).encode("ascii"), {"labels"})
        ls = good_lines("implementer")
        ls[i:i + 1] = ["Zero bugs.", "None."]
        self.expect(join(ls).encode("ascii"), {"labels"})
        ls = good_lines("implementer")
        ls[i] = "Zero bugs."
        self.expect(join(ls).encode("ascii"), {"labels"})
        ls = good_lines("implementer")
        ls[i] = "None at all"
        self.expect(join(ls).encode("ascii"), {"labels"})

    # R1
    def test_required_location(self):
        vm = at("implementer", "Verification method.")
        bd = at("implementer", "Build.")

        def run(fn):
            ls = good_lines("implementer")
            fn(ls)
            return join(ls).encode("ascii")
        self.expect(run(lambda ls: ls.__setitem__(vm, ls[vm].replace("Record both commands", "Record them"))),
                    {"required"})
        self.expect(run(lambda ls: (ls.__setitem__(vm, ls[vm].replace("Record both commands", "Record them")),
                                    ls.__setitem__(bd, ls[bd] + " Record both commands."))), {"required"})
        self.expect(run(lambda ls: (ls.__setitem__(vm, ls[vm].replace("Record both commands", "Record them")),
                                    ls.__setitem__(2, "Record both commands. " + INTRO))), {"required"})

    # R2, R3
    def test_required_wrap_case_spacing(self):
        def run(old, new, label="Verification method."):
            ls = good_lines("implementer")
            j = at("implementer", label)
            self.assertIn(old, ls[j])
            ls[j] = ls[j].replace(old, new)
            return join(ls).encode("ascii")
        self.expect(run("by contradiction", "by\ncontradiction"), {"required"})
        self.expect(run("directly", "Directly"), {"required"})
        self.expect(run("by contradiction", "By contradiction"), {"required"})
        self.expect(run("80 %", "80%", "Budget."), {"required"})
        self.expect(run("NEEDS_DECISION", "NEEDS DECISION", "Owner-only decisions."), {"required"})

    # R4
    def test_required_inside_longer_word(self):
        def run(old, new, label):
            ls = good_lines("implementer")
            j = at("implementer", label)
            self.assertIn(old, ls[j])
            ls[j] = ls[j].replace(old, new)
            return join(ls).encode("ascii")
        self.expect(run("directly", "indirectly", "Verification method."), {"required"})
        self.expect(run("directly", "directly-ish", "Verification method."), {"required"})
        self.expect(run("directly", "_directly", "Verification method."), {"required"})
        self.expect(run("reaps or is killed", "is unkilled", "Background work."), {"required"})
        self.expect(run("reaps or is killed", "reaps", "Background work."), set())

    # R5
    def test_report_contract(self):
        j = at("implementer", "Report contract.")

        def run(text):
            ls = good_lines("implementer")
            ls[j] = "Report contract. " + text
            return join(ls).encode("ascii")
        self.expect(run("Start with " + STATUS + " first."), set())
        self.expect(run("Start with STATUS_LINE first."), {"required"})
        self.expect(run("Start with status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED first."), {"required"})
        self.expect(run("Start with DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED first."), {"required"})

    # R6
    def test_background_work_either_word(self):
        j = at("implementer", "Background work.")

        def run(text):
            ls = good_lines("implementer")
            ls[j] = "Background work. " + text
            return join(ls).encode("ascii")
        self.expect(run("Each job reaps."), set())
        self.expect(run("Each job is killed."), set())
        self.expect(run("It reaps and is killed."), set())
        self.expect(run("Nothing is said."), {"required"})

    # R7
    def test_dispatch_discipline(self):
        role = "controller"
        j = at(role, "Dispatch discipline.")

        def run(text):
            ls = good_lines(role)
            ls[j] = "Dispatch discipline. " + text
            return join(ls).encode("ascii")
        ticked = ["`%s`" % h for h in PLAN_HEADINGS]
        self.expect(run(" ".join(ticked) + " fork"), set(), role)
        for k in range(len(ticked)):
            self.expect(run(" ".join(ticked[:k] + ticked[k + 1:]) + " fork"), {"required"}, role)
        self.expect(run(" ".join(ticked)), {"required"}, role)
        swapped = ticked[:]
        swapped[0], swapped[1] = swapped[1], swapped[0]
        self.expect(run(" ".join(swapped) + " fork"), {"required"}, role)
        self.expect(run(" ".join(ticked[:0] + [ticked[1], ticked[0]] + ticked[2:]) + " fork"), {"required"}, role)
        self.expect(run(" ".join(PLAN_HEADINGS) + " fork"), {"required"}, role)
        self.expect(run(" ".join(ticked[:1] + [PLAN_HEADINGS[1]] + ticked[2:]) + " fork"), {"required"}, role)
        self.expect(run(" ".join(swapped) + " then " + " ".join(ticked) + " fork"), {"required"}, role)

    # R8
    def test_required_runs_inside_block_problems(self):
        ls = good_lines("investigator")
        j = at("investigator", "Read-only.")
        ls[j] = "Read-only. Touch nothing."
        self.assertEqual(kinds(join(ls).encode("ascii"), "investigator"), {"required"})


class ArgumentsTest(unittest.TestCase):
    def test_unknown_and_program_roles(self):                 # A1, S5
        self.assertEqual(kinds(good("implementer"), "foo"), {"role"})
        self.assertEqual(kinds(good("implementer"), ""), {"role"})
        raw = (join(["# Strict block: program_controller", "", INTRO, "", "Verification method. x"])).encode("ascii")
        self.assertEqual(kinds(raw, "program_controller"), {"labels", "required"})
        self.assertEqual(kinds(good("investigator"), "implementer"), {"first-line", "labels"})
        self.assertIn("first-line", kinds(good("implementer"), "investigator"))

    def test_str_raises(self):                                # A2
        with self.assertRaises(TypeError):
            block_problems(good_text("implementer"), "implementer")
        with self.assertRaises(TypeError):
            block_problems(bytearray(good("implementer")), "implementer")


class LabelsParagraphTest(unittest.TestCase):
    HEAD = "# h\n\nintro\n\n"

    def test_labels_edge_cases(self):                         # L4, L5
        self.assertEqual(labels(self.HEAD + "E.g. one\n\nBudget. Stop at 80 %\n"), ["E.g.", "Budget."])
        self.assertEqual(labels(self.HEAD + "Budget. a\nsecond. line\nthird\n"), ["Budget."])
        self.assertEqual(labels(self.HEAD + "Zero bugs.\nmore\n\nplain\n"), ["", ""])
        self.assertEqual(labels(""), [])
        self.assertEqual(labels("# h\n\nintro\n"), [])

    def test_paragraph(self):                                 # L6
        text = self.HEAD + "Build. a\nline two\nline three\n\nBudget. b\n\nBuild. again\n"
        self.assertEqual(paragraph(text, "Budget."), "Budget. b")
        with self.assertRaises(ValueError):
            paragraph(text, "Build.")
        with self.assertRaises(ValueError):
            paragraph(text, "Absent.")
        self.assertEqual(paragraph(self.HEAD + "Build. a\nline two\nline three\n", "Build."),
                         "Build. a\nline two\nline three")


class WholeTokenTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertTrue(whole_token("directly", "do it directly, now"))
        self.assertTrue(whole_token("directly", "directly"))
        self.assertFalse(whole_token("directly", "indirectly"))
        self.assertFalse(whole_token("directly", "directlyx"))
        self.assertFalse(whole_token("directly", "directly-x"))
        self.assertFalse(whole_token("directly", "_directly"))
        self.assertFalse(whole_token("directly", "directly_"))
        self.assertFalse(whole_token("directly", "directly9"))
        self.assertTrue(whole_token("killed", "been killed."))
        self.assertFalse(whole_token("killed", "unkilled"))
        self.assertTrue(whole_token("killed", "unkilled and killed"))
        self.assertTrue(whole_token("`## Role`", "x `## Role` y"))
        self.assertFalse(whole_token("a", ""))


class ForbiddenTest(unittest.TestCase):
    POSITIVE = [("lap-timer", "the lap timer repo"), ("old-decision-number", "per DEC-7"),
                ("spec-clause", "spec D99"), ("row-id", "row X9-ABC-1"), ("old-paths", "tools/gates/x"),
                ("owner-handle", "ask superbrobenji"), ("hardware", "flash the board"),
                ("model-name", "use Opus"), ("old-steps", "S1 block b3"),
                ("model-name", "opus4"), ("model-name", "sonnet45"), ("hardware", "esp32s3"),
                ("hardware", "flashed it"), ("lap-timer", "lap_timer")]

    def test_forbidden_list_self_check(self):                 # F1, F5
        for name, sample in self.POSITIVE:
            with self.subTest(sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], [name])
        for sample, name in [("flashes", "hardware"), ("lap-timer", "lap-timer"), ("lapTimer", "lap-timer"),
                             ("docs/superpowers/x", "old-paths"), ("run_all.py", "old-paths"),
                             ("umbrella plan", "old-paths"), ("benji", "owner-handle"),
                             ("esp-idf", "hardware"), ("firmware", "hardware"), ("serial port", "hardware"),
                             ("ota", "hardware"), ("power of 10", "hardware"), ("p10", "hardware"),
                             ("unity", "hardware"), ("haiku", "model-name"), ("sonnet", "model-name"),
                             ("fable", "model-name"), ("DEC-1234", "old-decision-number"), ("D1", "spec-clause"),
                             ("D999", "spec-clause"), ("A1-B-1", "row-id"), ("Z12-ABC-345", "row-id")]:
            with self.subTest(sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], [name])

    def test_negative_samples(self):                          # F2
        for clean in ["DEC-20261031-k3f9", "a D alone", "opusculum", "dock the window", "tier3", "DEC-12345",
                      "D1000", "otamatone", "unity5x", "lap and timer", "Sonneteer"]:
            with self.subTest(clean):
                self.assertEqual(forbidden_hits(clean), [])

    def test_case(self):                                      # F3
        for sample, name in [("OPUS", "model-name"), ("Lap Timer", "lap-timer"), ("ESP32", "hardware"),
                             ("Benji", "owner-handle"), ("dec-7", "old-decision-number"),
                             ("S1 BLOCK B3", "old-steps")]:
            with self.subTest(sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], [name])
        for sample in ["d12", "x9-abc-1", "d1"]:
            with self.subTest(sample):
                self.assertEqual(forbidden_hits(sample), [])

    def test_position_and_multiplicity(self):                 # F4
        self.assertEqual(forbidden_hits("Opus here"), [("model-name", 1, "Opus")])
        self.assertEqual(forbidden_hits("clean\nclean\nthe lap timer"), [("lap-timer", 3, "lap timer")])
        self.assertEqual(forbidden_hits("Opus and lap timer"), [("model-name", 1, "Opus"), ("lap-timer", 1, "lap timer")])
        self.assertEqual(forbidden_hits("lap timer and Opus"), [("lap-timer", 1, "lap timer"), ("model-name", 1, "Opus")])
        self.assertEqual(forbidden_hits("Opus Opus"), [("model-name", 1, "Opus"), ("model-name", 1, "Opus")])
        self.assertEqual(forbidden_hits("a Opus\nb Haiku"), [("model-name", 1, "Opus"), ("model-name", 2, "Haiku")])
        self.assertEqual(forbidden_hits("ok\nok\nuse Fable"), [("model-name", 3, "Fable")])
        self.assertEqual(forbidden_hits("Opus\n"), [("model-name", 1, "Opus")])
        self.assertEqual(forbidden_hits(""), [])

    def test_wrapped_phrases(self):                           # F6
        self.assertEqual([(h[0], h[1]) for h in forbidden_hits("x lap\ntimer y")], [("lap-timer", 1)])
        self.assertEqual(forbidden_hits("a\nb serial\nport c"), [("hardware", 2, "serial port")])
        self.assertEqual([(h[0], h[1]) for h in forbidden_hits("the umbrella\nplan")], [("old-paths", 1)])
        self.assertEqual([(h[0], h[1]) for h in forbidden_hits("z\npower of\n10")], [("hardware", 2)])
        self.assertEqual([(h[0], h[1]) for h in forbidden_hits("S1 block\nb3")], [("old-steps", 1)])
        self.assertEqual([(h[0], h[1]) for h in forbidden_hits("lap\ntimer\nlap\ntimer")],
                         [("lap-timer", 1), ("lap-timer", 3)])
        self.assertEqual(forbidden_hits("lap\n\ntimer"), [])
        self.assertEqual(forbidden_hits("serial\n\nport"), [])
        self.assertEqual(forbidden_hits("para one lap timer\nmore text"), [("lap-timer", 1, "lap timer")])
        self.assertEqual(forbidden_hits("more text\nlap timer"), [("lap-timer", 2, "lap timer")])
        self.assertEqual(forbidden_hits("lap\ntimer\nOpus"), [("lap-timer", 1, "lap timer"), ("model-name", 3, "Opus")])

    def test_line_splitting_is_lf_only(self):                 # F8
        for sep in ["\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\r"]:
            with self.subTest(repr(sep)):
                self.assertEqual(forbidden_hits("a" + sep + "b\nlap timer"), [("lap-timer", 2, "lap timer")])

    def test_scope_covers_every_present_block(self):          # F7
        with tempfile.TemporaryDirectory() as td:
            bad = good_text("implementer").replace("Write the test", "Write the lap timer test").encode("ascii")
            d = make_dir(td, {"implementer.md": bad, "program_controller.md": b"Opus\n"})
            problems = dir_problems(d, ("implementer",))
            self.assertTrue(any(p.startswith("implementer.md: forbidden lap-timer line 7") for p in problems), problems)
            self.assertTrue(any(p.startswith("program_controller.md: forbidden model-name line 1") for p in problems),
                            problems)


class FileSetTest(unittest.TestCase):
    def check(self, files, written=("implementer",), prep=None):
        with tempfile.TemporaryDirectory() as td:
            d = make_dir(td, files)
            if prep:
                prep(d, td)
            return dir_problems(d, written)

    def test_exact_names_only(self):                          # S1
        self.assertEqual(self.check({"implementer.md": good("implementer")}), [])
        for name in ["foo.md", "README.md", "implementer.txt", "implementer.MD", "implementer", "Implementer.md",
                     "implementer.md.md", ".md", "investigator.md ", "implementer.mdx"]:
            with self.subTest(name):         # alone in the directory, so a case-insensitive filesystem cannot merge it
                got = self.check({name: b"x\n"}, written=())
                self.assertEqual(len(got), 1, got)
                self.assertTrue(got[0].startswith("stray: " + name), got)

    def test_case_variant_alone_is_refused(self):             # S1, on any filesystem
        got = self.check({"Implementer.md": good("implementer")})
        self.assertTrue(any(p.startswith("stray: Implementer.md") for p in got), got)

    def test_hidden_and_editor_entries(self):                 # S2
        ok = {"implementer.md": good("implementer")}
        for name in [".DS_Store", ".gitkeep", ".implementer.md.swp", "implementer.md~"]:
            with self.subTest(name):
                got = self.check(dict(ok, **{name: b""}))
                self.assertEqual(len(got), 1, got)
                self.assertTrue(got[0].startswith("stray: " + name), got)

    def test_entry_kinds(self):                               # S3
        ok = good("implementer")

        def mk(kind):
            def prep(d, td):
                p = os.path.join(d, "investigator.md")
                outside = os.path.join(td, "outside.md")
                with open(outside, "wb") as f:
                    f.write(good("investigator"))
                if kind == "dir":
                    os.mkdir(p)
                elif kind == "link-inside":
                    os.symlink("implementer.md", p)
                elif kind == "link-outside":
                    os.symlink(outside, p)
                elif kind == "dangling":
                    os.symlink(os.path.join(td, "nowhere"), p)
                elif kind == "fifo":
                    os.mkfifo(p)
            return prep
        for kind in ["dir", "link-inside", "link-outside", "dangling", "fifo"]:
            with self.subTest(kind):
                got = self.check({"implementer.md": ok}, prep=mk(kind))
                self.assertEqual(got, ["kind: investigator.md is not a regular file"], got)
        # the same kinds on a written role: refused, and never reported as a pass
        got = self.check({}, prep=lambda d, td: os.mkdir(os.path.join(d, "implementer.md")))
        self.assertEqual(got, ["kind: implementer.md is not a regular file"])

    def test_written_and_unwritten_roles_missing(self):       # S4
        self.assertEqual(self.check({}, written=("implementer",)), ["missing: implementer.md"])
        self.assertEqual(self.check({"implementer.md": good("implementer")}, written=("implementer",)), [])
        self.assertEqual(self.check({"implementer.md": good("implementer")}, written=("implementer", "investigator")),
                         ["missing: investigator.md"])
        self.assertEqual(self.check({"implementer.md": good("implementer")}, written=("implementer",)), [])

    def test_program_role_file_is_format_checked(self):       # S5
        raw = join(["# Strict block: stream_controller", "", INTRO, "", "Zero bugs. None."]).encode("ascii")
        got = self.check({"stream_controller.md": raw}, written=())
        self.assertEqual(got, ["stream_controller.md: labels: role stream_controller has no LABELS row"])

    def test_format_errors_are_named_with_the_file(self):
        got = self.check({"implementer.md": good("implementer")[:-1]})
        self.assertEqual(got, ["implementer.md: final-newline: the file does not end with a newline"])

    def test_directory_itself(self):                          # S6
        with tempfile.TemporaryDirectory() as td:
            missing = os.path.join(td, "nope")
            got = dir_problems(missing, ("implementer",))
            self.assertEqual([p.split(":")[0] for p in got], ["directory", "missing"])
            afile = os.path.join(td, "afile")
            with open(afile, "wb") as f:
                f.write(b"x")
            self.assertEqual([p.split(":")[0] for p in dir_problems(afile, ("implementer",))], ["directory", "missing"])
            real = make_dir(td, {"implementer.md": good("implementer")})
            link = os.path.join(td, "link")
            os.symlink(real, link)
            got = dir_problems(link, ("implementer",))
            self.assertEqual([p.split(":")[0] for p in got], ["directory", "missing"])
            self.assertEqual(dir_problems(real, ("implementer",)), [])


class BoundaryTest(unittest.TestCase):
    """Edges of each pattern and of the line checks, one assertion per production condition."""

    def test_forbidden_word_boundaries(self):
        for clean in ["ADD12", "xD12", "Tools-gates", "xbenjix", "reflash", "botany", "xesp-idf", "spower of 10",
                      "sp10", "xunity", "Sonnetx"]:
            with self.subTest(clean):
                self.assertEqual(forbidden_hits(clean), [])
        for sample, name in [("Tools/Gates", "old-paths"), ("DOCS/SUPERPOWERS", "old-paths"),
                             ("RUN_ALL.PY", "old-paths"), ("UMBRELLA PLAN", "old-paths"),
                             ("S12 block b3", "old-steps"), ("S1 block b12", "old-steps"),
                             ("Row X12-AB-345", "row-id"), ("Z1-A-1", "row-id")]:
            with self.subTest(sample):
                self.assertEqual([h[0] for h in forbidden_hits(sample)], [name])

    def test_hit_column_orders_wrapped_hits(self):
        self.assertEqual(forbidden_hits("Opus and lap\ntimer"), [("model-name", 1, "Opus"), ("lap-timer", 1, "lap timer")])
        self.assertEqual(forbidden_hits("lap\ntimer and Opus x lap timer"),
                         [("lap-timer", 1, "lap timer"), ("model-name", 2, "Opus"), ("lap-timer", 2, "lap timer")])

    def test_whole_token_neighbour_case(self):
        self.assertFalse(whole_token("directly", "Xdirectly"))
        self.assertFalse(whole_token("directly", "directlyX"))
        self.assertFalse(whole_token("directly", "adirectly"))

    def test_label_may_start_at_column_zero_of_the_text(self):
        self.assertEqual(labels("# h\n\nintro\n\n. x\n"), ["."])

    def test_control_and_encoding_byte_edges(self):
        for byte, kind in [(b"\x01", "control"), (b"\x08", "control"), (b"\x09", "control"), (b"\x1f", "control"),
                           (b"\x20", None), (b"\x7e", None), (b"\x7f", "control"), (b"\x80", "encoding")]:
            raw = good("implementer").replace(b"Write the test", b"Write" + byte + b"the test")
            self.assertEqual(kinds(raw), {kind} if kind else set(), byte)

    def test_one_problem_per_kind_per_line(self):
        raw = good("implementer").replace(b"Write the test", b"Write\t\tthe\ttest")
        self.assertEqual([p for p in block_problems(raw, "implementer") if p.startswith("control")],
                         ["control: byte 0x09 on line 7"])

    def test_short_files(self):
        self.assertEqual(kinds(b"# Strict block: implementer\nx\n"), {"truncated", "labels"})
        self.assertEqual(kinds(("# Strict block: implementer\n\nbad\n").encode("ascii")), {"intro", "labels"})
        self.assertEqual(kinds(("# Strict block: implementer\nx\nbad\n").encode("ascii")),
                         {"second-line", "intro", "labels"})
        self.assertEqual(kinds(("# Strict block: implementer\n\n" + INTRO + "\nx\n").encode("ascii")),
                         {"intro", "labels"})

    def test_dispatch_order_messages(self):
        role = "controller"
        j = at(role, "Dispatch discipline.")
        ticked = ["`%s`" % h for h in PLAN_HEADINGS]

        def run(text):
            ls = good_lines(role)
            ls[j] = "Dispatch discipline. " + text
            return block_problems(join(ls).encode("ascii"), role)
        missing = run(" ".join(ticked[1:]) + " fork")
        self.assertEqual(missing, ["required: Dispatch discipline. lacks '`## Role`'"])
        self.assertEqual(run(" ".join(ticked[:2] + ticked[3:]) + " fork"),
                         ["required: Dispatch discipline. lacks '`## Findings`'"])
        bare_first = run("## Brief first. " + " ".join(ticked) + " fork")
        self.assertEqual(bare_first, [])
        swapped = run(" ".join([ticked[1], ticked[0]] + ticked[2:]) + " fork")
        self.assertEqual(swapped, ["required: Dispatch discipline. names the dispatch headings out of order"])


class FixRound1Test(unittest.TestCase):
    def body(self, role, label):
        with open(os.path.join(pc.prompts_dir(), role + ".md"), "rb") as f:
            return paragraph(f.read().decode("ascii"), label)

    def test_short_content_with_trailing_newlines_pins_kinds(self):        # F3, P4, P5
        probs = block_problems(b"\n\n\n", "implementer")
        self.assertEqual({p.split(":")[0] for p in probs}, {"final-newline", "truncated", "first-line", "labels"})
        self.assertTrue(any(p.startswith("truncated: 0 lines") for p in probs), probs)
        probs = block_problems(b"# Strict block: implementer\n\n\n\n", "implementer")
        self.assertEqual({p.split(":")[0] for p in probs}, {"final-newline", "truncated", "labels"})
        self.assertTrue(any(p.startswith("truncated: 1 lines") for p in probs), probs)
        self.assertEqual(kinds(b"\n"), {"truncated", "first-line", "labels"})
        self.assertEqual(kinds(b""), {"final-newline", "truncated", "first-line", "labels"})

    def test_report_contract_says_pick_one_value(self):                    # F1
        for role in WRITTEN:
            body = self.body(role, "Report contract.")
            self.assertIn("one value from `" + STATUS + "`", body, role)
            self.assertIn("for example `status: DONE`", body, role)
            self.assertNotIn("exactly `status", body, role)

    def test_investigator_report_file_is_the_one_write(self):              # F2
        body = self.body("investigator", "Read-only.")
        self.assertIn("except that you write the report file the dispatch's Report line names", body)
        self.assertIn("the one write you make", body)
        self.assertIn("no tracked file", body)

    def test_no_subagents_bans_agent_tasks_only(self):                     # Q-B11r-1
        for role in WRITTEN:
            if "No subagents." in LABELS[role]:                # the controller dispatches workers: it has no such label
                self.assertIn("Do not dispatch agents, workflows or other agent tasks", self.body(role, "No subagents."))
                self.assertNotIn("background", self.body(role, "No subagents."))
            self.assertIn("A job you start in the background is yours", self.body(role, "Background work."))


GATE = "python3 -m gates run_all"
STATUS_VALUES = {"DONE", "DONE_WITH_FINDINGS", "NEEDS_DECISION", "BLOCKED", "DENIED"}
EXC_PHRASES = ("one proposed exception", "`rule-override`", "only the proposal and its evidence", "playbook",
               "before the owner rules", "the evidence's own commands", "tier4", "top_tier_fallback")
# Unrelated-findings rule (owner Q-B12r-1): the status mapping, pinned in the Verdict of the three blocks
DONE_RULE = (("Verdict.", "the change itself holds no finding"), ("Verdict.", "Unrelated findings"),
             ("Verdict.", "does not by itself make the status DONE_WITH_FINDINGS"),
             ("Report contract.", "unrelated findings"),
             # F-B12rr-2: the subject of the rule, in Verdict. and in Zero bugs. (a reversed rule is refused)
             ("Verdict.", "did not cause"), ("Zero bugs.", "did not cause"), ("Zero bugs.", "Unrelated findings"),
             ("Zero bugs.", "the change caused is a finding"),
             ("Report contract.", "findings; unrelated findings"))
# F-B12rr2-1: routing in No out-of-scope bucket. (the two reviewers), by cause
OOS_RULE = (("No out-of-scope bucket.", "Unrelated findings"), ("No out-of-scope bucket.", "did not cause"),
            ("No out-of-scope bucket.", "one the change caused goes in findings"))
DONE_WITH_FINDINGS_WHEN = {"task_reviewer": "when the change itself holds a finding",
                           "final_reviewer": "when the change itself holds a finding",
                           "final_verifier": "when you broke the change itself"}
# Task B1.2 content table, written out here: role -> (paragraph label, string that must be a whole token in it)
B12_CONTENT = {
    "task_reviewer": [("Method.", GATE), ("Method.", "every claim")] + list(OOS_RULE)
    + list(DONE_RULE) + [("Verdict.", DONE_WITH_FINDINGS_WHEN["task_reviewer"])],
    "final_reviewer": [("Method.", GATE), ("Method.", "every claim"), ("Branch scope.", "whole branch")]
    + list(OOS_RULE) + list(DONE_RULE)
    + [("Verdict.", DONE_WITH_FINDINGS_WHEN["final_reviewer"])],
    "final_verifier": [("Adversarial scope.", GATE), ("Adversarial scope.", "tier4"),
                       ("Adversarial scope.", "top_tier_fallback")] + list(DONE_RULE)
    + [("Verdict.", DONE_WITH_FINDINGS_WHEN["final_verifier"])],
    "exception_reviewer": [("Exception scope.", s) for s in EXC_PHRASES],
}
B12_ROLES = tuple(B12_CONTENT)


def disk(role):
    with open(os.path.join(pc.prompts_dir(), role + ".md"), "rb") as f:
        return f.read().decode("ascii")


def content_problems(role, text):
    """The Task B1.2 checks, run on the real file and on mutated copies of it: each string a whole token in its
    named paragraph; tier4 only in the two top-tier blocks."""
    out = []
    for label, s in B12_CONTENT[role]:
        try:
            ok = whole_token(s, paragraph(text, label))
        except ValueError:
            ok = False
        if not ok:
            out.append("%s lacks %r" % (label, s))
    if role in ("task_reviewer", "final_reviewer") and whole_token("tier4", text):
        out.append("tier4 given to %s" % role)
    return out


def verdicts_differ(task_text, final_text):
    return paragraph(task_text, "Verdict.") != paragraph(final_text, "Verdict.")


def in_para(text, label, fn):
    p = paragraph(text, label)
    new = fn(p)
    assert new != p, (label, "mutation changed nothing")
    return text.replace(p, new)


def other_para(text, label, s, dest):
    """Move s out of paragraph `label` and into paragraph `dest`."""
    return in_para(in_para(text, label, lambda p: p.replace(s, "zzz")), dest, lambda p: p + " " + s)


class B12Test(unittest.TestCase):
    def test_real_files_pass_content_checks(self):            # C1 C2 C3 C6 C8 C9 C10
        for role in B12_ROLES:
            with self.subTest(role=role):
                self.assertEqual(content_problems(role, disk(role)), [])

    def test_reviewer_blocks_differ_in_scope(self):           # C3 C4
        t, f = disk("task_reviewer"), disk("final_reviewer")
        self.assertTrue(verdicts_differ(t, f))
        self.assertTrue(whole_token("whole branch", paragraph(f, "Branch scope.")))
        same = in_para(t, "Verdict.", lambda p: paragraph(f, "Verdict."))
        self.assertFalse(verdicts_differ(same, f))                                   # identical is refused
        self.assertTrue(verdicts_differ(in_para(f, "Verdict.", lambda p: p + "x"), f))       # one char passes
        self.assertTrue(verdicts_differ(in_para(f, "Verdict.", lambda p: p[:-1]), f))

    def test_gate_and_claim_rerun_in_named_paragraph(self):   # C1 C2
        for role, label in (("task_reviewer", "Method."), ("final_reviewer", "Method."),
                            ("final_verifier", "Adversarial scope.")):
            t = disk(role)
            with self.subTest(role=role, case="absent"):
                bad = in_para(t, label, lambda p: p.replace(GATE, "the gates"))
                self.assertIn("%s lacks %r" % (label, GATE), content_problems(role, bad))
            with self.subTest(role=role, case="only in another paragraph"):
                bad = other_para(t, label, GATE, "Verdict.")
                self.assertIn("%s lacks %r" % (label, GATE), content_problems(role, bad))
            with self.subTest(role=role, case="joined"):
                bad = in_para(t, label, lambda p: p.replace(GATE, GATE + "x"))
                self.assertIn("%s lacks %r" % (label, GATE), content_problems(role, bad))
            with self.subTest(role=role, case="substring elsewhere only"):
                bad = in_para(t, label, lambda p: p.replace(GATE, "xpython3 -m gates run_all"))
                self.assertIn("%s lacks %r" % (label, GATE), content_problems(role, bad))
            body = paragraph(t, label)
            sentence = [x for x in body.replace("\n", " ").split(". ") if GATE in x]      # not negated
            self.assertTrue(sentence and not re.search(r"\b(never|not|no|without|skip)\b", sentence[0]), role)
        for role in ("task_reviewer", "final_reviewer"):
            with self.subTest(role=role, case="every claim"):
                t = disk(role)
                for bad in (in_para(t, "Method.", lambda p: p.replace("every claim", "the claims")),
                            other_para(t, "Method.", "every claim", "Verdict."),
                            in_para(t, "Method.", lambda p: p.replace("every claim", "every claims"))):
                    self.assertIn("Method. lacks 'every claim'", content_problems(role, bad))

    def test_branch_scope_variants(self):                     # C3
        t = disk("final_reviewer")
        for new in ("whole branches", "whole  branch", "Whole branch", "wholebranch", "whole-branch"):
            with self.subTest(new):
                bad = in_para(t, "Branch scope.", lambda p: p.replace("whole branch", new))
                self.assertIn("Branch scope. lacks 'whole branch'", content_problems("final_reviewer", bad))
        bad = in_para(t, "Branch scope.", lambda p: p.replace("whole branch", "zzz"))
        self.assertIn("Branch scope. lacks 'whole branch'", content_problems("final_reviewer", bad))
        bad = other_para(t, "Branch scope.", "whole branch", "Verdict.")
        self.assertIn("Branch scope. lacks 'whole branch'", content_problems("final_reviewer", bad))

    def test_top_tier_named_tier4(self):                      # C6 C7 DB-2
        for role, label in (("final_verifier", "Adversarial scope."), ("exception_reviewer", "Exception scope.")):
            t = disk(role)
            want = "%s lacks 'tier4'" % label
            for name, new in (("absent", "zzz"), ("tier40", "tier40"), ("tier4x", "tier4x"), ("tier3", "tier3"),
                              ("tier-4", "tier-4"), ("Tier4", "Tier4"), ("_tier4", "_tier4")):
                with self.subTest(role=role, case=name):
                    self.assertIn(want, content_problems(role, in_para(t, label, lambda p: p.replace("tier4", new))))
            with self.subTest(role=role, case="elsewhere"):
                self.assertIn(want, content_problems(role, other_para(t, label, "tier4", "Verdict.")))
            with self.subTest(role=role, case="model name"):
                bad = in_para(t, label, lambda p: p.replace("tier4", "Opus"))
                self.assertIn(want, content_problems(role, bad))
                self.assertEqual({h[0] for h in forbidden_hits(bad)}, {"model-name"})
        for role in ("task_reviewer", "final_reviewer"):
            with self.subTest(role=role, case="tier4 not given"):
                self.assertFalse(whole_token("tier4", disk(role)))
                bad = in_para(disk(role), "Verdict.", lambda p: p + " tier4")
                self.assertEqual(content_problems(role, bad), ["tier4 given to " + role])

    def test_exception_scope_phrases(self):                   # C8 C9 C10 DB-5
        t = disk("exception_reviewer")
        for s in EXC_PHRASES:
            want = "Exception scope. lacks %r" % s
            with self.subTest(s=s, case="missing"):
                self.assertIn(want, content_problems("exception_reviewer",
                                                     in_para(t, "Exception scope.", lambda p: p.replace(s, "zzz"))))
            with self.subTest(s=s, case="misplaced"):
                self.assertIn(want, content_problems("exception_reviewer",
                                                     other_para(t, "Exception scope.", s, "Verdict.")))
            if s[0].isalnum() and s[-1].isalnum():
                with self.subTest(s=s, case="joined"):
                    bad = in_para(t, "Exception scope.", lambda p: p.replace(s, "x" + s + "x"))
                    self.assertIn(want, content_problems("exception_reviewer", bad))
        p = paragraph(t, "Exception scope.")
        self.assertIn("argue against", p)
        self.assertIn("read nothing outside", p)
        self.assertIn("re-run the evidence's own commands", p)
        self.assertIn("deviation a project playbook allows", p)
        self.assertIn("draft decision", p)

    def test_unrelated_findings_do_not_change_done(self):     # F-B12r-1, owner Q-B12r-1
        for role in ("task_reviewer", "final_reviewer", "final_verifier"):
            t = disk(role)
            rules = list(DONE_RULE) + [("Verdict.", DONE_WITH_FINDINGS_WHEN[role])] + (
                list(OOS_RULE) if role != "final_verifier" else [])
            for label, s in rules:
                want = "%s lacks %r" % (label, s)
                for name, bad in (("missing", in_para(t, label, lambda p: p.replace(s, "zzz"))),
                                  ("joined", in_para(t, label, lambda p: p.replace(s, s + "x"))),
                                  ("misplaced", other_para(t, label, s, "Budget." if label == "Zero bugs." else
                                                           "Zero bugs."))):
                    with self.subTest(role=role, s=s, case=name):
                        self.assertIn(want, content_problems(role, bad))
            v = paragraph(t, "Verdict.")
            self.assertNotIn("holds no finding", v.replace("the change itself holds no finding", ""))
            self.assertLess(v.index("Report status DONE when"), v.index("Unrelated findings"))
        # reproducer of the review: the old text, DONE on "the diff holds no finding", is refused
        old = in_para(disk("task_reviewer"), "Verdict.",
                      lambda p: p.replace("the change itself holds no finding", "the diff holds no finding"))
        self.assertIn("Verdict. lacks 'the change itself holds no finding'", content_problems("task_reviewer", old))
        self.assertNotIn("Unrelated findings", paragraph(disk("exception_reviewer"), "Verdict."))   # not a member

    def test_scope_paragraph_missing_is_a_check_failure(self):    # C8, label gone
        t = disk("exception_reviewer")
        bad = t.replace(paragraph(t, "Exception scope.") + "\n\n", "")
        self.assertIn("Exception scope. lacks 'tier4'", content_problems("exception_reviewer", bad))
        self.assertIn("labels", {p.split(":")[0] for p in block_problems(bad.encode("ascii"), "exception_reviewer")})

    def test_verdicts_name_only_status_values(self):          # C11, owner Q-B12-4
        for role in ("final_verifier", "exception_reviewer", "task_reviewer", "final_reviewer"):
            with self.subTest(role=role):
                v = paragraph(disk(role), "Verdict.")
                caps = set(re.findall(r"[A-Z][A-Z_]{2,}", v))
                self.assertTrue(caps and caps <= STATUS_VALUES, (caps, v))
                self.assertIn("status", v)
        for role in ("final_verifier", "exception_reviewer"):
            v = paragraph(disk(role), "Verdict.")
            self.assertIn("findings", v)
            for word in ("UPHOLD", "REJECT", "APPROVED"):
                self.assertNotIn(word, v)
        v = paragraph(disk("final_verifier"), "Verdict.") + " UPHOLD"
        self.assertFalse(set(re.findall(r"[A-Z][A-Z_]{2,}", v)) <= STATUS_VALUES)

    def test_four_files_missing_from_disk_are_refused(self):  # F1
        self.assertEqual(WRITTEN[:7], ("implementer", "implementer_transcription", "investigator", "task_reviewer",
                                       "final_reviewer", "final_verifier", "exception_reviewer"))
        for role in B12_ROLES:
            with self.subTest(role=role):
                with tempfile.TemporaryDirectory() as td:
                    files = {r + ".md": disk(r).encode("ascii") for r in WRITTEN if r != role}
                    d = make_dir(td, files)
                    self.assertEqual(dir_problems(d, WRITTEN), ["missing: %s.md" % role])

    def test_labels_mutated_per_file(self):                   # F2
        for role in B12_ROLES:
            t = disk(role)
            labs = list(LABELS[role])
            first, second = paragraph(t, labs[1]), paragraph(t, labs[2])
            cases = {
                "missing": t.replace(first + "\n\n", ""),
                "duplicated": t.replace(first, first + "\n\n" + first),
                "reordered": t.replace(first, "@@").replace(second, first).replace("@@", second),
                "renamed": t.replace(first, "Renamed." + first[len(labs[1]):]),
            }
            for name, bad in cases.items():
                with self.subTest(role=role, case=name):
                    self.assertNotEqual(bad, t)
                    self.assertIn("labels", kinds(bad.encode("ascii"), role))

    def test_required_strings_mutated_per_file(self):         # F3
        for role in B12_ROLES:
            t = disk(role)
            for label in LABELS[role]:
                for item in REQUIRED.get(label, ()):
                    alts = item if isinstance(item, tuple) else (item,)
                    gone = in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "zzz"))
                    joined = in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "x" + a))
                    for name, bad in (("missing", gone), ("inside a longer word", joined)):
                        with self.subTest(role=role, label=label, item=item, case=name):
                            self.assertIn("required", kinds(bad.encode("ascii"), role))

    def test_format_mutated_per_file(self):                   # F4
        for role in B12_ROLES:
            t = disk(role)
            b = t.encode("ascii")
            title = "# Strict block: " + role
            cases = [
                ("crlf", t.replace("\n", "\r\n").encode("ascii"), "line-ending"),
                ("no final newline", b[:-1], "final-newline"),
                ("two final newlines", b + b"\n", "final-newline"),
                ("en dash", t.replace("Zero bugs.", "Zero \u2013 bugs.").encode("utf-8"), "encoding"),
                ("tab", t.replace("Zero bugs.", "Zero\tbugs.").encode("ascii"), "control"),
                ("inner heading", t.replace("\n\nZero bugs.", "\n# x\n\nZero bugs.").encode("ascii"), "heading"),
                ("setext", t.replace("\n\nZero bugs.", "\n---\n\nZero bugs.").encode("ascii"), "setext"),
                ("trailing space", t.replace("\n\nZero bugs.", " \n\nZero bugs.").encode("ascii"), "trailing-ws"),
                ("title", t.replace(title, "## Strict block: " + role, 1).encode("ascii"), "first-line"),
            ]
            for name, raw, kind in cases:
                with self.subTest(role=role, case=name):
                    self.assertIn(kind, kinds(raw, role))
            with self.subTest(role=role, case="trailing space on a real line"):
                lines = t.split("\n")
                lines[2] += " "
                self.assertIn("trailing-ws", kinds("\n".join(lines).encode("ascii"), role))

    def test_forbidden_strings_in_each_file(self):            # F5
        samples = [("lap-timer", "the lap timer repo"), ("old-decision-number", "per DEC-7"), ("spec-clause", "spec D99"),
                   ("row-id", "row X9-ABC-1"), ("old-paths", "tools/gates/x"), ("owner-handle", "ask superbrobenji"),
                   ("hardware", "flash the board"), ("model-name", "use Opus"), ("old-steps", "S1 block b3"),
                   ("model-name", "sonnet45"), ("hardware", "esp32s3"), ("lap-timer", "lap_timer"),
                   ("lap-timer", "lap\ntimer"), ("hardware", "serial\nport")]
        for role in B12_ROLES:
            t = disk(role)
            self.assertEqual(forbidden_hits(t), [], role)
            for name, sample in samples:
                with self.subTest(role=role, sample=sample):
                    bad = in_para(t, "Zero bugs.", lambda p: p + " " + sample.replace("\n", " ")) if "\n" not in sample \
                        else in_para(t, "Zero bugs.", lambda p: p + " " + sample)
                    self.assertIn(name, [h[0] for h in forbidden_hits(bad)])
                    with tempfile.TemporaryDirectory() as td:
                        files = {r + ".md": disk(r).encode("ascii") for r in WRITTEN if r != role}
                        files[role + ".md"] = bad.encode("ascii")
                        got = dir_problems(make_dir(td, files), WRITTEN)
                        self.assertTrue(any(p.startswith(role + ".md: forbidden " + name) for p in got), got)


def _replace_all(p, alts, fn):
    for a in alts:
        p = p.replace(a, fn(a))
    return p


AUDIT_ROLES = ("audit_reviewer", "audit_verifier")
B13_ROLES = ("controller",) + AUDIT_ROLES
TRIAGE = ("the owner rules", "before any plan", "`triage`")                 # spec section 8, Q-B13-1 (a)
CTRL_FIX_LOOP = ("rounds 1-3", "rounds 4-5", "one tier up", "owner question")     # spec section 10, Q-B13-1 (a)
CTRL_HEADINGS = tuple("`%s`" % h for h in DISPATCH_HEADINGS)
RULING = "Ruling: what -- why -- cost if wrong -- spec cite"                  # spec section 7.1
# Task B1.3 content table, written out here: role -> (paragraph label, string that must be a whole token in it)
B13_CONTENT = {
    "controller": [("Dispatch discipline.", s) for s in CTRL_HEADINGS]
    + [("Dispatch discipline.", s) for s in ("fork dispatch is refused", "`models.tiers`", "`top_tier_roles`")]
    + [("Rulings.", RULING), ("Rulings.", "`rulings.max_per_block`")]
    + [("Continuation.", s) for s in CTRL_FIX_LOOP + ("handoff", "BLOCKED: budget",
                                                      "Nothing continues from inherited memory")]
    + [("Input domain.", "input-domain table"), ("Oracle.", "production path"),
       ("Oracle.", "independent expected value"), ("Finding class.", "class: <dimension>: <members>")],
    "audit_reviewer": [("Owner-only decisions.", s) for s in TRIAGE]
    + [("Coverage first.", "coverage list"), ("Coverage first.", "progress file")],
    "audit_verifier": [("Owner-only decisions.", s) for s in TRIAGE]
    + [("Method.", "every reproducer"), ("Method.", "coverage list"), ("Method.", "extends")],
}
VERDICT_PARA = {"controller": "Report contract.", "audit_verifier": "Verdict."}       # owner Q-B12-4 pattern


def b13_problems(role, text):
    """The Task B1.3 checks, run on the real file and on mutated copies of it. Never raises on a missing paragraph."""
    out = []
    for label, s in B13_CONTENT[role]:
        try:
            ok = whole_token(s, paragraph(text, label))
        except ValueError:
            ok = False
        if not ok:
            out.append("%s lacks %r" % (label, s))
    if role == "controller":
        try:
            at = [pc._find_token(h, paragraph(text, "Dispatch discipline.")) for h in CTRL_HEADINGS]
            if min(at) >= 0 and any(a > b for a, b in zip(at, at[1:])):
                out.append("Dispatch discipline. names the dispatch headings out of order")
        except ValueError:
            pass
    if role in AUDIT_ROLES and whole_token("tier4", text):
        out.append("tier4 given to " + role)
    if role in VERDICT_PARA:
        try:
            caps = set(re.findall(r"[A-Z][A-Z_]{2,}", paragraph(text, VERDICT_PARA[role])))
            if not caps or not caps <= STATUS_VALUES:
                out.append("%s names %r, not only STATUS_LINE values" % (VERDICT_PARA[role], sorted(caps)))
        except ValueError:
            out.append("%s is missing" % VERDICT_PARA[role])
    return out


def audit_methods_differ(reviewer_text, verifier_text):
    return paragraph(reviewer_text, "Method.") != paragraph(verifier_text, "Method.")


def b13_move(text, label, alts, dest):
    """Move every alternative that paragraph `label` holds as a whole token into paragraph `dest`."""
    for a in alts:
        if whole_token(a, paragraph(text, label)):
            text = other_para(text, label, a, dest)
    return text


def b13_swap(p, a, b):
    return p.replace(a, "@@").replace(b, a).replace("@@", b)


class B13Test(unittest.TestCase):
    def test_all_b_roles_written(self):                       # F1 F2, the plan's test
        self.assertEqual(sorted(WRITTEN), sorted(B_ROLES))
        self.assertEqual(WRITTEN[7:], ("controller", "audit_reviewer", "audit_verifier"))     # plan order
        for name, t in (("one dropped", WRITTEN[:-1]), ("one twice", WRITTEN + ("controller",)),
                        ("program role added", WRITTEN + ("program_controller",)),
                        ("one swapped for a program role", WRITTEN[:-1] + ("stream_controller",))):
            with self.subTest(name):
                self.assertNotEqual(sorted(t), sorted(B_ROLES))

    def test_real_files_pass_the_plan_tests_and_content_checks(self):    # C1 C2 C3 C5 C6 C7 C8 C9 C10 A1-A5 A7
        for role in B13_ROLES:
            with self.subTest(role=role):
                self.assertEqual(b13_problems(role, disk(role)), [])
                self.assertEqual(block_problems(disk(role).encode("ascii"), role), [])
        p = paragraph(disk("controller"), "Dispatch discipline.")                       # the plan's tests, in the plan's form
        at = [pc._find_token(h, p) for h in CTRL_HEADINGS]
        self.assertTrue(min(at) >= 0 and at == sorted(at) and whole_token("fork dispatch is refused", p))
        self.assertTrue(whole_token("`models.tiers`", p) and whole_token("`top_tier_roles`", p))
        c = paragraph(disk("controller"), "Continuation.")
        self.assertTrue(all(whole_token(s, c) for s in CTRL_FIX_LOOP))
        r = paragraph(disk("controller"), "Rulings.")
        self.assertTrue(whole_token(RULING, r) and whole_token("`rulings.max_per_block`", r))
        for role in AUDIT_ROLES:
            o = paragraph(disk(role), "Owner-only decisions.")
            self.assertTrue(all(whole_token(s, o) for s in TRIAGE), role)

    def test_every_content_string_absent_joined_wrapped_or_misplaced(self):     # C2 C3 C5 C6 C7 C8 C9 A1-A5
        for role in B13_ROLES:
            t = disk(role)
            for label, s in B13_CONTENT[role]:
                want = "%s lacks %r" % (label, s)
                cases = [("missing", in_para(t, label, lambda p: p.replace(s, "zzz"))),
                         ("joined", in_para(t, label, lambda p: p.replace(s, "x" + s + "x"))),
                         ("misplaced", other_para(t, label, s, "Zero bugs."))]
                if " " in s:
                    cases.append(("wrapped", in_para(t, label, lambda p: p.replace(s, s.replace(" ", "\n", 1)))))
                for name, bad in cases:
                    with self.subTest(role=role, label=label, s=s, case=name):
                        self.assertIn(want, b13_problems(role, bad))

    def test_dispatch_headings_missing_swapped_or_malformed(self):     # C1, M3
        t = disk("controller")
        for i, h in enumerate(CTRL_HEADINGS):
            with self.subTest(heading=h, case="missing"):
                bad = in_para(t, "Dispatch discipline.", lambda p: p.replace(h, "zzz"))
                self.assertIn("Dispatch discipline. lacks %r" % h, b13_problems("controller", bad))
                self.assertIn("required", kinds(bad.encode("ascii"), "controller"))
            with self.subTest(heading=h, case="without backticks"):
                bad = in_para(t, "Dispatch discipline.", lambda p: p.replace(h, h.strip("`")))
                self.assertIn("Dispatch discipline. lacks %r" % h, b13_problems("controller", bad))
            if i + 1 < len(CTRL_HEADINGS):
                with self.subTest(heading=h, case="swapped with the next"):
                    bad = in_para(t, "Dispatch discipline.", lambda p: b13_swap(p, h, CTRL_HEADINGS[i + 1]))
                    self.assertIn("Dispatch discipline. names the dispatch headings out of order",
                                  b13_problems("controller", bad))
                    self.assertIn("required", kinds(bad.encode("ascii"), "controller"))
        bad = in_para(t, "Dispatch discipline.", lambda p: p.replace("`## Budget: tokens=<n> minutes=<n>`", "`## Budget`"))
        self.assertIn("Dispatch discipline. lacks '`## Budget: tokens=<n> minutes=<n>`'", b13_problems("controller", bad))
        bad = in_para(t, "Dispatch discipline.", lambda p: p.replace("tokens=<n> minutes=<n>", "tokens=<n>"))
        self.assertIn("required", kinds(bad.encode("ascii"), "controller"))
        bad = in_para(t, "Dispatch discipline.", lambda p: p.replace("minutes=<n>", "minutes=5"))
        self.assertTrue(b13_problems("controller", bad))
        for i, h in enumerate(CTRL_HEADINGS):                       # the list in another paragraph only
            with self.subTest(heading=h, case="in another paragraph only"):
                bad = other_para(t, "Dispatch discipline.", h, "Zero bugs.")
                self.assertIn("Dispatch discipline. lacks %r" % h, b13_problems("controller", bad))
        for label in ("Dispatch discipline.",):                     # M3: a missing paragraph is a failed check, not an error
            bad = t.replace(paragraph(t, label) + "\n\n", "")
            self.assertIn("Dispatch discipline. lacks '`## Role`'", b13_problems("controller", bad))
            self.assertIn("labels", kinds(bad.encode("ascii"), "controller"))

    def test_fork_refusal_phrase(self):                          # C2
        t = disk("controller")
        p = paragraph(t, "Dispatch discipline.")
        self.assertTrue(whole_token("fork dispatch is refused", p))
        for name, new in (("only fork", "a fork inherits"), ("forks", "forks dispatch is refused"),
                          ("fork dispatch is refused-ish", "fork dispatch is refusedx"),
                          ("no refusal", "fork dispatch is allowed")):
            with self.subTest(name):
                bad = in_para(t, "Dispatch discipline.", lambda q: q.replace("fork dispatch is refused", new))
                self.assertIn("Dispatch discipline. lacks 'fork dispatch is refused'", b13_problems("controller", bad))
        self.assertIn("required", kinds(in_para(t, "Dispatch discipline.",
                                                lambda q: q.replace("fork dispatch is refused", "zzz").replace("fork", "zzz"))
                                        .encode("ascii"), "controller"))

    def test_tiers_not_models_in_controller_and_tier4_rule(self):    # C3 C4 F6 A6
        t = disk("controller")
        self.assertEqual(forbidden_hits(t), [])
        for model in ("Opus", "sonnet", "Haiku", "fable45"):
            with self.subTest(model=model):
                bad = in_para(t, "Dispatch discipline.", lambda p: p + " Use " + model + ".")
                self.assertEqual({h[0] for h in forbidden_hits(bad)}, {"model-name"})
        # C4: tier4 is neither required nor refused in the controller
        self.assertEqual(b13_problems("controller", in_para(t, "Dispatch discipline.", lambda p: p + " tier4")), [])
        self.assertEqual(b13_problems("controller", t), [])
        for role in AUDIT_ROLES:                                  # A6: refused in the audit blocks, wherever it is
            for label in ("Method.", "Zero bugs.", "Owner-only decisions."):
                with self.subTest(role=role, label=label):
                    self.assertFalse(whole_token("tier4", disk(role)))
                    bad = in_para(disk(role), label, lambda p: p + " tier4")
                    self.assertEqual(b13_problems(role, bad), ["tier4 given to " + role])
            bad = in_para(disk(role), "Method.", lambda p: p + " tier4x")
            self.assertEqual(b13_problems(role, bad), [])           # a longer word is not the tier

    def test_fix_loop_rounds_other_than_1_3_and_4_5(self):      # C6 C7
        t = disk("controller")
        for s, new in (("rounds 1-3", "rounds 1-2"), ("rounds 1-3", "rounds 1-30"), ("rounds 1-3", "round 1-3"),
                       ("rounds 1-3", "rounds 2-3"), ("rounds 4-5", "rounds 4-6"), ("rounds 4-5", "rounds 4-50"),
                       ("rounds 4-5", "round 4-5"), ("rounds 4-5", "rounds 5-5"), ("one tier up", "one tier down"),
                       ("one tier up", "one tier upx"), ("owner question", "owner questions")):
            with self.subTest(s=s, new=new):
                bad = in_para(t, "Continuation.", lambda p: p.replace(s, new))
                self.assertIn("Continuation. lacks %r" % s, b13_problems("controller", bad))
        for s in CTRL_FIX_LOOP:                                   # only in another paragraph, even whole-file present
            bad = other_para(t, "Continuation.", s, "Merge and checkpoint.")
            self.assertTrue(whole_token(s, bad))
            self.assertIn("Continuation. lacks %r" % s, b13_problems("controller", bad))

    def test_ruling_format_variants(self):                       # C5
        t = disk("controller")
        for name, new in (("one dash", "Ruling: what - why - cost if wrong - spec cite"),
                          ("en dash", "Ruling: what – why – cost if wrong – spec cite"),
                          ("reordered", "Ruling: why -- what -- cost if wrong -- spec cite"),
                          ("no colon", "Ruling what -- why -- cost if wrong -- spec cite")):
            with self.subTest(name):
                bad = in_para(t, "Rulings.", lambda p: p.replace(RULING, new))
                self.assertIn("Rulings. lacks %r" % RULING, b13_problems("controller", bad))
        bad = in_para(t, "Rulings.", lambda p: p.replace(RULING, RULING.replace("what -- why", "what\n-- why")))
        self.assertIn("Rulings. lacks %r" % RULING, b13_problems("controller", bad))
        bad = in_para(t, "Rulings.", lambda p: p.replace(RULING, RULING.replace("what -- why", "what\n--\nwhy")))
        self.assertIn("setext", kinds(bad.encode("ascii"), "controller"))             # F5
        bad = in_para(t, "Rulings.", lambda p: p.replace(RULING, "Ruling: what – why – cost if wrong – spec cite"))
        self.assertIn("encoding", kinds(bad.encode("utf-8"), "controller"))
        bad = in_para(t, "Rulings.", lambda p: p.replace("`rulings.max_per_block`", "rulings.max_per_block"))
        self.assertIn("Rulings. lacks '`rulings.max_per_block`'", b13_problems("controller", bad))

    def test_triage_variants(self):                              # A1 A2
        for role in AUDIT_ROLES:
            t = disk(role)
            for s, new in (("`triage`", "triage"), ("before any plan", "before any plans"),
                           ("before any plan", "before a plan"), ("the owner rules", "the reviewer rules"),
                           ("the owner rules", "the owner ruled")):
                with self.subTest(role=role, s=s, new=new):
                    bad = in_para(t, "Owner-only decisions.", lambda p: p.replace(s, new))
                    self.assertIn("Owner-only decisions. lacks %r" % s, b13_problems(role, bad))
            for s in TRIAGE:                                      # present elsewhere in the file only
                bad = other_para(t, "Owner-only decisions.", s, "Zero bugs.")
                self.assertTrue(whole_token(s, bad))
                self.assertIn("Owner-only decisions. lacks %r" % s, b13_problems(role, bad))
            o = paragraph(t, "Owner-only decisions.")
            self.assertTrue(all(whole_token(s, o) for s in ("decision_classes.owner_only", "NEEDS_DECISION",
                                                              "at least two options")))

    def test_coverage_and_method_variants(self):                 # A3 A4 A5
        t = disk("audit_reviewer")
        bad = other_para(t, "Coverage first.", "coverage list", "Method.")
        self.assertIn("Coverage first. lacks 'coverage list'", b13_problems("audit_reviewer", bad))
        bad = other_para(t, "Coverage first.", "progress file", "Method.")
        self.assertIn("Coverage first. lacks 'progress file'", b13_problems("audit_reviewer", bad))
        v = disk("audit_verifier")
        for new in ("reproducers", "every reproducers", "the reproducer", "each reproducer"):
            with self.subTest(new=new):
                bad = in_para(v, "Method.", lambda p: p.replace("every reproducer", new))
                self.assertIn("Method. lacks 'every reproducer'", b13_problems("audit_verifier", bad))
        bad = other_para(v, "Method.", "every reproducer", "Verdict.")
        self.assertIn("Method. lacks 'every reproducer'", b13_problems("audit_verifier", bad))
        self.assertIn("coverage list", paragraph(v, "Method."))
        bad = in_para(v, "Method.", lambda p: p.replace("extends", "replaces"))
        self.assertIn("Method. lacks 'extends'", b13_problems("audit_verifier", bad))

    def test_verdict_values_only_status_line(self):              # C10 A7
        for role, label in VERDICT_PARA.items():
            t = disk(role)
            v = paragraph(t, label)
            self.assertIn("status", v)
            for word in ("APPROVED", "UPHOLD", "PASS", "REJECT", "DONE_WITH_FINDING"):
                with self.subTest(role=role, word=word):
                    bad = in_para(t, label, lambda p: p + " Report " + word + ".")
                    self.assertTrue([x for x in b13_problems(role, bad) if "not only STATUS_LINE" in x])
            bad = t.replace(v, "")                                # the paragraph's label is gone
            self.assertNotEqual(bad, t)
            self.assertTrue([x for x in b13_problems(role, bad) if "is missing" in x or "lacks" in x])

    def test_audit_blocks_differ(self):                          # A8
        r, v = disk("audit_reviewer"), disk("audit_verifier")
        self.assertTrue(audit_methods_differ(r, v))
        same = in_para(r, "Method.", lambda p: paragraph(v, "Method."))
        self.assertFalse(audit_methods_differ(same, v))
        self.assertTrue(audit_methods_differ(in_para(v, "Method.", lambda p: p + "x"), v))
        self.assertTrue(audit_methods_differ(in_para(v, "Method.", lambda p: p[:-1]), v))
        self.assertNotEqual(r, v)

    def test_controller_required_paragraph_content(self):        # C8 C9 F4
        t = disk("controller")
        for label in ("Input domain.", "Oracle.", "Finding class.", "Continuation.", "Owner-only decisions.",
                      "Report contract.", "Verification method.", "Budget.", "Background work."):
            for item in REQUIRED[label]:
                alts = item if isinstance(item, tuple) else (item,)
                for name, bad in (("missing", in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "zzz"))),
                                  ("joined", in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "x" + a))),
                                  ("misplaced", b13_move(t, label, alts, "Zero bugs."))):
                    with self.subTest(label=label, item=item, case=name):
                        self.assertIn("required", kinds(bad.encode("ascii"), "controller"))

    def test_no_reuse_of_b12_helpers(self):                      # X2 X3: the B1.2 helpers are defined once
        import ast
        with open(os.path.join(pc.REPO_ROOT, "tests", "test_prompt_blocks.py"), "rb") as f:
            tree = ast.parse(f.read())
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        for name in ("disk", "in_para", "other_para", "content_problems", "verdicts_differ"):
            self.assertEqual(names.count(name), 1, name)
        assigned = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        for name in ("GATE", "STATUS_VALUES", "WRITTEN", "B12_ROLES", "B12_CONTENT"):
            self.assertEqual(assigned.count(name), 1, name)
        self.assertEqual(content_problems("task_reviewer", disk("task_reviewer")), [])     # B1.2 function unchanged in use

    def test_three_files_missing_from_disk_are_refused(self):   # F1
        for role in B13_ROLES:
            with self.subTest(role=role):
                with tempfile.TemporaryDirectory() as td:
                    files = {r + ".md": disk(r).encode("ascii") for r in WRITTEN if r != role}
                    self.assertEqual(dir_problems(make_dir(td, files), WRITTEN), ["missing: %s.md" % role])

    def test_labels_mutated_per_file(self):                      # F3
        for role in B13_ROLES:
            t = disk(role)
            labs = list(LABELS[role])
            self.assertEqual(labels(t), labs)
            first, second = paragraph(t, labs[1]), paragraph(t, labs[2])
            cases = {
                "missing": t.replace(first + "\n\n", ""),
                "duplicated": t.replace(first, first + "\n\n" + first),
                "reordered": t.replace(first, "@@").replace(second, first).replace("@@", second),
                "renamed": t.replace(first, "Renamed." + first[len(labs[1]):]),
                "no full stop": t.replace(first, first.replace(labs[1], labs[1][:-1], 1)),
            }
            for name, bad in cases.items():
                with self.subTest(role=role, case=name):
                    self.assertNotEqual(bad, t)
                    self.assertIn("labels", kinds(bad.encode("ascii"), role))

    def test_required_strings_mutated_per_file(self):           # F4
        for role in AUDIT_ROLES:
            t = disk(role)
            for label in LABELS[role]:
                for item in REQUIRED.get(label, ()):
                    alts = item if isinstance(item, tuple) else (item,)
                    for name, bad in (("missing", in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "zzz"))),
                                      ("inside a longer word",
                                       in_para(t, label, lambda p: _replace_all(p, alts, lambda a: "x" + a))),
                                      ("only in another paragraph",
                                       b13_move(t, label, alts, "Zero bugs." if label != "Zero bugs." else "Budget."))):
                        with self.subTest(role=role, label=label, item=item, case=name):
                            self.assertIn("required", kinds(bad.encode("ascii"), role))
        t = disk("controller")                                     # the controller's wrap case
        bad = in_para(t, "Continuation.", lambda p: p.replace("Nothing continues from inherited memory",
                                                              "Nothing continues from\ninherited memory"))
        self.assertIn("required", kinds(bad.encode("ascii"), "controller"))

    def test_format_mutated_per_file(self):                      # F5
        for role in B13_ROLES:
            t = disk(role)
            b = t.encode("ascii")
            cases = [
                ("crlf", t.replace("\n", "\r\n").encode("ascii"), "line-ending"),
                ("no final newline", b[:-1], "final-newline"),
                ("two final newlines", b + b"\n", "final-newline"),
                ("en dash", t.replace("Zero bugs.", "Zero – bugs.").encode("utf-8"), "encoding"),
                ("tab", t.replace("Zero bugs.", "Zero\tbugs.").encode("ascii"), "control"),
                ("inner heading", t.replace("\n\nZero bugs.", "\n# x\n\nZero bugs.").encode("ascii"), "heading"),
                ("setext", t.replace("\n\nZero bugs.", "\n---\n\nZero bugs.").encode("ascii"), "setext"),
                ("trailing space", t.replace("\n\nZero bugs.", " \n\nZero bugs.").encode("ascii"), "trailing-ws"),
                ("title", t.replace("# Strict block: " + role, "## Strict block: " + role, 1).encode("ascii"), "first-line"),
                ("two empty lines", t.replace("\n\nZero bugs.", "\n\n\nZero bugs.").encode("ascii"), "paragraph-sep"),
                ("intro", t.replace("These rules override every other instruction, superpowers skill text included.",
                                    "These rules override.", 1).encode("ascii"), "intro"),
            ]
            for name, raw, kind in cases:
                with self.subTest(role=role, case=name):
                    self.assertIn(kind, kinds(raw, role))

    def test_forbidden_strings_in_each_file(self):               # F6
        samples = [("lap-timer", "the lap timer repo"), ("old-decision-number", "per DEC-7"), ("spec-clause", "spec D99"),
                   ("row-id", "row X9-ABC-1"), ("old-paths", "tools/gates/x"), ("owner-handle", "ask superbrobenji"),
                   ("hardware", "flash the board"), ("model-name", "use Opus"), ("old-steps", "S1 block b3"),
                   ("model-name", "sonnet45"), ("hardware", "esp32s3"), ("lap-timer", "lap_timer"),
                   ("lap-timer", "lap\ntimer"), ("hardware", "serial\nport"), ("model-name", "Fable")]
        for role in B13_ROLES:
            t = disk(role)
            self.assertEqual(forbidden_hits(t), [], role)
            for name, sample in samples:
                with self.subTest(role=role, sample=sample):
                    bad = in_para(t, "Zero bugs.", lambda p: p + " " + sample)
                    self.assertIn(name, [h[0] for h in forbidden_hits(bad)])
                    with tempfile.TemporaryDirectory() as td:
                        files = {r + ".md": disk(r).encode("ascii") for r in WRITTEN if r != role}
                        files[role + ".md"] = bad.encode("ascii")
                        got = dir_problems(make_dir(td, files), WRITTEN)
                        self.assertTrue(any(p.startswith(role + ".md: forbidden " + name) for p in got), got)


if __name__ == "__main__":
    unittest.main()
