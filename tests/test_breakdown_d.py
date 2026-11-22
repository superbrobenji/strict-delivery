"""Task P2.2 part d: ``breakdown_errors`` conditions that the earlier tests left unkilled by mutation (PC3): each case
is a row that triggers exactly one condition, and the expected ``(suffix, reason)`` list is written by hand from
gates/lib/breakdown.py and the table rows BE4-BE21 of task-P2.2-domain.md."""
import unittest

from gates.lib.breakdown import breakdown_errors
from tests.test_breakdown import row, st


def of(errs, suffix):
    return [(s, m) for s, m in errs if s == suffix]


class OneCondition(unittest.TestCase):
    def test_stream_id_problem(self):  # BE4: a stream id that is a reserved word
        for sid in ("integration", "records"):
            with self.subTest(sid):
                got = of(breakdown_errors(row(st(sid, ["A1.1"]), st("b", ["B1.1"]))), "streams")
                self.assertEqual(len(got), 1, got)
                self.assertTrue(got[0][1].startswith("stream id '%s': " % sid), got)

    def test_duplicate_stream_id_reported_once(self):  # BE4
        got = breakdown_errors(row(st("a", ["A1.1"]), st("a", ["A1.2"]), st("a", ["A1.3"])))
        self.assertEqual(got, [("streams", "duplicate stream id 'a'")])

    def test_same_task_in_two_streams_of_one_id(self):  # BE6: no "in streams a and a" for a repeated stream id
        got = breakdown_errors(row(st("a", ["A1.1"]), st("a", ["A1.1"]), groups=[]))
        self.assertEqual(got, [("streams", "duplicate stream id 'a'")])

    def test_residual_with_an_empty_paths_key(self):  # BE8
        got = breakdown_errors(row(dict(st("a", ["A1.1"], residual=True), paths=[]), st("b", ["B1.1"])))
        self.assertEqual(got, [("residual", "stream a is residual and has paths")])

    def test_task_id_reasons_are_each_their_own(self):  # BE5
        got = breakdown_errors(row(st("a", ["x"]), st("b", ["B1.1"]), groups=[]))
        self.assertEqual(got, [("tasks", "task 'x' of stream a has no '.', so no sub-block")])
        got = breakdown_errors(row(st("a", ["a.b.c"]), st("b", ["B1.1"]), groups=[]))
        self.assertEqual(got, [("tasks", "task 'a.b.c' of stream a: the id must be <block>.<n> of [0-9A-Za-z]+ parts")])

    def test_done_named_by_an_edge(self):  # BE10
        got = breakdown_errors(row(done=["Z9.9"], edges=[{"from": "Z9.9", "to": "A1.1"}]))
        self.assertIn(("done", "task Z9.9 is done and named by an edge"), got)

    def test_period_never_opens_each_way(self):  # BE11, D-B9: lo is program-close; hi is program-start
        got = breakdown_errors(row(st("a", ["A1.1"], period={"from": "program-close", "until": "merged:b/B1"}),
                                   st("b", ["B1.1"])))
        self.assertEqual(of(got, "period"), [("period", "stream a: period program-close .. merged:b/B1 can never open")])
        got = breakdown_errors(row(st("a", ["A1.1"], period={"from": "merged:b/B1", "until": "program-start"}),
                                   st("b", ["B1.1"])))
        self.assertEqual(of(got, "period"), [("period", "stream a: period merged:b/B1 .. program-start can never open")])

    def test_path_item_with_another_key(self):  # BE11
        got = breakdown_errors(row(st("a", ["A1.1"], paths=[{"path": "a/", "owner": "x"}]), st("b", ["B1.1"])))
        self.assertEqual(got, [("paths", "stream a: item 0 is neither a path nor a path/from/until map")])

    def test_never_open_window_is_not_compared_for_overlap(self):  # BE12
        a = st("a", ["A1.1"], paths=["a/", {"path": "x/", "from": "merged:b/B1", "until": "merged:b/B1"}])
        b = st("b", ["B1.1"], paths=["b/", "x/"])
        got = breakdown_errors(row(a, b))
        self.assertEqual(got, [("paths", "stream a: x/: window merged:b/B1 .. merged:b/B1 can never open")])

    def test_paths_of_one_stream_may_nest(self):  # BE12
        self.assertEqual(breakdown_errors(row(st("a", ["A1.1"], paths=["a/", "a/x.py"]), st("b", ["B1.1"]))), [])

    def test_windows_that_touch_the_other_way(self):  # BE14
        def two(wa, wb, edges=()):
            return row(st("a", ["A1.1"], paths=[dict(path="x/", **wa)]), st("b", ["B1.1"], paths=[dict(path="x/", **wb)]),
                       edges=list(edges))
        self.assertEqual(breakdown_errors(two({"from": "merged:b/B1"}, {"until": "merged:b/B1"})), [])    # b ends where a starts
        self.assertEqual(breakdown_errors(two({"from": "merged:a/A1"}, {"until": "merged:b/B1"},
                                              [{"from": "B1.1", "to": "A1.1"}])), [])                     # b ends before a starts
        self.assertNotEqual(breakdown_errors(two({"from": "merged:a/A1"}, {"until": "merged:b/B1"},
                                                 [{"from": "A1.1", "to": "B1.1"}])), [])

    def test_self_edge_is_not_a_cycle(self):  # BE18
        got = breakdown_errors(row(edges=[{"from": "A1.1", "to": "A1.1"}]))
        self.assertEqual(got, [("edges", "edge A1.1 -> A1.1 is an edge from a task to itself")])

    def test_tasks_without_a_sub_block_are_not_lifted(self):  # BE27: no sub-block cycle through "no sub-block"
        a = st("a", ["x1", "x2"])
        b = st("b", ["B1.1", "B1.2"])
        got = breakdown_errors(row(a, b, groups=[], edges=[{"from": "x1", "to": "B1.1"}, {"from": "B1.2", "to": "x2"}]))
        self.assertEqual(of(got, "edges"), [])

    def test_group_path_of_edges_in_either_direction(self):  # BE21
        base = [st("a", ["A1.1", "A1.2", "A1.3"]), st("b", ["B1.1"])]
        got = breakdown_errors(row(*base, groups=[{"id": "g", "tasks": ["A1.1", "A1.3"]}],
                                   edges=[{"from": "A1.3", "to": "A1.2"}, {"from": "A1.2", "to": "A1.1"}]))
        self.assertEqual(got, [("groups", "group g holds A1.1 and A1.3, joined by a path of edges")])


if __name__ == "__main__":
    unittest.main()
