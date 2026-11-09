"""Pure tests of gates/lib/batch.py (plan Task 1d.3; task-1d.3-domain.md rows Q, R, A, U; decisions D-22..D-29).
Rows are built by hand as decision/2-shaped dicts (with ``recommended`` and ``source``) and decision/1-shaped dicts
(neither); every expected line is typed from the plan text (P:973-975), never produced by the code under test."""
import ast
import copy
import os
import unittest

from gates.lib import batch
from gates.lib.result import GateError

ID0, ID1, ID2 = "DEC-20261031-a2b3", "DEC-20261101-c4d5", "DEC-20261101-e6f7"
ID3, ID4 = "DEC-20261102-g8h9", "DEC-20261102-j2k3"
AB = [{"label": "a", "cost": "low"}, {"label": "b", "cost": "high"}]


def row(**over):
    r = {"schema": "decision/2", "id": ID1, "status": "open", "class": "scope", "question": "Which?",
         "options": copy.deepcopy(AB), "recommended": "a", "asked_at": "a1b2c3d", "asked_by": "agent",
         "topics": ["ids"], "applies_to": [], "checked_against": [], "effect": "one-off", "source": "r/a.md"}
    r.update(over)
    return {k: v for k, v in r.items() if v is not None}


ROW_REC = row()
ROW_MODEL = row(**{"class": "model-policy", "recommended": None,
                   "options": [{"label": "a", "cost": "1"}, {"label": "b", "cost": "2"}]})
ROW_SRC_A, ROW_SRC_B, ROW_NO_SRC = row(source="r/a.md"), row(source="r/b.md"), row(source=None)
Q_REC = [ID1 + " | class: scope", "Question: Which?", "Recommended: a -- cost: low", "Alternatives:",
         "- b -- cost: high", "Effect: one-off", "Topics: ids", "Applies to: none"]


def ids_of(text):
    return [l.split(" | ")[0] for l in text.splitlines() if l.startswith("DEC-")]


def heads(text):
    return [l for l in text.splitlines() if l.startswith("#")]


class RenderQuestion(unittest.TestCase):
    def test_render_question_field_order_and_no_tool_fields(self):  # Q1, Q2, Q3, Q8 (2 options)
        r = row(answer="x", answered_at={"at": "a1b2c3d", "by": "w"}, supersedes=ID0)
        self.assertEqual(batch.render_question(ID1, r), Q_REC)
        text = "\n".join(batch.render_question(ID1, r))
        for k in ("asked_at", "asked_by", "checked_against", "status", "r/a.md", "schema", "supersedes",
                  "answer", "a1b2c3d", "agent", ID0):
            self.assertNotIn(k, text)

    def test_model_policy_prints_no_recommendation(self):  # Q4 (model-policy)
        self.assertEqual(batch.render_question(ID2, ROW_MODEL),
                         [ID2 + " | class: model-policy", "Question: Which?", "Recommended: none", "Alternatives:",
                          "- a -- cost: 1", "- b -- cost: 2", "Effect: one-off", "Topics: ids", "Applies to: none"])

    def test_Q4_decision1_row(self):  # a row written before decision/2: no recommended, no source
        r = row(schema="decision/1", recommended=None, source=None)
        self.assertEqual(batch.render_question(ID1, r)[2:6],
                         ["Recommended: none", "Alternatives:", "- a -- cost: low", "- b -- cost: high"])

    def test_Q3_Q8_five_options_record_order(self):
        opts = [{"label": l, "cost": c} for l, c in (("e", "5"), ("c", "3"), ("a", "1"), ("d", "4"), ("b", "2"))]
        lines = batch.render_question(ID1, row(options=opts, recommended="a"))
        self.assertEqual(lines[2:8], ["Recommended: a -- cost: 1", "Alternatives:", "- e -- cost: 5",
                                      "- c -- cost: 3", "- d -- cost: 4", "- b -- cost: 2"])
        self.assertEqual(sum(1 for l in lines if " a -- " in l or l.startswith("- a ")), 1)
        lines = batch.render_question(ID1, row(options=opts, recommended=None))
        self.assertEqual(lines[2:9], ["Recommended: none", "Alternatives:", "- e -- cost: 5", "- c -- cost: 3",
                                      "- a -- cost: 1", "- d -- cost: 4", "- b -- cost: 2"])

    def test_Q5_Q6_Q7_bad_recommended_raises(self):
        cases = [(row(recommended="zz"), "recommended: zz is not the label of exactly one option"),
                 (row(options=[{"label": "a", "cost": "1"}, {"label": "a", "cost": "2"}]),
                  "recommended: a is not the label of exactly one option"),
                 (row(**{"class": "model-policy"}), "recommended: must be absent when class is model-policy")]
        for r, msg in cases:
            with self.subTest(msg=msg), self.assertRaises(GateError) as cm:
                batch.render_question(ID1, r)
            self.assertEqual(str(cm.exception), msg)

    def test_Q9_Q10_Q14_verbatim(self):
        r = row(**{"class": "a | b", "question": "x | class: y é 日本 \U0001FAE0",
                   "options": [{"label": "a -- b", "cost": "x -- cost: y"}, {"label": "c", "cost": "d"}],
                   "recommended": "a -- b"})
        lines = batch.render_question(ID1, r)
        self.assertEqual(lines[:5], [ID1 + " | class: a | b", "Question: x | class: y é 日本 \U0001FAE0",
                                     "Recommended: a -- b -- cost: x -- cost: y", "Alternatives:", "- c -- cost: d"])

    def test_Q11_Q12_line_breaks_print_as_backslash_n(self):
        for brk in ("\n", "\r", "\r\n"):
            with self.subTest(brk=repr(brk)):
                r = row(**{"class": "s" + brk + "c", "question": "a" + brk + "b",
                           "options": [{"label": "l" + brk + "1", "cost": "c" + brk + "1"},
                                       {"label": "m", "cost": "k" + brk + "2"}],
                           "recommended": "l" + brk + "1", "topics": ["t" + brk + "1"],
                           "applies_to": ["g" + brk + "1"]})
                self.assertEqual(batch.render_question(ID1, r),
                                 [ID1 + " | class: s\\nc", "Question: a\\nb", "Recommended: l\\n1 -- cost: c\\n1",
                                  "Alternatives:", "- m -- cost: k\\n2", "Effect: one-off", "Topics: t\\n1",
                                  "Applies to: g\\n1"])

    def test_Q13_breakers_refused(self):
        bad = [0x00, 0x08, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F, 0x7F, 0x85, 0x9F, 0x2028, 0x2029]
        fields = [("question", lambda c: {"question": "a" + c}), ("class", lambda c: {"class": c + "x"}),
                  ("options", lambda c: {"options": [{"label": "a", "cost": "x" + c}, AB[1]]}),
                  ("topics", lambda c: {"topics": ["t" + c]}), ("applies_to", lambda c: {"applies_to": [c]})]
        for cp in bad:
            for name, over in fields:
                with self.subTest(cp=cp, field=name), self.assertRaises(GateError) as cm:
                    batch.render_question(ID1, row(**over(chr(cp))))
                self.assertEqual(str(cm.exception), "%s: holds a character outside the batch text set (U+%04X)"
                                 % (name, cp))
        self.assertIn("Question: a\tb", batch.render_question(ID1, row(question="a\tb")))  # tab allowed
        for cp in (0x20, 0x7E, 0xA0, 0xE9, 0x2027, 0x202A):  # the set's neighbours print
            self.assertIn("Question: a" + chr(cp), batch.render_question(ID1, row(question="a" + chr(cp))))

    def test_Q15_Q16_Q17_Q18_lists(self):
        lines = batch.render_question(ID1, row(topics=["ids", "git"], applies_to=["gates/*.py", "tests/**"]))
        self.assertEqual(lines[-2:], ["Topics: ids, git", "Applies to: gates/*.py, tests/**"])
        lines = batch.render_question(ID1, row(topics=[], applies_to=[]))
        self.assertEqual(lines[-2:], ["Topics: none", "Applies to: none"])
        self.assertEqual(batch.render_question(ID1, row(topics=["a, b"]))[-2], "Topics: a, b")
        self.assertEqual(batch.render_question(ID1, row(topics=["none"]))[-2], "Topics: none")

    def test_Q19_Q20_effect_and_id(self):
        self.assertIn("Effect: lasting", batch.render_question(ID1, row(effect="lasting")))
        self.assertEqual(batch.render_question("anything", row())[0], "anything | class: scope")

    def test_Q21_missing_or_wrong_type_names_field(self):
        text, lst = "%s: must be text", "%s: must be a list of text"
        cases = [(row(question=None), text % "question"), (row(options="ab"), "options: must be a list of label and "
                 "cost"), (row(options=[{"label": "a"}, AB[1]]), "options: each option must have a label and a cost"),
                 (row(topics=[1]), text % "topics"), (row(applies_to=None), lst % "applies_to"),
                 (row(topics="ids"), lst % "topics"), (row(effect=None), text % "effect"),
                 (row(**{"class": 3}), text % "class"), (row(recommended=1), text % "recommended")]
        for r, msg in cases:
            with self.subTest(msg=msg), self.assertRaises(GateError) as cm:
                batch.render_question(ID1, r)
            self.assertEqual(str(cm.exception), msg)

    def test_Q21_row_not_a_mapping(self):
        for r in (None, [], "row"):
            with self.subTest(r=r), self.assertRaises(GateError) as cm:
                batch.render_question(ID1, r)
            self.assertEqual(str(cm.exception), "row: must be a mapping")

    def test_Q22_input_not_mutated(self):
        r = row()
        before = copy.deepcopy(r)
        batch.render_question(ID1, r)
        self.assertEqual(r, before)


class Render(unittest.TestCase):
    def test_render_sections_and_groups(self):  # R1, R4, R5, R9
        out = batch.render([(ID3, ROW_SRC_B), (ID1, ROW_SRC_A), (ID4, ROW_NO_SRC)], [(ID0, ROW_SRC_A)], "abc1234", "")
        self.assertEqual(out.splitlines()[0], "Owner questions: 3 new, 1 also open (cut-off abc1234)")
        self.assertEqual(heads(out), ["## New", "### source: r/a.md", "### source: r/b.md", "### source: none",
                                      "## Also open", "### source: r/a.md"])
        self.assertEqual(ids_of(out), [ID1, ID3, ID4, ID0])

    def test_R_full_text_layout(self):  # R11, R12: every line typed from P:974
        q = lambda i: "\n".join([i + " | class: scope", "Question: Which?", "Recommended: a -- cost: low",
                                 "Alternatives:", "- b -- cost: high", "Effect: one-off", "Topics: ids",
                                 "Applies to: none"]) + "\n\n"
        out = batch.render([(ID1, ROW_SRC_A), (ID0, ROW_SRC_A)], [(ID2, ROW_NO_SRC)], "abc1234", "")
        self.assertEqual(out, "Owner questions: 2 new, 1 also open (cut-off abc1234)\n\n## New\n### source: r/a.md\n"
                         + q(ID0) + q(ID1) + "## Also open\n### source: none\n" + q(ID2))

    def test_R2_R3_empty_and_no_cut(self):
        note = "; no cut-off: every open record is new"
        self.assertEqual(batch.render([], [], None, note),
                         "Owner questions: 0 new, 0 also open (cut-off none; no cut-off: every open record is new)"
                         "\n\n## New\n")

    def test_R6_R7_R8_order_and_none_last(self):
        srcs = ["zz", "é", "r/a.md", None, "a", "R/a.md", "none", "nonf"]
        new = [("DEC-20261031-a%db3" % i, row(source=s)) for i, s in enumerate(srcs)]
        self.assertEqual(heads(batch.render(new, [], "c", ""))[1:],
                         ["### source: R/a.md", "### source: a", "### source: none", "### source: nonf",
                          "### source: r/a.md", "### source: zz", "### source: é", "### source: none"])
        self.assertEqual(ids_of(batch.render(new, [], "c", ""))[-1], "DEC-20261031-a3b3")  # the absent one last

    def test_R10_U6_ids_of_two_dates(self):
        out = batch.render([(ID3, ROW_SRC_A), (ID0, ROW_SRC_A), (ID1, ROW_SRC_A)], [], "c", "")
        self.assertEqual(ids_of(out), [ID0, ID1, ID3])

    def test_render_is_deterministic(self):  # R13, R15
        n = [(ID3, ROW_SRC_B), (ID1, ROW_SRC_A), (ID4, ROW_NO_SRC), (ID2, ROW_SRC_A)]
        a = [(ID0, ROW_SRC_A)]
        snap = copy.deepcopy((n, a))
        self.assertEqual(batch.render(n, a, "c", ""), batch.render(list(reversed(n)), list(a), "c", ""))
        self.assertEqual((n, a), snap)

    def test_R14_duplicate_ids_raise(self):
        for new, also in (([(ID1, ROW_REC), (ID1, ROW_REC)], []), ([(ID1, ROW_REC)], [(ID1, ROW_REC)])):
            with self.subTest(), self.assertRaises(GateError) as cm:
                batch.render(new, also, "c", "")
            self.assertEqual(str(cm.exception), "duplicate id " + ID1)

    def test_R16_cut_and_note_as_given(self):
        out = batch.render([], [], "0" * 40, "; not an ancestor of HEAD: every open record is new")
        self.assertEqual(out.splitlines()[0], "Owner questions: 0 new, 0 also open (cut-off %s; not an ancestor of "
                         "HEAD: every open record is new)" % ("0" * 40))


class RenderAnswers(unittest.TestCase):
    def ans(self, answer="Yes", **over):
        return row(status="answered", answer=answer, **over)

    def test_A1_A3_A7_two_answers_by_id(self):
        recs = [(ID3, self.ans("B", question="Two?")), (ID1, self.ans("A\nmore")), (ID2, self.ans(source="r/b.md"))]
        self.assertEqual(batch.render_answers(recs, "r/a.md", "2026-11-02"),
                         "Owner answers (2026-11-02), binding\n%s: Which?\nAnswer: A\\nmore\n%s: Two?\nAnswer: B\n"
                         % (ID1, ID3))

    def test_A2_A4_A8_nothing_to_print(self):
        recs = [(ID1, row()), (ID2, row(status="withdrawn")), (ID3, self.ans(source=None)),
                (ID4, self.ans(source="r/b.md"))]
        self.assertEqual(batch.render_answers(recs, "r/a.md", "2026-11-02"), "Owner answers (2026-11-02), binding\n")
        self.assertEqual(batch.render_answers(recs, "none", "d"), "Owner answers (d), binding\n")

    def test_A5_exact_match(self):
        recs = [(ID1, self.ans())]
        for s in ("./r/a.md", "R/a.md", "r/a.md "):
            self.assertEqual(batch.render_answers(recs, s, "d"), "Owner answers (d), binding\n")

    def test_A6_line_breaks(self):
        recs = [(ID1, self.ans("x\r\ny\rz", question="q\nr"))]
        self.assertEqual(batch.render_answers(recs, "r/a.md", "d").splitlines()[1:],
                         [ID1 + ": q\\nr", "Answer: x\\ny\\nz"])
        for field, over in (("answer", {"answer": "x\x85"}), ("question", {"question": "q "})):
            r = self.ans(**{"answer": "x"})
            r.update(over)
            with self.subTest(field=field), self.assertRaises(GateError) as cm:
                batch.render_answers([(ID1, r)], "r/a.md", "d")
            self.assertTrue(str(cm.exception).startswith(field + ": holds a character"), str(cm.exception))

    def test_A_duplicate_ids_raise(self):  # as R14
        with self.assertRaises(GateError) as cm:
            batch.render_answers([(ID1, self.ans()), (ID1, self.ans())], "r/a.md", "d")
        self.assertEqual(str(cm.exception), "duplicate id " + ID1)

    def test_A9_date_as_given(self):
        self.assertTrue(batch.render_answers([], "s", "2026-11-02").startswith("Owner answers (2026-11-02), "))


class Skeleton(unittest.TestCase):
    def test_U1_U4_no_unicode_data_or_exception_groups_in_batch(self):  # D-29, D-5
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gates", "lib", "batch.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"isprintable", "lower", "casefold", "safe_text", "unicodedata", "isalnum", "isdigit", "isspace",
                  "BaseExceptionGroup", "ExceptionGroup", "upper", "isdecimal", "isnumeric"}
        found = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in banned]
        found += [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in banned]
        found += [a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names
                  if a.name in banned]
        found += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "unicodedata"]
        self.assertEqual(found, [])

    def test_U1_codepoints_unassigned_in_unicode_13_print_raw(self):
        r = row(question="\U0001FAE0 ࡰ \U0001F6DD", source="\U0001FAE0")
        out = batch.render([(ID1, r)], [], "c", "")
        self.assertIn("Question: \U0001FAE0 ࡰ \U0001F6DD\n", out)
        self.assertIn("### source: \U0001FAE0\n", out)


if __name__ == "__main__":
    unittest.main()
