"""Tests of gates/lib/checkpoints.py and of gates/schemas/handoff.yml and ledger.yml (plan Task P1.2; the rows HF, PS, RL,
PH, HE, LP, CP, ML, LE, GS and V of the input-domain table task-P1.2-domain.md, settled by its "Binding controller
decisions" D-Q1 to D-Q30). Every expected value is written out here by hand from the plan and the decisions, never read
back from ``checkpoints``; the ledger patterns are also checked against a pure-Python reference parser written below
(no regular expression), over a generated corpus. Configs come from ``tests.helpers.minimal_config()`` through
``config.load``."""
import builtins
import copy
import os
import re
import tempfile
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates.lib import checkpoints, config, dispatch, ids, migrations, schema, yamlsub
from gates.lib.checkpoints import (checkpoint_lines, handoff_errors, ledger_errors, merged_lines, parse_handoff,
                                   plan_slug, question_errors, resume_line)
from gates.lib.schema import files_of, load_schema, validate_front_matter, validate_markdown
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, int_limit, make_repo, minimal_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANDOFF_YML = os.path.join(schema.SCHEMAS_DIR, "handoff.yml")
LEDGER_YML = os.path.join(schema.SCHEMAS_DIR, "ledger.yml")

_CFG: dict = {}


def cfg() -> dict:
    """``config.load`` of a fixture repository whose config is ``minimal_config()`` (built once, copied per call)."""
    if not _CFG:
        with tempfile.TemporaryDirectory() as d:
            make_repo(d, minimal_config())
            _CFG.update(config.load(d))
    return copy.deepcopy(_CFG)


H7 = "abcdef1"
H40 = "0123456789abcdef0123456789abcdef01234567"
H40B = "fedcba9876543210fedcba9876543210fedcba98"
D1 = "DEC-20261101-abcd"
D2 = "DEC-20261102-bn3p"
F1 = "F-20261101-abcd"
PLAN = "docs/strict-delivery/plans/x.md"
LEDGER_PATH = ".strict-delivery/state/plans/x/ledger.md"
ROLE_IDS = ("program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
            "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer",
            "audit_verifier", "investigator", "plan_writer", "plan_reviewer", "drafter")
OWNER_ONLY = ("triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close", "rule-override",
              "profile-override", "program-create", "stream-ownership", "stream-merge", "request-dispute", "program-close")


def resume(ids_=()):
    """The resume line of ROW with the given open ids, spelled out from plan P:2449 and Process :57."""
    return ("Resume strict-delivery plan %s at P1.3; branch block/p1; head abcdef1; open questions: %s."
            % (PLAN, ", ".join(ids_) if ids_ else "none"))


OPTS = [{"label": "a", "cost": "c1"}, {"label": "b", "cost": "c2"}]
Q1 = {"qid": "q1", "class": "scope", "question": "Which?", "effect": "lasting", "options": OPTS, "recommended": "a"}
Q_MODEL = {"qid": "q1", "class": "model-policy", "question": "Which model?", "effect": "one-off", "options": OPTS}
Q_NOREC = {k: v for k, v in Q1.items() if k != "recommended"}
WT_ROOT = {"path": ".", "branch": "block/p1", "head": H7, "porcelain": ""}
WT_OTHER = {"path": "../w", "branch": None, "head": H40, "porcelain": " M a\n?? b\n"}
ROW = {
    "schema": "handoff/1", "plan": PLAN, "spec": ["docs/strict-delivery/specs/s.md"], "branch": "block/p1",
    "head": H7, "base": H40, "ledger": LEDGER_PATH, "resume": resume(), "block": "P1", "next_task": "P1.3",
    "findings_in_flight": [], "open_decisions": [], "rulings": 0, "grant": None, "live_subagents": [],
    "role": "controller", "budget": {"tokens": 300000, "minutes": 150}, "worktrees": [WT_ROOT],
    "skills": ["strict-delivery"], "ledger_from": 3, "batch_cut": None, "questions": [],
}
SUB = {"agent": "ag1", "task": "P1.2", "worktree": "../w", "transcript": "t/a.jsonl", "last_record": "r1",
       "jobs": [{"id": "j1", "state": "running"}, {"id": "j2", "state": "finished"}]}
RESUME_FIELDS = {
    "live_subagents": [SUB], "worktrees": [WT_ROOT, WT_OTHER], "skills": ["superpowers:executing-plans", "strict-delivery"],
    "required_reads": [{"path": "gates/lib/schema.py", "lines": "1-9", "why": "w"}, {"path": "a.md", "why": "w"}],
    "ledger_from": 3, "batch_cut": H7,
}
REQUIRED = ("plan", "spec", "branch", "head", "base", "ledger", "resume", "block", "next_task", "findings_in_flight",
            "open_decisions", "rulings", "grant", "live_subagents", "role", "budget", "worktrees", "skills",
            "ledger_from", "batch_cut", "questions")


def R(**kw):
    r = copy.deepcopy(ROW)
    r.update(kw)
    return r


def slurp(path) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def text_of(row) -> str:
    return "---\n" + yamlsub.emit(row) + "---\nbody\n"


def raw_text(key, raw, row=None) -> str:
    """The emitted text of ``row`` with its top-level line ``key: ...`` replaced by ``key: <raw>``."""
    t = text_of(row if row is not None else ROW)
    out, n = re.subn(r"(?m)^%s: .*$" % re.escape(key), lambda m: "%s: %s" % (key, raw), t)
    assert n == 1, key
    return out


HS = load_schema(HANDOFF_YML)
LS = load_schema(LEDGER_YML)
BAD_SHA = "must be 7 to 40 lowercase hex digits"


def vf(row_or_text, c=None):
    t = row_or_text if isinstance(row_or_text, str) else text_of(row_or_text)
    return validate_front_matter(HS, t, c or cfg())


def he(**kw):
    return handoff_errors(R(**kw), cfg())


LH = "<!-- schema: ledger/1 -->\n"
C0 = "CHECKPOINT 1a 1a.1 head=abcdef1 tests=5/5 gates=PASS next=1a.2"
R0 = "Ruling: a -- b -- c -- d"
Q0 = "Request: R-20261102-bn3p from=c to=a files=gates/__main__.py need=register cites status=open"
U0 = "UPDATE 1b from=main@abcdef1 head=abcdef2 tests=5/5 gates=n/a"
M0H = ("MERGED pr=3 head=%s merge=%s merged_by=superbrobenji at=2026-11-02T08:59:36Z final=no stream=a block=1c "
       "approval=host" % (H40, H40B))
M0C = ("MERGED pr=3 head=%s merge=%s merged_by=superbrobenji at=2026-11-02T08:59:36Z final=no stream=a block=1c "
       "approval=chat pr=3 head=%s words=approve PR 3" % (H40, H40B, H40))


def lerr(body, **kw):
    return ledger_errors(LH + body + "\n", cfg(), **kw)


def pattern_ok(line):
    """True when the schema reports nothing for ``line`` (prose, or a keyword line that conforms)."""
    return validate_markdown(LS, LH + line + "\n") == []


# ======================================================================== handoff schema (producer 1)

class HandoffSchema(unittest.TestCase):
    def test_valid_handoff(self):  # HF0, HE1, plan P:2474-2475
        text = text_of(ROW)
        self.assertEqual(validate_front_matter(load_schema(HANDOFF_YML), text, cfg()), [])
        self.assertEqual(handoff_errors(parse_handoff(text), cfg()), [])
        self.assertEqual(parse_handoff(text), ROW)  # emit then parse round-trips (head "abcdef1", block "P1")
        full = R(**RESUME_FIELDS)
        self.assertEqual(parse_handoff(text_of(full)), full)

    def test_handoff_schema_tag(self):  # HF1
        self.assertEqual(vf(raw_text("schema", "handoff/2")), ["schema: expected handoff/1, got handoff/2; "
                                                                "run /strict-delivery:upgrade"])
        t = text_of({k: v for k, v in ROW.items() if k != "schema"})
        self.assertEqual(vf(t), ["schema: expected handoff/1, got (missing)"])
        for raw in ("ledger/1", "handoff/01", "5", '""'):
            with self.subTest(raw=raw):
                got = vf(raw_text("schema", raw))
                self.assertEqual(len(got), 1)
                self.assertTrue(got[0].startswith("schema: expected handoff/1, got "), got)
        self.assertEqual(vf(raw_text("schema", "handoff/1")), [])

    def test_handoff_unknown_key(self):  # HF2
        for k in ("in_progress_outside_plan", "Plan", "extra"):
            with self.subTest(key=k):
                self.assertEqual(vf(R(**{k: "x"})), ["%s: unknown key" % k])

    def test_handoff_required_fields(self):  # HF3
        for k in REQUIRED:
            with self.subTest(field=k):
                self.assertEqual(vf({a: b for a, b in ROW.items() if a != k}), ["%s: required key is missing" % k])

    def test_handoff_optional_fields(self):  # HF4
        self.assertEqual(vf(ROW), [])
        for k in ("program", "stream", "required_reads"):
            self.assertNotIn(k, ROW)
        self.assertEqual(vf(R(program="20261101-x", stream="a", required_reads=[])), [])

    def test_handoff_str_fields(self):  # HF5
        bad = {"5": "must be a non-empty string", "true": "must be a non-empty string", "[]": "must be a non-empty string",
               "null": "must not be null", '""': "must be a non-empty string"}
        for f in ("plan", "branch", "ledger", "resume", "block", "next_task", "role"):
            for raw, why in bad.items():
                with self.subTest(field=f, raw=raw):
                    self.assertEqual(vf(raw_text(f, raw)), ["%s: %s" % (f, why)])
            with self.subTest(field=f, raw="mapping"):
                self.assertEqual(vf(R(**{f: {"a": 1}})), ["%s: must be a non-empty string" % f])

    def test_handoff_numeric_looking_ids(self):  # HF6
        self.assertEqual(vf(raw_text("block", "12")), ["block: must be a non-empty string"])
        self.assertEqual(vf(raw_text("block", "1")), ["block: must be a non-empty string"])
        self.assertEqual(vf(raw_text("block", '"12"')), [])
        self.assertEqual(vf(raw_text("next_task", "1.2")), [])
        self.assertEqual(vf(R(block="12")), [])  # the emitter quotes it

    def test_handoff_spec(self):  # HF7
        self.assertEqual(vf(R(spec=[])), ["spec: must hold at least 1 items"])
        self.assertEqual(vf(R(spec=["docs/s.md"])), [])
        self.assertEqual(vf(R(spec=["docs/s.md", "docs/t.md"])), [])
        self.assertEqual(vf(R(spec=[5])), ["spec.0: must be a non-empty string"])
        self.assertEqual(vf(R(spec="x")), ["spec: must be a list"])

    def test_handoff_sha_fields(self):  # HF8, HF23 (same rule)
        good = (H7, H40, "1234567")
        bad = ("abcdef", "a" * 41, "ABCDEF1", "abcdefg", "")
        for f in ("head", "base"):
            for v in good:
                with self.subTest(field=f, v=v):
                    self.assertEqual(vf(R(**{f: v})), [])
            for v in bad:
                with self.subTest(field=f, v=v):
                    self.assertEqual(vf(R(**{f: v})), ["%s: %s" % (f, BAD_SHA)])
            with self.subTest(field=f, v="unquoted digits"):  # U1: an all-digit sha written unquoted is an int
                self.assertEqual(vf(raw_text(f, "1234567")), ["%s: %s" % (f, BAD_SHA)])

    def test_handoff_finding_ids(self):  # HF9
        self.assertEqual(vf(R(findings_in_flight=[])), [])
        self.assertEqual(vf(R(findings_in_flight=[F1])), [])
        for v in (D1, "F-20261301-abcd", "F-20261101-ab0d"):
            with self.subTest(v=v):
                got = vf(R(findings_in_flight=[v]))
                self.assertEqual(len(got), 1)
                self.assertTrue(got[0].startswith("findings_in_flight.0: "), got)
        self.assertEqual(vf(R(findings_in_flight="none")), ["findings_in_flight: must be a list"])

    def test_handoff_decision_ids(self):  # HF10
        self.assertEqual(vf(R(open_decisions=[D1])), [])
        for v in (F1, "DEC-20260230-abcd"):
            with self.subTest(v=v):
                got = vf(R(open_decisions=[v]))
                self.assertEqual(len(got), 1)
                self.assertTrue(got[0].startswith("open_decisions.0: "), got)
        self.assertEqual(vf(raw_text("open_decisions", "none")), ["open_decisions: must be a list"])

    def test_handoff_rulings_and_digit_limits(self):  # HF11, V1
        for v, want in ((0, []), (3, []), (-1, ["rulings: must be at least 0"]), (True, ["rulings: must be an integer"]),
                        ("3", ["rulings: must be an integer"])):
            with self.subTest(v=v):
                self.assertEqual(vf(R(rulings=v)), want)
        too_big = lambda out: len(out) == 1 and out[0].startswith("front matter: line ") and out[0].endswith("integer too large")
        for limit in INT_LIMITS:
            with int_limit(limit):
                got = vf(raw_text("rulings", "9" * 1000))
                if limit == 640:  # U2 of Task P1.1's report: a 1000-digit integer needs the default or no limit
                    self.assertTrue(too_big(got), got)
                else:
                    self.assertEqual(got, [])
                for n in (1001, 4300, 4301):
                    with self.subTest(limit=limit, digits=n):
                        self.assertTrue(too_big(vf(raw_text("rulings", "9" * n))))

    def test_handoff_grant_forms(self):  # HF12 (schema part; the form is handoff_errors', D-Q1)
        self.assertEqual(vf(R(grant=None)), [])
        self.assertEqual(vf(R(grant="pr=3 head=" + H40)), [])
        self.assertEqual(vf(R(grant="")), ["grant: must be a non-empty string"])
        self.assertEqual(vf(R(grant=5)), ["grant: must be a non-empty string"])
        for v, ok in ((None, True), ("pr=3 head=" + H40, True), ("pr=3 head=" + H7, False), (D1, False),
                      ("pr=x head=" + H40, False), ("pr=3 head=" + H40 + " extra", False),
                      ("pr=3 head=" + H40.upper(), False), ("pr=0 head=" + H40, False), ("pr=03 head=" + H40, False),
                      ("pr=" + "9" * 600 + " head=" + H40, True), ("pr=" + "9" * 601 + " head=" + H40, False),
                      ("pr=3  head=" + H40, False), ("pr=3 head=" + H40 + "\n", False)):
            with self.subTest(v=v):
                got = [e for e in he(grant=v) if e.startswith("grant")]
                self.assertEqual(got, [] if ok else ["grant: must be null or 'pr=<n> head=<40 hex>'"])

    def test_live_subagents_entries_required(self):  # HF13, plan P:2499-2500
        self.assertEqual(vf(R(live_subagents=[])), [])
        self.assertEqual(vf(R(live_subagents=[SUB])), [])
        for k in SUB:
            with self.subTest(missing=k):
                self.assertEqual(vf(R(live_subagents=[{a: b for a, b in SUB.items() if a != k}])),
                                 ["live_subagents.0.%s: required key is missing" % k])
        self.assertEqual(vf(R(live_subagents=[{**SUB, "zz": "1"}])), ["live_subagents.0.zz: unknown key"])
        old = vf(R(live_subagents=["agent-1"]))  # the old bare-string shape
        self.assertEqual(old, ["live_subagents.0: must be a mapping"])
        self.assertTrue(any(e.startswith("live_subagents") for e in old))
        self.assertEqual(vf(R(live_subagents="none")), ["live_subagents: must be a list"])

    def test_live_subagent_jobs(self):  # HF14
        for st in ("running", "finished", "stopped"):
            self.assertEqual(vf(R(live_subagents=[{**SUB, "jobs": [{"id": "j", "state": st}]}])), [])
        self.assertEqual(vf(R(live_subagents=[{**SUB, "jobs": []}])), [])
        for st in ("killed", "Running", ""):
            with self.subTest(state=st):
                got = vf(R(live_subagents=[{**SUB, "jobs": [{"id": "j", "state": st}]}]))
                self.assertEqual(got, ["live_subagents.0.jobs.0.state: must be one of running, finished, stopped"])
        self.assertEqual(vf(R(live_subagents=[{**SUB, "jobs": [{"state": "running"}]}])),
                         ["live_subagents.0.jobs.0.id: required key is missing"])
        self.assertEqual(vf(R(live_subagents=[{**SUB, "jobs": [{"id": "j"}]}])),
                         ["live_subagents.0.jobs.0.state: required key is missing"])
        self.assertEqual(vf(R(live_subagents=[{**SUB, "jobs": ["j1"]}])), ["live_subagents.0.jobs.0: must be a mapping"])

    def test_handoff_role_is_a_str(self):  # HF15 (membership is handoff_errors', HE6)
        for r in ROLE_IDS + ("implementor",):
            self.assertEqual(vf(R(role=r)), [])

    def test_handoff_budget(self):  # HF16
        self.assertEqual(vf(R(budget={"tokens": 1, "minutes": 1})), [])
        self.assertEqual(vf(R(budget={"tokens": 0, "minutes": 1})), ["budget.tokens: must be at least 1"])
        self.assertEqual(vf(R(budget={"tokens": 1, "minutes": 0})), ["budget.minutes: must be at least 1"])
        self.assertEqual(vf(R(budget={"tokens": True, "minutes": 1})), ["budget.tokens: must be an integer"])
        self.assertEqual(vf(R(budget={"tokens": "5", "minutes": 1})), ["budget.tokens: must be an integer"])
        self.assertEqual(vf(R(budget={"minutes": 1})), ["budget.tokens: required key is missing"])
        self.assertEqual(vf(R(budget={"tokens": 1})), ["budget.minutes: required key is missing"])
        self.assertEqual(vf(R(budget={"tokens": 1, "minutes": 1, "x": 1})), ["budget.x: unknown key"])
        self.assertEqual(vf(R(budget=5)), ["budget: must be a mapping"])
        self.assertEqual(vf("---\n" + yamlsub.emit({k: v for k, v in ROW.items() if k != "budget"}) + "budget: null\n---\n"),
                         ["budget: must not be null"])
        t = "---\n" + yamlsub.emit({k: v for k, v in ROW.items() if k != "budget"}) + "budget:\n  tokens: %s\n  minutes: 1\n---\n"
        self.assertEqual(vf(t % ("9" * 4301)), ["front matter: line %d: integer too large" % (len(yamlsub.emit(
            {k: v for k, v in ROW.items() if k != "budget"}).split("\n")) + 2)])

    def test_handoff_program_stream_types(self):  # HF17
        self.assertEqual(vf(R(program="20261101-x", stream="a")), [])
        self.assertEqual(vf(R(program="20261101-x")), [])
        self.assertEqual(vf(R(stream="a")), [])
        self.assertEqual(vf(R(program="")), ["program: must be a non-empty string"])
        self.assertEqual(vf(R(stream=5)), ["stream: must be a non-empty string"])

    def test_worktrees_fields(self):  # HF18
        self.assertEqual(vf(R(worktrees=[])), ["worktrees: must hold at least 1 items"])
        self.assertEqual(vf(R(worktrees=[WT_ROOT])), [])
        for k in WT_ROOT:
            with self.subTest(missing=k):
                self.assertEqual(vf(R(worktrees=[{a: b for a, b in WT_ROOT.items() if a != k}])),
                                 ["worktrees.0.%s: required key is missing" % k])
        w = lambda **kw: vf(R(worktrees=[{**WT_ROOT, **kw}]))
        self.assertEqual(w(zz=1), ["worktrees.0.zz: unknown key"])
        self.assertEqual(w(path=5), ["worktrees.0.path: must be a non-empty string"])
        self.assertEqual(w(branch=None), [])
        self.assertEqual(w(branch=""), ["worktrees.0.branch: must be a non-empty string"])
        self.assertEqual(w(head="abc"), ["worktrees.0.head: %s" % BAD_SHA])
        self.assertEqual(w(porcelain=""), [])
        self.assertEqual(w(porcelain=" M a\n?? b\n"), [])
        self.assertEqual(w(porcelain=5), ["worktrees.0.porcelain: must be a string"])
        self.assertEqual(w(porcelain=None), ["worktrees.0.porcelain: must not be null"])

    def test_porcelain_roundtrip_through_emit(self):  # HF19
        for p in ("", " M a\n", " M a\n?? b\n", "A  a\n\n?? b\n", "tab\there \n", "?? \"caf\\303\\251\"\n", "x",
                  "  M two\n M one\n"):
            with self.subTest(porcelain=p):
                row = R(worktrees=[{**WT_ROOT, "porcelain": p}])
                self.assertEqual(parse_handoff(text_of(row))["worktrees"][0]["porcelain"], p)
                self.assertEqual(vf(row), [])
        # a hand-written block whose first line is indented deeper than the second fails (writers must emit)
        hand = text_of(R(worktrees=[])).replace("worktrees: []", "worktrees:\n  - path: .\n    branch: b\n    head: %s\n"
                                                "    porcelain: |\n        M a\n      M b\n" % H7)
        got = vf(hand)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("front matter: line ") and "indentation" in got[0], got)

    def test_required_reads_fields(self):  # HF20
        rr = lambda v: vf(R(required_reads=v))
        self.assertEqual(rr([]), [])
        self.assertEqual(rr("x"), ["required_reads: must be a list"])
        self.assertEqual(rr({"a": 1}), ["required_reads: must be a list"])
        self.assertEqual(rr([{"why": "w"}]), ["required_reads.0.path: required key is missing"])
        self.assertEqual(rr([{"path": "a.md"}]), ["required_reads.0.why: required key is missing"])
        self.assertEqual(rr([{"path": "a.md", "why": "w", "ref": "x"}]), ["required_reads.0.ref: unknown key"])
        self.assertEqual(rr([{"path": 5, "why": "w"}]), ["required_reads.0.path: must be a non-empty string"])
        self.assertEqual(rr([{"path": "a.md", "why": ""}]), ["required_reads.0.why: must be a non-empty string"])
        self.assertEqual(rr([{"path": "a.md", "why": "w", "lines": "3-9"}]), [])
        self.assertEqual(rr([{"path": "a.md", "why": "w", "lines": 3}]),
                         ["required_reads.0.lines: must be a non-empty string"])
        self.assertEqual(rr([{"path": "a.md", "why": "w", "lines": ""}]),
                         ["required_reads.0.lines: must be a non-empty string"])

    def test_handoff_skills(self):  # HF21
        self.assertEqual(vf(R(skills=[])), ["skills: must hold at least 1 items"])
        self.assertEqual(vf(R(skills=["superpowers:executing-plans", "strict-delivery"])), [])
        self.assertEqual(vf(R(skills=[5])), ["skills.0: must be a non-empty string"])
        self.assertEqual(vf(R(skills=[""])), ["skills.0: must be a non-empty string"])
        self.assertEqual(vf(R(skills="x")), ["skills: must be a list"])
        self.assertEqual(parse_handoff(text_of(R(skills=["b", "a"]))) ["skills"], ["b", "a"])  # order kept

    def test_handoff_ledger_from(self):  # HF22
        for v, want in ((0, ["ledger_from: must be at least 2"]), (1, ["ledger_from: must be at least 2"]), (2, []),
                        (3, []), (-1, ["ledger_from: must be at least 2"]), (True, ["ledger_from: must be an integer"]),
                        ("2", ["ledger_from: must be an integer"])):
            with self.subTest(v=v):
                self.assertEqual(vf(R(ledger_from=v)), want)
        self.assertEqual(vf(raw_text("ledger_from", "5.5")), ["ledger_from: must be an integer"])
        self.assertEqual(vf(raw_text("ledger_from", "9" * 4301))[0][-17:], "integer too large")

    def test_handoff_batch_cut(self):  # HF23
        for v in (None, H7, H40):
            self.assertEqual(vf(R(batch_cut=v)), [])
        for v in ("abcdef", "a" * 41, "ABCDEF1", ""):
            with self.subTest(v=v):
                self.assertEqual(vf(R(batch_cut=v)), ["batch_cut: %s" % BAD_SHA])
        self.assertEqual(vf(raw_text("batch_cut", "1234567")), ["batch_cut: %s" % BAD_SHA])

    def test_questions_fields(self):  # HF24
        q = lambda v: vf(R(questions=v))
        self.assertEqual(q([]), [])
        self.assertEqual(q([Q1]), [])
        self.assertEqual(q([Q_NOREC]), [])
        for k in ("qid", "class", "question", "effect", "options"):
            with self.subTest(missing=k):
                self.assertEqual(q([{a: b for a, b in Q1.items() if a != k}]), ["questions.0.%s: required key is missing" % k])
        self.assertEqual(q([{**Q1, "zz": "1"}]), ["questions.0.zz: unknown key"])
        for e in ("lasting", "one-off"):
            self.assertEqual(q([{**Q1, "effect": e}]), [])
        for e in ("forever", "Lasting"):
            self.assertEqual(q([{**Q1, "effect": e}]), ["questions.0.effect: must be one of lasting, one-off"])
        self.assertEqual(q([{**Q1, "options": []}]), ["questions.0.options: must hold at least 2 items"])
        self.assertEqual(q([{**Q1, "options": OPTS[:1]}]), ["questions.0.options: must hold at least 2 items"])
        self.assertEqual(q([{**Q1, "options": [{"label": "a"}, OPTS[1]]}]), ["questions.0.options.0.cost: required key is missing"])
        self.assertEqual(q([{**Q1, "options": [{"cost": "c"}, OPTS[1]]}]), ["questions.0.options.0.label: required key is missing"])
        self.assertEqual(q([{**Q1, "options": [{**OPTS[0], "x": 1}, OPTS[1]]}]), ["questions.0.options.0.x: unknown key"])
        self.assertEqual(q([{**Q1, "recommended": None}]), ["questions.0.recommended: must not be null"])

    def test_porcelain_triple_dash_roundtrip(self):  # HF25
        for p in ("---", "a\n---\nb\n", "---\n", " M a\n---\n"):
            with self.subTest(porcelain=p):
                row = R(worktrees=[{**WT_ROOT, "porcelain": p}])
                t = text_of(row)
                self.assertEqual(vf(t), [])
                self.assertEqual(parse_handoff(t)["worktrees"][0]["porcelain"], p)

    def test_real_handoffs_not_validated_in_p12(self):  # HF26: no module declares handoff or ledger (P:2456)
        self.assertEqual({"handoff", "ledger"} & schema.produced_kinds(), set())
        real = os.path.join(REPO, ".strict-delivery", "state", "plans", "2026-10-31-strict-delivery-framework", "handoff.md")
        if os.path.exists(real):  # not asserted to be valid or invalid: Task P1.3 Step 5 migrates it
            self.assertIsInstance(validate_front_matter(HS, slurp(real), cfg()), list)

    def test_handoff_and_ledger_file_lists(self):  # HF27, V5
        for kind, name in (("handoff", "handoff.md"), ("ledger", "ledger.md")):
            with tempfile.TemporaryDirectory() as d:
                make_repo(d, minimal_config())
                base = os.path.join(d, ".strict-delivery", "state", "plans")
                for slug in ("a", "a-b", "a b"):
                    os.makedirs(os.path.join(base, slug))
                    for f in ("handoff.md", "ledger.md"):
                        with open(os.path.join(base, slug, f), "w", encoding="utf-8") as fh:
                            fh.write("x\n")
                sch = load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))
                pre = ".strict-delivery/state/plans/"
                self.assertEqual(files_of(sch, d, cfg()), [pre + "a b/" + name, pre + "a-b/" + name, pre + "a/" + name])

    def test_spec9_fields_present(self):  # HE23: every field of spec section 9's list has a schema field
        for name in ("plan", "spec", "branch", "head", "base", "ledger", "resume", "block", "next_task",
                     "findings_in_flight", "open_decisions", "rulings", "grant", "live_subagents"):
            self.assertIn(name, HS.fields)
        self.assertEqual((HS.kind, HS.version, HS.format), ("handoff", 1, "front-matter"))


# ======================================================================== plan_slug, resume_line, parse_handoff

class PlanSlug(unittest.TestCase):
    def test_plan_slug(self):  # PS1, plan P:2495-2496
        self.assertEqual(plan_slug("docs/strict-delivery/plans/x.md"), "x")

    def test_plan_slug_forms(self):  # PS2, PS3
        for path, want in (("a/b/c.md", "c"), ("c.md", "c"), ("./c.md", "c"), ("x.md.md", "x.md"), ("x.mdx.md", "x.mdx"),
                           ("d/a b.md", "a b"), ("d/a:b.md", "a:b"), ("d/\u00e9.md", "\u00e9")):
            with self.subTest(path=path):
                self.assertEqual(plan_slug(path), want)

    def test_plan_slug_without_md_raises(self):  # PS4, PS5, PS6
        for path in ("x", "x.txt", "", "a/b/", "/", "x.MD", ".md", "a/.md", "axmd", None, b"x.md", 5):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    plan_slug(path)

    def test_plan_slug_unicode_same_on_both(self):  # PS7, V2
        for ch in ("\u0870", "\U0001fae8", "\u2c2f", "\u0c5d", "\u00a0", "\n", "A"):
            with self.subTest(ch=ch):
                self.assertEqual(plan_slug("d/n%s.md" % ch), "n" + ch)  # no case folding, no normalisation
        self.assertEqual(plan_slug("d/" + "x" * 4301 + ".md"), "x" * 4301)


class ResumeLine(unittest.TestCase):
    def test_resume_line_none(self):  # RL1
        self.assertEqual(resume_line(ROW), resume())
        self.assertEqual(resume_line(ROW), "Resume strict-delivery plan docs/strict-delivery/plans/x.md at P1.3; "
                                           "branch block/p1; head abcdef1; open questions: none.")

    def test_resume_lists_decisions_then_qids(self):  # RL2, plan P:2478-2479
        self.assertTrue(resume_line({**ROW, "open_decisions": [D1], "questions": [Q1]}).endswith("open questions: %s, q1." % D1))

    def test_resume_line_order(self):  # RL3, RL4, RL5
        self.assertTrue(resume_line(R(open_decisions=[D2, D1])).endswith("open questions: %s, %s." % (D2, D1)))
        self.assertTrue(resume_line(R(questions=[{**Q1, "qid": "z"}, {**Q1, "qid": "a"}])).endswith("open questions: z, a."))
        self.assertTrue(resume_line(R(open_decisions=[D1])).endswith("open questions: %s." % D1))
        self.assertTrue(resume_line(R(questions=[Q1])).endswith("open questions: q1."))
        self.assertTrue(resume_line(R(open_decisions=[D1, D1], questions=[{**Q1, "qid": D1}])).endswith(
            "open questions: %s, %s, %s." % (D1, D1, D1)))  # printed as given (D-Q17)

    def test_resume_line_field_text(self):  # RL6 (D-Q18: single line of printable ASCII)
        got = resume_line(R(next_task="a b; c: d", plan="p q", branch="b/c", head="abc"))
        self.assertEqual(got, "Resume strict-delivery plan p q at a b; c: d; branch b/c; head abc; open questions: none.")
        for f in ("plan", "next_task", "branch", "head"):
            for bad in ("a\nb", "a\rb", "caf\u00e9", "a\u2028b", ""):
                with self.subTest(field=f, bad=bad):
                    with self.assertRaises(ValueError) as cm:
                        resume_line(R(**{f: bad}))
                    self.assertIn(f, str(cm.exception))
        self.assertEqual(len(resume_line(R(next_task="x" * 4301))), len(resume()) - 4 + 4301)

    def test_resume_line_bad_rows(self):  # RL7, RL8 (D-Q3)
        for row in ({}, {k: v for k, v in ROW.items() if k != "next_task"}, R(open_decisions="none"), R(questions=[5]),
                    R(questions=[{}]), R(branch=None), R(questions=None), R(open_decisions=None), R(open_decisions=[5]), R(questions=[{"qid": 5}]), "x", None, []):
            with self.subTest(row=repr(row)[:60]):
                with self.assertRaises(ValueError):
                    resume_line(row)

    def test_resume_line_matches_process_text(self):  # RL9: the Process line :57 with the plan path substituted
        want = ("Resume strict-delivery plan docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md at <next task>; "
                "branch <branch>; head <sha>; open questions: <ids or none>.")
        got = resume_line(R(plan="docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md", next_task="<next task>",
                            branch="<branch>", head="<sha>"))
        self.assertEqual(got.replace("none.", "<ids or none>."), want)


class ParseHandoff(unittest.TestCase):
    def test_parse_handoff_valid(self):  # PH1
        t = text_of(ROW) + "---\nmore body\n"
        self.assertEqual(parse_handoff(t), ROW)

    def test_parse_handoff_errors(self):  # PH2, PH4, PH5 (D-Q4): one structural error, Task P1.1's texts
        for t, msg in (("schema: x\n---\n", "front matter: first line must be '---'"),
                       ("---\nschema: x\n", "front matter: no closing '---' line"),
                       ("---\n---\n", "front matter: must be a mapping"),
                       ("---\n- a\n---\n", "front matter: must be a mapping"),
                       ("---\na: x\nb: [\n---\n", "front matter: line 3: "),
                       ("\ufeff---\na: 1\n---\n", "front matter: first line must be '---'"),
                       ("---\r\na: 1\r\n---\r\n", "front matter: first line must be '---'"),
                       (None, "front matter: text must be a string"), (b"---\n---\n", "front matter: text must be a string"),
                       (5, "front matter: text must be a string")):
            with self.subTest(text=repr(t)[:40]):
                with self.assertRaises(ValueError) as cm:
                    parse_handoff(t)
                self.assertTrue(str(cm.exception).startswith(msg), str(cm.exception))
                if isinstance(t, str):  # the same text validate_front_matter reports
                    self.assertEqual(vf(t)[0], str(cm.exception))

    def test_parse_handoff_does_not_run_the_schema(self):  # PH3 (D-Q4)
        self.assertEqual(parse_handoff("---\nzzz: 1\n---\n"), {"zzz": 1})


# ======================================================================== handoff_errors (producer 5)

class HandoffErrors(unittest.TestCase):
    def test_resume_line_must_match_fields(self):  # HE2, plan P:2476-2477
        self.assertIn("resume: expected '" + resume_line(ROW) + "'", handoff_errors({**ROW, "resume": "x"}, cfg()))
        good = resume()
        for bad in (good[:-1], good.replace("; branch", ", branch"), good + " ", good.replace("Resume", "resume"),
                    good.replace("plan ", "plan  "), "x", "", good.replace("x.md", "y.md")):
            with self.subTest(resume=bad):
                self.assertEqual(he(resume=bad), ["resume: expected '%s'" % good])
        self.assertEqual(he(open_decisions=[D1, D2], resume=resume([D1, D2])), [])
        self.assertEqual(he(open_decisions=[D1, D2], resume=resume([D2, D1])),
                         ["resume: expected '%s'" % resume([D1, D2])])

    def test_resume_tracks_open_items(self):  # HE3
        self.assertEqual(he(open_decisions=[D1]), ["resume: expected '%s'" % resume([D1])])
        self.assertEqual(he(questions=[Q1]), ["resume: expected '%s'" % resume(["q1"])])
        self.assertEqual(he(questions=[Q1], resume=resume(["q1"])), [])

    def test_handoff_plan_rules(self):  # HE4 (D-Q5)
        pre = "docs/strict-delivery/plans/"
        want = "plan: must be docs/strict-delivery/plans/<name>.md"

        def got(plan):
            return [e for e in he(plan=plan, resume=resume().replace(PLAN, plan), ledger=LEDGER_PATH) if e.startswith("plan")]
        self.assertEqual(got(pre + "x.md"), [])
        for p in ("docs/x.md", pre + "x.txt", pre + "../x.md", "/" + pre + "x.md", "docs/strict-delivery/plansx/x.md",
                  pre + "sub/x.md", pre + ".md", pre + "x.md/", "x.md", "", "docs/strict-delivery/plansx.md", "xxxx/strict-delivery/plans/x.md"):
            with self.subTest(plan=p):
                self.assertEqual(got(p), [want])
        for p in (pre + "caf\u00e9.md", pre + "a\nb.md"):
            with self.subTest(plan=p):
                self.assertEqual(got(p), ["plan: must be a single line of printable ASCII"])
        self.assertEqual(got(pre + "x.md.md"), [])
        c = cfg()
        c["paths"]["plans"] = "plans2"
        self.assertEqual([e for e in handoff_errors(R(plan="plans2/x.md", resume=resume().replace(PLAN, "plans2/x.md")), c)
                          if e.startswith("plan")], [])
        self.assertEqual([e for e in handoff_errors(R(plan=PLAN), c) if e.startswith("plan")], ["plan: must be plans2/<name>.md"])
        c["paths"]["plans"] = "docs//plans"  # a prefix that is not normalised: the whole path must pass _path_ok (D-Q5)
        self.assertEqual([e for e in handoff_errors(R(plan="docs//plans/x.md"), c) if e.startswith("plan")],
                         ["plan: must be docs//plans/<name>.md"])

    def test_handoff_ledger_must_match_plan(self):  # HE5 (D-Q6)
        exp = "ledger: expected '%s'" % LEDGER_PATH
        for bad in (".strict-delivery/state/plans/y/ledger.md", ".strict-delivery/state/plans/x/handoff.md",
                    "./" + LEDGER_PATH, "/" + LEDGER_PATH, ""):
            with self.subTest(ledger=bad):
                self.assertEqual(he(ledger=bad), [exp])
        self.assertEqual(he(plan="docs/strict-delivery/plans/a.md", ledger=".strict-delivery/state/plans/a/ledger.md",
                            resume=resume().replace("x.md", "a.md")), [])

    def test_handoff_role_each_roles_id(self):  # HE6
        self.assertEqual(tuple(dispatch.ROLES), ROLE_IDS)
        for r in ROLE_IDS:
            with self.subTest(role=r):
                self.assertEqual(he(role=r), [])
        for r in ("implementor", "Controller", "controller "):
            with self.subTest(role=r):
                self.assertEqual(he(role=r), ["role: must be one of " + ", ".join(ROLE_IDS)])

    def test_program_and_stream_together(self):  # HE7, plan P:2480-2481
        self.assertTrue(any(e.startswith("stream:") for e in handoff_errors({**ROW, "program": "20261101-x"}, cfg())))
        self.assertEqual(he(program="20261101-x", stream="a"), [])
        self.assertEqual(he(program="20261101-x"), ["stream: required when program is present"])
        self.assertEqual(he(stream="a"), ["program: required when stream is present"])
        for bad in ("Program", "-x", "a_b", "", "a\n", "caf\u00e9", "\u0870", "x" * 4301 + "!"):
            with self.subTest(bad=bad):
                self.assertIn("program: must match [a-z0-9][a-z0-9-]*", he(program=bad, stream="a")
                              if bad != "" else ["program: must match [a-z0-9][a-z0-9-]*"])
                self.assertIn("stream: must match [a-z0-9][a-z0-9-]*", he(program="p", stream=bad)
                              if bad != "" else ["stream: must match [a-z0-9][a-z0-9-]*"])
        self.assertEqual(he(program="a" * 4301, stream="b"), [])

    def test_question_qid_rules(self):  # HE8 (D-Q7)
        bad = "must be a string matching [a-z0-9][a-z0-9-]*"
        for qid in ("Q1", "q/1", "q 1", "-q", "", "q\u00e9", "q" * 4300 + "/"):
            with self.subTest(qid=qid[:10]):
                self.assertEqual([e for e in he(questions=[{**Q1, "qid": qid}]) if ".qid" in e], ["questions.0.qid: " + bad])
        self.assertEqual([e for e in he(questions=[{**Q1, "qid": 5}]) if ".qid" in e], ["questions.0.qid: " + bad])
        two = he(questions=[Q1, {**Q1, "recommended": "b"}], resume=resume(["q1", "q1"]))
        self.assertEqual([e for e in two if "qid" in e], ["questions.1.qid: q1 given twice"])
        self.assertFalse([e for e in two if e.startswith("questions.q1.")])
        three = he(questions=[Q_NOREC, Q1], resume=resume(["q1", "q1"]))
        self.assertEqual([e for e in three if "recommended" in e], [])  # neither copy of a repeated qid is checked by qid  # rules keyed by qid skip a repeated qid
        self.assertEqual([e for e in he(questions=[{**Q_NOREC, "qid": "Q1"}]) if "recommended" in e], [])  # bad qid: skipped

    def test_question_class_must_be_owner_only(self):  # HE9, plan P:2482-2483
        self.assertTrue(any("class" in e for e in handoff_errors({**ROW, "questions": [{**Q1, "class": "chat"}]}, cfg())))
        for c in OWNER_ONLY:
            with self.subTest(cls=c):
                q = {**Q1, "class": c}
                if c == "model-policy":
                    q = {k: v for k, v in q.items() if k != "recommended"}
                self.assertEqual(he(questions=[q], resume=resume(["q1"])), [])
        for c in ("chat", "Scope", "triage "):
            self.assertEqual([e for e in he(questions=[{**Q1, "class": c}], resume=resume(["q1"])) if "class" in e],
                             ["questions.0.class: %s is not an owner-only class (%s)" % (c, ", ".join(OWNER_ONLY))])
        c = cfg()
        c["decision_classes"]["owner_only"].append("hardware")
        self.assertEqual(handoff_errors(R(questions=[{**Q1, "class": "hardware"}], resume=resume(["q1"])), c), [])
        self.assertEqual(he(questions=[{**Q1, "class": 5}], resume=resume(["q1"])), [])  # wrong type: the schema names it

    def test_handoff_question_needs_recommended_except_model_policy(self):  # HE10, design 3.6, plan P:2505-2508
        e = lambda q: handoff_errors({**ROW, "questions": [q], "resume": resume(["q1"])}, cfg())
        self.assertIn("questions.q1.recommended: missing", handoff_errors({**ROW, "questions": [Q_NOREC]}, cfg()))
        self.assertEqual(handoff_errors({**ROW, "questions": [Q_MODEL], "resume": resume(["q1"])}, cfg()), [])
        self.assertIn("questions.q1.recommended: class model-policy carries no recommended option",
                      handoff_errors({**ROW, "questions": [{**Q_MODEL, "recommended": "a"}]}, cfg()))
        self.assertEqual(e(Q_NOREC), ["questions.q1.recommended: missing"])
        self.assertEqual(e(Q1), [])
        self.assertEqual(e({**Q1, "recommended": "b"}), [])
        for v in ("c", "A", ""):
            self.assertEqual(e({**Q1, "recommended": v}), ["questions.q1.recommended: %s is not the label of exactly one option" % v])
        twice = {**Q1, "options": [{"label": "a", "cost": "x"}, {"label": "a", "cost": "y"}]}
        self.assertEqual(e(twice), ["questions.q1.recommended: a is not the label of exactly one option"])
        # D-Q8: a model-policy question with a recommended that names no label gets both errors
        self.assertEqual(e({**Q_MODEL, "recommended": "zz"}),
                         ["questions.q1.recommended: class model-policy carries no recommended option",
                          "questions.q1.recommended: zz is not the label of exactly one option"])
        self.assertEqual(e({**Q_MODEL, "recommended": "a"}),
                         ["questions.q1.recommended: class model-policy carries no recommended option"])

    def test_question_source_single_line(self):  # HE11 (D-Q9)
        e = lambda s: [x for x in he(questions=[{**Q1, "source": s}], resume=resume(["q1"])) if "source" in x]
        want = ["questions.q1.source: must be a non-empty single line of printable ASCII"]
        self.assertEqual(he(questions=[Q1], resume=resume(["q1"])), [])
        self.assertEqual(e("reports/a.md"), [])
        self.assertEqual(e("   "), [])  # whitespace-only is a non-empty line
        self.assertEqual(e("x" * 4301), [])
        for s in ("", "a\nb", "a\rb", "a\u2028b", "a\u0085b", "caf\u00e9", "a\tb"):
            with self.subTest(source=s):
                self.assertEqual(e(s), want)

    def test_question_errors_called_by_handoff_errors(self):  # HE22
        qs = [Q_NOREC, {**Q1, "qid": "q2", "class": "chat", "source": ""}]
        direct = question_errors(qs, cfg())
        self.assertTrue(direct)
        got = handoff_errors(R(questions=qs, resume=resume(["q1", "q2"])), cfg())
        self.assertEqual(got, direct)
        self.assertEqual(question_errors("x", cfg()), [])
        self.assertEqual(question_errors(None, cfg()), [])
        self.assertEqual(question_errors(5, cfg()), [])
        self.assertEqual(question_errors([5, Q1], cfg()), [])

    def test_live_subagents_uniqueness(self):  # HE12, D-Q14
        wts = [WT_ROOT, WT_OTHER]
        ok = lambda subs: he(live_subagents=subs, worktrees=wts)
        self.assertEqual(ok([SUB]), [])
        self.assertEqual(ok([SUB, {**SUB, "task": "t2"}]), ["live_subagents.1.agent: ag1 given twice"])
        self.assertEqual(ok([SUB, {**SUB, "agent": "AG1"}]), [])  # case differs
        self.assertEqual(ok([{**SUB, "jobs": [{"id": "j", "state": "running"}, {"id": "j", "state": "stopped"}]}]),
                         ["live_subagents.0.jobs.1.id: j given twice"])
        self.assertEqual(ok([SUB, {**SUB, "agent": "ag2"}]), [])  # the same job ids in two agents pass
        self.assertEqual(ok([{**SUB, "worktree": "../nope"}]), ["live_subagents.0.worktree: not in worktrees"])
        self.assertEqual(ok([{**SUB, "worktree": "."}]), [])
        self.assertEqual(he(live_subagents=[SUB], worktrees="x"), [])  # worktrees of the wrong type: skipped

    def test_worktree_path_rules(self):  # HE13 (D-Q11)
        bad = ("worktrees.1.path: must be '.' or a normalised relative path with '..' only as a leading run "
               "(printable ASCII, no backslash)")
        for p in ("../w", "../../w", "a/b", "w"):
            with self.subTest(path=p):
                self.assertEqual(he(worktrees=[WT_ROOT, {**WT_OTHER, "path": p}]), [])
        for p in ("a/../b", "/abs", "./w", "a//b", "a/", "..", "a/..", "w\\x", "", "\u0870", "caf\u00e9", "a\nb", "../",
                  "../a/../b", "../../", "x" * 4300 + "/../y"):
            with self.subTest(path=p[:12]):
                self.assertEqual(he(worktrees=[WT_ROOT, {**WT_OTHER, "path": p}]), [bad])
        self.assertEqual(he(worktrees=[WT_ROOT, {**WT_OTHER, "path": "x" * 4301}]), [])

    def test_worktrees_need_exactly_one_root(self):  # HE14, plan P:2501-2502
        self.assertTrue(any(e.startswith("worktrees") for e in handoff_errors({**ROW, "worktrees": [WT_OTHER]}, cfg())))
        self.assertEqual(he(worktrees=[WT_OTHER]), ["worktrees: exactly one entry must have path '.' (found 0)"])
        self.assertEqual(he(worktrees=[WT_ROOT, {**WT_OTHER, "path": "."}]),
                         ["worktrees.1.path: . given twice", "worktrees: exactly one entry must have path '.' (found 2)"])
        self.assertEqual(he(worktrees=[WT_ROOT, WT_OTHER, {**WT_OTHER}]), ["worktrees.2.path: ../w given twice"])
        self.assertEqual(he(worktrees=[WT_ROOT, {**WT_OTHER, "path": "./"}]),
                         ["worktrees.1.path: must be '.' or a normalised relative path with '..' only as a leading run "
                          "(printable ASCII, no backslash)"])
        self.assertEqual(he(worktrees=[WT_ROOT, WT_OTHER, {**WT_OTHER, "path": "../v", "branch": None}]), [])  # branch repeated
        self.assertEqual(he(worktrees=[]), ["worktrees: exactly one entry must have path '.' (found 0)"])

    def test_required_read_path_rules(self):  # HE15, plan P:2503-2504
        for p in ("../x", "/x", "."):
            with self.subTest(path=p):
                self.assertTrue(any(e.startswith("required_reads.0.path") for e in handoff_errors(
                    {**ROW, "required_reads": [{"path": p, "why": "w"}]}, cfg())))
        bad = ("required_reads.0.path: must be a normalised repo-relative path (no leading '/', no '..' segment, not '.')")
        for p in ("a.md", "gates/lib/x.py", "a b"):
            self.assertEqual(he(required_reads=[{"path": p, "why": "w"}]), [])
        for p in ("../x", "/x", ".", "a/../b", "a//b", "./a", "a/"):
            self.assertEqual(he(required_reads=[{"path": p, "why": "w"}]), [bad])
        self.assertEqual(he(required_reads=[{"path": "caf\u00e9", "why": "w"}]),
                         ["required_reads.0.path: must be a single line of printable ASCII"])

    def test_required_read_lines_pattern(self):  # HE16 (D-Q2)
        bad = "required_reads.0.lines: must be <first>-<last> or <first>-end"
        for v in ("1-3", "3-9", "3-end", "5-2", "9-3", "1-" + "9" * 600, "9" * 600 + "-end"):
            with self.subTest(lines=v[:12]):
                self.assertEqual(he(required_reads=[{"path": "a.md", "lines": v, "why": "w"}]), [])
        for v in ("3", "0-2", "0-3", "3-", "a-b", "01-3", "1-03", "1-end2", "1-END", "1-3 ", "", "1-" + "9" * 601,
                  "9" * 4301 + "-end", "1-3\n", "-3", "9" * 601 + "-3"):
            with self.subTest(lines=v[:12]):
                self.assertEqual(he(required_reads=[{"path": "a.md", "lines": v, "why": "w"}]), [bad])
        self.assertEqual(he(required_reads=[{"path": "a.md", "lines": 3, "why": "w"}]), [])  # wrong type: the schema names it
        self.assertEqual(he(required_reads=[{"path": "a.md", "lines": 3, "why": "w"}, {"path": "a.md", "lines": 3, "why": "w"}]), [])

    def test_required_reads_unique_per_lines(self):  # HE17 (D-Q12)
        a = {"path": "a.md", "why": "w"}
        self.assertEqual(he(required_reads=[a, {**a, "lines": "1-3"}]), [])  # with and without lines
        self.assertEqual(he(required_reads=[{**a, "lines": "1-3"}, {**a, "lines": "4-5"}]), [])
        self.assertEqual(he(required_reads=[a, {**a, "why": "other"}]), ["required_reads.1: a.md listed twice"])
        self.assertEqual(he(required_reads=[{**a, "lines": "1-3"}, {**a, "lines": "1-3"}]), ["required_reads.1: a.md listed twice"])
        self.assertEqual(he(required_reads=[a, {**a, "lines": "1-3"}, a]), ["required_reads.2: a.md listed twice"])

    def test_resume_fields_valid(self):  # HE18, plan P:2497-2498
        self.assertEqual(handoff_errors({**ROW, **RESUME_FIELDS}, cfg()), [])

    def test_handoff_errors_all_reported(self):  # HE19, D-Q6: field order of P:2430-2439, then per-item order
        y = "docs/strict-delivery/plans/y.md"
        row = R(plan=y, resume="z", role="nope", program="p", grant="g", worktrees=[WT_OTHER], questions=[Q_NOREC],
                skills=["s", "s"], spec=["a", "a"])
        self.assertEqual(handoff_errors(row, cfg()), [
            "spec.1: a given twice",
            "ledger: expected '.strict-delivery/state/plans/y/ledger.md'",
            "resume: expected '%s'" % resume(["q1"]).replace(PLAN, y),
            "grant: must be null or 'pr=<n> head=<40 hex>'",
            "role: must be one of " + ", ".join(ROLE_IDS),
            "stream: required when program is present",
            "worktrees: exactly one entry must have path '.' (found 0)",
            "skills.1: s given twice",
            "questions.q1.recommended: missing",
        ])

    def test_duplicates_refused(self):  # D-Q13
        self.assertEqual(he(spec=["a", "b", "a"]), ["spec.2: a given twice"])
        self.assertEqual(he(skills=["a", "a"]), ["skills.1: a given twice"])
        self.assertEqual(he(findings_in_flight=[F1, F1]), ["findings_in_flight.1: %s given twice" % F1])
        self.assertEqual(he(open_decisions=[D1, D1], resume=resume([D1, D1])), ["open_decisions.1: %s given twice" % D1])

    def test_single_line_fields(self):  # D-Q18
        want = "must be a single line of printable ASCII"
        for f in ("branch", "block", "next_task"):
            self.assertIn("%s: %s" % (f, want), he(**{f: "a\nb"}))
        self.assertIn("spec.0: " + want, he(spec=["a\nb"]))
        self.assertIn("skills.0: " + want, he(skills=["caf\u00e9"]))
        self.assertIn("live_subagents.0.task: " + want, he(live_subagents=[{**SUB, "task": "a\nb"}], worktrees=[WT_ROOT, WT_OTHER]))
        self.assertIn("questions.0.question: " + want, he(questions=[{**Q1, "question": "a\nb"}], resume=resume(["q1"])))
        self.assertIn("questions.0.options.0.label: " + want,
                      he(questions=[{**Q1, "options": [{"label": "a\nb", "cost": "c"}, OPTS[1]]}], resume=resume(["q1"])))
        self.assertIn("questions.0.options.1.cost: " + want,
                      he(questions=[{**Q1, "options": [OPTS[0], {"label": "b", "cost": "c\u00e9"}]}], resume=resume(["q1"])))
        self.assertEqual(he(worktrees=[{**WT_ROOT, "porcelain": " M caf\u00e9\n"}]), [])  # porcelain is exempt
        sub = {**SUB, "transcript": "a\nb", "last_record": "a\nb"}
        self.assertEqual([e for e in he(live_subagents=[sub], worktrees=[WT_ROOT, WT_OTHER]) if want in e],
                         ["live_subagents.0.transcript: " + want, "live_subagents.0.last_record: " + want])
        self.assertEqual(he(worktrees=[{**WT_ROOT, "branch": "a\nb"}]), ["worktrees.0.branch: " + want])
        self.assertEqual(he(required_reads=[{"path": "a.md", "why": "a\nb"}]), ["required_reads.0.why: " + want])

    def test_handoff_errors_on_bad_rows(self):  # HE20, HE21 (D-Q3)
        self.assertEqual(handoff_errors("x", cfg()), ["handoff: must be a mapping"])
        self.assertEqual(handoff_errors(None, cfg()), ["handoff: must be a mapping"])
        self.assertEqual(handoff_errors([], cfg()), ["handoff: must be a mapping"])
        for row in ({}, R(questions="x"), R(worktrees=[5]), R(required_reads=[{}]), R(spec=None), R(plan=5), R(skills=5),
                    R(live_subagents=[5, {"jobs": 5}]), R(questions=[5, {"qid": []}]), R(findings_in_flight=5),
                    R(program=5, stream=[]), R(required_reads=[{"path": 5, "lines": 5}]), R(grant=5), R(role=5), R(live_subagents=5),
                    R(worktrees="x"), R(required_reads=5)):
            with self.subTest(row=repr(row)[:50]):
                self.assertIsInstance(handoff_errors(row, cfg()), list)  # never raises on a mapping
        self.assertEqual(handoff_errors({}, cfg()), [])  # nothing present, nothing to check (the schema names the rest)
        self.assertEqual(handoff_errors(R(questions="x"), cfg()), [])
        self.assertEqual(handoff_errors(R(open_decisions="x"), cfg()), [])  # resume_line raises inside: no resume error
        self.assertEqual(handoff_errors(R(plan="docs/x.txt", ledger="y", resume=resume().replace(PLAN, "docs/x.txt")), cfg()), ["plan: must be docs/strict-delivery/plans/<name>.md"])


# ======================================================================== ledger patterns (producer 6)

def _tok(s):
    return s != "" and all("!" <= c <= "~" for c in s)


def _hex(s, lo, hi):
    return lo <= len(s) <= hi and all(c in "0123456789abcdef" for c in s)


def _num(s):
    return (s == "0" or (s != "" and s[0] in "123456789")) and len(s) <= 600 and all(c in "0123456789" for c in s)


def _pr(s):
    return s != "" and s[0] in "123456789" and _num(s)


def _tests(s):
    if not s.startswith("tests="):
        return False
    a = s[6:].split("/")
    return len(a) == 2 and _num(a[0]) and _num(a[1])


def _printable(s):
    return all(" " <= c <= "~" for c in s)


def _ref_checkpoint(line):
    p = line.split(" ")
    return (len(p) == 7 and p[0] == "CHECKPOINT" and _tok(p[1]) and _tok(p[2]) and p[3].startswith("head=")
            and _hex(p[3][5:], 7, 40) and _tests(p[4]) and p[5] in ("gates=PASS", "gates=n/a")
            and p[6].startswith("next=") and _tok(p[6][5:]))


def _ref_update(line):
    p = line.split(" ")
    if not (len(p) == 6 and p[0] == "UPDATE" and _tok(p[1]) and p[2].startswith("from=")):
        return False
    branch, at, sha = p[2][5:].rpartition("@")
    return (at == "@" and _tok(branch) and _hex(sha, 7, 40) and p[3].startswith("head=") and _hex(p[3][5:], 7, 40)
            and _tests(p[4]) and p[5] in ("gates=PASS", "gates=n/a"))


def _ruling_printable(s):  # printable ASCII and exactly U+00A7 (decision D-Q24), nothing else
    return all(" " <= c <= "~" or c == "\u00a7" for c in s)


def _ref_ruling(line):
    if not line.startswith("Ruling: "):
        return False
    parts = line[8:].split(" -- ")
    return len(parts) == 4 and all(x != "" and _ruling_printable(x) and x[0] != " " and x[-1] != " " for x in parts)


def _stream(s):
    return s != "" and s[0] in "abcdefghijklmnopqrstuvwxyz0123456789" and all(
        c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in s)


def _ref_request(line):
    p = line.split(" ")
    if len(p) < 7 or p[0] != "Request:":
        return False
    idp = p[1].split("-")
    alnum = lambda s, n=None: s != "" and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in s) \
        and (n is None or len(s) == n)
    if not (len(idp) == 3 and alnum(idp[0]) and alnum(idp[1], 8) and all(c in "0123456789" for c in idp[1])
            and alnum(idp[2], 4)):
        return False
    if not (p[2].startswith("from=") and _stream(p[2][5:]) and p[3].startswith("to=") and _stream(p[3][3:])
            and p[4].startswith("files=") and _tok(p[4][6:])):
        return False
    tail = p[5:]
    if tail and tail[-1].startswith("sha=") and _hex(tail[-1][4:], 7, 40) and len(tail) >= 2:
        tail = tail[:-1]
    if not tail or tail[-1] not in ("status=open", "status=done", "status=disputed"):
        return False
    need = " ".join(tail[:-1])
    return need.startswith("need=") and len(need) > 5 and _printable(need)


def _ref_merged(line):
    p = line.split(" ")
    if len(p) < 9 or p[0] != "MERGED":
        return False
    if not (p[1].startswith("pr=") and _pr(p[1][3:]) and p[2].startswith("head=") and _hex(p[2][5:], 40, 40)
            and p[3].startswith("merge=") and _hex(p[3][6:], 40, 40) and p[4].startswith("merged_by=") and _tok(p[4][10:])
            and p[5].startswith("at=") and p[6] in ("final=yes", "final=no")):
        return False
    at = p[5][3:]
    if not (len(at) == 20 and at[4] == "-" and at[7] == "-" and at[10] == "T" and at[13] == ":" and at[16] == ":"
            and at[19] == "Z" and all(c in "0123456789" for c in at[0:4] + at[5:7] + at[8:10] + at[11:13] + at[14:16] + at[17:19])):
        return False
    i = 7
    if p[i].startswith("stream=") or p[i].startswith("block="):
        if not (p[i].startswith("stream=") and _stream(p[i][7:]) and len(p) > i + 1 and p[i + 1].startswith("block=")
                and p[i + 1][6:] != "" and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                                              for c in p[i + 1][6:])):
            return False
        i += 2
    if i >= len(p):
        return False
    if p[i] == "approval=host":
        return i == len(p) - 1
    if p[i] != "approval=chat" or len(p) < i + 4:
        return False
    if not (p[i + 1].startswith("pr=") and _pr(p[i + 1][3:]) and p[i + 2].startswith("head=") and _hex(p[i + 2][5:], 40, 40)
            and p[i + 3].startswith("words=")):
        return False
    words = " ".join(p[i + 3:])[6:]
    return _printable(words) and any(c != " " for c in words)


REFS = {"CHECKPOINT": _ref_checkpoint, "Ruling": _ref_ruling, "Request": _ref_request, "UPDATE": _ref_update,
        "MERGED": _ref_merged}


def keyword(line):
    t = line.split(" ", 1)[0]
    return t[:-1] if t.endswith(":") else t


def ref_ok(line):
    """The reference verdict: ``line`` is prose (not keyword-led) or conforms to its keyword's form."""
    f = REFS.get(keyword(line))
    return True if f is None else f(line)


POOL = ["", "x", "\u00e9", "0", "007", "5", "-1", "a/b", "head=abcdef1", "head=ABCDEF1", "head=abcdef", "tests=5/4",
        "tests=5", "gates=FAIL", "gates=pass", "final=maybe", "=", "a=b", "--", "\t", "yes", "no", "xxx", "stream=a",
        "block=1c", "pr=3", "words=x", "status=open", "sha=abcdef1", "n/a", "PASS", "\r"]


def variants(base):
    parts = base.split(" ")
    out = {base, base + " x", base + " ", base + "\r", " " + base, base + "\t", base.replace(" ", "  ", 1)}
    for i in range(len(parts)):
        out.add(" ".join(parts[:i] + parts[i + 1:]))
        out.add(" ".join(parts[:i] + [parts[i], parts[i]] + parts[i + 1:]))
        out.add(" ".join(parts[:i] + [""] + parts[i:]))
        out.add(" ".join(parts[:i] + [parts[i].upper()] + parts[i + 1:]))
        for v in POOL:
            out.add(" ".join(parts[:i] + [v] + parts[i + 1:]))
            if "=" in parts[i]:
                out.add(" ".join(parts[:i] + [parts[i].split("=", 1)[0] + "=" + v] + parts[i + 1:]))
    return sorted(out)


RULING_PARTS = ["", " ", "x ", " x", "a -- b", "\u00e9", "x\ty", "--", "-", "x" * 50, "w=1"]


def ruling_variants():
    out = set()
    for opener in ("Ruling: ", "Ruling:  ", "Ruling (x): ", "Ruling ", "Ruling:", "Rulings: ", " Ruling: "):
        for sep in (" -- ", " --  ", "  -- ", " - ", " --- ", "--", " -- -- "):
            for n in range(1, 7):
                out.add(opener + sep.join(["p"] * n))
        for i in range(4):
            for v in RULING_PARTS:
                ps = ["a", "b", "c", "d"]
                ps[i] = v
                out.add(opener + " -- ".join(ps))
    return sorted(out)


class LedgerPatterns(unittest.TestCase):
    def test_ledger_first_line(self):  # LP1
        want = ["first line: expected '<!-- schema: ledger/1 -->'"]
        for t in (C0 + "\n", "<!-- schema: ledger/2 -->\n" + C0, "<!-- schema: ledger/1 --> \n" + C0,
                  "\ufeff<!-- schema: ledger/1 -->\n" + C0, "<!-- schema: ledger/1 -->\r\n" + C0 + "\r\n", "", "\n"):
            with self.subTest(text=repr(t)[:30]):
                self.assertEqual(ledger_errors(t, cfg()), want)
        self.assertEqual(ledger_errors(LH + C0 + "\n", cfg()), [])
        self.assertEqual(ledger_errors(None, cfg()), ["first line: text must be a string"])  # LE15

    def test_ledger_prose_is_free(self):  # LP2
        for body in ("", "prose\n\nmore prose", "| table | row |\n|---|---|", "Decision (owner delegation): a -- b -- c",
                     "Rulings: x", "Ruling:a -- b", "- CHECKPOINT x", " CHECKPOINT x", "prose CHECKPOINT x"):
            with self.subTest(body=body):
                self.assertEqual(ledger_errors(LH + body, cfg()), [])

    def test_decision_delegation_line_is_prose(self):  # LP10
        self.assertEqual(lerr("Decision (owner delegation): a -- b -- c"), [])

    def test_keyword_mid_line_is_prose(self):  # LP16
        for body in ("prose CHECKPOINT x", "| MERGED | x |", " CHECKPOINT bad", "- CHECKPOINT bad", "```\nCHECKPOINT bad\n```"):
            with self.subTest(body=body):
                errs = lerr(body)
                if body.startswith("```"):  # a fence is not special: its keyword line is still checked (P1.1 LV11)
                    self.assertEqual(errs, ["line 3: 'CHECKPOINT' line does not match " + LS.rules["CHECKPOINT"][0]])
                else:
                    self.assertEqual(errs, [])
        self.assertEqual(ledger_errors(C0 + "\n", cfg()), ["first line: expected '<!-- schema: ledger/1 -->'"])

    def test_checkpoint_line_forms(self):  # LP3, LP4, LE2; plan P:2484-2485
        self.assertEqual(lerr(C0), [])
        for s in ("gates=n/a", "head=" + "a" * 40, "head=" + "a" * 7):
            line = C0.replace("gates=PASS", s) if s.startswith("gates") else C0.replace("head=abcdef1", s)
            self.assertEqual(lerr(line), [], line)
        bad = {
            "trailing word": C0 + " x", "missing block": C0.replace("1a ", "", 1), "missing task": C0.replace(" 1a.1", ""),
            "missing head": C0.replace(" head=abcdef1", ""), "missing tests": C0.replace(" tests=5/5", ""),
            "missing gates": C0.replace(" gates=PASS", ""), "missing next": C0.replace(" next=1a.2", ""),
            "6 hex": C0.replace("abcdef1", "abcdef"), "41 hex": C0.replace("abcdef1", "a" * 41),
            "uppercase": C0.replace("abcdef1", "ABCDEF1"), "head empty": C0.replace("abcdef1", ""),
            "tests=5": C0.replace("5/5", "5"), "tests=a/b": C0.replace("5/5", "a/b"), "tests=5/5/5": C0.replace("5/5", "5/5/5"),
            "tests=-1/5": C0.replace("5/5", "-1/5"), "tests=05/5": C0.replace("5/5", "05/5"),
            "gates=FAIL": C0.replace("PASS", "FAIL"), "gates=pass": C0.replace("PASS", "pass"),
            "gates=N/A": C0.replace("PASS", "N/A"), "gates empty": C0.replace("gates=PASS", "gates="),
            "next empty": C0.replace("next=1a.2", "next="), "next two words": C0 + " x", "two spaces": C0.replace(" 1a.1", "  1a.1"),
            "tab": C0.replace(" 1a.1", "\t1a.1"), "trailing space": C0 + " ", "colon form": "CHECKPOINT: " + C0[11:],
            "CR": C0 + "\r", "non-ASCII token": C0.replace("1a.1", "1a.\u00e9"), "swapped": C0.replace("head=abcdef1 tests=5/5", "tests=5/5 head=abcdef1"),
        }
        pat = LS.rules["CHECKPOINT"][0]
        for name, line in bad.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), ["line 2: 'CHECKPOINT' line does not match " + pat])
        for line in ("CHECKPOINT 1a 1a.1 head=abcdef1 tests=0/0 gates=PASS next=x", "CHECKPOINT merged planning head=228c872 "
                     "tests=716/716 gates=PASS next=resume-plan-reviews", "CHECKPOINT a b head=abcdef1 tests=%s/%s gates=n/a next=c" % ("9" * 600, "9" * 600)):
            self.assertEqual(lerr(line), [], line)
        self.assertEqual(len(lerr("CHECKPOINT a b head=abcdef1 tests=%s/1 gates=n/a next=c" % ("9" * 601))), 1)

    def test_real_checkpoint_specimens(self):  # LP5
        real178 = ("CHECKPOINT 1a merged head=4c2f40f tests=396/396 gates=n/a next=1b.1 (stream A); stream C may start from "
                   "main; stream B after its B1.1 dispatch")
        real461 = "CHECKPOINT 1c0 planning head=228c872 tests=716/716 gates=PASS next=resume-plan-reviews"
        self.assertEqual(len(lerr(real178)), 1)
        self.assertEqual(lerr(real461), [])

    def test_ruling_needs_four_parts(self):  # LP6, LP7; plan P:2486-2487
        self.assertTrue(lerr("Ruling: a -- b -- c") and not lerr("Ruling: a -- b -- c -- d"))
        pat = LS.rules["Ruling"][0]
        bad = {"three": "Ruling: a -- b -- c -- d -- e", "two": "Ruling: a -- b -- c", "zero": "Ruling: a b c d",
               "no trailing space": "Ruling: a --b -- c -- d", "no spaces": "Ruling: a--b--c--d",
               "empty first": "Ruling:  -- b -- c -- d", "empty second": "Ruling: a --  -- c -- d",
               "empty last": "Ruling: a -- b -- c -- ", "all empty": "Ruling: -- -- -- ", "three dashes": "Ruling: a --- b -- c -- d",
               "space part": "Ruling: a --   -- c -- d", "leading space": "Ruling:  a -- b -- c -- d", "trailing space": "Ruling: a -- b -- c -- d ",
               "tab": "Ruling: a -- b\t -- c -- d", "non-ASCII": "Ruling: a -- b -- c -- \u00e9", "mid-dash": "Ruling: a -- b -- c -- d -- ",
               "bare": "Ruling:", "bare space": "Ruling: "}
        for name, line in bad.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), ["line 2: 'Ruling' line does not match " + pat])
        for line in (R0, "Ruling: a b -- c d -- e -- f g h", "Ruling: -- x -- y -- z -- w"[:0] + "Ruling: x-y -- z -- w -- v"):
            self.assertEqual(lerr(line), [], line)

    def test_ruling_colon_forms(self):  # LP8
        pat = LS.rules["Ruling"][0]
        err = ["line 2: 'Ruling' line does not match " + pat]
        for line in ("Ruling (x): a -- b -- c -- d", "Ruling:", "Ruling a -- b -- c -- d", "Ruling: "):
            with self.subTest(line=line):
                self.assertEqual(lerr(line), err)
        self.assertEqual(lerr("Ruling:a -- b -- c -- d"), [])  # token "Ruling:a" is not the word: prose
        self.assertEqual(lerr("Rulings: a -- b"), [])
        self.assertEqual(lerr("Ruling:  a -- b -- c -- d"), err)

    def test_real_ruling_specimens(self):  # LP9: the real ledger's Ruling lines agree with the reference parser
        path = os.path.join(REPO, ".strict-delivery", "state", "plans", "2026-10-31-strict-delivery-framework", "ledger.md")
        if not os.path.exists(path):
            self.skipTest("no real ledger")
        n = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh.read().split("\n"):
                if keyword(line) == "Ruling":
                    n += 1
                    self.assertEqual(pattern_ok(line), _ref_ruling(line), line[:80])
        self.assertGreater(n, 0)
        self.assertFalse(pattern_ok("Ruling (block 1b, 1 of 5): commit attribution uses the harness line -- why -- cost -- cite"))

    def test_request_line_forms(self):  # LP11, LE5
        self.assertEqual(lerr(Q0), [])
        pat = LS.rules["Request"][0]
        err = ["line 2: 'Request' line does not match " + pat]
        for name, line in {
            "missing from": Q0.replace(" from=c", ""), "missing to": Q0.replace(" to=a", ""), "missing files": Q0.replace(" files=gates/__main__.py", ""),
            "missing need": Q0.replace(" need=register cites", ""), "missing status": Q0.replace(" status=open", ""),
            "status closed": Q0.replace("open", "closed"), "status OPEN": Q0.replace("open", "OPEN"), "files empty": Q0.replace("gates/__main__.py", ""),
            "files space": Q0.replace("files=gates/__main__.py", "files=a b"), "need empty": Q0.replace("need=register cites", "need="),
            "id 3 chars": Q0.replace("bn3p", "bn3"), "id empty": Q0.replace("R-20261102-bn3p ", ""), "sha twice": Q0 + " sha=abcdef1 sha=abcdef2",
            "sha 6": Q0 + " sha=abcdef", "sha upper": Q0 + " sha=ABCDEF1", "old form": "Request: from=C to=A file=gates/__main__.py what=\"x\" why=\"y\" status=open",
            "stream upper": Q0.replace("from=c", "from=C"), "no colon": Q0.replace("Request:", "Request"),
        }.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), err)
        for name, line in {"sha 7": Q0 + " sha=abcdef1", "sha 40": Q0 + " sha=" + H40, "need with =": Q0.replace("register cites", 'a=b "q" -> c'),
                           "need with status": Q0.replace("register cites", "x status=done y"), "done": Q0.replace("open", "done"),
                           "disputed": Q0.replace("open", "disputed"), "files several": Q0.replace("gates/__main__.py", "a.py,b.py")}.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), [])

    def test_request_id_checked_against_config(self):  # LE5, LE14, D-Q28
        self.assertEqual(lerr(Q0), [])
        p = lambda ident: lerr(Q0.replace("R-20261102-bn3p", ident))
        for ident, frag in (("DEC-20261102-bn3p", "id does not match the form"), ("X-20261102-bn3p", "id does not match the form"),
                            ("R-20261102-bn0p", "id does not match the form"), ("R-20260230-bn3p", "is not a valid calendar date")):
            with self.subTest(ident=ident):
                got = p(ident)
                self.assertEqual(len(got), 1)
                self.assertTrue(got[0].startswith("line 2: %s: " % ident) and frag in got[0], got)
        c = cfg()
        c["ids"]["request"] = "RQ"
        self.assertEqual(ledger_errors(LH + Q0.replace("R-", "RQ-") + "\n", c), [])
        self.assertEqual(len(ledger_errors(LH + Q0 + "\n", c)), 1)

    def test_update_line_forms(self):  # LP12, LE3
        self.assertEqual(lerr(U0), [])
        pat = LS.rules["UPDATE"][0]
        err = ["line 2: 'UPDATE' line does not match " + pat]
        for name, line in {"missing block": U0.replace("1b ", "", 1), "missing from": U0.replace(" from=main@abcdef1", ""),
                           "missing head": U0.replace(" head=abcdef2", ""), "missing tests": U0.replace(" tests=5/5", ""),
                           "missing gates": U0.replace(" gates=n/a", ""), "from 3 hex": U0.replace("main@abcdef1", "main@abc"),
                           "from @hex only": U0.replace("main@abcdef1", "@abcdef1"), "from no hex": U0.replace("main@abcdef1", "main@"),
                           "head upper": U0.replace("abcdef2", "ABCDEF2"), "head short": U0.replace("abcdef2", "abc"),
                           "head long": U0.replace("abcdef2", "a" * 41), "gates FAIL": U0.replace("n/a", "FAIL"),
                           "trailing word": U0 + " x", "alone": "UPDATE"}.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), err)
        for line in (U0.replace("main", "block/p1"), U0.replace("main@abcdef1", "a@b@abcdef1"), U0.replace("n/a", "PASS")):
            self.assertEqual(lerr(line), [], line)

    def test_tests_passed_not_above_total(self):  # LE3, plan P:2488-2489; D-Q21
        self.assertIn("line 2: tests passed > total", ledger_errors(LH + "CHECKPOINT 1a 1a.1 head=abcdef1 tests=5/4 gates=PASS next=1a.2\n", cfg()))
        for t, bad in (("5/4", True), ("5/5", False), ("4/5", False), ("0/0", False), ("1/0", True), ("9" * 600 + "/" + "9" * 599, True)):
            with self.subTest(tests=t[:8]):
                self.assertEqual(lerr(C0.replace("5/5", t)), ["line 2: tests passed > total"] if bad else [])
                self.assertEqual(lerr(U0.replace("5/5", t)), ["line 2: tests passed > total"] if bad else [])
        self.assertEqual(ledger_errors(LH + "prose\n" + C0.replace("5/5", "6/5") + "\n", cfg()), ["line 3: tests passed > total"])

    def test_merged_line_forms(self):  # LP13
        self.assertEqual(lerr(M0H), [])
        self.assertEqual(lerr(M0C), [])
        pat = LS.rules["MERGED"][0]
        err = ["line 2: 'MERGED' line does not match " + pat]
        for words in ("a=b", 'say "hi"', "final=yes", "caf" + "e", "x" * 4301, "x y  z ", " x", "(x)"):
            with self.subTest(words=words[:10]):
                self.assertEqual(lerr(M0C.replace("approve PR 3", words)), [])
        bad = {"words empty": M0C.replace("words=approve PR 3", "words="), "words spaces": M0C.replace("approve PR 3", "   "),
               "words missing": M0C.replace(" words=approve PR 3", ""), "words non-ASCII": M0C.replace("approve", "appr\u00f4ve"),
               "words tab": M0C.replace("approve PR", "approve\tPR"), "words CR": M0C + "\r", "chat no pr": M0C.replace(" pr=3 head=%s words" % H40, " head=%s words" % H40),
               "chat no head": M0C.replace(" head=%s words" % H40, " words"), "chat short head": M0C.replace("head=%s words" % H40, "head=abcdef1 words"),
               "host extra": M0H + " x", "approval other": M0H.replace("approval=host", "approval=other"), "approval empty": M0H.replace("approval=host", "approval="),
               "approval not last": M0H.replace(" approval=host", "") .replace("final=no", "approval=host final=no")}
        for name, line in bad.items():
            with self.subTest(name=name):
                self.assertEqual(lerr(line), err)
        real318 = ("MERGED pr=1 head=7aeb5d4a575bf8393d52e853d3e1b93f9af04085 merge=30947245508ac47579d6c020648c90dc93451fd9 "
                   "merged_by=superbrobenji at=2026-11-02T06:23:42Z approval=chat pr=1 head=7aeb5d4 words=\"approve PR #1 at "
                   "7aeb5d4. recommmended for all is good\" final=no (block 1b)")
        real697 = ("MERGED PR-1c0 (#4): owner 2026-11-09 \"merged\"; gh: MERGED f83747a at 2026-11-09T09:41:43Z, head 371f1d4; "
                   "read-back: tree of f83747a equals tree of 371f1d4 (dd27e8ab)")
        for line in (real318, real697):  # LP17
            self.assertEqual(lerr(line), err)

    def test_merged_scalar_fields(self):  # LP14
        err = ["line 2: 'MERGED' line does not match " + LS.rules["MERGED"][0]]
        sub = lambda a, b: lerr(M0H.replace(a, b, 1))
        for a, b in (("pr=3", "pr=0"), ("pr=3", "pr=07"), ("pr=3", "pr=x"), ("pr=3", "pr="), ("pr=3", "pr=" + "9" * 601),
                     ("head=" + H40, "head=" + H40[:39]), ("head=" + H40, "head=" + H40 + "0"), ("head=" + H40, "head=" + H40.upper()),
                     ("merge=" + H40B, "merge=abcdef1"), ("merged_by=superbrobenji", "merged_by="), ("merged_by=superbrobenji", "by=superbrobenji"),
                     ("at=2026-11-02T08:59:36Z", "at=2026-11-02T08:59:36"), ("at=2026-11-02T08:59:36Z", "at=2026-11-02T08:59:36+00:00"),
                     ("at=2026-11-02T08:59:36Z", "at=2026-11-02 08:59:36Z"), ("at=2026-11-02T08:59:36Z", "at=12026-11-02T08:59:36Z"),
                     ("final=no", "final=maybe"), ("final=no", "final=YES"), ("final=no", "final="), ("merged_by=superbrobenji", "merged_by=\u00e9")):
            with self.subTest(a=a, b=b[:20]):
                self.assertEqual(sub(a, b), err)
        self.assertEqual(sub("pr=3", "pr=" + "9" * 600), [])
        self.assertEqual(sub("final=no", "final=yes"), [])
        # shape ok, calendar or clock wrong: the extra rule names it (D-Q23)
        for at in ("2026-13-40T25:61:61Z", "2026-02-30T00:00:00Z", "2026-11-02T24:00:00Z", "2026-11-02T00:00:60Z", "0000-01-01T00:00:00Z"):
            with self.subTest(at=at):
                self.assertEqual(sub("2026-11-02T08:59:36Z", at), ["line 2: at %s is not a valid UTC time" % at])
        self.assertEqual(sub("2026-11-02T08:59:36Z", "2024-02-29T23:59:59Z"), [])

    def test_merged_stream_block_optional(self):  # LP15 (D-Q24)
        pat = LS.rules["MERGED"][0]
        err = ["line 2: 'MERGED' line does not match " + pat]
        both = " stream=a block=1c"
        self.assertEqual(lerr(M0H), [])
        self.assertEqual(lerr(M0H.replace(both, "")), [])
        self.assertEqual(lerr(M0H.replace(" block=1c", "")), err)
        self.assertEqual(lerr(M0H.replace(" stream=a", "")), err)
        for s, b in (("init4", "4e"), ("residual", "R2"), ("a", "B2"), ("c", "P3"), ("docs", "5c")):
            self.assertEqual(lerr(M0H.replace("stream=a block=1c", "stream=%s block=%s" % (s, b))), [])
        for s, b in (("", "1c"), ("a b", "1c"), ("A", "1c"), ("\u00e9", "1c"), ("a", ""), ("a", "1 c"), ("a", "\u00e9"), ("a", "1-c"), ("-a", "1c")):
            with self.subTest(s=s, b=b):
                self.assertEqual(lerr(M0H.replace("stream=a block=1c", "stream=%s block=%s" % (s, b))), err)
        self.assertEqual(lerr(M0H.replace(both, "").replace(" approval=host", both + " approval=host")), [])
        self.assertEqual(lerr(M0H.replace(both + " approval=host", " approval=host" + both)), err)  # after approval

    def test_ledger_yml_patterns_load_verbatim(self):  # LP18
        want = [
            ("CHECKPOINT", "CHECKPOINT [!-~]+ [!-~]+ head=[0-9a-f]{7,40} tests=(?:0|[1-9][0-9]{0,599})/(?:0|[1-9][0-9]{0,599}) gates=(?:PASS|n/a) next=[!-~]+"),
            ("Ruling", "Ruling: (?![ -~\\xa7]* -- [ -~\\xa7]* -- [ -~\\xa7]* -- [ -~\\xa7]* -- )[!-~\\xa7](?:[ -~\\xa7]*[!-~\\xa7])? -- [!-~\\xa7](?:[ -~\\xa7]*[!-~\\xa7])? -- [!-~\\xa7](?:[ -~\\xa7]*[!-~\\xa7])? -- [!-~\\xa7](?:[ -~\\xa7]*[!-~\\xa7])?"),  # D-Q24: U+00A7 as \\xa7
            ("Request", "Request: [A-Za-z0-9]+-[0-9]{8}-[A-Za-z0-9]{4} from=[a-z0-9][a-z0-9-]* to=[a-z0-9][a-z0-9-]* files=[!-~]+ need=[ -~]+ status=(?:open|done|disputed)(?: sha=[0-9a-f]{7,40})?"),
            ("UPDATE", "UPDATE [!-~]+ from=[!-~]+@[0-9a-f]{7,40} head=[0-9a-f]{7,40} tests=(?:0|[1-9][0-9]{0,599})/(?:0|[1-9][0-9]{0,599}) gates=(?:PASS|n/a)"),
            ("MERGED", "MERGED pr=[1-9][0-9]{0,599} head=[0-9a-f]{40} merge=[0-9a-f]{40} merged_by=[!-~]+ at=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z final=(?:yes|no)(?: stream=[a-z0-9][a-z0-9-]* block=[0-9A-Za-z]+)? approval=(?:host|chat pr=[1-9][0-9]{0,599} head=[0-9a-f]{40} words= *[!-~][ -~]*)"),
        ]
        self.assertEqual([(i["word"], i["pattern"]) for i in LS.lines], want)
        self.assertEqual(LS.first_line, "<!-- schema: ledger/1 -->")
        self.assertEqual((LS.kind, LS.version, LS.format), ("ledger", 1, "markdown"))

    def test_ledger_patterns_ascii_only(self):  # LP19, V4
        self.assertEqual(dispatch.MAX_DIGITS, 600)  # the numeral bound of the patterns is the repository cap (V1, D-Q26)
        for word, (pattern, compiled) in LS.rules.items():
            with self.subTest(word=word):
                self.assertTrue(all(" " <= c <= "~" for c in pattern))
                for esc in ("\\w", "\\d", "\\s", "\\b", "\\W", "\\D", "\\S", "\\B", "(?i", "(?s"):
                    self.assertNotIn(esc, pattern)
        for ch in ("\u0870", "\u00a0", "\u2028", "\U0001fae8"):  # same verdict on both: refused
            self.assertEqual(len(lerr(C0.replace("1a.1", "1a" + ch))), 1)
            self.assertEqual(len(lerr(M0C.replace("approve", "app" + ch))), 1)

    def test_ledger_patterns_against_reference_oracle(self):  # the independent oracle of the table (PC1)
        bases = (C0, Q0, U0, M0H, M0C, Q0 + " sha=abcdef1", R0,
                 "CHECKPOINT merged planning head=228c872 tests=716/716 gates=PASS next=resume-plan-reviews")
        verdicts = {True: 0, False: 0}
        for base in bases:
            for line in variants(base) + (ruling_variants() if base == R0 else []):
                got = pattern_ok(line)
                verdicts[got] += 1
                self.assertEqual(got, ref_ok(line), repr(line))
        for line in ruling_variants():
            self.assertEqual(pattern_ok(line), ref_ok(line), repr(line))
        self.assertGreater(verdicts[True], 300)  # conforming (and prose) variants
        self.assertGreater(verdicts[False], 1500)  # nonconforming variants

    def test_pattern_cost_on_long_lines(self):  # a hostile long line must not take long (no nested unbounded quantifiers)
        import time
        t0 = time.time()
        for body in ("Ruling: " + "a -- " * 400 + "z", "Ruling: " + "a " * 3000, "Request: R-20261102-bn3p from=c to=a files=x need=" + "n " * 3000,
                     "MERGED pr=3 head=%s merge=%s merged_by=x at=2026-11-02T08:59:36Z final=no approval=chat pr=3 head=%s words=%s" % (H40, H40, H40, " " * 5000),
                     "CHECKPOINT " + "a " * 3000):
            self.assertIsInstance(lerr(body), list)
        self.assertLess(time.time() - t0, 5.0)


# ======================================================================== readers (producers 7 and 8)

LEDGER = (LH + "CHECKPOINT 1a 1a.1 head=abcdef1 tests=5/5 gates=PASS next=1a.2\n"
          "CHECKPOINT 1a 1a.2 head=abcdef2 tests=7/8 gates=n/a next=1a.3\n")
MERGED_FINAL = M0H.replace("final=no", "final=yes")
MERGED_FINAL2 = MERGED_FINAL.replace("pr=3", "pr=4", 1)


class CheckpointLines(unittest.TestCase):
    def test_checkpoint_lines_parsed_in_order(self):  # CP1, plan P:2493-2494
        self.assertEqual([c["next"] for c in checkpoint_lines(LEDGER)], ["1a.2", "1a.3"])
        self.assertEqual(checkpoint_lines(LEDGER), [
            {"line": 2, "block": "1a", "task": "1a.1", "head": "abcdef1", "passed": 5, "total": 5, "gates": "PASS", "next": "1a.2"},
            {"line": 3, "block": "1a", "task": "1a.2", "head": "abcdef2", "passed": 7, "total": 8, "gates": "n/a", "next": "1a.3"}])

    def test_checkpoint_lines_carry_line_numbers(self):  # CP2, plan P:2509-2510
        self.assertEqual([c["line"] for c in checkpoint_lines(LEDGER)], [2, 3])
        t = LH + "prose\n\n" + C0 + "\nmore\n" + C0 + "\n"
        self.assertEqual([c["line"] for c in checkpoint_lines(t)], [4, 6])

    def test_checkpoint_line_values(self):  # CP3
        c = checkpoint_lines(LH + C0.replace("5/5", "5/7") + "\n")[0]
        self.assertIs(type(c["passed"]), int)
        self.assertIs(type(c["total"]), int)
        self.assertEqual((c["passed"], c["total"], c["gates"]), (5, 7, "PASS"))

    def test_checkpoint_lines_none(self):  # CP4
        for t in (LH, LH + "prose", ""):
            self.assertEqual(checkpoint_lines(t), [])

    def test_checkpoint_lines_skips_bad(self):  # CP5, D-Q25
        t = LH + "CHECKPOINT bad\n" + C0 + " x\nCHECKPOINT: " + C0[11:] + "\n" + C0 + "\n"
        self.assertEqual([c["line"] for c in checkpoint_lines(t)], [5])

    def test_checkpoint_lines_first_token(self):  # CP6
        t = LH + "prose " + C0 + "\n " + C0 + "\n- " + C0 + "\n```\n" + C0 + "\n```\n"
        self.assertEqual([c["line"] for c in checkpoint_lines(t)], [6])  # a fence is not special
        self.assertEqual(checkpoint_lines(C0 + "\n"), [])  # the first line is never a keyword line

    def test_checkpoint_lines_text_types(self):  # CP8, LE15
        for t in (None, b"", 5, ["x"]):
            with self.subTest(t=t):
                with self.assertRaises(ValueError):
                    checkpoint_lines(t)
                with self.assertRaises(ValueError):
                    merged_lines(t)

    def test_checkpoint_numbers_same_on_both(self):  # CP7, V1: no unguarded int() of long text
        for limit in INT_LIMITS:
            with int_limit(limit):
                big = "9" * 600
                got = checkpoint_lines(LH + "CHECKPOINT a b head=abcdef1 tests=%s/%s gates=n/a next=c\n" % (big, big))
                self.assertEqual(got[0]["passed"], int(big))
                for n in (601, 4300, 4301):
                    t = LH + "CHECKPOINT a b head=abcdef1 tests=%s/1 gates=n/a next=c\n" % ("9" * n)
                    self.assertEqual(checkpoint_lines(t), [])
                    self.assertEqual(len(ledger_errors(t, cfg())), 1)

    def test_checkpoint_lines_real_ledger(self):  # CP9, LE16
        path = os.path.join(REPO, ".strict-delivery", "state", "plans", "2026-10-31-strict-delivery-framework", "ledger.md")
        if not os.path.exists(path):
            self.skipTest("no real ledger")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        text = body if body.startswith(LH) else LH + body
        got = checkpoint_lines(text)
        self.assertIsInstance(got, list)
        self.assertEqual([c["line"] for c in got], sorted(c["line"] for c in got))
        self.assertIsInstance(ledger_errors(text, cfg()), list)  # test_ledger_errors_real_ledger_reports_known_nonconforming
        self.assertIsInstance(merged_lines(text), list)


class MergedLines(unittest.TestCase):
    def test_merged_line_form_and_single_final(self):  # ML1, ML2, LE7, LE8; plan P:2490-2492 (owner Q-15 (a))
        self.assertEqual(merged_lines(LH + MERGED_FINAL)[0]["final"], "yes")
        self.assertTrue(any("final=yes after a final line" in e for e in ledger_errors(LH + MERGED_FINAL + "\n" + MERGED_FINAL2 + "\n", cfg())))
        a1 = MERGED_FINAL
        a2 = MERGED_FINAL.replace("pr=3", "pr=5", 1)
        b1 = MERGED_FINAL.replace("pr=3", "pr=4", 1).replace("stream=a", "stream=b")
        ok = ledger_errors(LH + a1 + "\n" + b1 + "\n", cfg(), per_stream=True)
        self.assertFalse(any("final=yes after" in e for e in ok))
        bad = ledger_errors(LH + a1 + "\n" + a2 + "\n", cfg(), per_stream=True)
        self.assertEqual(bad, ["line 3: final=yes after a final line of stream a"])
        self.assertTrue(any("final=yes after a final line of stream a" in e for e in bad))
        self.assertEqual(ledger_errors(LH + a1 + "\n" + b1 + "\n", cfg()), ["line 3: final=yes after a final line"])  # default: plan-wide
        self.assertEqual(ledger_errors(LH + a1 + "\n" + M0H.replace("pr=3", "pr=6", 1) + "\n", cfg()), [])  # final=yes then final=no
        self.assertEqual(ledger_errors(LH + M0H.replace("pr=3", "pr=6", 1) + "\n" + a1 + "\n", cfg()), [])  # final=no then final=yes
        h = merged_lines(LH + M0H + "\n")[0]
        self.assertEqual(h, {"pr": 3, "head": H40, "merge": H40B, "merged_by": "superbrobenji", "at": "2026-11-02T08:59:36Z",
                             "final": "no", "stream": "a", "block": "1c", "approval": "host", "approval_pr": None,
                             "approval_head": None, "words": None})
        c = merged_lines(LH + M0C + "\n")[0]
        self.assertEqual((c["approval"], c["approval_pr"], c["approval_head"], c["words"]), ("chat", 3, H40, "approve PR 3"))
        d = merged_lines(LH + M0C.replace("approval=chat pr=3 head=%s" % H40, "approval=chat pr=5 head=%s" % H40B) + "\n")[0]
        self.assertEqual((d["pr"], d["head"], d["approval_pr"], d["approval_head"]), (3, H40, 5, H40B))  # the two pr/head pairs apart
        self.assertEqual(sorted(d), sorted(h))
        self.assertIs(type(c["pr"]), int)
        self.assertIs(type(c["approval_pr"]), int)

    def test_merged_lines_legacy_fields_none(self):  # ML3, ML4
        legacy = M0H.replace(" stream=a block=1c", "")
        three = [legacy.replace("pr=3", "pr=%d" % n, 1) for n in (7, 5, 6)]
        got = merged_lines(LH + "\n".join(three) + "\n")
        self.assertEqual([g["pr"] for g in got], [7, 5, 6])  # file order
        self.assertTrue(all(g["stream"] is None and g["block"] is None for g in got))

    def test_merged_lines_real_specimens(self):  # ML6
        t = LH + "MERGED PR-1c0 (#4): owner x\nMERGED pr=1 head=7aeb5d4 approval=chat\n" + M0H + "\n"
        self.assertEqual([g["pr"] for g in merged_lines(t)], [3])

    def test_merged_words_verbatim(self):  # ML7
        for w in ("a=b", 'say "hi"', "final=yes", "x" * 4301, "  lead and trail  ", "a  b", "(x) -> y"):
            with self.subTest(words=w[:10]):
                self.assertEqual(merged_lines(LH + M0C.replace("approve PR 3", w) + "\n")[0]["words"], w)

    def test_merged_numbers_same_on_both(self):  # ML8, V1
        for limit in INT_LIMITS:
            with int_limit(limit):
                big = "9" * 600
                self.assertEqual(merged_lines(LH + M0H.replace("pr=3", "pr=" + big, 1) + "\n")[0]["pr"], int(big))
                for n in (601, 4300, 4301):
                    t = LH + M0H.replace("pr=3", "pr=" + "9" * n, 1) + "\n"
                    self.assertEqual(merged_lines(t), [])
                    self.assertEqual(len(ledger_errors(t, cfg())), 1)


class LedgerErrors(unittest.TestCase):
    def test_ledger_clean(self):  # LE1, LP3
        self.assertEqual(lerr(C0 + "\n" + R0), [])
        for line in (C0, R0, Q0, U0, M0H, M0C):
            self.assertEqual(lerr(line), [], line)

    def test_merged_pr_recorded_twice(self):  # LE6 (D-Q23)
        m = lambda pr, stream="a": M0H.replace("pr=3", "pr=%s" % pr, 1).replace("stream=a", "stream=%s" % stream)
        self.assertEqual(ledger_errors(LH + m(3) + "\n" + m(3) + "\n" + m(3) + "\n", cfg()),
                         ["line 3: pr 3 recorded twice", "line 4: pr 3 recorded twice"])
        self.assertEqual(ledger_errors(LH + m(3) + "\n" + m(3, "b") + "\n", cfg(), per_stream=True), ["line 3: pr 3 recorded twice"])
        self.assertEqual(ledger_errors(LH + m(3) + "\n" + m(4) + "\n", cfg()), [])
        self.assertEqual(len(ledger_errors(LH + m(3) + "\n" + m("03") + "\n", cfg())), 1)  # 03 fails the pattern, no pr to count

    def test_unknown_stream_checked_only_when_ids_given(self):  # LE9 (D-Q24)
        t = lambda s: LH + M0H.replace("stream=a", "stream=%s" % s) + "\n"
        self.assertEqual(ledger_errors(t("a"), cfg(), stream_ids={"a", "b"}), [])
        self.assertEqual(ledger_errors(t("c"), cfg(), stream_ids={"a", "b"}), ["line 2: unknown stream c"])
        self.assertEqual(ledger_errors(t("c"), cfg(), stream_ids=frozenset({"a"})), ["line 2: unknown stream c"])
        self.assertEqual(ledger_errors(t("a"), cfg(), stream_ids=set()), ["line 2: unknown stream a"])
        self.assertEqual(ledger_errors(t("c"), cfg()), [])  # None: not checked (Q-F80-2 (a))
        self.assertEqual(ledger_errors(t("c"), cfg(), stream_ids=None), [])
        legacy = LH + M0H.replace(" stream=a block=1c", "") + "\n"
        self.assertEqual(ledger_errors(legacy, cfg(), stream_ids={"a"}), [])  # no stream: skipped
        legacy2 = legacy + legacy.split("\n")[1].replace("pr=3", "pr=4", 1).replace("final=no", "final=yes") + "\n"
        legacy3 = legacy2 + legacy.split("\n")[1].replace("pr=3", "pr=5", 1).replace("final=no", "final=yes") + "\n"
        self.assertEqual(ledger_errors(legacy3, cfg(), per_stream=True), ["line 4: final=yes after a final line of stream (none)"])

    def test_merged_block_needs_heading(self):  # LE10, D-Q29, D-Q30
        plan = ("# Plan\n\n## Block 1c: gates (branch)\n\ntext\n\n## Block 2 (sub-blocks 2a, 2b)\n\n### Block 2a: x\n")
        self.assertEqual(ledger_errors(LH + M0H + "\n", cfg(), plan_text=plan), [])
        self.assertEqual(ledger_errors(LH + M0H.replace("block=1c", "block=9z") + "\n", cfg(), plan_text=plan),
                         ["line 2: block 9z has no block heading"])
        self.assertEqual(ledger_errors(LH + M0H.replace("block=1c", "block=9z") + "\n", cfg(), plan_text=""),
                         ["line 2: block 9z has no block heading"])  # "" is given: every block has no heading
        self.assertEqual(ledger_errors(LH + M0H.replace("block=1c", "block=9z") + "\n", cfg(), plan_text=None), [])
        self.assertEqual(ledger_errors(LH + M0H.replace(" stream=a block=1c", "") + "\n", cfg(), plan_text=""), [])  # no block field
        self.assertEqual(ledger_errors(LH + M0H.replace("block=1c", "block=1c0") + "\n", cfg(), plan_text=plan),
                         ["line 2: block 1c0 has no block heading"])

    def test_block_heading_grammar(self):  # D-Q30: P:2739 read exactly
        ids_ = checkpoints.block_ids
        self.assertEqual(ids_("## Block 1a: x\n## Block 2 (sub)\n"), {"1a", "2"})
        self.assertEqual(ids_("## Block 1a x\n## Block 1b\n## Block 1c:\n## Block 1d(\n## Block P1:y"), {"1c", "P1"})
        self.assertEqual(ids_("### Block B2: x\n"), set())  # outside a Stream section
        self.assertEqual(ids_("## Stream B\n### Block B2: x\n### Block B3 (y)\n## Block P1: z\n### Block B4: w\n"), {"B2", "B3", "P1"})
        self.assertEqual(ids_("## Stream `runtime`, sub-block 3a (branch x)\n"), {"3a"})
        self.assertEqual(ids_("## Stream a, sub-block 5c\n## Stream b, sub-block 6 x\n## Stream c, sub-block 7c (\n"), {"5c", "7c"})
        self.assertEqual(ids_("## Stream a, sub-block 5c\r\n"), set())
        self.assertEqual(ids_("### Block 3 end (x)\n### Block 5 divergences (y)\n## Block 9\n"), set())
        self.assertEqual(ids_("# Block 1a: x\n#### Block 1b: x\n Block 1c: x\n## block 1d: x\n## Block 1é: x\n## Block 1e :x\n"), set())
        self.assertEqual(ids_("## Stream a, sub-block 5c (x)\n### Block 5c1: y\n## Other\n### Block 5c2: z\n"), {"5c", "5c1"})
        self.assertEqual(ids_("```\n## Block 1a: x\n```\n"), {"1a"})  # a fence is not special

    def test_ledger_errors_does_not_check_block_tasks(self):  # LE11
        two = M0H + "\n" + M0H.replace("pr=3", "pr=4", 1).replace("final=no", "final=no")
        self.assertEqual(ledger_errors(LH + two + "\n", cfg(), plan_text="## Block 1c: x\n"), [])  # two lines for one block

    def test_ledger_errors_order(self):  # LE12, D-Q27
        body = (C0.replace("5/5", "6/5") + "\nCHECKPOINT bad\n" + Q0.replace("bn3p", "bn0p") + "\n" + M0H.replace("at=2026-11-02T08:59:36Z", "at=2026-02-30T00:00:00Z") + "\n")
        got = ledger_errors(LH + body, cfg())
        self.assertEqual([e.split(":")[0] for e in got], ["line 2", "line 3", "line 4", "line 5"])
        self.assertEqual(got[0], "line 2: tests passed > total")
        self.assertTrue(got[1].startswith("line 3: 'CHECKPOINT' line does not match"))
        self.assertTrue(got[2].startswith("line 4: R-20261102-bn0p: "))
        self.assertEqual(got[3], "line 5: at 2026-02-30T00:00:00Z is not a valid UTC time")
        # a line failing its pattern gets no extra rule (D-Q27)
        self.assertEqual(len(lerr("CHECKPOINT x y head=abcdef1 tests=5/4 gates=FAIL next=z")), 1)

    def test_ledger_errors_argument_types(self):  # LE13 (D-Q27)
        for kw in ({"plan_text": 5}, {"plan_text": b"x"}, {"stream_ids": ["a"]}, {"stream_ids": "abc"}, {"stream_ids": {1}},
                   {"stream_ids": {"a": 1}}, {"per_stream": 1}, {"per_stream": None}, {"per_stream": "yes"}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    ledger_errors(LH + C0 + "\n", cfg(), **kw)
        self.assertEqual(ledger_errors(LH, cfg(), plan_text="", stream_ids=frozenset(), per_stream=True), [])

    def test_ledger_errors_text_types(self):  # LE15
        for t in (None, b"x", 5):
            self.assertEqual(ledger_errors(t, cfg()), ["first line: text must be a string"])

    def test_ledger_errors_real_ledger_reports_known_nonconforming(self):  # LE16
        path = os.path.join(REPO, ".strict-delivery", "state", "plans", "2026-10-31-strict-delivery-framework", "ledger.md")
        if not os.path.exists(path):
            self.skipTest("no real ledger")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        text = body if body.startswith(LH) else LH + body
        errs = ledger_errors(text, cfg())
        self.assertTrue(all(e.startswith("line ") for e in errs))
        lines = text.split("\n")
        flagged = {int(e.split(":")[0][5:]) for e in errs}
        for n, line in enumerate(lines, 1):  # every line the oracle calls bad is flagged
            if n > 1 and not ref_ok(line):
                self.assertIn(n, flagged, line[:80])


# ======================================================================== the section sign in a Ruling (F-20261118-ikag)

RULING_BEFORE = ("Ruling: (?![ -~]* -- [ -~]* -- [ -~]* -- [ -~]* -- )[!-~](?:[ -~]*[!-~])? -- [!-~](?:[ -~]*[!-~])? -- "
                 "[!-~](?:[ -~]*[!-~])? -- [!-~](?:[ -~]*[!-~])?")
# the six real Ruling lines of origin/main's ledger.md (lines 19, 24, 25, 102, 103, 107) and the seventh (line 20)
REAL_RULINGS = {
    19: "Ruling: .gitignore (`.superpowers/`, `__pycache__/`, `.strict-delivery/receipts/`) is created in Task 1a.1 -- the clean-tree rule needs it and no task owns it -- cost if wrong: one extra file in 1a.1's diff -- spec §5 (receipts git-ignored), §16",
    24: 'Ruling: unstated grammar rules 1,2,5,6,7 (extra plain-start refusals `, ] } ? -`, trailing-comma refusal, control-char/surrogate refusal, top-level scalar accepted, quoted \'<<\' is a plain key) stand -- each refuses an input outside the accepted grammar (fail closed) or accepts a node the grammar already lists -- cost if wrong: a hand-written file using these needs quoting -- plan Global Constraints "every other YAML feature is refused with a line number", spec §6',
    25: 'Ruling: unstated rule 8 (load() on missing/unreadable file raises OSError) is a defect, fixed in round 1 as YamlError naming `shown` -- brief: "Every YamlError from it carries shown"; gates fail closed on missing input as <gate>.input -- cost if wrong: none -- spec §13',
    102: 'Ruling: R-rev3-1 finding owner keys declared in finding.yml via required_when/absent_when on kind (nested map) -- spec §7.2 "never from hand-coded field lists" settles it -- cost if wrong: schema-language nesting rework in 1b.1 -- spec §7.2.',
    103: 'Ruling: R-rev3-2 decisions ask candidates = union of per-topic, per-applies_to-glob (equal or fnmatch either way) and per-question-word (>=4 chars) find hits -- spec §7.4 "runs find on the new question\'s topics, paths and keywords" needs OR to find related records -- cost if wrong: noisier or thinner candidate lists -- spec §7.4.',
    107: 'Ruling: R-rev5-1 config.load refuses two ids kinds sharing a prefix -- spec §7.2 cross-register uniqueness through the prefix check presumes distinct prefixes -- cost if wrong: a project cannot alias prefixes -- spec §7.2. Rulings this block: 3 of 5.',
}
REAL_RULING_20 = ("Ruling: strict prompt blocks are dispatched verbatim; their lap-timer commit-gate paths (tools/gates/run_all.py, "
                  "tools/.venv) do not exist here, so each ## Task states this repo's bootstrap commit gate -- cost if wrong: a "
                  "child follows the wrong gate text -- spec §16 bootstrap")
SS = "§"


def _ruling_with(i, part):
    ps = ["a", "b", "c", "d"]
    ps[i] = part
    return "Ruling: " + " -- ".join(ps)


class RulingSectionSign(unittest.TestCase):
    def test_pattern_text_only_gained_the_escape(self):  # the dialect, and nothing else changed
        pat = LS.rules["Ruling"][0]
        self.assertEqual(schema._pattern_problem(pat), "")
        self.assertTrue(all(" " <= c <= "~" for c in pat))
        self.assertEqual(pat.replace("\\xa7", ""), RULING_BEFORE)
        self.assertEqual(pat.count("\\xa7"), 16)
        self.assertEqual(sum(pat.count(c) for c in "*+?|"), 17)  # the quantifier count is unchanged
        self.assertEqual(sum(pat.count(c) for c in "{}"), 0)

    def test_other_patterns_do_not_mention_the_escape(self):
        for word in ("CHECKPOINT", "Request", "UPDATE", "MERGED"):
            self.assertNotIn("xa7", LS.rules[word][0], word)

    def test_section_sign_in_each_part_position(self):
        for i in range(4):
            for name, part in (("alone", SS), ("first", SS + "x"), ("last", "x" + SS), ("both ends", SS + "x" + SS),
                               ("inside", "x" + SS + "y"), ("with spaces", "x " + SS + " y")):
                with self.subTest(part=i, name=name):
                    self.assertEqual(lerr(_ruling_with(i, part)), [])

    def test_section_sign_in_all_four_parts(self):
        self.assertEqual(lerr("Ruling: " + " -- ".join([SS] * 4)), [])

    def test_section_sign_does_not_open_a_fifth_part_or_a_space_edge(self):
        pat = LS.rules["Ruling"][0]
        err = ["line 2: 'Ruling' line does not match " + pat]
        for line in ("Ruling: a -- b -- c -- d -- " + SS, "Ruling: " + " -- ".join([SS] * 5), "Ruling: a -- b -- c --  " + SS,
                     "Ruling: " + SS + " -- b -- c", "Ruling: a -- b -- c -- " + SS + " "):
            with self.subTest(line=line):
                self.assertEqual(lerr(line), err)

    def test_neighbours_and_other_non_ascii_stay_refused_in_every_part(self):
        pat = LS.rules["Ruling"][0]
        err = ["line 2: 'Ruling' line does not match " + pat]
        for cp in (0xa0, 0xa6, 0xa8, 0xe9, 0x2014, 0x870, 0x1fae8, 0x80, 0xff, 0x7f, 0x09, 0xa7 + 0x100):
            c = chr(cp)
            for i in range(4):
                for name, part in (("alone", c), ("first", c + "x"), ("last", "x" + c), ("inside", "x" + c + "y")):
                    with self.subTest(cp="U+%04X" % cp, part=i, name=name):
                        self.assertEqual(lerr(_ruling_with(i, part)), err)

    def test_real_ruling_lines_of_origin_main_match(self):
        for n, line in REAL_RULINGS.items():
            with self.subTest(line=n):
                self.assertTrue(line.startswith("Ruling: ") and SS in line)
                self.assertEqual(lerr(line), [])
                self.assertTrue(pattern_ok(line))

    def test_real_ruling_line_20_still_fails_with_two_separators(self):
        pat = LS.rules["Ruling"][0]
        self.assertEqual(REAL_RULING_20.count(" -- "), 2)
        self.assertEqual(lerr(REAL_RULING_20), ["line 2: 'Ruling' line does not match " + pat])
        self.assertEqual(lerr(REAL_RULING_20.replace(SS, "s")), ["line 2: 'Ruling' line does not match " + pat])

    def test_other_four_line_kinds_refuse_the_section_sign(self):
        for name, base, old in (("CHECKPOINT", C0, "1a.1"), ("CHECKPOINT next", C0, "1a.2"), ("Request files", Q0, "gates/__main__.py"),
                                ("Request need", Q0, "register cites"), ("UPDATE", U0, "1b"), ("MERGED words", M0C, "approve PR 3"),
                                ("MERGED by", M0H, "superbrobenji")):
            for new in (SS, "x" + SS, SS + "x"):
                line = base.replace(old, new, 1)
                with self.subTest(kind=name, new=new):
                    self.assertNotEqual(line, base)
                    self.assertFalse(pattern_ok(line))
                    self.assertEqual(len(lerr(line)), 1)
                    self.assertFalse(ref_ok(line))
        self.assertTrue(pattern_ok(C0) and pattern_ok(Q0) and pattern_ok(U0) and pattern_ok(M0H) and pattern_ok(M0C))

    def test_reference_parser_agrees_on_every_ruling_variant(self):
        extra = [_ruling_with(i, p) for i in range(4) for p in (SS, SS + "x", "x" + SS, " ", "¦", "¨", "é", "—", "ࡰ")]
        for line in ruling_variants() + extra:
            with self.subTest(line=line):
                self.assertEqual(pattern_ok(line), ref_ok(line))


# ======================================================================== the repository and the versions

class Repository(unittest.TestCase):
    def test_handoff_and_ledger_unproduced_not_checked(self):  # GS1 (P:2456)
        from io import StringIO
        out = StringIO()
        with mock.patch("sys.stdout", out):
            code = gates_main.main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out.getvalue())
        self.assertNotIn("schema.handoff", out.getvalue())
        self.assertNotIn("schema.ledger", out.getvalue())

    def test_schema_files_load(self):  # GS2
        sch = schema.schemas()
        self.assertEqual(sorted(sch), ["breakdown", "claim", "claude-block", "config", "decision", "decision-index",
                                       "finding", "finding-index", "gitignore-block", "handoff", "in-force",
                                       "init-answers", "ledger", "merged-log", "mutation-transcript", "overview", "profile", "request",
                                       "review-report", "status", "streams", "sync-log"])  # Task P2.1 part i adds the five program schemas; Task 4a.1 adds four; 6E.1 the two evidence kinds
        for k in ("handoff", "ledger"):
            self.assertIn(k, schema.KNOWN_KINDS)

    def test_migrate_handoff_ledger_identity(self):  # GS4
        self.assertEqual(migrations.current_version("handoff"), 1)
        self.assertEqual(migrations.current_version("ledger"), 1)
        row = {"schema": "handoff/1", "plan": "x"}
        self.assertEqual(migrations.migrate("handoff", copy.deepcopy(row)), row)

    def test_checkpoints_imports_same_on_both(self):  # GS5
        src = slurp(checkpoints.__file__)
        self.assertNotIn("BaseExceptionGroup", src)
        self.assertNotIn("except BaseException", src)
        self.assertIsNone(re.search(r"(?m)^\s*except\s*:", src))
        self.assertEqual(sorted(m for m in ("dispatch", "ids", "schema", "yamlsub") if "from gates.lib import" in src), ["dispatch", "ids", "schema", "yamlsub"])

    def test_digit_limits_same_on_both(self):  # V1 (rows HF11, CP7, ML8 carry the cases; the library has no int() of text above 600 digits)
        for limit in INT_LIMITS:
            with int_limit(limit):
                self.assertEqual(plan_slug("d/" + "x" * 4301 + ".md"), "x" * 4301)
                self.assertEqual(len(resume_line(R(next_task="9" * 4301))), len(resume()) - 4 + 4301)

    def test_unicode_version_independent(self):  # V2: no str.lower/isprintable/\w decides a verdict
        for ch in ("\u0870", "\U0001fae8", "\u2c2f", "\u0c5d", "\u00a0", "\u2028", "\u0085"):
            with self.subTest(ch=repr(ch)):
                self.assertIn("questions.q1.source: must be a non-empty single line of printable ASCII",
                              he(questions=[{**Q1, "source": "a" + ch}], resume=resume(["q1"])))
                self.assertIn("worktrees.1.path: must be '.' or a normalised relative path with '..' only as a leading run "
                              "(printable ASCII, no backslash)", he(worktrees=[WT_ROOT, {**WT_OTHER, "path": "w" + ch}]))
                self.assertEqual(he(questions=[{**Q1, "qid": "q" + ch}])[0:0], [])
                self.assertIn("questions.0.qid: must be a string matching [a-z0-9][a-z0-9-]*", he(questions=[{**Q1, "qid": "q" + ch}]))

    def test_exception_groups_propagate(self):  # V3
        beg = getattr(builtins, "BaseExceptionGroup", None)
        eg = getattr(builtins, "ExceptionGroup", None)
        if beg is None:
            self.skipTest("BaseExceptionGroup is absent on this interpreter (3.9)")
        for exc in (beg("x", [KeyboardInterrupt()]), eg("x", [ValueError()])):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(ids, "id_problem", side_effect=exc):
                    with self.assertRaises(beg) as cm:
                        ledger_errors(LH + Q0 + "\n", cfg())
                self.assertIs(cm.exception, exc)
                with mock.patch.object(schema, "load_schema", side_effect=exc):
                    with self.assertRaises(beg) as cm:
                        checkpoint_lines(LEDGER)
                self.assertIs(cm.exception, exc)



class FixRound1(unittest.TestCase):
    """Fix round 1 of Task P1.2 (findings F-20261118-rkcp, -s325, -n8fn, -2tif)."""

    def test_empty_nested_strings_refused(self):  # F-20261118-rkcp: every nested str field refuses ""
        sub = lambda **kw: R(live_subagents=[{**SUB, **kw}])
        job = lambda **kw: R(live_subagents=[{**SUB, "jobs": [{"id": "j", "state": "running", **kw}]}])
        qq = lambda **kw: R(questions=[{**Q1, **kw}])
        opt = lambda **kw: R(questions=[{**Q1, "options": [{**OPTS[0], **kw}, OPTS[1]]}])
        cases = [
            ("live_subagents.0.agent", sub(agent="")), ("live_subagents.0.task", sub(task="")),
            ("live_subagents.0.worktree", sub(worktree="")), ("live_subagents.0.transcript", sub(transcript="")),
            ("live_subagents.0.last_record", sub(last_record="")), ("live_subagents.0.jobs.0.id", job(id="")),
            ("questions.0.qid", qq(qid="")), ("questions.0.class", qq(**{"class": ""})),
            ("questions.0.question", qq(question="")), ("questions.0.recommended", qq(recommended="")),
            ("questions.0.source", qq(source="")), ("questions.0.options.0.label", opt(label="")),
            ("questions.0.options.0.cost", opt(cost="")),
        ]
        for path, row in cases:
            with self.subTest(path=path):
                self.assertIn("%s: must be a non-empty string" % path, vf(row))
        # D-Q8 (controller, review F3): an empty recommended gets the schema error and the label error
        self.assertEqual(vf(qq(recommended="")), ["questions.0.recommended: must be a non-empty string"])
        self.assertEqual([e for e in he(questions=[{**Q1, "recommended": ""}], resume=resume(["q1"]))],
                         ["questions.q1.recommended:  is not the label of exactly one option"])

    def test_recommended_with_three_options(self):  # F-20261118-s325
        three = [{"label": "a", "cost": "x"}, {"label": "b", "cost": "y"}, {"label": "c", "cost": "z"}]
        e = lambda rec: he(questions=[{**Q1, "options": three, "recommended": rec}], resume=resume(["q1"]))
        for rec in ("a", "b", "c"):
            self.assertEqual(e(rec), [], rec)
        self.assertEqual(e("d"), ["questions.q1.recommended: d is not the label of exactly one option"])
        twin = [{"label": "a", "cost": "x"}, {"label": "b", "cost": "y"}, {"label": "b", "cost": "z"}]
        self.assertEqual(he(questions=[{**Q1, "options": twin, "recommended": "b"}], resume=resume(["q1"])),
                         ["questions.q1.recommended: b is not the label of exactly one option"])
        self.assertEqual(he(questions=[{**Q1, "options": twin, "recommended": "a"}], resume=resume(["q1"])), [])

    def test_ledger_argument_texts_and_wrong_typed_ledger(self):  # F-20261118-n8fn
        self.assertEqual(he(ledger=5), [])  # a non-str ledger is the schema's error, no 'expected' error beside it
        self.assertEqual(he(ledger=None), [])
        t = LH + C0 + "\n"
        for kw, msg in (({"plan_text": 5}, "ledger_errors: plan_text must be None or a string"),
                        ({"stream_ids": ["a"]}, "ledger_errors: stream_ids must be None or a set of strings"),
                        ({"stream_ids": {1}}, "ledger_errors: stream_ids must be None or a set of strings"),
                        ({"per_stream": 1}, "ledger_errors: per_stream must be a bool")):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError) as cm:
                    ledger_errors(t, cfg(), **kw)
                self.assertEqual(str(cm.exception), msg)

    def test_required_read_path_refuses_backslash(self):  # F-20261118-2tif (D-Q11, as worktrees.<i>.path)
        bad = "required_reads.0.path: must be a normalised repo-relative path (no leading '/', no '..' segment, not '.')"
        for p in ("a\\b", "a\\", "\\a", "dir/a\\b.md"):
            with self.subTest(path=p):
                self.assertEqual(he(required_reads=[{"path": p, "why": "w"}]), [bad])
        self.assertEqual(he(required_reads=[{"path": "dir/a.md", "why": "w"}]), [])


if __name__ == "__main__":
    unittest.main()
