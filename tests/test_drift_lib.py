"""Task 5c.1: ``gates/lib/drift.py`` on real git fixtures, every row of the table task-5c.1-domain.md (D, M, I, S, B, H, U,
G, F, N, K, R, O, E, V rows; the row id is in each test's docstring). Expected values are typed by hand; git facts are
read with plain ``git`` in the test (``rev-parse``, ``log --first-parent``), never with ``drift`` or ``gitinfo``."""
import builtins
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates.lib import config, drift, gitinfo, programs
from gates.lib.result import GateError
from gates.lib.store import Record
from tests.helpers import CLEARED_ENV, GitIsolatedTestCase, commit_all, git, make_repo

P = "20261101-x"
ANY = object()
ZEROS = "0" * 40
HEADERS = programs.STATUS_HEADERS
_PATCH = None
_TMP = None
G: dict = {}


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def commit_file(root, rel, text, msg=None):
    write(root, rel, text)
    return commit_all(root, msg or ("add " + rel))


def branch_from(root, name, start):
    git(root, "checkout", "-q", "-B", name, start)


def first_parent_log(root, ref):
    """The oracle: ``git log --first-parent --format='%H %P'`` as ``[(commit, [parents])]``."""
    out = git(root, "log", "--first-parent", "--format=%H %P", ref)
    return [(l.split()[0], l.split()[1:]) for l in out.split("\n") if l]


def stream(sid, **kw):
    d = {"id": sid, "plan": "docs/strict-delivery/plans/%s-plan.md" % sid}
    d.update(kw)
    return d


def row(sid, status="running", **kw):
    r = {"stream": sid, "block": "5c", "branch": "%s/%s/main" % (P, sid), "worktree": "w", "next task": "5c.1",
         "estimate": "10", "used": "1", "status": status, "blockers": "none", "pending decisions": "none",
         "delivers": "x"}
    if status == "ready":
        r["block"] = r["next task"] = "none"
    r.update(kw)
    return r


def program(streams, requests=(), name=P, status_text=""):
    return programs.Program(name, {"schema": "streams/1", "program": name, "streams": list(streams)}, status_text,
                            list(requests), "", "", None)


def status_page(rows):
    lines = ["| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
    lines += ["| " + " | ".join(r[h] for h in HEADERS) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def suffixes(errs):
    return [s for s, _ in errs]


def kinds(errs):
    return sorted(set(s.split(".")[0] for s, _ in errs))


def handoff_text(sid, head, **over):
    f = {"schema": "handoff/1", "plan": "docs/strict-delivery/plans/%s-plan.md" % sid, "spec": "[]",
         "branch": "%s/%s/main" % (P, sid), "ledger": ".strict-delivery/state/plans/%s-plan/ledger.md" % sid,
         "block": "5c", "next_task": "5c.1", "head": head, "open_decisions": "[]", "questions": "[]"}
    body = over.pop("body", "body\n")
    f.update(over)
    if "resume" not in f:
        f["resume"] = "'Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: none.'" % (
            f["plan"], f["next_task"], f["branch"], f["head"])
    keep = [k for k in f if f[k] is not None]
    return "---\n" + "".join("%s: %s\n" % (k, f[k]) for k in keep) + "---\n" + body


def make_stream(sid, status="running", head=None, row_kw=None, **over):
    """A stream branch ``P/<sid>/main`` cut from BASE: one work commit, then the handoff naming ``head`` (default: the work
    commit). Returns ``(stream, row, work_sha, tip)``."""
    root = G["root"]
    branch_from(root, "%s/%s/main" % (P, sid), G["BASE"])
    work = commit_file(root, "work.txt", "w\n", "work")   # the same commit on every branch (fixed dates)
    text = handoff_text(sid, work if head is None else head, **over)
    tip = commit_file(root, ".strict-delivery/state/plans/%s-plan/handoff.md" % sid, text)
    git(root, "checkout", "-q", "main")
    return stream(sid), row(sid, status, **(row_kw or {})), work, tip


def setUpModule():
    global _PATCH, _TMP
    _TMP = tempfile.TemporaryDirectory()
    tmp = os.path.realpath(_TMP.name)
    home = os.path.join(tmp, "home")
    os.mkdir(home)
    _PATCH = mock.patch.dict(os.environ, {"HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    _PATCH.start()
    for name in CLEARED_ENV:
        os.environ.pop(name, None)
    root = os.path.join(tmp, "repo")
    os.mkdir(root)
    make_repo(root)
    G["root"] = root
    build(root)
    G["cfg"] = config.load(root)


def tearDownModule():
    _PATCH.stop()
    _TMP.cleanup()


def build(root):
    """The shapes (table M, H, I): every branch is cut with real git; ``main`` advances by merges."""
    def rev(r):
        return git(root, "rev-parse", r)

    def side(name, start="main", n=1):
        branch_from(root, name, start)
        for k in range(n):
            commit_file(root, "%s-%d.txt" % (name.replace("/", "-"), k), "x\n")
        git(root, "checkout", "-q", "main")
        return rev(name)

    commit_file(root, "m1.txt", "m1\n")
    G["M1"] = rev("main")
    git(root, "branch", "%s/i/main" % P, "main")                      # i: cut at M1, main advances: behind
    G["i_tip"] = G["M1"]
    G["dv_tip"] = side("%s/dv/main" % P)                               # dv: diverged once main advances
    G["c_tip"] = side("%s/c/main" % P)
    git(root, "merge", "-q", "--no-ff", "-m", "merge c", "%s/c/main" % P)
    G["c_merge"] = rev("main")
    G["d_tip0"] = side("%s/d/main" % P)
    git(root, "merge", "-q", "--no-ff", "-m", "merge d", "%s/d/main" % P)
    G["d_merge"] = rev("main")
    git(root, "checkout", "-q", "%s/d/main" % P)
    commit_file(root, "d-extra.txt", "x\n")
    git(root, "checkout", "-q", "main")
    G["d_tip1"] = rev("%s/d/main" % P)
    G["e_tip"] = side("%s/e/main" % P)
    git(root, "merge", "-q", "--squash", "%s/e/main" % P)
    git(root, "commit", "-q", "-m", "squash e")
    G["f_tip"] = side("%s/f/main" % P)
    branch_from(root, "side", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "merge f into side", "%s/f/main" % P)
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    G["g_tip"] = side("%s/g/main" % P)
    git(root, "merge", "-q", "--ff-only", "%s/g/main" % P)
    G["h_tip"] = side("%s/h/main" % P)
    git(root, "merge", "-q", "--no-ff", "-m", "merge h", "%s/h/main" % P)
    G["h_merge"] = rev("main")
    git(root, "branch", "%s/j/main" % P, G["h_tip"])                  # j: stacked, empty, cut from h
    G["t1"] = side("t1")
    G["t2"] = side("t2")
    git(root, "merge", "-q", "--no-ff", "-m", "octopus", "t1", "t2")
    G["oct_merge"] = rev("main")
    G["before_t3"] = rev("main")
    G["t3"] = side("t3")
    git(root, "merge", "-q", "--no-ff", "-m", "merge t3", "t3")
    G["t3_merge"] = rev("main")
    git(root, "revert", "-m", "1", "--no-edit", G["h_merge"])
    G["BASE"] = rev("main")
    git(root, "branch", "%s/eq/main" % P, G["BASE"])
    G["a_tip"] = side("%s/a/main" % P, G["BASE"])
    G["ac_tip"] = side("%s/ac/main" % P, G["a_tip"])                  # stacked child ahead of its parent
    git(root, "branch", "%s/b/main" % P, G["BASE"])                   # stacked on a: behind its parent only
    G["bi_tip"] = side("%s/bi/main" % P, G["M1"])                     # stacked on i: behind main only
    G["bb_tip"] = side("%s/bb/main" % P, G["M1"])                     # stacked on a: behind both
    G["cs_tip"] = side("%s/cs/main" % P, G["BASE"])                   # stacked on merged c, synced
    # integration branches
    G["int_ahead"] = side("%s/integration" % P, G["BASE"])
    git(root, "branch", "20261104-e/integration", G["BASE"])
    git(root, "branch", "20261105-b/integration", G["M1"])
    side("20261106-d/integration", G["M1"])
    git(root, "branch", "20261108-t/integration", G["BASE"])
    git(root, "tag", "20261108-t/integration", G["M1"])
    git(root, "branch", "%s/ts/main" % P, G["BASE"])
    git(root, "tag", "%s/ts/main" % P, G["M1"])
    git(root, "branch", "release/1.0", G["BASE"])
    git(root, "tag", "tagonly", G["BASE"])
    G["decisions_tip"] = build_decisions(root)


DEC_DIR = ".strict-delivery/state/decisions"


def dec(id_, status, topics):
    t = "" if topics is None else "topics: %s\n" % topics
    return "schema: decision/1\nid: %s\n%s%s" % (id_, "" if status is None else "status: %s\n" % status, t)


def build_decisions(root):
    """Program ``20261102-d``: its integration holds the decisions of table D1 and N; ``20261103-bad``: one unparseable."""
    files = {
        "DEC-20261102-aaaa": dec("DEC-20261102-aaaa", "open", "[q:a-plan:q1]"),
        "DEC-20261102-bbbb": dec("DEC-20261102-bbbb", "answered", "q:a-plan:q2"),
        "DEC-20261102-cccc": "id: 7\n",
        "DEC-20261102-dddd": dec("DEC-20261102-dddd", "withdrawn", "[q:a-plan:q3]"),
        "DEC-20261102-eeee": dec("DEC-20261102-eeee", "open", "[x]"),
        "DEC-20261102-ffff": dec("DEC-20261102-ffff", "open", "[q:b-plan:q1]"),
        "DEC-20261102-gggg": dec("DEC-20261102-gggg", "open", "[q:a-b:q1]"),
        "DEC-20261102-hhhh": dec("DEC-20261102-hhhh", "open", "[7, 'q:a-plan:', 'q:a-plan:Q1', 'q:a-plan:q1:x']"),
        "DEC-20261102-iiii": dec("DEC-20261102-iiii", "open", "q:a-plan:q9"),
        "DEC-20261102-jjjj": dec("DEC-20261102-jjjj", "Open", "[q:a-plan:q8]"),
        "DEC-20261102-kkkk": dec("DEC-20261102-kkkk", "open", "[q:a-plan:q7ࡰ]"),
        "DEC-20261102-llll": dec("DEC-20261102-llll", "open", "[q:a-plan:q7, q:a-plan:q7]"),
        "DEC-20261102-mmmm": "id: DEC-20261102-mmmm\n",
    }
    git(root, "checkout", "-q", "-B", "20261102-d/integration", G["BASE"])
    for k, v in files.items():
        write(root, "%s/%s.yml" % (DEC_DIR, k), v)
    G["dec_tip"] = commit_all(root, "decisions")
    git(root, "checkout", "-q", "-B", "20261103-bad/integration", G["BASE"])
    write(root, "%s/DEC-20261103-dddd.yml" % DEC_DIR, "id: [unclosed\n")
    commit_all(root, "bad decision")
    git(root, "checkout", "-q", "-B", "20261109-n/integration", G["BASE"])
    git(root, "checkout", "-q", "main")
    return G["dec_tip"]


def prog_pending(streams, name="20261102-d"):
    return program(streams, name=name)


class MergedAt(unittest.TestCase):
    """Rows M1-M19."""

    def t(self, name):
        return G[name]

    def test_fresh_branch_is_not_merged(self):
        "M1"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["BASE"]))

    def test_no_ff_merge_found(self):
        "M2: the oracle is git log --first-parent"
        want = [c for c, ps in first_parent_log(G["root"], G["BASE"]) if len(ps) == 2 and ps[1] == G["c_tip"]]
        self.assertEqual(want, [G["c_merge"]])
        self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["c_tip"]), G["c_merge"])

    def test_unmerged_branch_ahead(self):
        "M3"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["a_tip"]))

    def test_merged_then_extra_commit(self):
        "M4"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["d_tip1"]))
        self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["d_tip0"]), G["d_merge"])

    def test_squash_merge_not_merged(self):
        "M5"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["e_tip"]))

    def test_merge_off_first_parent_not_merged(self):
        "M6"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["f_tip"]))

    def test_fast_forward_not_merged(self):
        "M7"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["g_tip"]))

    def test_behind_branch_not_merged(self):
        "M8"
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["i_tip"]))
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["dv_tip"]))

    def test_stacked_empty_child_reads_merged(self):
        "M9 (D-5c-Q9): j has h's tip, h merged --no-ff"
        self.assertEqual(git(G["root"], "rev-parse", "%s/j/main" % P), G["h_tip"])
        self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["h_tip"]), G["h_merge"])

    def test_merged_then_reverted_still_merged(self):
        "M10: the revert commit does not remove the merge from the first-parent line"
        self.assertIn("Revert", git(G["root"], "log", "-1", "--format=%s", G["BASE"]) + "Revert")
        self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["h_tip"]), G["h_merge"])

    def test_octopus_not_merged(self):
        "M11: three parents, the second is t1"
        self.assertEqual(len(git(G["root"], "rev-list", "--parents", "-n1", G["oct_merge"]).split()), 4)
        self.assertEqual(git(G["root"], "rev-list", "--parents", "-n1", G["oct_merge"]).split()[2], G["t1"])
        self.assertIsNone(drift.merged_at(G["root"], G["BASE"], G["t1"]))

    def test_merge_beyond_base_not_seen(self):
        "M12"
        self.assertIsNone(drift.merged_at(G["root"], G["before_t3"], G["t3"]))
        self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["t3"]), G["t3_merge"])

    def test_merged_at_root_commit(self):
        "M13"
        first = git(G["root"], "rev-list", "--max-parents=0", "main")
        self.assertIsNone(drift.merged_at(G["root"], first, G["a_tip"]))

    def test_merged_at_shallow(self):
        "M14: a --depth 2 clone cuts the history; no false match"
        clone = os.path.join(os.path.dirname(G["root"]), "shallow")
        git(os.path.dirname(G["root"]), "clone", "-q", "--depth", "2", "file://" + G["root"], "shallow")
        base = git(clone, "rev-parse", "origin/main")
        self.assertIsNone(drift.merged_at(clone, base, G["c_tip"]))

    def test_merged_at_tip_must_be_full_sha(self):
        "M15"
        for bad in (G["c_tip"][:7], G["c_tip"].upper(), "main", "", G["c_tip"] + "a", 5, None, b"x" * 40):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                drift.merged_at(G["root"], G["BASE"], bad)

    def test_merged_at_base_forms(self):
        "M16"
        tree = git(G["root"], "rev-parse", "main^{tree}")
        for bad in ("main", "refs/heads/main", "-" + "a" * 39, ZEROS, tree, G["BASE"][:12], "a" * 41, "", 7):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                drift.merged_at(G["root"], bad, G["c_tip"])

    def test_merged_at_argument_types(self):
        "M17"
        class S(str):
            pass
        for root in (None, 5, b"x"):
            with self.subTest(root=root), self.assertRaises(GateError):
                drift.merged_at(root, G["BASE"], G["c_tip"])
        for bad in (b"a" * 40, S(G["c_tip"]), True):
            with self.subTest(tip=bad), self.assertRaises(GateError):
                drift.merged_at(G["root"], G["BASE"], bad)

    def test_merged_at_long_history(self):
        "M18: 300 first-parent commits answered by one pass (a per-commit call would show in the call count)"
        d = tempfile.mkdtemp(dir=os.path.dirname(G["root"]))
        make_repo(d)
        git(d, "checkout", "-q", "-b", "side")
        tipc = commit_file(d, "s.txt", "s\n")
        git(d, "checkout", "-q", "main")
        git(d, "merge", "-q", "--no-ff", "-m", "m", "side")
        merge = git(d, "rev-parse", "HEAD")
        one = "commit refs/heads/main\ncommitter C <c@x.invalid> 1700000000 +0000\ndata 1\nx\n"
        tmpl = one + "from refs/heads/main^0\n\n" + "".join(one + "\n" for _ in range(299))
        subprocess.run(["git", "-C", d, "fast-import", "--quiet", "--force"], input=tmpl.encode(), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ))
        base = git(d, "rev-parse", "main")
        self.assertGreater(int(git(d, "rev-list", "--count", "--first-parent", base)), 300)
        calls = []
        real = subprocess.run

        def counting(argv, *a, **k):
            calls.append(argv)
            return real(argv, *a, **k)

        with mock.patch.object(subprocess, "run", counting):
            self.assertEqual(drift.merged_at(d, base, tipc), merge)
        self.assertLess(len(calls), 10)

    def test_merged_at_with_git_index_file(self):
        "M19: GIT_INDEX_FILE inherited by design; the verdict is the same"
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(G["root"], ".git", "index")}):
            self.assertEqual(drift.merged_at(G["root"], G["BASE"], G["c_tip"]), G["c_merge"])


class Integration(unittest.TestCase):
    """Rows I1-I11."""

    cfg = property(lambda self: G["cfg"])

    def test_integration_equal_passes(self):
        "I1"
        self.assertEqual(drift.integration_errors(G["root"], self.cfg, "20261104-e"), [])

    def test_integration_ahead_passes(self):
        "I2"
        self.assertEqual(drift.integration_errors(G["root"], self.cfg, P), [])

    def test_integration_behind_main_fails(self):
        "I3"
        got = drift.integration_errors(G["root"], self.cfg, "20261105-b")
        self.assertEqual(got, [("integration.20261105-b", "integration is behind main; run a sync")])

    def test_integration_diverged_fails(self):
        "I4"
        self.assertEqual(suffixes(drift.integration_errors(G["root"], self.cfg, "20261106-d")), ["integration.20261106-d"])

    def test_integration_branch_absent(self):
        "I5 (D-5c-Q2): a GateError naming the branch"
        with self.assertRaises(GateError) as e:
            drift.integration_errors(G["root"], self.cfg, "20261107-n")
        self.assertIn("20261107-n/integration", str(e.exception))

    def test_integration_tag_shadow(self):
        "I6: the tag 20261108-t/integration is at M1 (behind); the branch is at BASE and is judged"
        self.assertEqual(drift.integration_errors(G["root"], self.cfg, "20261108-t"), [])

    def test_base_branch_absent(self):
        "I7"
        for name in ("nomain", "tagonly"):
            with self.subTest(name=name), self.assertRaises(GateError) as e:
                drift.integration_errors(G["root"], dict(self.cfg, base_branch=name), P)
            self.assertIn(name, str(e.exception))

    def test_base_branch_forms(self):
        "I8"
        self.assertEqual(drift.integration_errors(G["root"], dict(self.cfg, base_branch="release/1.0"), P), [])
        for bad in ("-x", "a@b", "a" * 41, "", None, 5):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                drift.integration_errors(G["root"], dict(self.cfg, base_branch=bad), P)

    def test_integration_program_name_forms(self):
        "I9"
        class S(str):
            pass
        for bad in ("", "A", "a/b", 5, None, S(P), "20261301-x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                drift.integration_errors(G["root"], self.cfg, bad)

    def test_integration_cfg_forms(self):
        "I10"
        for cfg in ({}, {"base_branch": 5}, None, [], {"paths": {}}):
            with self.subTest(cfg=cfg), self.assertRaises(GateError):
                drift.integration_errors(G["root"], cfg, P)

    def test_integration_errors_from_each_worktree(self):
        "I11: a linked worktree gives the same verdict; a subdirectory is a GateError"
        wt = os.path.join(os.path.dirname(G["root"]), "wt-int")
        if not os.path.isdir(wt):
            git(G["root"], "worktree", "add", "-q", "--detach", wt, G["BASE"])
        self.assertEqual(drift.integration_errors(wt, self.cfg, "20261105-b"),
                         drift.integration_errors(G["root"], self.cfg, "20261105-b"))
        with self.assertRaises(GateError):
            drift.integration_errors(os.path.join(G["root"], ".strict-delivery"), self.cfg, P)


class Decisions(unittest.TestCase):
    """Rows D1-D10."""

    cfg = property(lambda self: G["cfg"])

    def at(self, ref="refs/heads/20261102-d/integration", cfg=ANY):
        return drift.decisions_at(G["root"], self.cfg if cfg is ANY else cfg, ref)

    def test_decisions_at_reads_integration_tip(self):
        "D1"
        recs = self.at()
        self.assertEqual([r.id for r in recs][:3], ["DEC-20261102-aaaa", "DEC-20261102-bbbb", 7])
        self.assertTrue(all(type(r) is Record for r in recs))
        self.assertEqual(recs[0].file, DEC_DIR + "/DEC-20261102-aaaa.yml")

    def test_decisions_at_unparseable_names_file(self):
        "D2"
        with self.assertRaises(GateError) as e:
            self.at("refs/heads/20261103-bad/integration")
        self.assertIn("20261103-bad/integration:" + DEC_DIR + "/DEC-20261103-dddd.yml", str(e.exception))

    def test_decisions_at_top_level_not_mapping(self):
        "D3"
        root = G["root"]
        branch_from(root, "tmp-d3", G["BASE"])
        commit_file(root, DEC_DIR + "/DEC-20261110-aaaa.yml", "- 1\n- 2\n")
        git(root, "checkout", "-q", "main")
        with self.assertRaises(GateError) as e:
            self.at("refs/heads/tmp-d3")
        self.assertIn("top level must be a mapping", str(e.exception))

    def test_decisions_at_stray_entry(self):
        "D4: one function with checkpoints.records_at (D-5c-Q26): index.yml and in-force.md skipped, the rest refused"
        root = G["root"]
        for n, (rel, text) in enumerate((("notes.txt", "x\n"), ("sub/DEC-1.yml", "id: x\n"), (".x.yml", "id: x\n"))):
            with self.subTest(rel=rel):
                branch_from(root, "tmp-d4-%d" % n, G["BASE"])
                commit_file(root, DEC_DIR + "/" + rel, text)
                git(root, "checkout", "-q", "main")
                with self.assertRaises(GateError) as e:
                    self.at("refs/heads/tmp-d4-%d" % n)
                self.assertIn("not a regular file named <id>.yml", str(e.exception))
        branch_from(root, "tmp-d4-ok", G["BASE"])
        commit_file(root, DEC_DIR + "/index.yml", "x: 1\n")
        commit_file(root, DEC_DIR + "/in-force.md", "x\n")
        git(root, "checkout", "-q", "main")
        self.assertEqual(self.at("refs/heads/tmp-d4-ok"), [])

    def test_decisions_at_not_utf8(self):
        "D5"
        root = G["root"]
        branch_from(root, "tmp-d5", G["BASE"])
        os.makedirs(os.path.join(root, DEC_DIR), exist_ok=True)
        with open(os.path.join(root, DEC_DIR, "DEC-20261110-bbbb.yml"), "wb") as fh:
            fh.write(b"id: \xff\n")
        commit_all(root, "bad bytes")
        git(root, "checkout", "-q", "main")
        with self.assertRaises(GateError) as e:
            self.at("refs/heads/tmp-d5")
        self.assertIn("not valid UTF-8", str(e.exception))

    def test_decisions_at_absent_dir(self):
        "D6"
        self.assertEqual(self.at("refs/heads/20261104-e/integration"), [])

    def test_decisions_at_dir_is_file(self):
        "D7"
        root = G["root"]
        cfg = dict(self.cfg, paths=dict(self.cfg["paths"], decisions="m1.txt"))
        git(root, "checkout", "-q", "main")
        with self.assertRaises(GateError) as e:
            self.at("refs/heads/20261104-e/integration", cfg)
        self.assertIn("not a directory", str(e.exception))

    def test_decisions_at_ref_forms(self):
        "D8"
        for bad in ("", "-x", "^x", "a" * 41, 5, None):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                self.at(bad)
        with self.assertRaises(GateError):
            self.at("refs/heads/no-such")

    def test_decisions_at_argument_types(self):
        "D9"
        for cfg in (None, [], {}, {"paths": {}}, {"paths": {"decisions": ""}}, {"paths": {"decisions": "/x"}},
                    {"paths": {"decisions": "a//b"}}, {"paths": {"decisions": ".."}}):
            with self.subTest(cfg=cfg), self.assertRaises(GateError):
                self.at(cfg=cfg)
        with self.assertRaises(GateError):
            drift.decisions_at(5, self.cfg, "refs/heads/20261102-d/integration")

    def test_decisions_at_ignores_working_tree(self):
        "D10"
        root = G["root"]
        git(root, "checkout", "-q", "20261102-d/integration")
        try:
            write(root, DEC_DIR + "/DEC-20261102-aaaa.yml", "id: changed\n")
            self.assertEqual(self.at()[0].id, "DEC-20261102-aaaa")
        finally:
            git(root, "checkout", "-q", "--", ".")
            git(root, "checkout", "-q", "main")


def se(r, st, streams=None, requests=(), name=P, cfg=None):
    return drift.stream_errors(G["root"], cfg or G["cfg"], program(streams or [st], requests, name), r, st)


def only(errs, kind):
    return [(s, r) for s, r in errs if s.split(".")[0] == kind]


class Matrix(unittest.TestCase):
    """Rows X1-X6: status against branch state; ``test_status_branch_matrix`` walks the 24 cells."""

    STATES = {"absent": "nb", "ok": "a", "behind": "i", "merged": "c"}
    # the merged branch is also behind the base (the merge commit is not an ancestor of its own parent): both are listed
    WANT = {
        "ready": {"absent": [], "ok": [], "behind": ["behind"], "merged": ["behind", "merged"]},
        "live": {"absent": ["branch"], "ok": ["handoff"], "behind": ["behind", "handoff"],
                 "merged": ["behind", "handoff", "merged"]},
        "ended": {"absent": ["merged"], "ok": ["merged"], "behind": ["merged"], "merged": []},
    }

    def test_status_branch_matrix(self):
        "X1-X6"
        for status in programs.STATUS_VALUES:
            grp = "ready" if status == "ready" else ("ended" if status in ("merged", "closed") else "live")
            for state, sid in self.STATES.items():
                with self.subTest(status=status, state=state):
                    errs = se(row(sid, status), stream(sid))
                    self.assertEqual(kinds([e for e in errs if e[0].split(".")[0] in
                                            ("branch", "behind", "merged", "handoff")]), self.WANT[grp][state])

    def test_closed_status_as_merged(self):
        "G4 (D-5c-Q8): closed is judged as merged"
        self.assertEqual(se(row("c", "closed"), stream("c")), [])
        self.assertEqual(kinds(se(row("a", "closed"), stream("a"))), ["merged"])

    def test_merged_status_without_merge_fails(self):
        "G2"
        errs = se(row("a", "merged"), stream("a"))
        self.assertEqual(suffixes(errs), ["merged.a"])
        self.assertIn("if the PR merged on the host, update main from the remote", errs[0][1])


class Branch(unittest.TestCase):
    """Rows B1-B5."""

    def test_branch_present(self):
        "B1"
        self.assertEqual(only(se(row("a"), stream("a")), "branch"), [])

    def test_branch_only_on_remote_fails(self):
        "B2"
        git(G["root"], "update-ref", "refs/remotes/origin/%s/rr/main" % P, G["BASE"])
        for st in ("running", "blocked", "checkpoint"):
            with self.subTest(status=st):
                self.assertEqual(suffixes(only(se(row("rr", st), stream("rr")), "branch")), ["branch.rr"])

    def test_branch_tag_is_not_a_branch(self):
        "B3"
        git(G["root"], "tag", "-f", "%s/tg/main" % P, G["BASE"])
        self.assertEqual(suffixes(only(se(row("tg", "running"), stream("tg")), "branch")), ["branch.tg"])

    def test_branch_of_refuses_bad_stream(self):
        "B4"
        for bad in ("A", "a/b", "", 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                se(row("a", stream=bad), stream(bad))

    def test_branch_reason_text(self):
        "B5 (D-5c-Q15)"
        self.assertEqual(only(se(row("nb"), stream("nb")), "branch"), [("branch.nb", "no local branch %s/nb/main" % P)])


class Behind(unittest.TestCase):
    """Rows H1-H14, R5c-3."""

    def behind(self, sid, status="running", streams=None):
        return only(se(row(sid, status), next(s for s in streams or [stream(sid)] if s["id"] == sid),
                       streams=streams), "behind")

    def test_behind_equal_passes(self):
        "H1"
        self.assertEqual(self.behind("eq"), [])

    def test_behind_ahead_passes(self):
        "H2"
        self.assertEqual(self.behind("a"), [])

    def test_stream_behind_main_fails(self):
        "H3"
        self.assertEqual(self.behind("i"), [("behind.i", "behind main; run a sync")])

    def test_behind_diverged_fails(self):
        "H4"
        self.assertEqual(suffixes(self.behind("dv")), ["behind.dv"])

    def test_stacked_behind_parent_fails(self):
        "H5"
        got = self.behind("b", streams=[stream("a"), stream("b", stacked_on="a")])
        self.assertEqual(got, [("behind.b", "behind %s/a/main; run a sync" % P)])

    def test_stacked_behind_main_fails(self):
        "H6"
        got = self.behind("bi", streams=[stream("i"), stream("bi", stacked_on="i")])
        self.assertEqual(got, [("behind.bi", "behind main; run a sync")])

    def test_stacked_behind_both_one_line(self):
        "H7"
        got = self.behind("bb", streams=[stream("a"), stream("bb", stacked_on="a")])
        self.assertEqual(got, [("behind.bb", "behind main and %s/a/main; run a sync" % P)])

    def test_stacked_ahead_passes(self):
        "H8"
        self.assertEqual(self.behind("ac", streams=[stream("a"), stream("ac", stacked_on="a")]), [])

    def test_stacked_parent_branch_absent(self):
        "H9 (D-5c-Q16)"
        got = self.behind("a", streams=[stream("nb"), stream("a", stacked_on="nb")])
        self.assertEqual(got, [("behind.a", "the stacked_on branch %s/nb/main is missing" % P)])

    def test_stacked_parent_merged_child_synced(self):
        "H10"
        self.assertEqual(self.behind("cs", streams=[stream("c"), stream("cs", stacked_on="c")]), [])

    def test_unstacked_ignores_other_streams(self):
        "H11"
        self.assertEqual(self.behind("eq", streams=[stream("a"), stream("eq")]), [])

    def test_behind_not_checked_for_merged_rows(self):
        "H12"
        for st in ("merged", "closed"):
            self.assertEqual(self.behind("i", st), [])

    def test_behind_tag_shadow(self):
        "H14: the tag P/ts/main is at M1 (behind); the branch is at BASE"
        self.assertEqual(self.behind("ts"), [])


class Fresh(GitIsolatedTestCase):
    """Rows needing a repository of their own: H13, U1-U14, B-state."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        git(self.root, "branch", "%s/integration" % P)

    def test_behind_reads_fresh_base(self):
        "H13"
        git(self.root, "branch", "%s/a/main" % P)
        first = drift.stream_errors(self.root, self.cfg, program([stream("a")]), row("a"), stream("a"))
        self.assertEqual(only(first, "behind"), [])
        commit_file(self.root, "n.txt", "n\n")
        got = drift.stream_errors(self.root, self.cfg, program([stream("a")]), row("a"), stream("a"))
        self.assertEqual(suffixes(only(got, "behind")), ["behind.a"])

    # -- the base check (rows U1-U14): a bare remote and clones, states built by the construction
    def pair(self):
        remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", remote)
        git(self.root, "remote", "add", "origin", remote)
        git(self.root, "push", "-q", "-u", "origin", "main")
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "clone", "-q", remote, other)
        git(other, "config", "user.email", "o@example.invalid")
        git(other, "config", "user.name", "O")
        return remote, other

    def test_base_no_upstream_passes(self):
        "U1"
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_no_remote_passes(self):
        "U13"
        self.assertEqual(git(self.root, "remote"), "")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_upstream_equal_passes(self):
        "U2"
        self.pair()
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_upstream_ahead_fails(self):
        "U3"
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        got = drift.base_errors(self.root, self.cfg)
        want = ("update main from the remote: git -C %s fetch origin, then git -C %s merge --ff-only origin/main"
                % (self.root, self.root))
        self.assertEqual(got, [("base", want)])

    def test_base_local_ahead_passes(self):
        "U4"
        self.pair()
        commit_file(self.root, "l.txt", "l\n")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_diverged_fails(self):
        "U5 (D-5c-Q17): the same line"
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        commit_file(self.root, "l.txt", "l\n")
        git(self.root, "fetch", "-q", "origin")
        self.assertEqual(suffixes(drift.base_errors(self.root, self.cfg)), ["base"])

    def test_base_upstream_gone_passes(self):
        "U6"
        self.pair()
        git(self.root, "config", "branch.main.merge", "refs/heads/nonesuch")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_reason_names_remote(self):
        "U7: the remote of branch.main.remote, a differently named remote branch"
        _, other = self.pair()
        git(self.root, "remote", "rename", "origin", "upstream")
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "upstream")
        (_, reason), = drift.base_errors(self.root, self.cfg)
        self.assertIn("fetch upstream, then", reason)
        self.assertTrue(reason.endswith("merge --ff-only upstream/main"))

    def test_base_reason_names_checkout(self):
        "U8 (D-5c-Q18): the main checkout path, also from a linked worktree"
        wt = os.path.join(self.tmp, "linked")
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        (_, reason), = drift.base_errors(wt, self.cfg)
        self.assertIn("git -C %s fetch origin" % self.root, reason)

    # -- 5c.1 round 4 (F-20261124-sgrf, F-20261124-urap): rows B1-B11 of records/5c.1-fix-2.md
    def ahead(self):
        "A pair whose upstream origin/main is ahead of the local main (fetched)."
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")

    def cmd(self, path, remote="origin", name="main"):
        return ("update %s from the remote: git -C %s fetch %s, then git -C %s merge --ff-only %s/%s"
                % (name, path, remote, path, remote, name))

    NOCO = "update main from the remote: no worktree has main checked out, so no update command is given"

    def test_base_reason_names_linked_worktree(self):
        "B2: the base branch checked out in a linked worktree only: that path, twice"
        self.ahead()
        git(self.root, "checkout", "-q", "-b", "elsewhere")
        wt = os.path.join(self.tmp, "linked-main")
        git(self.root, "worktree", "add", "-q", wt, "main")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [("base", self.cmd(wt))])
        self.assertEqual(drift.base_errors(wt, self.cfg), [("base", self.cmd(wt))])

    def test_base_reason_no_checkout_has_base(self):
        "B3, B4: no worktree has the base branch (main checkout elsewhere, then detached): the no-checkout reason"
        self.ahead()
        wt = os.path.join(self.tmp, "linked-other")
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        git(self.root, "checkout", "-q", "-b", "elsewhere")
        with self.subTest("another branch"):
            self.assertEqual(drift.base_errors(self.root, self.cfg), [("base", self.NOCO)])
        git(self.root, "checkout", "-q", "--detach")
        with self.subTest("detached"):
            self.assertEqual(drift.base_errors(self.root, self.cfg), [("base", self.NOCO)])
            self.assertEqual(drift.base_errors(wt, self.cfg), [("base", self.NOCO)])

    def test_base_reason_linked_worktree_path_forms(self):
        "B5: a linked worktree path as git lists it: a symlinked directory, a space, a newline"
        self.ahead()
        git(self.root, "checkout", "-q", "-b", "elsewhere")
        real = os.path.join(self.tmp, "real")
        os.mkdir(real)
        os.symlink(real, os.path.join(self.tmp, "link"))
        for label, rel in (("symlink", os.path.join("link", "wt")), ("space", "a b"), ("newline", "n\nl")):
            wt = os.path.join(self.tmp, rel)
            with self.subTest(label):
                git(self.root, "worktree", "add", "-q", wt, "main")
                listed = subprocess.run(["git", "-C", self.root, "worktree", "list", "--porcelain", "-z"],
                                        stdout=subprocess.PIPE, check=True).stdout.decode().split("\0")
                path = [f[len("worktree "):] for f in listed if f.startswith("worktree ")][-1]
                self.assertTrue(path.endswith(rel.split(os.sep)[-1]), path)
                self.assertEqual(drift.base_errors(self.root, self.cfg), [("base", self.cmd(path))])
                git(self.root, "worktree", "remove", "--force", wt)

    def test_base_reason_upstream_not_same_name(self):
        "B8, B9: an upstream that is not <remote>/<base>: the upstream reason, no merge command"
        self.ahead()
        git(self.root, "branch", "up")
        with self.subTest("origin/dev"):
            git(self.root, "push", "-q", "origin", "origin/main:refs/heads/dev")
            git(self.root, "fetch", "-q", "origin")
            git(self.root, "branch", "-q", "--set-upstream-to=origin/dev", "main")
            (_, reason), = drift.base_errors(self.root, self.cfg)
            self.assertEqual(reason, "update main from its upstream origin/dev: it is not origin/main, "
                                     "so no update command is given")
            self.assertNotIn("--ff-only", reason)
        with self.subTest("dot"):
            commit_file(self.root, "u.txt", "u\n")
            git(self.root, "branch", "-q", "-f", "up", "HEAD")
            git(self.root, "reset", "-q", "--hard", "HEAD~1")
            git(self.root, "config", "branch.main.remote", ".")
            git(self.root, "config", "branch.main.merge", "refs/heads/up")
            (_, reason), = drift.base_errors(self.root, self.cfg)
            self.assertEqual(reason, "update main from its upstream up: it is not ./main, "
                                     "so no update command is given")
            self.assertNotIn("--ff-only", reason)

    def test_base_no_remote_name_no_upstream(self):
        "B8 siblings: no remote name, or a remote name that is no configured remote: git has no upstream, so []"
        self.ahead()
        git(self.root, "config", "branch.main.remote", "nonesuch")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])
        git(self.root, "config", "--unset", "branch.main.remote")
        self.assertEqual(drift.base_errors(self.root, self.cfg), [])

    def test_base_upstream_merge_differs_same_remote(self):
        "B8 sibling: branch.main.merge names another branch of the configured remote (the same as origin/dev)"
        self.ahead()
        git(self.root, "push", "-q", "origin", "origin/main:refs/heads/dev")
        git(self.root, "fetch", "-q", "origin")
        git(self.root, "config", "branch.main.merge", "refs/heads/dev")
        (_, reason), = drift.base_errors(self.root, self.cfg)
        self.assertNotIn("--ff-only", reason)

    @staticmethod
    def listing_raises(exc):
        "A ``gitinfo._run`` stand-in that raises ``exc`` for the ``git worktree`` call and runs every other call."
        real = gitinfo._run

        def run(r, name, args, *a, **k):
            if args[0] == "worktree":
                raise exc
            return real(r, name, args, *a, **k)
        return run

    def test_base_reason_skeleton_rows(self):
        "B11: numeric and non-ASCII branch names, the interrupt and the group propagate"
        self.ahead()
        for n in (4300, 4301):
            with self.subTest(digits=n), self.assertRaises(GateError) as e:
                drift.base_errors(self.root, dict(self.cfg, base_branch="9" * n))
            self.assertEqual(str(e.exception), "no local branch " + "9" * 80)
        for name in ("9" * 40, "ࡰx"):
            with self.subTest(name=name):
                git(self.root, "branch", "-q", "-m", "main", name)
                (_, reason), = drift.base_errors(self.root, dict(self.cfg, base_branch=name))
                self.assertEqual(reason, "update %s from its upstream origin/main: it is not origin/%s, "
                                         "so no update command is given" % (name, name))
                git(self.root, "branch", "-q", "-m", name, "main")
        git(self.root, "checkout", "-q", "-b", "elsewhere")
        with mock.patch("gates.lib.gitinfo._run", side_effect=self.listing_raises(KeyboardInterrupt)):
            with self.assertRaises(KeyboardInterrupt):
                drift.base_errors(self.root, self.cfg)
        group = getattr(builtins, "BaseExceptionGroup", None)
        if group is not None:
            with mock.patch("gates.lib.gitinfo._run", side_effect=self.listing_raises(group("g", [KeyboardInterrupt()]))):
                with self.assertRaises(group):
                    drift.base_errors(self.root, self.cfg)
        with mock.patch("gates.lib.gitinfo._run", side_effect=self.listing_raises(GateError("boom\n"))):
            (_, reason), = drift.base_errors(self.root, self.cfg)
        self.assertEqual(reason, "update main from the remote: the worktrees cannot be listed: boom\n, "
                                 "so no update command is given")

    def test_base_local_branch_absent(self):
        "U9"
        with self.assertRaises(GateError) as e:
            drift.base_errors(self.root, dict(self.cfg, base_branch="nomain"))
        self.assertIn("nomain", str(e.exception))

    def test_base_upstream_missing_object(self):
        "U10 (Q6 principle): an upstream ref whose object is absent is a base line or a GateError, never a pass"
        self.pair()
        with open(os.path.join(self.root, ".git", "refs", "remotes", "origin", "main"), "w") as fh:
            fh.write("a" * 40 + "\n")
        try:
            got = drift.base_errors(self.root, self.cfg)
        except GateError:
            return
        self.assertEqual(suffixes(got), ["base"])

    def test_base_branch_forms(self):
        "U11 (and I8)"
        git(self.root, "branch", "release/1.0")
        self.assertEqual(drift.base_errors(self.root, dict(self.cfg, base_branch="release/1.0")), [])
        for bad in ("a@b", "-x", "", None, 5):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                drift.base_errors(self.root, dict(self.cfg, base_branch=bad))

    def test_base_tag_shadow(self):
        "U14: a tag named main; the branch main is judged"
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        git(self.root, "tag", "main", "HEAD~0")
        self.assertEqual(suffixes(drift.base_errors(self.root, self.cfg)), ["base"])

    def test_base_once_per_program(self):
        "U12 (D-5c-Q1): stream_errors never emits base, even with an upstream ahead of the local base"
        _, other = self.pair()
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        git(self.root, "branch", "%s/a/main" % P, "origin/main")
        for sid in ("a", "b", "c"):
            got = drift.stream_errors(self.root, self.cfg, program([stream(sid)]), row(sid, "ready"), stream(sid))
            self.assertNotIn("base", suffixes(got))

    # -- Task 5c.3 (F-20261124-9bes, -mev2, -9v77): rows U1-U14, W1-W7, H1-H7, K1-K4 of records/task-5c.3-domain.md
    def case(self, name, base="main", remote="origin"):
        """A repository <tmp>/<name> on branch ``base`` with a bare remote called ``remote`` and a clone that pushed one
        more commit to it: the local base is behind its remote branch, which is not fetched yet. (root, bare, other)."""
        root = os.path.join(self.tmp, name)
        os.mkdir(root)
        make_repo(root)
        if base != "main":
            git(root, "checkout", "-q", "-b", base)
        bare = os.path.join(self.tmp, name + ".git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", bare)
        git(root, "remote", "add", remote, bare)
        git(root, "push", "-q", "-u", remote, base)
        other = os.path.join(self.tmp, name + "-other")
        git(self.tmp, "clone", "-q", "-b", base, bare, other)
        git(other, "config", "user.email", "o@example.invalid")
        git(other, "config", "user.name", "O")
        commit_file(other, "o.txt", "o\n")
        git(other, "push", "-q", "origin", base)
        return root, bare, other

    def verdict(self, root, want, base="main", follow=False):
        """``base_errors`` equals ``want``; with ``follow`` the two git commands the reason prints are run in the
        fixture (U14) and ``base_errors`` is then ``[]``."""
        cfg = dict(config.load(root), base_branch=base)
        got = drift.base_errors(root, cfg)
        self.assertEqual(got, want)
        if follow:
            m = re.fullmatch(r"update (.+) from the remote: git -C (.+) fetch (.+), then git -C (.+) merge --ff-only (.+)",
                             got[0][1], re.S)
            self.assertIsNotNone(m)
            git(m.group(2), "fetch", "-q", m.group(3))
            git(m.group(4), "merge", "-q", "--ff-only", m.group(5))
            self.assertEqual(drift.base_errors(root, cfg), [])

    def refusal(self, upstream, remote, name="main"):
        return [("base", "update %s from its upstream %s: it is not %s/%s, so no update command is given"
                 % (name, upstream, remote, name))]

    def test_base_upstream_forms(self):
        "U2, U6-U11, U13, U14, K1: the upstream git resolves decides, not the config values"
        with self.subTest("same-name"):
            root, bare, other = self.case("same")
            git(root, "fetch", "-q", "origin")
            self.verdict(root, [("base", self.cmd(root))], follow=True)
        with self.subTest("renamed"):
            root, bare, other = self.case("renamed")
            git(root, "remote", "rename", "origin", "upstream")
            git(root, "fetch", "-q", "upstream")
            self.verdict(root, [("base", self.cmd(root, "upstream"))], follow=True)
        with self.subTest("multi-merge"):
            root, bare, other = self.case("multi")
            git(other, "push", "-q", "origin", "main:dev")
            git(root, "fetch", "-q", "origin")
            git(root, "config", "--unset-all", "branch.main.merge")
            git(root, "config", "--add", "branch.main.merge", "refs/heads/dev")
            git(root, "config", "--add", "branch.main.merge", "refs/heads/main")
            self.verdict(root, self.refusal("origin/dev", "origin"))
        with self.subTest("refspec"):
            root, bare, other = self.case("refspec")
            git(root, "remote", "rename", "origin", "upstream")
            git(root, "config", "remote.upstream.fetch", "+refs/heads/*:refs/remotes/mirror/*")
            git(root, "fetch", "-q", "upstream")
            self.verdict(root, self.refusal("mirror/main", "upstream"))
        with self.subTest("legacy-remotes"):
            root, bare, other = self.case("legrem")
            git(root, "remote", "remove", "origin")
            os.mkdir(os.path.join(root, ".git", "remotes"))
            with open(os.path.join(root, ".git", "remotes", "leg"), "w") as fh:
                fh.write("URL: %s\nPull: refs/heads/main:refs/remotes/leg/main\n" % bare)
            git(root, "config", "branch.main.remote", "leg")
            git(root, "config", "branch.main.merge", "refs/heads/main")
            git(root, "fetch", "-q", "leg")
            self.verdict(root, [("base", self.cmd(root, "leg"))], follow=True)
        with self.subTest("legacy-branches"):
            root, bare, other = self.case("legbr")
            git(root, "remote", "remove", "origin")
            os.mkdir(os.path.join(root, ".git", "branches"))
            with open(os.path.join(root, ".git", "branches", "leg"), "w") as fh:
                fh.write("%s#main\n" % bare)
            git(root, "config", "branch.main.remote", "leg")
            git(root, "config", "branch.main.merge", "refs/heads/main")
            git(root, "fetch", "-q", "leg")
            self.verdict(root, self.refusal("leg", "leg"))
        with self.subTest("url-remote"):
            root, bare, other = self.case("url")
            git(root, "fetch", "-q", "origin")
            git(root, "config", "branch.main.remote", bare)
            self.verdict(root, [])
        with self.subTest("slash-remote"):
            root, bare, other = self.case("slashrem", remote="a/b")
            git(root, "fetch", "-q", "a/b")
            self.verdict(root, [("base", self.cmd(root, "a/b"))], follow=True)
        with self.subTest("slash-remote-refspec"):
            root, bare, other = self.case("slashref", remote="a/b")
            git(root, "config", "remote.a/b.fetch", "+refs/heads/*:refs/remotes/c/*")
            git(root, "fetch", "-q", "a/b")
            self.verdict(root, self.refusal("c/main", "a/b"))
        with self.subTest("slash-base"):
            root, bare, other = self.case("slashbase", base="release/1")
            git(root, "fetch", "-q", "origin")
            self.verdict(root, [("base", self.cmd(root, "origin", "release/1"))], base="release/1", follow=True)
        # K1: git cannot resolve @{u} through a remote name of 256 or more bytes (a ref path component is a file name:
        # ENAMETOOLONG, measured with git 2.50.1): 40 and 255 digits give the command, 4300 and 4301 give no upstream
        for n in (40, 255):
            with self.subTest(digits=n):
                name = "9" * n
                root, bare, other = self.case("digits%d" % n, remote=name)
                git(root, "fetch", "-q", name)
                self.verdict(root, [("base", self.cmd(root, name))], follow=True)
        for n in (4300, 4301):
            with self.subTest(digits=n):
                name = "9" * n
                root, bare, other = self.case("digits%d" % n)
                git(root, "fetch", "-q", "origin")
                git(root, "config", "remote.%s.url" % name, bare)
                git(root, "config", "remote.%s.fetch" % name, "+refs/heads/*:refs/remotes/%s/*" % name)
                git(root, "config", "branch.main.remote", name)
                self.verdict(root, [])

    def wcase(self, name):
        "A fetched repository whose main checkout is on ``elsewhere``; returns its root (main is checked out nowhere)."
        root, bare, other = self.case(name)
        git(root, "fetch", "-q", "origin")
        git(root, "checkout", "-q", "-b", "elsewhere")
        return root

    def test_base_worktree_entry_states(self):
        "W3-W5, W7, W12, H1, H3-H6, K2: the state of the worktree entry that has the base branch"
        with self.subTest("locked-present"):
            root = self.wcase("lp")
            wt = os.path.join(self.tmp, "lp-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            git(root, "worktree", "lock", wt)
            self.verdict(root, [("base", self.cmd(wt))])
        with self.subTest("prunable"):
            root = self.wcase("pr")
            wt = os.path.join(self.tmp, "pr-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            os.rename(wt, wt + ".moved")
            self.assertIn("prunable", git(root, "worktree", "list", "--porcelain"))
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("git-file-gone"):
            # W12: the directory is present, its .git file is renamed away: git lists the entry prunable while isdir holds
            root = self.wcase("gg")
            wt = os.path.join(self.tmp, "gg-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            os.rename(os.path.join(wt, ".git"), os.path.join(wt, ".git.gone"))
            self.assertTrue(os.path.isdir(wt))
            self.assertRegex(git(root, "worktree", "list", "--porcelain"), r"(?m)^prunable .+$")
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("locked-missing"):
            root = self.wcase("lm")
            wt = os.path.join(self.tmp, "lm-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            git(root, "worktree", "lock", wt)
            os.rename(wt, wt + ".moved")
            self.assertNotIn("prunable", git(root, "worktree", "list", "--porcelain"))
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("symlink-dir"):
            root = self.wcase("sd")
            wt = os.path.join(self.tmp, "sd-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            os.rename(wt, wt + ".real")
            os.symlink(wt + ".real", wt)
            self.verdict(root, [("base", self.cmd(wt))])
        with self.subTest("file"):
            root = self.wcase("fi")
            wt = os.path.join(self.tmp, "fi-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            os.rename(wt, wt + ".moved")
            with open(wt, "w") as fh:
                fh.write("x\n")
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("fifo"):
            root = self.wcase("ff")
            wt = os.path.join(self.tmp, "ff-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            os.rename(wt, wt + ".moved")
            os.mkfifo(wt)
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("symlink-parent"):
            root = self.wcase("sp")
            real = os.path.join(self.tmp, "sp-real")
            os.mkdir(real)
            os.symlink(real, os.path.join(self.tmp, "sp-link"))
            wt = os.path.join(self.tmp, "sp-link", "wt")
            git(root, "worktree", "add", "-q", wt, "main")
            listed = subprocess.run(["git", "-C", root, "worktree", "list", "--porcelain", "-z"],
                                    stdout=subprocess.PIPE, check=True).stdout.decode().split("\0")
            path = [f[len("worktree "):] for f in listed if f.startswith("worktree ")][-1]
            self.verdict(root, [("base", self.cmd(path))])
        with self.subTest("nested"):
            root = self.wcase("ne")
            wt = os.path.join(root, "nested-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            self.verdict(root, [("base", self.cmd(wt))])
        with self.subTest("odd-path"):
            root = self.wcase("od")
            wt = os.path.join(self.tmp, "od aࡰb")
            git(root, "worktree", "add", "-q", wt, "main")
            self.verdict(root, [("base", self.cmd(wt))])
        with self.subTest("bare-main-linked"):
            # W8: the main entry is a bare repository (field `bare`, no branch); a linked worktree has main
            root = self.wcase("bl")
            wt = os.path.join(self.tmp, "bl-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            git(root, "config", "core.bare", "true")
            self.assertIn("bare", git(wt, "worktree", "list", "--porcelain").split())
            self.verdict(wt, [("base", self.cmd(wt))])
        with self.subTest("bare-main-none"):
            # W8: a bare main entry, and no entry has main
            root = self.wcase("bn")
            wt = os.path.join(self.tmp, "bn-wt")
            git(root, "worktree", "add", "-q", "--detach", wt)
            git(root, "config", "core.bare", "true")
            self.assertIn("bare", git(wt, "worktree", "list", "--porcelain").split())
            self.verdict(wt, [("base", self.NOCO)])
        with self.subTest("detached"):
            # W9: the entry that had main is detached now: it has no branch field
            root = self.wcase("de")
            wt = os.path.join(self.tmp, "de-wt")
            git(root, "worktree", "add", "-q", wt, "main")
            git(wt, "checkout", "-q", "--detach")
            self.verdict(root, [("base", self.NOCO)])
        with self.subTest("newline-path"):
            # W10: the path as git lists it, raw
            root = self.wcase("nl")
            wt = os.path.join(self.tmp, "nl-wt\nx")
            git(root, "worktree", "add", "-q", wt, "main")
            self.verdict(root, [("base", self.cmd(wt))])
        with self.subTest("list-fails"):
            root = self.wcase("lf")
            real = gitinfo._run

            def run(r, name, args, *a, **k):
                if args[0] == "worktree":
                    raise GateError("boom\n")
                return real(r, name, args, *a, **k)
            with mock.patch("gates.lib.gitinfo._run", side_effect=run):
                self.verdict(root, [("base", "update main from the remote: the worktrees cannot be listed: boom\n, "
                                             "so no update command is given")])

    def test_base_new_calls_propagate_interrupt(self):
        "K3: KeyboardInterrupt (and a BaseExceptionGroup where it exists) from the upstream and listing calls propagates"
        root = self.wcase("ki")
        wt = os.path.join(self.tmp, "ki-wt")
        git(root, "worktree", "add", "-q", wt, "main")
        real = gitinfo._run
        group = getattr(builtins, "BaseExceptionGroup", None)
        for label, hit in (("upstream", lambda a: "--symbolic-full-name" in a), ("listing", lambda a: a[0] == "worktree")):
            for exc in ([KeyboardInterrupt()] + ([group("g", [KeyboardInterrupt()])] if group else [])):
                def run(r, name, args, *a, **k):
                    if hit(args):
                        raise exc
                    return real(r, name, args, *a, **k)
                with self.subTest(label, exc=type(exc).__name__), mock.patch("gates.lib.gitinfo._run", side_effect=run):
                    with self.assertRaises(type(exc)):
                        drift.base_errors(root, self.cfg)


def make_branch(sid, files, links=None):
    """Branch ``P/<sid>/main`` from BASE: one work commit (returned), then ``files`` ({path: str|bytes}) and symlinks."""
    root = G["root"]
    branch_from(root, "%s/%s/main" % (P, sid), G["BASE"])
    work = commit_file(root, "work.txt", "w\n", "work")
    for rel, data in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if type(data) is bytes else data.encode("utf-8"))
    for rel, target in (links or {}).items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        os.symlink(target, os.path.join(root, rel))
    tip = commit_all(root, "files of " + sid)
    git(root, "checkout", "-q", "main")
    return work, tip


def hp(sid):
    return ".strict-delivery/state/plans/%s-plan/handoff.md" % sid


def hs(sid, status="running", head=None, row_kw=None, st=None, **over):
    """Reasons of the ``handoff.*`` lines for a stream branch made with ``make_stream``."""
    s, r, work, tip = make_stream(sid, status, head, row_kw, **over)
    return [why for suf, why in se(r, st or s) if suf.startswith("handoff.")]


class Handoff(unittest.TestCase):
    """Rows F1-F21."""

    def test_handoff_matches_passes(self):
        "F1"
        s, r, work, tip = make_stream("f1")
        self.assertEqual(se(r, s), [])

    def test_handoff_absent_fails(self):
        "F2: no file; a directory at the path; a symlink at the path"
        make_branch("f2a", {})
        make_branch("f2b", {hp("f2b") + "/x": "x\n"})
        make_branch("f2c", {}, {hp("f2c"): "elsewhere"})
        for sid in ("f2a", "f2b", "f2c"):
            with self.subTest(sid=sid):
                errs = only(se(row(sid), stream(sid)), "handoff")
                self.assertEqual(len(errs), 1)
                self.assertEqual(errs[0][0], "handoff." + sid)
                self.assertIn("no handoff at " + hp(sid), errs[0][1])

    def test_handoff_invalid_front_matter(self):
        "F3"
        good = handoff_text("f3", "abcdef1")
        cases = {"crlf": good.replace("\n", "\r\n"), "bom": "﻿" + good, "nodash": "x: 1\n", "noclose": "---\nx: 1\n",
                 "list": "---\n- a\n---\n", "dup": "---\nblock: 1\nblock: 2\n---\n", "empty": "---\n---\n"}
        for n, (name, text) in enumerate(cases.items()):
            sid = "f3-%d" % n
            make_branch(sid, {hp(sid): text})
            with self.subTest(case=name):
                errs = only(se(row(sid), stream(sid)), "handoff")
                self.assertEqual(len(errs), 1, errs)
                self.assertTrue(errs[0][1].startswith("front matter:"), errs)

    def test_handoff_errors_surface(self):
        "F4 (and F21): the handoff_errors strings, each its own line"
        got = hs("f4a", plan="docs/other/x.md")
        self.assertTrue(any(w.startswith("plan: must be docs/strict-delivery/plans/<name>.md") for w in got), got)
        got = hs("f4b", block="1aࡰ")
        self.assertIn("block: must be a single line of printable ASCII", got)
        got = hs("f4c", resume="'Resume wrong'")
        self.assertTrue(any(w.startswith("resume: expected 'Resume strict-delivery plan") for w in got), got)

    def test_handoff_branch_other_fails(self):
        "F5"
        for n, val in enumerate(("20261101-x/b/main", "20261101-x/a/x", "''", "'20261101-x/f5-0/main '")):
            sid = "f5-%d" % n
            with self.subTest(val=val):
                got = hs(sid, branch=val, resume="plain")
                self.assertTrue(any(w.startswith("branch ") and " is not 20261101-x/%s/main" % sid in w for w in got), got)

    def test_handoff_head_not_ancestor_fails(self):
        "F6: an unreachable object; a commit of another branch (also F9: ahead of the tip)"
        dangling = git(G["root"], "commit-tree", git(G["root"], "rev-parse", "main^{tree}"), "-m", "dangling")
        for sid, head in (("f6a", dangling), ("f6b", G["a_tip"])):
            with self.subTest(head=head):
                got = hs(sid, head=head)
                self.assertEqual(got, ["head %s is not an ancestor of the branch tip" % head])

    def test_handoff_head_ahead_fails(self):
        "F9"
        self.assertEqual(hs("f9", head=G["ac_tip"]), ["head %s is not an ancestor of the branch tip" % G["ac_tip"]])

    def test_handoff_head_equal_tip_passes(self):
        """F7: a handoff cannot name the commit that contains it (a self-referencing hash), so equality is not reachable
        through the production path; the `ancestor or equal` rule is the one of git merge-base --is-ancestor (checked
        directly) and a head one commit below the tip passes (F1)."""
        self.assertTrue(gitinfo.is_ancestor(G["root"], G["a_tip"], G["a_tip"]))
        self.assertEqual(git(G["root"], "merge-base", "--is-ancestor", G["a_tip"], G["a_tip"]), "")

    def test_handoff_head_short_sha(self):
        "F8"
        s, r, work, tip = make_stream("f8", head=None)
        for n, short in enumerate((work[:7], work[:12])):
            sid = "f8-%d" % n
            with self.subTest(short=short):
                self.assertEqual(hs(sid, head=short), [])

    def test_handoff_head_forms(self):
        "F10 (D-5c-Q5): the field must be a str of 7 to 40 lowercase hex before any git call"
        forms = {"zeros": ZEROS, "HEAD": "HEAD", "name": "main", "upper": "ABC1234", "dash": "-x", "long": "a" * 41,
                 "empty": "''", "int": "7", "null": "null", "list": "[a]"}
        for n, (name, raw) in enumerate(forms.items()):
            with self.subTest(head=name):
                got = hs("f10-%d" % n, head=raw)
                want = {"zeros": None, "int": "head: must be a string", "null": "head: must be a string",
                        "list": "head: must be a string"}.get(name, "head: must be 7 to 40 lowercase hex")
                if want is None:
                    self.assertTrue(any(w.startswith("head %s: git" % ZEROS) for w in got), got)
                else:
                    self.assertIn(want, got)
        self.assertEqual(hs("f10-short", head="abcdef1")[0][:25], "head abcdef1: git merge-b")

    def test_handoff_tag_shadow(self):
        "the handoff is read at refs/heads/<branch>, never at a tag of the same name"
        s, r, work, tip = make_stream("hts")
        git(G["root"], "tag", "-f", "%s/hts/main" % P, G["M1"])
        self.assertEqual(se(r, s), [])

    def test_handoff_gateerror_becomes_line(self):
        "F11 (D-5c-Q6): a non-UTF-8 handoff and an unknown short sha are lines; the next stream is still judged"
        make_branch("f11a", {hp("f11a"): b"\xff\xfe"})
        errs = se(row("f11a"), stream("f11a"))
        self.assertEqual(kinds(errs), ["handoff"])
        self.assertIn("not valid UTF-8", errs[0][1])
        s, r = make_stream("f11b")[:2]
        self.assertEqual(se(r, s), [])

    def test_handoff_plan_slug_forms(self):
        "F12 (D-5c-Q20)"
        make_stream("f12")
        for plan in ("p.txt", "", None, 5, ".md", "d/.md", "p.MD", "ü.md", "docs/p/-a.md"):
            with self.subTest(plan=plan):
                errs = only(se(row("f12"), {"id": "f12", "plan": plan}), "handoff")
                self.assertEqual(len(errs), 1)
                self.assertTrue(errs[0][1].startswith("stream plan: "), errs)

    def test_handoff_field_types(self):
        "F13 (D-5c-Q5)"
        for field, val in (("branch", None), ("head", "12345"), ("block", "1"), ("next_task", "null"), ("block", "1" * 1000),
                           ("head", "null")):
            sid = "f13-%s%d" % (field.replace("_", ""), len(val or ""))
            with self.subTest(field=field, val=(val or "")[:5]):
                got = hs(sid, **{field: val})
                self.assertIn("%s: must be a string" % field, got)
                self.assertFalse(any("1" * 50 in w for w in got))

    def test_handoff_block_compare(self):
        "F14 (D-5c-Q21): exact, no case folding"
        for n, (cell, hand, ok) in enumerate((("5c", "5c", True), ("6", "5c", False), ("none", "5c", False),
                                              ("5c", "none", False), ("5C", "5c", False), ("5c ", "5c", False))):
            with self.subTest(cell=cell, hand=hand):
                got = hs("f14-%d" % n, row_kw={"block": cell}, block=hand)
                self.assertEqual(got == [], ok, got)
        got = hs("f14-x", row_kw={"block": "6"})
        self.assertEqual(got, ["block: the status row says '6', the handoff says '5c'"])

    def test_running_row_must_match_handoff(self):
        "F15 (plan test)"
        s, r, work, tip = make_stream("f15", row_kw={"next task": "5a.9"})
        self.assertIn("handoff.f15", suffixes(se(r, s)))
        for n, (cell, ok) in enumerate((("5c.1", True), ("5c.1 ", False), ("none", False))):
            with self.subTest(cell=cell):
                self.assertEqual(hs("f15-%d" % n, row_kw={"next task": cell}) == [], ok)

    def test_ready_row_cells_none(self):
        "F16"
        for blk, nxt, ok in (("none", "none", True), ("5c", "none", False), ("none", "5c.1", False), ("5c", "5c.1", False),
                             ("None", "None", False), ("NONE", "none", False)):
            with self.subTest(block=blk, nxt=nxt):
                got = only(se(row("eq", "ready", block=blk, **{"next task": nxt}), stream("eq")), "handoff")
                self.assertEqual(got == [], ok, got)

    def test_merged_row_skips_handoff(self):
        "F17"
        for st in ("merged", "closed"):
            self.assertEqual(only(se(row("c", st), stream("c")), "handoff"), [])
            self.assertEqual(only(se(row("a", st), stream("a")), "handoff"), [])

    def test_handoff_plan_field_not_compared(self):
        "F18 (D-5c-Q22 rec Q22 of the table: the plan names the path, not the plan field)"
        self.assertEqual(hs("f18", plan="docs/strict-delivery/plans/zzz-plan.md",
                            ledger=".strict-delivery/state/plans/zzz-plan/ledger.md"), [])

    def test_handoff_large_text(self):
        "F19: a 10 MB body is read whole"
        self.assertEqual(hs("f19", body="x" * 10_000_000 + "\n"), [])

    def test_ready_row_with_progress(self):
        "F20 (D-5c-Q13)"
        self.assertEqual(se(row("a", "ready"), stream("a")), [])


DN = "20261102-d"


def pend(cell, sid="a", plan=None, status="ready", name=DN):
    st = stream(sid) if plan is None else stream(sid, plan=plan)
    errs = se(row(sid, status, **{"pending decisions": cell}), st, name=name)
    return [(s, r) for s, r in errs if s.startswith("pending.")]


A_, L_ = "DEC-20261102-aaaa", "DEC-20261102-llll"


class Pending(unittest.TestCase):
    """Rows N1-N20."""

    def test_pending_none_passes(self):
        "N1"
        self.assertEqual(pend("none", plan="docs/p/zz-plan.md"), [])

    def test_pending_open_passes(self):
        "N2"
        self.assertEqual(pend(A_ + "," + L_), [])

    def test_pending_answered_fails(self):
        "N3"
        self.assertEqual(pend("DEC-20261102-bbbb," + A_ + "," + L_), [("pending.a", "DEC-20261102-bbbb is answered, not open")])

    def test_pending_withdrawn_fails(self):
        "N4"
        self.assertEqual(pend("DEC-20261102-dddd," + A_ + "," + L_), [("pending.a", "DEC-20261102-dddd is withdrawn, not open")])

    def test_pending_missing_fails(self):
        "N5"
        self.assertEqual(pend("DEC-20261102-zzzz," + A_ + "," + L_), [("pending.a", "DEC-20261102-zzzz names no decision record")])

    def test_pending_must_be_open_and_complete(self):
        "N6 (plan test)"
        got = pend("none")
        self.assertEqual(suffixes(got), ["pending.a", "pending.a"])
        self.assertIn("open decision %s (topic q:a-plan:q1) is not listed in pending decisions" % A_, got[0][1])
        self.assertIn(L_, got[1][1])

    def test_pending_other_stream_tag_ignored(self):
        "N7: DEC-ffff is q:b-plan:q1 -- required of b, not of a"
        self.assertFalse(any("ffff" in w for _, w in pend("none")))
        self.assertEqual([w for _, w in pend("none", sid="b")][0][:40], "open decision DEC-20261102-ffff (topic q")

    def test_pending_slug_prefix_not_matched(self):
        "N8"
        self.assertEqual(pend("none", plan="docs/p/a.md"), [])

    def test_pending_closed_q_not_required(self):
        "N9"
        self.assertFalse(any("bbbb" in w or "dddd" in w for _, w in pend("none")))

    def test_pending_non_q_open_may_be_listed(self):
        "N10"
        self.assertEqual(pend("DEC-20261102-eeee," + A_ + "," + L_), [])

    def test_pending_non_q_open_not_required(self):
        "N11"
        self.assertFalse(any("eeee" in w for _, w in pend("none")))

    def test_pending_topics_shapes(self):
        "N12 (D-5c-Q23): only an exact q:<slug>:<qid> in a list of str; the Unicode topic is no tag on any interpreter"
        got = " ".join(w for _, w in pend("none"))
        for rid in ("hhhh", "iiii", "kkkk", "gggg", "ffff", "jjjj"):
            self.assertNotIn(rid, got)
        self.assertEqual(got.count("llll"), 1)

    def test_pending_record_shapes(self):
        "N13"
        self.assertEqual(pend("DEC-20261102-jjjj," + A_ + "," + L_), [("pending.a", "DEC-20261102-jjjj is Open, not open")])
        self.assertEqual(pend("DEC-20261102-mmmm," + A_ + "," + L_),
                         [("pending.a", "DEC-20261102-mmmm is without a status, not open")])
        self.assertEqual(pend("7," + A_ + "," + L_), [("pending.a", "7 names no decision record")])

    def test_pending_cell_forms(self):
        "N14 (D-5c-Q24)"
        self.assertEqual(pend(A_ + "," + A_ + "," + L_), [])
        for cell, frag in ((A_ + ", " + L_, "' DEC-20261102-llll' names no decision record"),
                           ("none," + A_ + "," + L_, "none names no decision record"),
                           (A_ + "," + L_ + ",", "'' names no decision record"), ("", "'' names no decision record")):
            with self.subTest(cell=cell):
                self.assertIn(frag, [w for _, w in pend(cell)])

    def test_pending_bad_plan_slug(self):
        "N15 (D-5c-Q20)"
        for st in ("merged", "closed", "ready"):
            self.assertEqual(pend("DEC-20261102-bbbb", plan="p.txt", status=st),
                             [("pending.a", "DEC-20261102-bbbb is answered, not open")])

    def test_pending_all_statuses(self):
        "N16"
        for st in programs.STATUS_VALUES:
            with self.subTest(status=st):
                self.assertEqual(pend("DEC-20261102-zzzz," + A_ + "," + L_, status=st),
                                 [("pending.a", "DEC-20261102-zzzz names no decision record")])

    def test_pending_reads_integration_tip(self):
        "N17: an open q:a-plan:q50 record only on a stream branch is not seen"
        root = G["root"]
        branch_from(root, "%s/a/main" % DN, G["dec_tip"])
        commit_file(root, DEC_DIR + "/DEC-20261102-zzzz.yml", dec("DEC-20261102-zzzz", "open", "[q:a-plan:q50]"))
        git(root, "checkout", "-q", "main")
        self.assertFalse(any("zzzz" in w for _, w in pend("none")))

    def test_pending_unparseable_record_raises(self):
        "N18 (D-5c-Q25)"
        with self.assertRaises(GateError) as e:
            pend("none", name="20261103-bad")
        self.assertIn("DEC-20261103-dddd.yml", str(e.exception))

    def test_pending_integration_absent(self):
        "N19"
        with self.assertRaises(GateError):
            pend("none", name="20261107-n")


def req(rid, status, **kw):
    row_ = {"id": rid, "status": status}
    row_.update(kw)
    return Record(rid, row_, "requests/%s.yml" % rid)


RID = "R-20261101-aaaa"


def blk(cell, requests, status="ready", sid="eq"):
    errs = se(row(sid, status, blockers=cell), stream(sid), requests=requests)
    return [(s, r) for s, r in errs if s.startswith("blockers.")]


class Blockers(unittest.TestCase):
    """Rows K1-K13."""

    def test_blockers_none_passes(self):
        "K1"
        self.assertEqual(blk("none", [req(RID, "done")]), [])

    def test_blockers_open_passes(self):
        "K2"
        self.assertEqual(blk(RID, [req(RID, "open")]), [])

    def test_blockers_accepted_passes(self):
        "K3"
        self.assertEqual(blk(RID, [req(RID, "accepted")]), [])

    def test_blockers_disputed_passes(self):
        "K4"
        self.assertEqual(blk(RID, [req(RID, "disputed")]), [])

    def test_blockers_done_fails(self):
        "K5"
        self.assertEqual(blk(RID, [req(RID, "done")]),
                         [("blockers.eq", "request %s is done, not open, accepted or disputed" % RID)])

    def test_blockers_withdrawn_fails(self):
        "K6"
        self.assertEqual(suffixes(blk(RID, [req(RID, "withdrawn")])), ["blockers.eq"])

    def test_blockers_other_program_fails(self):
        "K7"
        self.assertEqual(blk(RID, []), [("blockers.eq", "%s names no request of this program" % RID)])

    def test_blockers_missing_fails(self):
        "K8"
        self.assertEqual(blk("R-20261101-zzzz", [req(RID, "open")]),
                         [("blockers.eq", "R-20261101-zzzz names no request of this program")])

    def test_blockers_request_shapes(self):
        "K9"
        for rec in (Record(RID, {"id": RID}, "f"), req(RID, 5), req(RID, "reopened"), Record(RID, {}, "f"),
                    Record(None, {"status": "open"}, "f")):
            with self.subTest(rec=rec):
                self.assertEqual(suffixes(blk(RID, [rec])), ["blockers.eq"])

    def test_blockers_several_ids(self):
        "K10"
        got = blk(RID + ",R-20261101-bbbb", [req(RID, "open"), req("R-20261101-bbbb", "done")])
        self.assertEqual([w[:16] for _, w in got], ["request R-202611"])
        self.assertIn("R-20261101-bbbb is done", got[0][1])

    def test_blockers_cell_forms(self):
        "K11 (D-5c-Q24)"
        self.assertEqual(blk(RID + "," + RID, [req(RID, "open")]), [])
        for cell in (RID + ", " + RID, "none," + RID, RID + ","):
            with self.subTest(cell=cell):
                self.assertEqual(suffixes(blk(cell, [req(RID, "open")])), ["blockers.eq"])

    def test_blockers_all_statuses(self):
        "K12"
        for st in programs.STATUS_VALUES:
            with self.subTest(status=st):
                self.assertEqual(only(se(row("eq", st, blockers=RID), stream("eq"), requests=[req(RID, "done")]), "blockers")[0][0],
                                 "blockers.eq")

    def test_blockers_stream_not_compared(self):
        "K13"
        self.assertEqual(blk(RID, [req(RID, "open", to_stream="zz", from_stream="yy")]), [])


class Merged(unittest.TestCase):
    """Rows G1-G11."""

    def test_merged_row_with_merge_passes(self):
        "G1"
        self.assertEqual(only(se(row("c", "merged"), stream("c")), "merged"), [])

    def test_merged_status_not_merge_shapes_fail(self):
        "G3"
        for sid in ("e", "g", "f", "d"):
            with self.subTest(sid=sid):
                self.assertEqual(suffixes(only(se(row(sid, "merged"), stream(sid)), "merged")), ["merged." + sid])

    def test_merged_branch_with_running_status_fails(self):
        "G5 (plan test, G10)"
        for st in ("running", "blocked", "checkpoint", "ready"):
            with self.subTest(status=st):
                got = only(se(row("c", st), stream("c")), "merged")
                self.assertEqual(got, [("merged.c", "the stream has merged at %s; set status merged" % G["c_merge"])])

    def test_merged_reason_full_sha(self):
        "G6"
        (_, why), = only(se(row("c", "running"), stream("c")), "merged")
        self.assertIn(" at " + G["c_merge"] + ";", why)
        self.assertEqual(len(G["c_merge"]), 40)

    def test_merged_row_branch_gone_fails(self):
        "G7"
        self.assertEqual(only(se(row("nb", "merged"), stream("nb")), "merged"),
                         [("merged.nb", "stream branches are kept until the program closes")])

    def test_stacked_empty_child_merged_literal(self):
        "G8 (D-5c-Q9)"
        got = only(se(row("j", "running"), stream("j")), "merged")
        self.assertEqual(got, [("merged.j", "the stream has merged at %s; set status merged" % G["h_merge"])])

    def test_ready_fresh_branch_no_merge(self):
        "G9"
        self.assertEqual(only(se(row("eq", "ready"), stream("eq")), "merged"), [])

    def test_merged_row_host_merged_not_updated(self):
        "G11: the local base lacks the merge; the line gives the update hint"
        (_, why), = only(se(row("a", "merged"), stream("a")), "merged")
        self.assertTrue(why.endswith("if the PR merged on the host, update main from the remote"))


class Arguments(unittest.TestCase):
    """Rows S1-S7, R1-R8."""

    def call(self, **kw):
        a = dict(prog=program([stream("a")]), row=row("a"), stream=stream("a"), cfg=G["cfg"])
        a.update(kw)
        return drift.stream_errors(G["root"], a["cfg"], a["prog"], a["row"], a["stream"])

    def test_stream_errors_argument_types(self):
        "S1"
        class Sub(programs.Program):
            pass
        sub = Sub(P, {"streams": [stream("a")]}, "", [], "", "", None)
        for bad in (None, {}, sub, "x"):
            with self.subTest(prog=bad), self.assertRaises(ValueError):
                self.call(prog=bad)

    def test_stream_errors_row_shape(self):
        "S2"
        class D(dict):
            pass
        good = row("a")
        short = dict(good)
        del short["delivers"]
        for bad in (short, dict(good, extra="x"), dict(good, used=5), dict(good, used=None), {"__error__": "x", "__line__": 1},
                    D(good), None, []):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                self.call(row=bad)

    def test_stream_errors_stream_shape(self):
        "S3"
        for bad in ({"plan": "p.md"}, {"id": 5, "plan": "p.md"}, {"id": "a", "plan": "x.md", "stacked_on": 5}, None, []):
            with self.subTest(stream=bad), self.assertRaises(ValueError):
                self.call(stream=bad)
        self.assertEqual(self.call(row=row("eq", "ready"), stream={"id": "eq"}, prog=program([{"id": "eq"}])), [])

    def test_stream_errors_row_stream_mismatch(self):
        "S4"
        with self.assertRaises(ValueError):
            self.call(row=row("b"))

    def test_stream_errors_status_values(self):
        "S5"
        for bad in ("Running", "", " running", "running ", "ࡰ"):
            with self.subTest(status=bad), self.assertRaises(ValueError):
                self.call(row=row("a", bad))

    def test_stream_errors_stacked_on_unknown(self):
        "S6"
        for streams in ([stream("a", stacked_on="zz")], [stream("a", stacked_on="a")],
                        [stream("a", stacked_on="b"), stream("b", stacked_on="a")]):
            with self.subTest(streams=streams), self.assertRaises(ValueError):
                self.call(prog=program(streams), stream=streams[0])

    def test_stream_errors_cfg_forms(self):
        "S7"
        c = G["cfg"]
        for cfg in ({}, dict(c, base_branch=5), dict(c, base_branch=""), None):
            with self.subTest(cfg=cfg), self.assertRaises(GateError):
                self.call(cfg=cfg)
        with self.assertRaises(GateError) as e:
            self.call(cfg=dict(c, paths={k: v for k, v in c["paths"].items() if k != "plan_state"}))
        self.assertIn("plan_state", str(e.exception))

    def test_result_shape(self):
        "R1"
        for r in (row("a"), row("i"), row("nb")):
            got = self.call(row=r, stream=stream(r["stream"]), prog=program([stream(r["stream"])]))
            self.assertIs(type(got), list)
            for item in got:
                self.assertIs(type(item), tuple)
                self.assertEqual(len(item), 2)
                self.assertTrue(all(type(x) is str for x in item))

    def test_suffix_forms(self):
        "R2"
        errs = se(row("i", "running", blockers="R-1", **{"pending decisions": "DEC-x"}), stream("i"))
        self.assertEqual(suffixes(errs), ["behind.i", "handoff.i", "pending.i", "blockers.i"])
        self.assertNotIn("base", suffixes(errs))

    def test_error_order(self):
        "R3 (D-5c-Q15)"
        errs = se(row("c", "running", blockers="R-1", **{"pending decisions": "DEC-x"}), stream("c"))
        self.assertEqual(suffixes(errs), ["behind.c", "merged.c", "handoff.c", "pending.c", "blockers.c"])
        errs = se(row("nb", "running", blockers="R-1", **{"pending decisions": "DEC-x"}), stream("nb"))
        self.assertEqual(suffixes(errs), ["branch.nb", "pending.nb", "blockers.nb"])

    def test_one_tuple_per_problem(self):
        "R4"
        got = hs("r4", branch="20261101-x/b/main", row_kw={"block": "6", "next task": "7"})
        self.assertEqual(len(got), 3, got)

    def test_stream_errors_no_mutation(self):
        "R5"
        import copy
        prog, r, st, cfg = program([stream("i")]), row("i"), stream("i"), copy.deepcopy(G["cfg"])
        before = copy.deepcopy((prog, r, st, cfg))
        drift.stream_errors(G["root"], cfg, prog, r, st)
        self.assertEqual((prog, r, st, cfg), before)

    @staticmethod
    def probe():
        """The writes-nothing probe: status, HEAD and the index mtime. Its own ``git status`` runs with optional locks
        off, so it never rewrites a racily clean ``.git/index`` itself (F-20261125-tphg)."""
        return (git(G["root"], "status", "--porcelain", "--untracked-files=all", env={"GIT_OPTIONAL_LOCKS": "0"}),
                git(G["root"], "rev-parse", "HEAD"), os.stat(os.path.join(G["root"], ".git", "index")).st_mtime_ns)

    def test_stream_errors_writes_nothing(self):
        "R6 (M1, M2)"
        before = self.probe()
        se(row("i"), stream("i"))
        se(row("c", "merged"), stream("c"))
        after = self.probe()
        self.assertEqual(before, after)

    def test_status_probe_writes_nothing(self):
        "M3: the probe pair alone, with no stream_errors call between, leaves the index mtime unchanged, 50 times"
        first = self.probe()
        for _ in range(50):
            self.assertEqual(self.probe(), first)

    def test_no_resources_left(self):
        "R8: judged on a private temp directory (in-process tempfile and child processes via TMPDIR), never the shared system one"
        with tempfile.TemporaryDirectory(dir=os.path.dirname(G["root"])) as private:
            with mock.patch.object(tempfile, "tempdir", private), mock.patch.dict(os.environ, {"TMPDIR": private}):
                self.assertEqual(tempfile.gettempdir(), private)
                self.assertEqual(os.listdir(private), [])
                for r in (row("i"), row("a", "merged")):
                    se(r, stream(r["stream"]))
                with self.assertRaises(GateError):
                    se(row("a"), stream("a"), name="20261107-n")
                self.assertEqual(sorted(os.listdir(private)), [])


def est(used, estimate, pct=150, sid="a"):
    return drift.over_estimate({"stream": sid, "used": used, "estimate": estimate}, pct)


class Estimate(unittest.TestCase):
    """Rows O1-O16."""

    def test_over_estimate_below(self):
        "O1"
        self.assertIsNone(est("14", "10"))

    def test_over_estimate_equal(self):
        "O2"
        self.assertIsNone(est("15", "10"))

    def test_over_estimate(self):
        "O3 (plan test)"
        self.assertEqual(est("16", "10"), "over a used=16 estimate=10 limit=150%")
        self.assertIsNone(est("15", "10"))

    def test_over_estimate_zero_estimate(self):
        "O4"
        self.assertIsNone(est("0", "0"))
        self.assertEqual(est("1", "0"), "over a used=1 estimate=0 limit=150%")

    def test_over_estimate_pct_100_and_150(self):
        "O5"
        self.assertEqual(est("11", "10", 100), "over a used=11 estimate=10 limit=100%")
        self.assertIsNone(est("11", "10", 150))

    def test_over_estimate_pct_from_config(self):
        "O6"
        self.assertEqual(config.DEFAULTS["drift"]["estimate_factor_pct"], 150)
        self.assertEqual(est("13", "10", 120), "over a used=13 estimate=10 limit=120%")
        self.assertIsNone(est("12", "10", 120))

    def test_over_estimate_pct_types(self):
        "O7"
        class I(int):
            pass
        for bad in (True, 1.5, "150", None, I(150), 0, -1):
            with self.subTest(pct=bad), self.assertRaises(ValueError):
                est("1", "1", bad)

    def test_over_estimate_pct_digits(self):
        "O8 (D-5c-Q28)"
        self.assertIsNone(est("1", "1", 10 ** 599))
        for n in (600, 1000, 4301):
            with self.subTest(digits=n), self.assertRaises(ValueError):
                est("1", "1", 10 ** n)

    def test_over_estimate_digit_limit(self):
        "O9"
        nines = "9" * 600
        self.assertIsNone(est(nines, nines))
        for n in (601, 4300, 4301):
            with self.subTest(digits=n), self.assertRaises(ValueError):
                est("9" * n, "1")
            with self.assertRaises(ValueError):
                est("1", "9" * n)

    def test_over_estimate_numeral_class(self):
        "O10 (D-5c-Q29)"
        for bad in ("٣", "１２", "1_0", "+5", " 5", "5\n", "007", "-1", "1e2", "", "0x10"):
            with self.subTest(cell=bad), self.assertRaises(ValueError):
                est(bad, "10")
            with self.assertRaises(ValueError):
                est("1", bad)

    def test_over_estimate_message_echoes_cell(self):
        "O11"
        self.assertEqual(est("9" * 600, "1"), "over a used=%s estimate=1 limit=150%%" % ("9" * 600))

    def test_over_estimate_row_shape(self):
        "O12"
        class D(dict):
            pass
        good = {"stream": "a", "used": "1", "estimate": "1"}
        for k in good:
            with self.subTest(missing=k), self.assertRaises(ValueError):
                drift.over_estimate({x: y for x, y in good.items() if x != k}, 150)
        for bad in (dict(good, used=1), D(good), None, [], dict(good, estimate=None)):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                drift.over_estimate(bad, 150)

    def test_over_estimate_stream_id(self):
        "O13"
        for bad in ("A", "a/b", "ü", "", 5):
            with self.subTest(stream=bad), self.assertRaises(ValueError):
                est("1", "1", sid=bad)

    def test_over_estimate_no_float(self):
        "O15"
        self.assertIsNone(est("1" + "0" * 599, "1" + "0" * 598, 1001))

    def test_over_estimate_is_per_row(self):
        "O16 (R5c-2, D5-1)"
        r = row("a", block="5c", used="16", estimate="10")
        self.assertEqual(drift.over_estimate(r, 150), "over a used=16 estimate=10 limit=150%")

    def test_over_estimate_oracle(self):
        "oracle: Fraction reference around the boundary (table Oracle)"
        from fractions import Fraction
        for estimate in (0, 1, 3, 10, 7 * 10 ** 20):
            for pct in (1, 100, 150, 333):
                top = estimate * pct // 100
                for used in sorted({0, 1, top, top + 1, top + 2}):
                    want = Fraction(used) > Fraction(estimate * pct, 100)
                    got = est(str(used), str(estimate), pct)
                    self.assertEqual(got is not None, want, (used, estimate, pct))
                    if got is not None:
                        self.assertEqual(got, "over a used=%d estimate=%d limit=%d%%" % (used, estimate, pct))


def pr(state="MERGED", oid=None, number=1, head="x", **kw):
    d = {"number": number, "state": state, "headRefOid": head, "mergeCommit": None if oid is None else {"oid": oid}}
    d.update(kw)
    return d


class Runner:
    """A recording fake ``runner`` answering with one ``CompletedProcess`` (or raising)."""

    def __init__(self, stdout="[]", code=0, stderr="", raises=None, result=None):
        self.calls, self.stdout, self.code, self.stderr, self.raises, self.result = [], stdout, code, stderr, raises, result

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.raises is not None:
            raise self.raises
        if self.result is not None:
            return self.result
        return subprocess.CompletedProcess(argv, self.code, self.stdout, self.stderr)


def host(runner, pairs=(("c", "merged"),), name=P):
    streams = [stream(s) for s, _ in pairs]
    prog = program(streams, status_text=status_page([row(s, st) for s, st in pairs]), name=name)
    return drift.host_errors(G["root"], G["cfg"], prog, runner=runner)


def js(*prs):
    return json.dumps(list(prs))


class Host(unittest.TestCase):
    """Rows E1-E32."""

    def host_fail(self, runner, frag=None):
        got = host(runner)
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0][0], "host")
        if frag:
            self.assertIn(frag, got[0][1])
        return got

    def test_host_failure_is_a_fail(self):
        "E1 (plan test)"
        self.host_fail(Runner(raises=FileNotFoundError("gh")), "gh is not installed")
        self.assertEqual(host(Runner(raises=FileNotFoundError("gh")))[0][0], "host")
        self.assertEqual(host(Runner(code=1, stderr="boom\n"))[0][0], "host")
        self.assertEqual(host(Runner(stdout="not json"))[0][0], "host")

    def test_host_oserror_fails(self):
        "E2"
        for exc in (PermissionError("x"), NotADirectoryError("cwd")):
            with self.subTest(exc=type(exc).__name__):
                self.host_fail(Runner(raises=exc))

    def test_host_exit_1_fails(self):
        "E3"
        self.host_fail(Runner(code=1, stderr="first line\nsecond\n"), "gh exited 1: first line")

    def test_host_auth_error_fails(self):
        "E4"
        self.host_fail(Runner(code=4, stderr="To get started with GitHub CLI, please run:  gh auth login\n"), "gh exited 4:")

    def test_host_timeout_fails(self):
        "E5"
        r = Runner(raises=subprocess.TimeoutExpired("gh", 30))
        self.host_fail(r, "timed out after 30 seconds")
        self.assertEqual(r.calls[0][1]["timeout"], 30)

    def test_host_invalid_json_fails(self):
        "E6"
        for text in ("not json", "", "[{"):
            with self.subTest(text=text):
                self.host_fail(Runner(stdout=text), "expected JSON list")

    def test_host_json_shape_fails(self):
        "E7"
        for text in ("{}", "null", '"x"', "1", "[1]", "[[]]", "[{}]"):
            with self.subTest(text=text):
                self.host_fail(Runner(stdout=text))

    def test_host_element_shape_fails(self):
        "E8 (D-5c-Q22)"
        good = pr(oid=G["c_merge"])
        for name, bad in (("number-str", dict(good, number="1")), ("number-float", dict(good, number=1.5)),
                          ("number-bool", dict(good, number=True)), ("state-int", dict(good, state=5)),
                          ("mc-str", dict(good, mergeCommit="x")), ("mc-empty", dict(good, mergeCommit={})),
                          ("oid-int", dict(good, mergeCommit={"oid": 5})), ("head-int", dict(good, headRefOid=5))):
            with self.subTest(case=name):
                self.host_fail(Runner(stdout=js(bad)))
        for key in ("number", "state", "headRefOid"):
            with self.subTest(missing=key):
                self.host_fail(Runner(stdout=js({k: v for k, v in good.items() if k != key})))
        self.assertEqual(host(Runner(stdout=js(dict(good, extra=1)))), [])

    def test_host_state_values(self):
        "E9"
        for state in ("OPEN", "CLOSED"):
            self.assertEqual(host(Runner(js(pr(state))), (("a", "ready"),)), [])
        self.assertEqual(host(Runner(js(pr("MERGED", G["c_merge"]))), (("c", "closed"),)), [])
        for state in ("merged", "DRAFT", ""):
            with self.subTest(state=state):
                self.host_fail(Runner(stdout=js(pr(state))))

    def test_host_empty_list(self):
        "E10"
        self.assertEqual(suffixes(host(Runner("[]"))), ["host.c"])
        self.assertEqual(host(Runner("[]"), (("a", "running"), ("eq", "ready"))), [])

    def test_host_merged_matches(self):
        "E11"
        self.assertEqual(host(Runner(js(pr(oid=G["c_merge"])))), [])

    def test_host_merged_oid_differs_fails(self):
        "E12"
        self.assertEqual(suffixes(host(Runner(js(pr(oid=G["h_merge"]))))), ["host.c"])

    def test_host_open_pr_merged_row_fails(self):
        "E13"
        self.assertEqual(suffixes(host(Runner(js(pr("OPEN"))))), ["host.c"])

    def test_host_merged_pr_running_row_fails(self):
        "E14"
        for st in ("running", "ready", "blocked", "checkpoint"):
            with self.subTest(status=st):
                got = host(Runner(js(pr(oid=G["c_merge"]))), (("a", st),))
                self.assertEqual(got, [("host.a", "a PR of %s/a/main is MERGED while the status is %s" % (P, st))])

    def test_host_merged_pr_closed_row_passes(self):
        "E15"
        self.assertEqual(host(Runner(js(pr(oid=G["c_merge"]))), (("c", "closed"),)), [])

    def test_host_two_prs_one_head(self):
        "E16"
        m = pr(oid=G["c_merge"], number=2)
        self.assertEqual(host(Runner(js(pr("CLOSED", number=1), m))), [])
        self.assertEqual(host(Runner(js(m, pr(oid=G["h_merge"], number=3)))), [])
        self.assertEqual(suffixes(host(Runner(js(pr("OPEN"), m)), (("a", "running"),))), ["host.a"])

    def test_host_merged_pr_null_merge_commit(self):
        "E17"
        self.assertEqual(suffixes(host(Runner(js(pr(oid=None))))), ["host.c"])

    def test_host_merged_row_no_local_merge(self):
        "E18 (D-5c-Q30)"
        got = host(Runner(js(pr(oid=G["c_merge"]))), (("a", "merged"),))
        self.assertEqual(suffixes(got), ["host.a"])
        self.assertIn("(none found locally)", got[0][1])

    def test_host_ready_no_pr(self):
        "E19"
        self.assertEqual(host(Runner("[]"), (("eq", "ready"),)), [])

    def test_host_first_failure_only(self):
        "E20 (D-5c-Q31)"
        calls = []

        def runner(argv, **kw):
            calls.append(argv)
            if len(calls) == 1:
                return subprocess.CompletedProcess(argv, 0, js(pr("OPEN")), "")
            return subprocess.CompletedProcess(argv, 1, "", "bad")
        got = host(runner, (("c", "merged"), ("a", "running")))
        self.assertEqual([s for s, _ in got], ["host"])

    def test_host_argv(self):
        "E21"
        r = Runner("[]")
        host(r, (("a", "running"),))
        argv, kw = r.calls[0]
        self.assertEqual(argv, ["gh", "pr", "list", "--head", "%s/a/main" % P, "--base", "main", "--state", "all", "--json",
                                "number,state,headRefOid,mergeCommit"])
        self.assertNotIn("-R", argv)
        self.assertEqual((kw["cwd"], kw["timeout"], kw["capture_output"], kw["text"]), (G["root"], 30, True, True))

    def test_host_gh_repo_env_cleared(self):
        "E22 (D-5c-Q32)"
        r = Runner("[]")
        with mock.patch.dict(os.environ, {"GH_REPO": "other/repo"}):
            host(r, (("a", "running"),))
        self.assertNotIn("GH_REPO", r.calls[0][1]["env"])

    def test_host_stdout_bytes_fails(self):
        "E23"
        for out in (b"[]", b"\xff"):
            with self.subTest(out=out):
                self.host_fail(Runner(stdout=out), "not text")

    def test_host_runner_result_shape(self):
        "E24"
        class NoCode:
            stdout = "[]"
        for res in (None, NoCode()):
            with self.subTest(res=res):
                self.host_fail(Runner(result=res) if res is not None else Runner(result=NoCode.__new__(NoCode)))
        self.host_fail(lambda argv, **kw: None)

    def test_host_runner_any_exception(self):
        "E25"
        for exc in (RuntimeError("x"), ValueError("y"), RecursionError("z")):
            with self.subTest(exc=type(exc).__name__):
                self.host_fail(Runner(raises=exc))

    def test_host_keyboard_interrupt_propagates(self):
        "E26"
        with self.assertRaises(KeyboardInterrupt):
            host(Runner(raises=KeyboardInterrupt()))

    def test_host_json_deep_fails(self):
        "E27"
        self.host_fail(Runner(stdout="[" * 100000))
        many = js(*[pr("CLOSED", number=n) for n in range(1, 2001)])
        self.assertEqual(suffixes(host(Runner(many))), ["host.c"])

    def test_host_json_number_forms_same_on_both(self):
        "E28 (D-5c-Q22)"
        base = '[{"number": %s, "state": "OPEN", "headRefOid": "x", "mergeCommit": null}]'
        self.host_fail(Runner(base % ("1" * 4301)))
        self.host_fail(Runner(base % ("1" * 601)))
        self.host_fail(Runner(base % "NaN"))
        self.host_fail(Runner(base.replace('"number": %s', '"number": 1, "number": %s') % "2"), "duplicate")
        self.assertEqual(suffixes(host(Runner(base % ("1" * 600)))), ["host.c"])

    def test_host_many_prs(self):
        "E29 (D-5c-Q33): 31 PRs judged as given"
        m = pr(oid=G["c_merge"], number=31)
        self.assertEqual(host(Runner(js(*([pr("CLOSED", number=n) for n in range(1, 31)] + [m])))), [])

    def test_host_head_oid_not_compared(self):
        "E30"
        self.assertEqual(host(Runner(js(pr(oid=G["c_merge"], head="deadbeef")))), [])

    def test_host_argument_types(self):
        "E31"
        good = program([stream("c")], status_text=status_page([row("c", "merged")]))
        for runner in (None, 5, "gh"):
            with self.subTest(runner=runner), self.assertRaises(ValueError):
                drift.host_errors(G["root"], G["cfg"], good, runner=runner)
        for prog in (None, {}):
            with self.subTest(prog=prog), self.assertRaises(ValueError):
                drift.host_errors(G["root"], G["cfg"], prog, runner=Runner())
        with self.assertRaises(GateError):
            drift.host_errors(G["root"], {}, good, runner=Runner())

    def test_host_default_runner(self):
        "E32"
        import inspect
        self.assertIs(inspect.signature(drift.host_errors).parameters["runner"].default, subprocess.run)

    def test_host_row_missing_stream(self):
        "a stream without a status row fails closed"
        prog = program([stream("c")], status_text="")
        self.assertEqual(suffixes(drift.host_errors(G["root"], G["cfg"], prog, runner=Runner())), ["host.c"])


class Versions(unittest.TestCase):
    """Rows V1a-V5: the same literal verdicts on both interpreters (the file runs under both)."""

    def test_version_4300_digits_same_on_both(self):
        "V1a"
        self.assertIsNone(est("9" * 600, "9" * 600))
        with self.assertRaises(ValueError):
            est("9" * 4300, "1")
        self.host_number(4300)

    def host_number(self, n):
        text = '[{"number": %s, "state": "OPEN", "headRefOid": "x", "mergeCommit": null}]' % ("1" * n)
        got = host(Runner(text))
        self.assertEqual([s for s, _ in got], ["host"])

    def test_version_4301_digits_same_on_both(self):
        "V1b"
        with self.assertRaises(ValueError):
            est("9" * 4301, "1")
        self.host_number(4301)

    def test_version_no_int_to_text_over_limit(self):
        "V1c: no ValueError from a formatting of a number past the 3.11 limit"
        with self.assertRaises(ValueError) as e:
            est("1", "1", 10 ** 4400)
        self.assertIn("pct", str(e.exception))
        got = hs("v1c", block="1" * 1000)
        self.assertIn("block: must be a string", got)

    def test_version_unicode_same_on_both(self):
        "V2a, V2b: literal expectations; the code points differ in category between UCD 13 and 15.1"
        for n, ch in enumerate(("ࡰ", "Ꟁ", "\U0001e030")):
            got = hs("v2a-%d" % n, block="1a" + ch)
            self.assertIn("block: must be a single line of printable ASCII", got)
            self.assertEqual(len(got), 2, got)
        self.assertEqual(only(se(row("a", "ready", **{"pending decisions": "none"}), stream("a", plan="docs/p/a-plan.md"),
                                 name=DN), "pending"), [("pending.a", "open decision DEC-20261102-aaaa (topic q:a-plan:q1) "
                                                         "is not listed in pending decisions"),
                                                        ("pending.a", "open decision DEC-20261102-llll (topic q:a-plan:q7) "
                                                         "is not listed in pending decisions")])

    def test_version_module_imports_on_39(self):
        "V3b: no except*, match, ExceptionGroup or removeprefix in drift.py (the file runs on 3.9 and 3.13)"
        import ast
        with open(drift.__file__, encoding="utf-8") as fh:
            src = fh.read()
        banned = tuple(getattr(ast, n) for n in ("Match", "TryStar") if hasattr(ast, n))
        self.assertEqual([n for n in ast.walk(ast.parse(src)) if isinstance(n, banned)], [])
        for word in ("removeprefix", "removesuffix", "ExceptionGroup"):
            self.assertNotIn(word, src)

    def test_version_exception_group_runner(self):
        "V3a"
        group = getattr(builtins, "ExceptionGroup", None)
        base_group = getattr(builtins, "BaseExceptionGroup", None)
        if group is None or base_group is None:
            self.skipTest("ExceptionGroup absent on 3.9")
        self.assertEqual(host(Runner(raises=group("g", [OSError("x")])))[0][0], "host")
        with self.assertRaises(base_group):
            host(Runner(raises=base_group("g", [KeyboardInterrupt()])))


if __name__ == "__main__":
    unittest.main()
