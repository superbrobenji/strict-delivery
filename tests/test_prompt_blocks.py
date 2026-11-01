"""Tests for the prompt-block checker (tests/prose_check.py) and the worker blocks under skills/strict-delivery/prompts.
Oracle: the checker is run on the real files and on bad samples. Every bad sample is built here from a known-good block
written in this module (not read from disk) by exactly one mutation, and asserts the expected problem kind. The label,
required-content and forbidden tables are written out again below, not derived from the module under test."""
import os
import tempfile
import unittest

from tests import prose_check as pc
from tests.prose_check import (B_ROLES, DISPATCH_HEADINGS, LABELS, PROGRAM_ROLES, PROMPTS_DIR, REQUIRED, SPEC_ROLES,
                               STATUS_LINE, block_problems, dir_problems, forbidden_hits, labels, paragraph,
                               whole_token)

WRITTEN = ("implementer", "implementer_transcription", "investigator")   # extended by B1.2, B1.3
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
        bare_first =run("## Brief first. " + " ".join(ticked) + " fork")
        self.assertEqual(bare_first, [])
        swapped = run(" ".join([ticked[1], ticked[0]] + ticked[2:]) + " fork")
        self.assertEqual(swapped, ["required: Dispatch discipline. names the dispatch headings out of order"])


if __name__ == "__main__":
    unittest.main()
