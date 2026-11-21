"""Task P2.2 part c: the rows of task-P2.2-domain.md for ``breakdown.yml`` (BS1-BS16), ``breakdown_errors`` (BE3, BE25)
and ``plan_errors`` (PE5-PE9, PE11, PE12, PE18, PE20, PE21) that parts a and b left without a test (row ids in the
comments). Expected values are written by hand from the plan lines :2735-2743 and the table."""
import os
import time
import unittest

from gates.lib import config, schema, yamlsub
from gates.lib.breakdown import breakdown_errors, plan_errors
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, write_record
from tests.test_breakdown import row as brow, st
from tests.test_program_cli import PS, breakdown_row, run
from tests.test_program_merged import RECORD_BREAKDOWN


class BreakdownSchema(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        make_repo(self.work)
        self.cfg = config.load(self.work)
        self.sch = schema.schemas()["breakdown"]

    def errs(self, **kw):
        r = breakdown_row()
        for k, v in kw.items():
            if v is ...:
                del r[k]
            else:
                r[k] = v
        return schema.validate(self.sch, r, self.cfg)

    def bad(self, row, *needles):
        errs = schema.validate(self.sch, row, self.cfg)
        self.assertTrue(errs, row)
        for n in needles:
            self.assertTrue(any(n in e for e in errs), (n, errs))

    def test_schema_accepts_record(self):  # BS1
        self.assertEqual(self.errs(), [])
        self.assertEqual(schema.validate(self.sch, RECORD_BREAKDOWN, self.cfg), [])

    def test_schema_tag(self):  # BS2
        for tag in ("breakdown/2", "ledger/1", "breakdown/01", ...):
            with self.subTest(tag):
                self.bad(dict(breakdown_row(), **({"schema": tag} if tag is not ... else {})) if tag is not ... else
                         {k: v for k, v in breakdown_row().items() if k != "schema"}, "breakdown/1")

    def test_schema_unknown_keys(self):  # BS3
        r = breakdown_row()
        cases = [("extra", dict(r, extra=1)),
                 ("owner", dict(r, streams=[dict(r["streams"][0], owner="x")] + r["streams"][1:])),
                 ("since", dict(r, streams=[dict(r["streams"][0], paths=[{"path": "a/", "since": "x"}])] + r["streams"][1:])),
                 ("at", dict(r, streams=[dict(r["streams"][0], period={"from": "program-start", "until": "program-close",
                                                                       "at": "x"})] + r["streams"][1:])),
                 ("via", dict(r, edges=[{"from": "A1.1", "to": "B1.1", "via": "x"}])),
                 ("n", dict(r, groups=[{"id": "g", "tasks": ["A1.1"], "n": 1}]))]
        for key, bad in cases:
            with self.subTest(key):
                self.bad(bad, "unknown key", key)

    def test_plan_equals_folder_name(self):  # BS4: the schema checks only the type; `create` compares (CP3)
        self.assertEqual(self.errs(plan="other"), [])
        for v in (5, None, ...):
            with self.subTest(repr(v)):
                self.assertTrue(self.errs(plan=v))

    def test_limit_types_and_digits(self):  # BS5, BS15
        for field in ("max_concurrent", "max_depth"):
            for v, want in ((0, "at least 1"), (-1, "at least 1"), (True, "integer"), ("2", "integer"), (1.5, "integer"),
                            (None, "null")):
                with self.subTest(field, v=repr(v)):
                    self.bad(dict(breakdown_row(), **{field: v}), want)
            self.assertEqual(self.errs(**{field: 10 ** 999}), [])
            self.assertEqual(self.errs(**{field: 1}), [])
        text = "x: 1" + "0" * 999
        self.assertEqual(yamlsub.parse(text)["x"], 10 ** 999)
        for n in (1001, 4300, 4301):
            with self.subTest(n):
                with self.assertRaises(yamlsub.YamlError) as cm:
                    yamlsub.parse("x: 1" + "0" * (n - 1))
                self.assertIn("integer too large", cm.exception.reason)

    def test_done_forms(self):  # BS6
        self.assertEqual(self.errs(done=["A1.1"]), [])
        for v in (..., None, "x", [1]):
            with self.subTest(repr(v)):
                self.assertTrue(self.errs(done=v))

    def test_streams_shape(self):  # BS7
        self.bad(dict(breakdown_row(), streams=[]), "at least 1")
        self.bad(dict(breakdown_row(), streams=["x"]), "map")

    def test_stream_id_is_a_str_only(self):  # BS8: the grammar is breakdown_errors' (BE4), not the schema's
        r = breakdown_row()
        r["streams"][0]["id"] = "A"
        self.assertEqual(schema.validate(self.sch, r, self.cfg), [])
        r["streams"][0]["id"] = 5
        self.assertTrue(schema.validate(self.sch, r, self.cfg))

    def test_residual_and_paths(self):  # BS9, BS10
        base = breakdown_row()
        res = {"id": "r", "tasks": ["R1.1"], "unblock": "x", "residual": True}
        self.assertEqual(schema.validate(self.sch, dict(base, streams=base["streams"] + [res]), self.cfg), [])
        self.bad(dict(base, streams=base["streams"] + [dict(res, paths=["r/"])]))                 # residual with paths
        self.bad(dict(base, streams=base["streams"] + [dict(res, residual="yes")]), "true or false")
        self.bad(dict(base, streams=base["streams"] + [dict(res, residual=1)]), "true or false")
        a = base["streams"][0]
        for good in (["a/"], [{"path": "a/"}], [{"path": "a/", "from": "program-start", "until": "program-close"}],
                     ["a/", {"path": "b/"}]):
            with self.subTest(good=repr(good)):
                self.assertEqual(schema.validate(self.sch, dict(base, streams=[dict(a, paths=good)] + base["streams"][1:]),
                                                 self.cfg), [])
        for bad in ([], [{"from": "x"}], [{"path": "a/", "x": 1}], [["a/"]], [5], [None]):
            with self.subTest(bad=repr(bad)):
                self.bad(dict(base, streams=[dict(a, paths=bad)] + base["streams"][1:]))

    def test_period_schema(self):  # BS11
        base = breakdown_row()
        a = base["streams"][0]
        ok = {"from": "program-start", "until": "program-close"}
        self.assertEqual(schema.validate(self.sch, dict(base, streams=[dict(a, period=ok)] + base["streams"][1:]),
                                         self.cfg), [])
        for bad in ({"from": "program-start"}, {"until": "program-close"}, dict(ok, at="x"), None, "x"):
            with self.subTest(repr(bad)):
                self.bad(dict(base, streams=[dict(a, period=bad)] + base["streams"][1:]))

    def test_tasks_unblock_schema(self):  # BS12
        base = breakdown_row()
        a = base["streams"][0]
        for key, v in (("tasks", []), ("tasks", [5]), ("tasks", None), ("unblock", None), ("unblock", 5)):
            with self.subTest(key, v=repr(v)):
                self.bad(dict(base, streams=[dict(a, **{key: v})] + base["streams"][1:]))
        self.bad(dict(base, streams=[{k: v for k, v in a.items() if k != "unblock"}] + base["streams"][1:]), "unblock")
        self.bad(dict(base, streams=[dict(a, unblock="")] + base["streams"][1:]), "non-empty")

    def test_edges_groups_schema(self):  # BS13
        self.assertEqual(self.errs(edges=[]), [])
        self.assertTrue(self.errs(edges=...))
        self.bad(dict(breakdown_row(), edges=[{"from": "A1.1"}]), "to")
        self.bad(dict(breakdown_row(), groups=[]), "at least 1")
        self.bad(dict(breakdown_row(), groups=[{"id": "g", "tasks": []}]), "at least 1")

    def test_file_kinds_through_check_schema(self):  # BS14: the shared reader refuses what is not a regular, valid file
        commit_all(self.work, "base")
        path = os.path.join(self.work, PS, "p", "breakdown.yml")
        os.makedirs(os.path.dirname(path))
        good = yamlsub.emit(breakdown_row(plan="p"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(good)
        code, out, err = run("check", "schema", "--root", self.work)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS schema.breakdown", out)
        for name, data in (("nul", good.replace("a/", "a\0")), ("duplicate key", good + "plan: p\n"),
                           ("flow mapping", "{plan: p}\n"), ("empty", ""), ("invalid utf-8", b"\xff\xfe")):
            with self.subTest(name):
                with open(path, "wb") as fh:
                    fh.write(data if type(data) is bytes else data.encode("utf-8"))
                code, out, err = run("check", "schema", "--root", self.work)
                self.assertEqual(code, 1, out)
                self.assertIn("FAIL schema.breakdown", out)
        os.unlink(path)
        os.mkdir(path)
        self.assertEqual(run("check", "schema", "--root", self.work)[0], 1)                       # a directory
        os.rmdir(path)
        os.symlink(os.path.join(self.tmp, "elsewhere.yml"), path)
        self.assertEqual(run("check", "schema", "--root", self.work)[0], 1)                       # a symlink

    def test_breakdown_is_a_known_kind(self):  # BS16, D-Q20
        self.assertIn("breakdown", schema.KNOWN_KINDS)
        self.assertEqual(schema.KNOWN_KINDS.index("breakdown"), schema.KNOWN_KINDS.index("merged-log") + 1)
        self.assertIn("breakdown", schema.schemas())


class BreakdownErrorsC(unittest.TestCase):
    def test_never_raises_on_wrong_shapes(self):  # BE3
        for r in ({}, {"streams": None}, {"streams": "x"}, {"streams": [5]}, brow(edges="x"), brow(edges=[5]),
                  brow(groups="x"), brow(done=5), {"streams": [{"id": "a"}], "edges": [], "groups": [], "done": []}):
            with self.subTest(repr(r)[:40]):
                self.assertIsInstance(breakdown_errors(r), list)

    def test_scale(self):  # BE25: 200 streams, 2000 tasks, 5000 edges return in bounded time
        streams = [st("s%d" % i, ["T%d.%d" % (i, k) for k in range(10)]) for i in range(200)]
        edges = []
        for i in range(200):
            for k in range(10):
                for j in (i + 1, i + 2, i + 3):
                    if j < 200 and len(edges) < 5000:
                        edges.append({"from": "T%d.%d" % (i, k), "to": "T%d.%d" % (j, k)})
        self.assertGreater(len(edges), 4000)
        r = brow(*streams, edges=edges, groups=[{"id": "g", "tasks": ["T0.0"]}])
        t0 = time.time()
        errs = breakdown_errors(r)
        self.assertLess(time.time() - t0, 30)
        self.assertIsInstance(errs, list)


def suff(text, **row):
    r = {"streams": [], "done": []}
    r.update(row)
    return [s for s, _ in plan_errors(text, r) if s.startswith("outline.") and not s.startswith(("outline.task",
                                                                                                  "outline.unplanned"))]


class PlanErrorsC(unittest.TestCase):
    def test_block_with_tasks_passes(self):  # PE5
        self.assertEqual(suff("## Block 2a:\n\n### Task 2a.1: x\n"), [])

    def test_block_needs_its_own_task_ids(self):  # PE6
        self.assertEqual(suff("## Block 2a:\n\n### Task 2b.1: x\n"), ["outline.block.2a"])
        self.assertEqual(suff("## Block 2a:\n\n### Task 2ab.1: x\n"), ["outline.block.2a"])   # a prefix of the id is no match

    def test_section_extent(self):  # PE7
        self.assertEqual(suff("## Block 2a:\n### Task 2a.1: x\n## Block 2b:\n"), ["outline.block.2b"])
        self.assertEqual(suff("## Block 2a:\n## Block 2b:\n### Task 2a.1: x\n"), ["outline.block.2a", "outline.block.2b"])
        self.assertEqual(suff("## Block 2a:\n### Task 2a.1: x\n#### Task 2a.2: y\n"), [])
        self.assertEqual(suff("## Block 2a:\n### Sub\n#### Task 2a.1: y\n"), [])          # a lower-level heading stays inside

    def test_umbrella_by_id_prefix(self):  # PE8
        ok = "## Block 2 (sub-blocks 2a, 2b)\n\n## Block 2a:\n### Task 2a.1: x\n\n## Block 2b:\n### Task 2b.1: y\n"
        self.assertEqual(suff(ok), [])
        self.assertEqual(suff(ok.replace("Task 2b.1", "Task 9.1")), ["outline.block.2", "outline.block.2b"])
        self.assertEqual(suff("## Block 2 (x)\n\n## Block 3:\n### Task 3.1: x\n"), ["outline.block.2"])   # no longer id
        self.assertEqual(suff("## Block 1c:\n### Task 1c.1: x\n\n## Block 1c0:\n\nprose\n"), ["outline.block.1c0"])
        self.assertEqual(suff("## Block 1d:\n\n## Block 1d2:\n### Task 1d2.1: x\n\n## Block 1d3:\n### Task 1d3.1: x\n"), [])
        self.assertEqual(suff("## Block 1d2:\n### Task 1d2.1: x\n\n## Block 1d:\n"), ["outline.block.1d"])   # only later blocks count

    def test_umbrella_by_sub_block_list(self):  # PE9
        head = "## Programs block (sub-blocks P1, P2)\n"
        body = "## Block P1:\n### Task P1.1: x\n## Block P2:\n### Task P2.1: y\n"
        later = '## Later blocks\n\n- **X.** Planned in full in section "%s" above.\n'
        text = body + head + later % head.strip()[3:]
        self.assertEqual(suff(text), [])
        self.assertEqual(suff(text.replace("Task P2.1", "Task Q.1")), ["outline.block.P2", "outline.later.1"])
        self.assertEqual(suff(text.replace("sub-blocks P1, P2", "sub-blocks P1, P9")), ["outline.later.1"])
        for lst in ("(sub-blocks )", "(sub-blocks P1-P2)", "(sub-blocks P1; P2)", "(sub-blocks P1,P2)"):
            with self.subTest(lst):
                h = "Programs block " + lst
                self.assertEqual(suff(body + "## " + h + "\n" + later % h), ["outline.later.1"])

    def test_heading_forms(self):  # PE11: a block heading is `## Block <id>:` or `## Block <id> (` at column 0
        for line in ("## Block 2a: x", "## Block 2a:x", "## Block 2a: ", "## Block 2a (x", "## Block 2a (sub-blocks 2a1)"):
            with self.subTest(line):
                self.assertEqual(suff(line + "\n"), ["outline.block.2a"])
        for line in ("## Block 2a", "## Block 2a.", "##  Block 2a:", "##Block 2a:", " ## Block 2a:", "## block 2a:",
                     "## Block \u00e9:", "## Block 2a_b:", "### Block 2a:"):
            with self.subTest(line[:25]):
                self.assertEqual(suff(line + "\n"), ["outline.structure"])

    def test_long_block_id_is_a_block(self):  # PE11: the id has no length cap (an id of 4301 characters is one id)
        self.assertEqual(suff("## Block " + "9" * 4301 + "x:\n"), ["outline.block." + "9" * 4301 + "x"])

    def test_stream_heading_forms(self):  # PE12
        t = "### Task 3a.1: x\n"
        for head in ("## Stream `runtime`, sub-block 3a (branch b)", "## Stream x, sub-block 3a"):
            with self.subTest(head):
                self.assertEqual(suff(head + "\n" + t), [])
        for head in ("## Stream x, sub-block 3a:", "## Stream x; sub-block 3a", "## Stream x sub-block 3a",
                     "## Stream x, sub-block 3a!"):
            with self.subTest(head):
                self.assertEqual(suff(head + "\n" + t), ["outline.structure"])

    def test_later_blocks_section_extent(self):  # PE18
        base = "## Block 2a:\n### Task 2a.1: x\n\n## Later blocks\n\n"
        self.assertEqual(suff(base + "- bad\n  - nested bad\n1. numbered bad\n## Other\n- after bad\n"),
                         ["outline.later.1"])
        self.assertEqual(suff(base + "\n\n- bad one\n\n- bad two\n"), ["outline.later.1", "outline.later.2"])
        self.assertEqual(suff("## Block 2a:\n### Task 2a.1: x\n"), [])                  # no section: no later line
        self.assertEqual(suff(base + "- bad\n## Later blocks\n- bad again\n"), ["outline.later.1", "outline.later.2"])

    def test_first_argument_forms(self):  # PE20
        class S(str):
            pass

        with self.assertRaises(ValueError):
            plan_errors(S("## Block 2a:\n"), {"streams": [], "done": []})
        self.assertEqual(suff("\ufeff## Block 2a:\n### Task 2a.1: x\n"), ["outline.structure"])   # a BOM spoils line 1
        self.assertEqual(suff("## Block 2a:\r\n### Task 2a.1: x\r\n"), [])      # CR is part of the heading text only
        t0 = time.time()
        big = "".join("## Block B%d:\n### Task B%d.1: x\n" % (i, i) for i in range(20000))
        self.assertEqual(suff(big), [])
        self.assertLess(time.time() - t0, 20)                                                       # linear, not quadratic

    def test_unicode_same_on_both(self):  # PE21, V2: ASCII classes only
        for ch in ("\u00e9", "\u0870", "\u2c2f", "\U0001fae8"):
            with self.subTest(hex(ord(ch))):
                self.assertEqual(suff("## Block %s:\n### Task %s.1: x\n" % (ch, ch)), ["outline.structure"])
                self.assertEqual(suff("## Block 2a: %s\n### Task 2a.1: %s\n" % (ch, ch)), [])


class DuplicateHeadings(unittest.TestCase):
    def test_duplicate_block_ids_and_texts(self):  # PE8, PE9: only later longer ids make an umbrella; a pointer needs every heading
        self.assertEqual(suff("## Block 1x:\n\nprose\n\n## Block 1x:\n### Task 1x.1: y\n"), ["outline.block.1x"])
        self.assertEqual(suff("## Block 1x:\n\n## Block 1x:\n\n"), ["outline.block.1x"])        # reported once
        text = ('## Block 2: same\n### Task 2.1: x\n\n## Block 2: same\n\nprose\n\n## Later blocks\n\n'
                '- **X.** Planned in full in section "Block 2: same" above.\n')
        self.assertEqual(suff(text), ["outline.block.2", "outline.later.1"])
