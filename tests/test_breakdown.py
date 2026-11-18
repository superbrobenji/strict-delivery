"""Tests for gates.lib.breakdown (plan Task P2.2): ``breakdown_errors`` and ``plan_errors`` on hand-written rows and
plan texts. Expected values come from the plan lines :2736-2743, :2759 and the table task-P2.2-domain.md (row ids in
the comments)."""
import os
import unittest

from gates.lib import breakdown, checkpoints
from gates.lib.breakdown import breakdown_errors, plan_errors

PS = ".strict-delivery/state/plans"
PLAN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "strict-delivery",
                         "plans", "2026-10-31-strict-delivery-framework.md")


def st(sid, tasks, paths=("%s/",), residual=False, **kw):
    s = {"id": sid, "tasks": list(tasks), "unblock": "at program start"}
    if residual:
        s["residual"] = True
    else:
        s["paths"] = [p % sid if type(p) is str and "%s" in p else p for p in paths]
    s.update(kw)
    return s


def row(*streams, **kw):
    r = {"schema": "breakdown/1", "plan": "p", "max_concurrent": 3, "max_depth": 2, "done": [],
         "streams": list(streams) or [st("a", ["A1.1"]), st("b", ["B1.1"])], "edges": [],
         "groups": [{"id": "g", "tasks": ["A1.1"]}]}
    r.update(kw)
    return r


def suffixes(errs):
    return [s for s, _ in errs]


def paths_row(*paths):
    return row(st("a", ["A1.1"], paths=[paths[0]]), st("b", ["B1.1"], paths=[paths[1]]))


class BreakdownErrors(unittest.TestCase):
    def test_valid_rows_pass(self):  # BE1, BE20
        self.assertEqual(breakdown_errors(row()), [])
        rec = row(st("pkg", ["P1.1"], paths=["plugin.json", {"path": "reg.py", "until": "merged:resid"}]),
                  st("resid", ["R1.1"], residual=True), st("init4", ["I1.1"], paths=["reg.py"], period={
                      "from": "merged:resid", "until": "program-close"}),
                  edges=[{"from": "P1.1", "to": "R1.1"}], groups=[{"id": "g", "tasks": ["P1.1"]}])
        self.assertEqual(breakdown_errors(rec), [])

    def test_argument_types(self):  # BE2
        for bad in (None, [], "x"):
            with self.assertRaises(ValueError):
                breakdown_errors(bad)
        with self.assertRaises(ValueError):
            breakdown_errors(row(), plans={"a": 5})

    def test_cycle_found_and_named(self):  # BE19, plan test :2784
        r = row(st("a", ["A1.1", "A1.2", "A1.3"]), st("b", ["B1.1"]), edges=[
            {"from": "A1.1", "to": "A1.2"}, {"from": "A1.2", "to": "A1.1"}], groups=[{"id": "g", "tasks": ["B1.1"]}])
        self.assertTrue(any(s == "edges" and "A1.1 -> A1.2 -> A1.1" in m for s, m in breakdown_errors(r)))
        three = row(st("a", ["A1.1", "A1.2", "A1.3"]), edges=[{"from": "A1.1", "to": "A1.2"}, {"from": "A1.2", "to": "A1.3"},
                                                            {"from": "A1.3", "to": "A1.1"}])
        self.assertTrue(any("A1.1 -> A1.2 -> A1.3 -> A1.1" in m for _, m in breakdown_errors(three)))
        chain = [st("a", ["A%d.1" % i for i in range(5000)])]
        long = row(*chain, edges=[{"from": "A%d.1" % i, "to": "A%d.1" % (i + 1)} for i in range(4999)],
                   groups=[{"id": "g", "tasks": ["A0.1"]}])
        self.assertEqual(breakdown_errors(long), [])  # no RecursionError

    def test_subblock_cycle_refused(self):  # BE27, UR1, D-Q16
        r = row(st("s", ["x.1", "x.2"]), st("t", ["y.1"]), edges=[{"from": "x.1", "to": "y.1"}, {"from": "y.1", "to": "x.2"}],
                groups=[{"id": "g", "tasks": ["x.1"]}])
        got = [m for s, m in breakdown_errors(r) if s == "edges"]
        self.assertEqual(len(got), 1)
        self.assertIn("merged:s/x -> merged:t/y -> merged:s/x", got[0])
        ok = row(st("s", ["x.1", "x.2"]), st("t", ["y.1"]), edges=[{"from": "x.1", "to": "x.2"}],
                 groups=[{"id": "g", "tasks": ["x.1"]}])
        self.assertEqual(breakdown_errors(ok), [])  # a same-stream edge across sub-blocks is no merge order

    def test_edges_unknown_and_self(self):  # BE17, BE18
        for e in ({"from": "A1.1", "to": "zz.1"}, {"from": "zz.1", "to": "A1.1"}, {"from": "A1.1", "to": "A1.1"}):
            self.assertIn("edges", suffixes(breakdown_errors(row(edges=[e]))))

    def test_group_rules(self):  # BE21
        a, b, c = "A1.1", "A1.2", "A1.3"
        base = [st("a", [a, b, c]), st("b", ["B1.1"])]
        for name, groups, edges, kw in (
                ("unknown task", [{"id": "g", "tasks": ["zz.1"]}], [], {}),
                ("task in two groups", [{"id": "g", "tasks": [a]}, {"id": "h", "tasks": [a]}], [], {}),
                ("same id twice", [{"id": "g", "tasks": [a]}, {"id": "g", "tasks": [b]}], [], {}),
                ("dependent directly", [{"id": "g", "tasks": [a, b]}], [{"from": a, "to": b}], {}),
                ("dependent through a third", [{"id": "g", "tasks": [a, c]}], [{"from": a, "to": b}, {"from": b, "to": c}], {}),
                ("over max_concurrent", [{"id": "g", "tasks": [a, b, c]}], [], {"max_concurrent": 2})):
            with self.subTest(name):
                self.assertIn("groups", suffixes(breakdown_errors(row(*base, groups=groups, edges=edges, **kw))))
        self.assertEqual(breakdown_errors(row(*base, groups=[{"id": "g", "tasks": [a, b]}], max_concurrent=2)), [])

    def test_limit_types(self):  # BE22, BS5
        for k in ("max_concurrent", "max_depth"):
            for bad in (0, True, "2", -1, 1.5):
                with self.subTest((k, bad)):
                    self.assertIn("limits", suffixes(breakdown_errors(row(**{k: bad}))))

    def test_stream_and_task_rules(self):  # BE4-BE9
        cases = {
            "duplicate stream ids": row(st("a", ["A1.1"]), st("a", ["B1.1"], paths=["b/"])),
            "task in two streams": row(st("a", ["A1.1"]), st("b", ["A1.1"])),
            "task twice in a stream": row(st("a", ["A1.1", "A1.1"]), st("b", ["B1.1"])),
            "sub-block split": row(st("a", ["4c.1"]), st("b", ["4c.2"])),
            "no dot": row(st("a", ["x"]), st("b", ["B1.1"])),
            "bad prefix": row(st("a", ["a.b.c"]), st("b", ["B1.1"])),
            "two residual": row(st("a", ["A1.1"], residual=True), st("b", ["B1.1"], residual=True)),
            "residual with paths": row(dict(st("a", ["A1.1"], residual=True), paths=["a/"]), st("b", ["B1.1"])),
            "no paths": row(dict(st("a", ["A1.1"]), paths=[]), st("b", ["B1.1"])),
            "done and in a stream": row(done=["A1.1"]),
            "done and in an edge": row(done=["Z9.9"], edges=[{"from": "Z9.9", "to": "A1.1"}]),
            "done twice": row(done=["Z9.9", "Z9.9"]),
            "unknown stream bound": row(st("a", ["A1.1"], period={"from": "merged:zz/1", "until": "program-close"}), st("b", ["B1.1"])),
            "not an event": row(st("a", ["A1.1"], paths=[{"path": "a/", "from": "later"}]), st("b", ["B1.1"])),
            "never opens": row(st("a", ["A1.1"], period={"from": "program-close", "until": "program-start"}), st("b", ["B1.1"])),
            "same from and until": row(st("a", ["A1.1"], paths=[{"path": "a/", "from": "merged:b/B1", "until": "merged:b/B1"}]),
                                       st("b", ["B1.1"])),
        }
        for name, r in cases.items():
            with self.subTest(name):
                self.assertNotEqual(breakdown_errors(r), [])

    def test_task_and_sub_block_reasons_are_exact(self):  # BE5, BE6, Q-F80W-11 (a): each reason is the one named
        got = breakdown_errors(row(st("a", ["A1.1"]), st("b", ["A1.1"])))
        self.assertEqual([m for s, m in got if s == "tasks"], ["task A1.1 is in streams a and b", "sub-block A1 has tasks in streams a and b"])
        got = breakdown_errors(row(st("a", ["4c.1"]), st("b", ["4c.2"])))
        self.assertEqual([m for s, m in got if s == "tasks"], ["sub-block 4c has tasks in streams a and b"])
        ok = breakdown_errors(row(st("a", ["4c.1", "4c.2"]), st("b", ["B1.1"])))
        self.assertEqual([m for s, m in ok if s == "tasks"], [])

    def test_overlapping_paths(self):  # BE12, BE13, plan test :2788
        self.assertNotEqual(breakdown_errors(paths_row("a/", "a/b.py")), [])
        self.assertNotEqual(breakdown_errors(paths_row("a/", "a/")), [])
        self.assertEqual(breakdown_errors(paths_row("a", "ab")), [])
        self.assertEqual(breakdown_errors(paths_row("a/b", "a/b.py")), [])
        self.assertNotEqual(breakdown_errors(paths_row("A/", "a/b.py")), [])
        self.assertNotEqual(breakdown_errors(paths_row("caf\u00e9/", "cafe\u0301/b.py")), [])

    def test_overlap_windows(self):  # BE14, Q-F80-1 (a)
        def two(wa, wb, edges=None, extra_a=("A1.1",), extra_b=("B1.1",)):
            return row(st("a", extra_a, paths=[dict(path="x/", **wa)]), st("b", extra_b, paths=[dict(path="x/", **wb)]),
                       edges=edges or [])
        chained = two({"until": "merged:b/B1"}, {"from": "merged:b/B1"}, extra_a=("A1.1",))
        self.assertEqual(breakdown_errors(chained), [])  # one's until equals the other's from
        ordered = two({"until": "merged:a/A1"}, {"from": "merged:b/B1"}, [{"from": "A1.1", "to": "B1.1"}])
        self.assertEqual(breakdown_errors(ordered), [])
        reverse = two({"until": "merged:a/A1"}, {"from": "merged:b/B1"}, [{"from": "B1.1", "to": "A1.1"}])
        self.assertNotEqual(breakdown_errors(reverse), [])
        unordered = two({"until": "merged:a/A1"}, {"from": "merged:b/B1"})
        self.assertNotEqual(breakdown_errors(unordered), [])
        self.assertNotEqual(breakdown_errors(two({}, {})), [])  # whole program against whole program
        same_stream = two({"until": "merged:a/A2"}, {"from": "merged:b/B1"}, [{"from": "A1.2", "to": "B1.1"}],
                          extra_a=("A1.1", "A2.1", "A1.2"))
        self.assertNotEqual(breakdown_errors(same_stream), [])  # the path leaves A1 and A2 does not reach B1

    def test_plan_workspace_with_plans(self):  # BE15, Q-F80W-15 (a), Q-F80W-19 (a)
        plans = {"a": "a-plan", "b": "b-plan"}
        for p in (".strict-delivery/", PS + "/b-plan/x.md"):
            with self.subTest(p):
                r = row(st("a", ["A1.1"], paths=[p]), st("b", ["B1.1"]))
                self.assertNotEqual(breakdown_errors(r, plans=plans), [])
                self.assertEqual(breakdown_errors(r), [])
        self.assertEqual(breakdown_errors(row(), plans=plans), [])

    def test_window_defaults(self):  # BE16, Q-F80r-1 (a)
        r = row(st("a", ["A1.1"], period={"from": "program-start", "until": "merged:b/B1"}, paths=["x/"]),
                st("b", ["B1.1"], period={"from": "merged:b/B1", "until": "program-close"}, paths=["x/"]))
        self.assertEqual(breakdown_errors(r), [])  # the two periods chain on merged:b/B1

    def test_order_independent(self):  # BE24
        r = row(st("a", ["A1.1"], paths=["a/", "a/b.py"]), st("b", ["B1.1", "A1.1"]))
        rev = row(*reversed(r["streams"]))
        self.assertEqual(sorted(breakdown_errors(r)), sorted(breakdown_errors(rev)))


PLAN = """# Plan

## Block 2 (sub-blocks 2a, 2b)

## Block 2a: first

### Task 2a.1: x

## Block 2b: second

### Task 2b.1: y

## Stream `s`, sub-block R2 (branch)

### Task R2.1: z

## Later blocks

- **Block 2.** Planned in full in section "Block 2 (sub-blocks 2a, 2b)" above.
"""


def prow(**kw):
    r = {"streams": [{"id": "a", "tasks": ["2a.1", "2b.1"]}, {"id": "residual", "tasks": ["R2.1"], "residual": True}],
         "done": []}
    r.update(kw)
    return r


class PlanErrors(unittest.TestCase):
    def test_good_plan_passes(self):
        self.assertEqual(plan_errors(PLAN, prow()), [])

    def test_plan_errors_fail_closed(self):  # PE2-PE4, PE14, PE15, PE17, F-QPL-1
        cases = {
            "no block heading": ("", "outline.structure"), "prose only": ("## Block 7:\n\nsome prose\n", "outline.block.7"),
            "bare bullet": ("## Block 7:\n\n- Task 7.1: x\n", "outline.block.7"),
            "other block's task": ("## Block 2a:\n\n### Task 2b.1: y\n", "outline.block.2a"),
            "umbrella with none": ("## Block 2 (sub-blocks)\n\n## Block 3:\n\n### Task 3.1: x\n", "outline.block.2"),
            "bullet without phrase": (PLAN.replace("Planned in full in section", "Soon in"), "outline.later.1"),
            "dangling pointer": (PLAN.replace('"Block 2 (sub-blocks 2a, 2b)"', '"Block 9"'), "outline.later.1"),
            "taskless target": (PLAN + "\n## Block 8: only prose\n\nxx\n".replace("xx", "yy"), "outline.block.8"),
        }
        for name, (text, want) in cases.items():
            with self.subTest(name):
                self.assertIn(want, suffixes(plan_errors(text, {"streams": [], "done": []})))
        self.assertIn("outline.task.9z.1", suffixes(plan_errors(PLAN, prow(done=["9z.1"]))))
        self.assertIn("outline.unplanned.2b.1", suffixes(plan_errors(PLAN, prow(streams=[
            {"id": "a", "tasks": ["2a.1"]}, {"id": "residual", "tasks": ["R2.1"], "residual": True}]))))
        self.assertEqual([s for s in suffixes(plan_errors(PLAN, prow(done=["2b.1"], streams=[
            {"id": "a", "tasks": ["2a.1"]}, {"id": "residual", "tasks": ["R2.1"], "residual": True}]))) if s.startswith("outline.unplanned")], [])
        # Q-F80W-10 (a): R2 has a block heading but is a sub-block of residual's tasks
        ev = prow()
        ev["streams"][0]["paths"] = [{"path": "x/", "until": "merged:a/R2"}]
        self.assertIn("outline.event.merged:a/R2", suffixes(plan_errors(PLAN, ev)))
        ev["streams"][1]["period"] = {"from": "merged:residual/R2", "until": "program-close"}
        self.assertNotIn("outline.event.merged:residual/R2", suffixes(plan_errors(PLAN, ev)))
        ev["streams"][1]["period"] = {"from": "merged:residual/R3", "until": "program-close"}
        self.assertIn("outline.event.merged:residual/R3", suffixes(plan_errors(PLAN, ev)))

    def test_conditional_heading_form(self):  # F-QPL-4, PE13
        r = {"streams": [{"id": "a", "tasks": ["3d.2"]}], "done": []}
        self.assertIn("outline.task.3d.2", suffixes(plan_errors("## Block 3d:\n### Task 3d.2 (only if x): y\n", r)))
        self.assertNotIn("outline.task.3d.2", suffixes(plan_errors("## Block 3d:\n### Task 3d.2: y (only if x)\n", r)))
        for head in ("### Task 3d.2: y", "#### Task 3d.2: y"):
            self.assertEqual(plan_errors("## Block 3d:\n%s\n" % head, r), [])
        for head in ("## Task 3d.2: y", "##### Task 3d.2: y", " ### Task 3d.2: y", "### Task  3d.2: y"):
            self.assertIn("outline.task.3d.2", suffixes(plan_errors("## Block 3d:\n%s\n" % head, r)))

    def test_block_heading_outside_stream_ignored(self):  # PE10
        text = "## Owner answers\n\n### Block 2 (2026-11-01)\n"
        self.assertIn("outline.structure", suffixes(plan_errors(text, {"streams": [], "done": []})))
        inside = "## Stream x, sub-block R1 (b)\n\n### Block R1a: y\n\n#### Task R1a.1: t\n"
        self.assertEqual([s for s in suffixes(plan_errors(inside, {"streams": [], "done": []})) if s != "outline.unplanned.R1a.1"], [])

    def test_types(self):  # PE19, PE20
        for args in ((None, {}), (b"", {}), ("x", None), ("x", [])):
            with self.assertRaises(ValueError):
                plan_errors(*args)

    def test_this_repository_plan_passes_its_headings(self):  # PE1, plan test :2790-2791
        with open(PLAN_FILE, encoding="utf-8") as fh:
            text = fh.read()
        heads = [l for l in text.split("\n") if breakdown._TASK_HEAD.match(l)]
        self.assertEqual(len(heads), 95)  # measured at the head of this task; the plan's 37 headings is stale (Q17)
        tasks = sorted({breakdown._TASK_HEAD.match(l).group(1) for l in heads})
        errs = plan_errors(text, {"streams": [{"id": "a", "tasks": tasks}], "done": []})
        self.assertEqual([e for e in errs if e[0].startswith("outline")], [])
        self.assertEqual(len(checkpoints.block_ids(text)), 45)

    def test_scale(self):  # PE22
        text = "\n".join("## Block B%d:\n### Task B%d.1: t" % (i, i) for i in range(500)) + "\n" + \
            "\n".join("### Task Z.%d: t" % i for i in range(5000))
        errs = plan_errors(text, {"streams": [], "done": []})
        self.assertEqual(len(errs), 5500)


if __name__ == "__main__":
    unittest.main()
