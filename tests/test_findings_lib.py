"""Tests for the finding schema and rules (gates.lib.findings) through the production call paths: rows are
written with ``write_record`` and read back with ``yamlsub.load``; evidence runs on real git repositories.
Expected error lists are written out literally, never derived from the code under test."""
import copy
import hashlib
import os
import unittest

from gates.lib import config, gitinfo, schema, yamlsub
from gates.lib.findings import (RESOLVED, SEVERITIES, STATUSES, TRANSITIONS, epic_errors, evidence_errors,
                                is_resolved, may_delete, transition_errors, validate)
from gates.lib.result import GateError
from gates.lib.store import Record
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, write_record

F1 = "F-20261031-k3f9"
F2 = "F-20261031-m4n5"
F3 = "F-20261031-p6q7"
F4 = "F-20261031-r8s9"
DA = "DEC-20261031-k3f9"
DB = "DEC-20261031-m4n5"
DC = "DEC-20261031-p6q7"
SHA = "a1b2c3d"
OWNER = {"kind": "plan", "plan": "p", "task": "1a.2"}
FINDING = {"schema": "finding/1", "id": F1, "status": "open", "source": "review", "severity": "HIGH",
           "class": "bug", "siblings": [], "cites": [{"file": "src/x.py", "lines": "1-2", "sha": SHA}],
           "repro": None, "owner": OWNER, "pin": None, "ruling": None, "evidence": [],
           "history": [{"status": "open", "sha": SHA, "by": "agent"}]}
PLAN_STATE = ".strict-delivery/state/plans"
T = PLAN_STATE + "/p/mutations/F.txt"
R = "docs/strict-delivery/reviews/p/r.md"
PATHS_OF = {"open": ["open"], "planned": ["open", "planned"], "in-progress": ["open", "planned", "in-progress"],
            "fixed-unpinned": ["open", "planned", "in-progress", "fixed-unpinned"],
            "pinned": ["open", "planned", "in-progress", "pinned"], "deferred": ["open", "deferred"],
            "closed": ["open", "closed"], "merged": ["open", "planned", "in-progress", "pinned", "merged"]}


def hist(*statuses):
    return [{"status": s, "sha": SHA, "by": "agent"} for s in statuses]


def drop(row, *keys):
    return {k: v for k, v in row.items() if k not in keys}


def mk(status, **over):
    """A finding row at ``status`` with a legal history; resolved statuses carry ``resolved_by``."""
    row = {**FINDING, "status": status, "history": hist(*PATHS_OF[status])}
    if status in RESOLVED:
        row["resolved_by"] = "p"
    return {**row, **over}


CLOSED = mk("closed")


def rec(row):
    return Record(row["id"], row, "x/%s.yml" % row["id"])


def dec(id_, status="answered", **over):
    base = {"schema": "decision/1", "id": id_, "status": status, "class": "scope", "question": "Keep X?",
            "options": [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}],
            "asked_at": SHA, "asked_by": "agent", "topics": [], "applies_to": [], "checked_against": [],
            "effect": "one-off"}
    if status == "answered":
        base.update({"answer": "Yes", "answered_at": {"at": SHA, "by": "who"}})
    if status == "withdrawn":
        base["withdrawn"] = {"at": SHA, "by": "who", "reason": "asked twice"}
    return {**base, **over}


def grant(id_, status="answered", plan="p"):
    return rec(dec(id_, status, **{"class": "merge-grant", "plan": plan}))


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = copy.deepcopy(config.DEFAULTS)

    def rt(self, row):
        """The row as the gates see it: written by write_record, read back by yamlsub.load."""
        write_record(self.work, "r.yml", row)
        return yamlsub.load(os.path.join(self.work, "r.yml"), "r.yml")

    def v(self, row):
        return validate(self.rt(row), self.cfg)


class SchemaTests(Base):
    def test_schema_file(self):  # S1, S2, S4, M4
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
        self.assertEqual((s.kind, s.version, s.format), ("finding", 1, "yaml"))
        self.assertEqual(s.files, [{"dir": "findings", "glob": "*.yml", "exclude": ["index.yml"]}])
        self.assertEqual(s.fields["schema"], {"type": "str"})

    def test_enums_equal_constants(self):  # S3, T1
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
        self.assertEqual(s.fields["status"]["values"], STATUSES)
        self.assertEqual(s.fields["history"]["items"]["fields"]["status"]["values"], STATUSES)
        self.assertEqual(s.fields["severity"]["values"], SEVERITIES)
        self.assertEqual(STATUSES, ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred",
                                    "closed", "merged"])
        self.assertEqual(RESOLVED, {"closed", "merged"})
        self.assertEqual(SEVERITIES, ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
        self.assertEqual(TRANSITIONS, {
            "open": ["planned", "deferred", "closed"], "planned": ["in-progress", "open", "deferred"],
            "in-progress": ["fixed-unpinned", "pinned", "planned"], "fixed-unpinned": ["pinned"],
            "pinned": ["closed", "merged"], "deferred": ["open", "planned"], "closed": ["merged"], "merged": []})

    def test_files_of_register_dir(self):
        make_repo(self.work)
        d = ".strict-delivery/state/findings/"
        for name in (F1 + ".yml", "index.yml", "index.md"):
            write_record(self.work, d + name, {"k": "v"})
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
        self.assertEqual(schema.files_of(s, self.work, self.cfg), [d + F1 + ".yml"])

    def test_schema_tag(self):  # S5
        self.assertEqual(validate({**FINDING, "schema": "finding/2"}, self.cfg),
                         ["schema: expected finding/1, got finding/2; run /strict-delivery:upgrade"])
        self.assertEqual(validate({**FINDING, "schema": "decision/1", "status": "merged"}, self.cfg),
                         ["schema: expected finding/1, got decision/1"])
        self.assertEqual(validate(drop(FINDING, "schema"), self.cfg), ["schema: expected finding/1, got (missing)"])

    def test_unknown_top_key(self):  # S6
        self.assertEqual(self.v({**FINDING, "extra": 1}), ["extra: unknown key"])

    def test_non_mapping_row(self):  # V24
        for v in (None, [], "x", 1):
            with self.subTest(repr(v)):
                self.assertEqual(validate(v, self.cfg), ["top level: must be a mapping"])
                self.assertEqual(transition_errors(v), ["history: must be a non-empty list"])
                self.assertIs(is_resolved(v), False)
                self.assertEqual(evidence_errors(v, self.work, self.cfg, [], frozenset()), [])
                self.assertIs(may_delete(v, self.work, self.cfg, []), False)


class FieldTests(Base):
    def check(self, key, value, expected, base=None):
        with self.subTest("%s=%r" % (key, value)):
            self.assertEqual(validate({**(base or FINDING), key: value}, self.cfg), expected)

    def test_valid_finding(self):  # V1
        self.assertEqual(self.v(FINDING), [])
        self.assertEqual(self.v(CLOSED), [])

    def test_required_keys(self):  # V2
        for key in ("schema", "id", "status", "source", "severity", "class", "siblings", "cites", "repro",
                    "owner", "pin", "ruling", "evidence", "history"):
            with self.subTest(key):
                errs = validate(drop(FINDING, key), self.cfg)
                want = ["schema: expected finding/1, got (missing)"] if key == "schema" \
                    else [key + ": required key is missing"]
                self.assertEqual(errs, want)

    def test_id(self):  # V3
        self.check("id", F1, [])
        for bad in ("DEC-20261031-k3f9", "F-20261031-K3F9", 1, None):
            with self.subTest(repr(bad)):
                errs = validate({**FINDING, "id": bad}, self.cfg)
                self.assertTrue(len(errs) == 1 and errs[0].startswith("id: "), errs)

    def test_status_and_severity(self):  # V4, V5
        for s in STATUSES:
            if s not in ("merged", "closed"):
                self.check("status", s, [], mk(s))
        self.check("status", "Open", ["status: must be one of %s" % ", ".join(STATUSES)])
        self.check("status", "done", ["status: must be one of %s" % ", ".join(STATUSES)])
        self.check("status", None, ["status: must not be null"])
        for s in SEVERITIES:
            self.check("severity", s, [])
        for bad in ("high", "SEVERE", 1):
            self.check("severity", bad, ["severity: must be one of CRITICAL, HIGH, MEDIUM, LOW, INFO"])

    def test_source_and_class(self):  # V6
        for key in ("source", "class"):
            self.check(key, "x", [])
            for bad in ("", 1, None):
                self.check(key, bad, [key + ": must be a non-empty string"] if bad != None
                           else [key + ": must not be null"])

    def test_siblings(self):  # V7
        self.check("siblings", [], [])
        self.check("siblings", ["a"], [])
        self.check("siblings", [""], ["siblings.0: must be a non-empty string"])
        self.check("siblings", "a", ["siblings: must be a list"])

    def test_cites(self):  # V8
        ok = {"file": "src/x.py", "lines": "1-2", "sha": SHA}
        self.check("cites", [ok], [])
        self.check("cites", [{**ok, "x": 1}], ["cites.0.x: unknown key"])
        self.check("cites", [{**ok, "lines": ""}], ["cites.0.lines: must be a non-empty string"])
        self.check("cites", [{**ok, "sha": "A1B2C3D"}], ["cites.0.sha: must be 7 to 40 lowercase hex digits"])
        self.check("cites", [{**ok, "sha": "a1b2c3"}], ["cites.0.sha: must be 7 to 40 lowercase hex digits"])
        self.check("cites", [{**ok, "file": "/a"}], [])  # file is a plain str, sha is shape only
        self.check("cites", [drop(ok, "sha")], ["cites.0.sha: required key is missing"])
        self.check("cites", "x", ["cites: must be a list"])

    def test_repro(self):  # V9
        self.check("repro", None, [])
        self.check("repro", "steps", [])
        self.check("repro", "", ["repro: must be a non-empty string"])
        self.check("repro", 1, ["repro: must be a non-empty string"])

    def test_owner_shapes(self):  # V10-V14, F8
        o = lambda **kw: {**FINDING, "owner": kw}
        self.assertEqual(validate(o(kind="plan", plan="p", task="1a.2"), self.cfg), [])
        self.assertEqual(validate(o(kind="plan", plan="p"), self.cfg),
                         ["owner.task: required key is missing (required_when matches)"])
        self.assertEqual(validate(o(kind="plan", plan="p", task="t", number=3), self.cfg),
                         ["owner.number: must be absent (absent_when matches)"])
        self.assertEqual(validate(o(kind="plan", task="t"), self.cfg),
                         ["owner.plan: required key is missing (required_when matches)"])
        self.assertEqual(validate(o(kind="issue", number=3), self.cfg), [])
        self.assertEqual(validate(o(kind="issue", number=3, plan="p"), self.cfg),
                         ["owner.plan: must be absent (absent_when matches)"])
        self.assertEqual(validate(o(kind="issue", number=3, task="t"), self.cfg),
                         ["owner.task: must be absent (absent_when matches)"])
        self.assertEqual(validate(o(kind="issue"), self.cfg),
                         ["owner.number: required key is missing (required_when matches)"])
        self.assertEqual(validate(o(kind="roadmap", plan="p"), self.cfg), [])
        self.assertEqual(validate(o(kind="roadmap", plan="p", task="t"), self.cfg),
                         ["owner.task: must be absent (absent_when matches)"])
        self.assertEqual(validate(o(kind="roadmap"), self.cfg),
                         ["owner.plan: required key is missing (required_when matches)"])
        self.assertEqual(validate(o(kind="roadmap", plan="p", number=3), self.cfg),
                         ["owner.number: must be absent (absent_when matches)"])
        self.assertEqual(validate(o(kind="issue", number=3, x=1), self.cfg), ["owner.x: unknown key"])
        self.assertEqual(validate(o(kind="team", plan="p"), self.cfg),
                         ["owner.kind: must be one of plan, issue, roadmap"])
        self.assertEqual(validate(o(plan="p", task="t"), self.cfg), ["owner.kind: required key is missing"])
        self.assertEqual(validate({**FINDING, "owner": ["x"]}, self.cfg), ["owner: must be a mapping"])
        self.assertEqual(validate({**FINDING, "owner": None}, self.cfg), ["owner: must not be null"])

    def test_owner_number(self):  # V13
        for n, want in ((0, "owner.number: must be at least 1"), (-1, "owner.number: must be at least 1"),
                        (True, "owner.number: must be an integer"), ("3", "owner.number: must be an integer")):
            with self.subTest(repr(n)):
                self.assertEqual(validate({**FINDING, "owner": {"kind": "issue", "number": n}}, self.cfg), [want])
        self.assertEqual(self.v({**FINDING, "owner": {"kind": "issue", "number": 3}}), [])

    def test_owner_plan_name(self):  # V15
        for plan, ok in (("p", True), ("a/b", False), ("a b", False)):
            with self.subTest(plan):
                errs = validate({**FINDING, "owner": {"kind": "plan", "plan": plan, "task": "t"}}, self.cfg)
                self.assertEqual(errs, [] if ok else ["owner.plan: must not contain '/' or whitespace"])

    def test_pin(self):  # V16
        pin = lambda **kw: {**mk("pinned"), "pin": kw}
        tr = SHA + ":" + T
        self.assertEqual(validate(pin(test="t", transcript=tr), self.cfg), [])
        self.assertEqual(validate(pin(test="  ", transcript=tr), self.cfg), [])
        self.assertEqual(validate(pin(test="npx jest -t 'adds totals'", transcript=tr), self.cfg), [])  # opaque
        self.assertEqual(validate(pin(test="", transcript=tr), self.cfg), ["pin.test: must be a non-empty string"])
        self.assertEqual(validate(pin(test="t"), self.cfg), ["pin.transcript: required key is missing"])
        for bad in (T, SHA + ":a#b", SHA + ":/a", SHA + ":a/../b", 5):
            self.assertEqual(validate(pin(test="t", transcript=bad), self.cfg),
                              ["pin.transcript: must be <sha>:<normalised repo-relative path>"], bad)
        self.assertEqual(validate({**FINDING, "pin": []}, self.cfg), ["pin: must be a mapping"])

    def test_ruling(self):  # V17
        self.check("ruling", None, [])
        self.check("ruling", DA, [])
        errs = validate({**FINDING, "ruling": F1}, self.cfg)
        self.assertTrue(len(errs) == 1 and errs[0].startswith("ruling: id does not match"), errs)

    def test_evidence_list(self):  # V18
        self.check("evidence", [], [])
        self.check("evidence", ["x"], [])
        self.check("evidence", [""], ["evidence.0: must be a non-empty string"])
        self.check("evidence", [1], ["evidence.0: must be a non-empty string"])

    def test_history_shape(self):  # V19
        h = {"status": "open", "sha": SHA, "by": "agent"}
        self.check("history", [], ["history: must hold at least 1 items"])
        self.check("history", [{**h, "status": "done"}], ["history.0.status: must be one of %s" % ", ".join(STATUSES)])
        self.check("history", [{**h, "at": 1}], ["history.0.at: unknown key"])
        self.check("history", [{**h, "sha": "ABC1234"}], ["history.0.sha: must be 7 to 40 lowercase hex digits"])
        self.check("history", [{**h, "by": ""}], ["history.0.by: must be a non-empty string"])

    def test_merged_unreachable_in_block_1(self):  # V20, OQ-6
        self.assertEqual(validate(mk("merged"), self.cfg), ["status: merged is set only by the cleanup step",
                                                            "history.4.status: merged is set only by the cleanup step"])
        row = mk("closed", history=hist("open", "closed", "merged"))
        self.assertEqual(validate(row, self.cfg), ["history.2.status: merged is set only by the cleanup step"])
        row = mk("merged", history=hist("open", "closed", "merged"))
        self.assertEqual(validate(row, self.cfg), ["status: merged is set only by the cleanup step",
                                                   "history.2.status: merged is set only by the cleanup step"])
        self.assertEqual(validate(CLOSED, self.cfg), [])

    def test_optional_review_fields(self):  # owner Q-ES
        self.assertEqual(self.v({**FINDING, "review_round": 2, "caused_by_change": True, "dimension": "S5"}), [])
        self.assertEqual(self.v({**FINDING, "review_round": 1}), [])
        self.assertEqual(self.v({**FINDING, "caused_by_change": False}), [])
        self.assertEqual(self.v(FINDING), [])  # absent is valid
        for bad in (0, -1, True, "2", 1.5, None):
            if isinstance(bad, float):
                continue  # the yaml subset has no floats
            self.check("review_round", bad, ["review_round: must not be null"] if bad is None else
                       ["review_round: must be at least 1"] if bad in (0, -1) and bad is not True
                       else ["review_round: must be an integer"])
        for bad in (0, 1, "true", None):
            self.check("caused_by_change", bad, ["caused_by_change: must not be null"] if bad is None
                       else ["caused_by_change: must be true or false"])
        for bad in ("", 1, None, ["x"]):
            self.check("dimension", bad, ["dimension: must not be null"] if bad is None
                       else ["dimension: must be a non-empty string"])
        self.check("dimension", "owner kinds", [])
        self.check("dimension", "x", [], {**FINDING, "review_round": 1})  # no cross-field rule

    def test_parent(self):  # V21
        self.check("parent", F2, [])
        self.check("parent", None, ["parent: must not be null"])
        errs = validate({**FINDING, "parent": DA}, self.cfg)
        self.assertTrue(len(errs) == 1 and errs[0].startswith("parent: id does not match"), errs)
        self.assertEqual(validate(FINDING, self.cfg), [])  # absent is fine

    def test_resolved_by(self):  # V22, V23
        self.assertEqual(validate(drop(CLOSED, "resolved_by"), self.cfg),
                         ["resolved_by: required key is missing (required_when matches)"])
        self.assertEqual(validate(drop(mk("merged"), "resolved_by"), self.cfg),
                         ["resolved_by: required key is missing (required_when matches)",
                          "status: merged is set only by the cleanup step",
                          "history.4.status: merged is set only by the cleanup step"])
        for s in STATUSES:
            if s not in RESOLVED:
                with self.subTest(s):
                    self.assertEqual(validate({**mk(s), "resolved_by": "p"}, self.cfg),
                                     ["resolved_by: must be absent (absent_when matches)"])
        for name, ok in (("p", True), ("a/b", False), ("a b", False), ("a\tb", False)):
            with self.subTest(repr(name)):
                self.assertEqual(validate({**CLOSED, "resolved_by": name}, self.cfg),
                                 [] if ok else ["resolved_by: must not contain '/' or whitespace"])


class TransitionTests(Base):
    def test_transition_table_all_pairs(self):  # T2: 64 pairs
        self.assertEqual(sorted(PATHS_OF), sorted(STATUSES))
        for a in STATUSES:
            for b in STATUSES:
                with self.subTest("%s -> %s" % (a, b)):
                    row = {**FINDING, "status": b, "history": hist(*(PATHS_OF[a] + [b]))}
                    self.assertEqual(transition_errors(row) == [], b in TRANSITIONS[a])
        for s in STATUSES:  # the paths used above are legal
            self.assertEqual(transition_errors({**FINDING, "status": s, "history": hist(*PATHS_OF[s])}), [], s)

    def test_first_entry(self):  # T3
        row = {**FINDING, "status": "planned", "history": hist("planned")}
        self.assertEqual(transition_errors(row), ["history.0.status: the first entry must be open, got planned"])

    def test_history_last_equals_status(self):  # T4
        self.assertEqual(transition_errors({**FINDING, "status": "planned"}),
                         ["status: planned differs from the last history entry (open)"])

    def test_merged_steps_are_legal_here(self):  # T5
        self.assertEqual(transition_errors(mk("merged")), [])
        self.assertEqual(transition_errors(mk("merged", history=hist("open", "closed", "merged"))), [])

    def test_malformed_history(self):  # T6
        for h in ([], None, "x", ["open"], [{"sha": SHA}], [{"status": 1}], [{"status": ["open"]}]):
            with self.subTest(repr(h)):
                errs = transition_errors({**FINDING, "history": h})
                self.assertEqual(len(errs), 1, errs)
        self.assertEqual(transition_errors(drop(FINDING, "history")), ["history: must be a non-empty list"])


class EvidenceBase(Base):
    def setUp(self):
        super().setUp()
        make_repo(self.work)
        files = {
            R: "r\n", T: "t\n", PLAN_STATE + "/q/mutations/F.txt": "t\n", PLAN_STATE + "/p/F.txt": "t\n",
            PLAN_STATE + "/mutations/F.txt": "t\n", PLAN_STATE + "/a/b/mutations/F.txt": "t\n",
            PLAN_STATE + "/p/mutations/a/F.txt": "t\n", PLAN_STATE + "/z/mutations": "file\n",
            "other/state/plans/q/mutations/F.txt": "t\n",
            "docs/strict-delivery/specs/x.md": "s\n", "docs/strict-delivery/plans/x.md": "s\n",
            ".strict-delivery/state/programs/x.yml": "s\n", ".strict-delivery/state/claims/x.yml": "s\n",
            ".strict-delivery/state/findings/%s.yml" % F2: "s\n", ".strict-delivery/state/findings/%s.yml" % F3: "s\n",
            ".strict-delivery/state/decisions/%s.yml" % DA: "s\n",
            ".strict-delivery/playbooks/x.md": "s\n", "src/x.py": "s\n", "docs/a:b.md": "s\n", "CLAUDE.md": "s\n",
            "docs/strict-delivery/specsx/y.md": "s\n", "dir/inner.txt": "s\n",
        }
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.work, rel)), exist_ok=True)
            with open(os.path.join(self.work, rel), "w") as fh:
                fh.write(text)
        os.symlink("src/x.py", os.path.join(self.work, "link.py"))
        self.c = commit_all(self.work, "evidence fixtures")
        git(self.work, "rm", "-q", R)  # the cleanup deletes the review report after commit c
        self.c2 = commit_all(self.work, "cleanup")
        with open(os.path.join(self.work, "untracked.md"), "w") as fh:
            fh.write("u\n")
        self.tracked = gitinfo.tracked_files(self.work)

    def ev(self, row, decs=(), tracked=None, changed=True):
        return evidence_errors(row, self.work, self.cfg, list(decs), self.tracked if tracked is None else tracked,
                               changed)

    def closed_with(self, *entries, **over):
        return {**CLOSED, "evidence": list(entries), **over}


class EvidenceEntryTests(EvidenceBase):
    def assertBad(self, entry, start="evidence.0: ", **kw):
        errs = self.ev(self.closed_with(entry), **kw)
        self.assertTrue(len(errs) == 1 and errs[0].startswith(start), (entry, errs))

    def test_bare_sha(self):  # E2
        tree = git(self.work, "rev-parse", self.c + "^{tree}")
        blob = git(self.work, "rev-parse", self.c + ":src/x.py")
        self.assertEqual(self.ev(self.closed_with(self.c)), [])
        self.assertEqual(self.ev(self.closed_with(self.c[:7])), [])
        for bad in (tree, blob, "f" * 40, "f" * 7):
            self.assertBad(bad)

    def test_ambiguous_short_sha(self):  # E2
        git(self.work, "config", "core.abbrev", "7")
        pre = self.c[:7]
        fake = self.c[7:8]
        fake = ("1" if fake != "1" else "2") + "0" * 32
        d = os.path.join(self.work, ".git", "objects", pre[:2])
        with open(os.path.join(d, pre[2:] + fake), "wb") as fh:
            fh.write(b"garbage")
        self.assertBad(pre)
        self.assertEqual(self.ev(self.closed_with(self.c)), [])  # the full sha still resolves

    def test_evidence_sha_path_survives_cleanup(self):  # E3, E5
        self.assertEqual(self.ev(self.closed_with(self.c + ":" + R)), [])  # survives the cleanup
        self.assertEqual(self.ev(self.closed_with(self.c[:7] + ":src/x.py")), [])
        self.assertEqual(self.ev(self.closed_with(self.c + ":docs/a:b.md")), [])  # split at the first ':'
        self.assertBad(self.c2 + ":" + R)  # deleted at the later commit
        self.assertBad(self.c + ":no/such/file")
        self.assertBad(self.c + ":dir")  # a directory
        self.assertBad(self.c + ":link.py")  # a symlink
        self.assertEqual(self.ev(self.closed_with("f" * 40 + ":" + R)), ["evidence.0: %s is not a commit" % ("f" * 40)])
        self.assertBad(R)

    def test_sha_path_shape(self):  # E4
        for p in ("/a", "a/../b", "./a", "", "a#b", "a//b", "a/"):
            self.assertBad(self.c + ":" + p)

    def test_classification(self):  # E1
        self.assertBad("ABC1234")  # uppercase: a plain path, not tracked
        self.assertBad("ABC1234:x")
        self.assertBad("a" * 41)

    def test_plain_path_allowed(self):  # E6
        for p in (".strict-delivery/playbooks/x.md", "CLAUDE.md", "src/x.py", "docs/a:b.md",
                  ".strict-delivery/state/decisions/%s.yml" % DA, "docs/strict-delivery/specsx/y.md"):
            with self.subTest(p):
                self.assertEqual(self.ev(self.closed_with(p)), [])

    def test_plain_path_refused(self):  # E7
        for p in ("untracked.md", "/etc/hostname", "../x", "dir", "link.py", "src//x.py", "./src/x.py", "a#b"):
            with self.subTest(p):
                self.assertBad(p)

    def test_plain_path_shape_before_tracked(self):  # E4, E7
        for p in ("../x", "/abs", "a//b", "./a", "a/"):
            with self.subTest(p):
                errs = self.ev(self.closed_with(p), tracked=self.tracked | {p})
                self.assertEqual(errs, ["evidence.0: %s is not a commit sha, <sha>:<path> or a normalised "
                                        "repo-relative path" % p])

    def test_plain_path_per_effort(self):  # E8
        for key, p in (("specs", "docs/strict-delivery/specs/x.md"), ("plans", "docs/strict-delivery/plans/x.md"),
                       ("plan_state", T), ("reviews", R), ("programs", ".strict-delivery/state/programs/x.yml"),
                       ("claims", ".strict-delivery/state/claims/x.yml")):
            with self.subTest(key):
                errs = self.ev(self.closed_with(p), tracked=self.tracked | {p})
                self.assertEqual(errs, ["evidence.0: %s is under %s, which is cleaned; cite it as <sha>:<path>"
                                        % (p, self.cfg["paths"][key])])

    def test_plain_path_findings(self):  # E9
        for fid in (F2, F3):
            p = ".strict-delivery/state/findings/%s.yml" % fid
            with self.subTest(fid):
                self.assertEqual(self.ev(self.closed_with(p)),
                                 ["evidence.0: %s is a finding record; cite it as <sha>:<path>" % p])
        p = ".strict-delivery/state/findings/%s.yml" % F2
        self.assertEqual(self.ev(self.closed_with(self.c + ":" + p)), [])

    def test_under_means_directory(self):  # E10
        self.cfg["paths"]["specs"] = "src"
        self.assertEqual(len(self.ev(self.closed_with("src/x.py"))), 1)
        self.cfg["paths"]["specs"] = "sr"
        self.assertEqual(self.ev(self.closed_with("src/x.py")), [])  # a shared prefix is not "under"
        self.cfg["paths"]["specs"] = "src/x.py"
        self.assertEqual(len(self.ev(self.closed_with("src/x.py"))), 1)  # the directory itself

    def test_checked_on_every_status(self):  # E11
        self.assertEqual(len(self.ev({**FINDING, "evidence": ["untracked.md"]})), 1)
        self.assertEqual(self.ev({**FINDING, "evidence": ["src/x.py", self.c]}), [])

    def test_closed_needs_evidence(self):  # E12
        self.assertEqual(self.ev(self.closed_with()), ["evidence: a closed finding needs at least one entry"])
        self.assertEqual(self.ev(self.closed_with(self.c)), [])
        self.assertEqual(self.ev(mk("planned")), [])

    def test_resolved_plain_path_not_checked_when_unchanged(self):  # E22, Q-1b3-3
        gone = self.closed_with("renamed/away.md")
        self.assertEqual(len(self.ev(gone)), 1)
        self.assertEqual(len(self.ev(gone, changed=True)), 1)
        self.assertEqual(self.ev(gone, changed=False), [])
        open_row = {**drop(gone, "resolved_by"), "status": "planned", "history": hist("open", "planned")}
        self.assertEqual(len(self.ev(open_row, changed=False)), 1)  # an unresolved row is always checked
        self.assertEqual(len(self.ev(self.closed_with(self.c + ":no/such/file"), changed=False)), 1)  # pinned stays
        self.assertEqual(len(self.ev(self.closed_with("docs/strict-delivery/plans/x.md"), changed=False)), 1)
        self.assertEqual(len(self.ev(self.closed_with("f" * 40), changed=False)), 1)

    def test_malformed_row(self):  # E23
        self.assertEqual(self.ev({**FINDING, "evidence": "x"}), [])
        self.assertEqual(self.ev({**FINDING, "evidence": [1, None, ""]}), [])
        self.assertEqual(self.ev({**FINDING, "pin": "x"}), [])
        self.assertEqual(self.ev(drop(mk("planned"), "owner")), [])
        self.assertEqual(self.ev({**FINDING, "ruling": 5}), [])
        self.assertEqual(self.ev({**FINDING, "history": None}), [])

    def test_root_not_toplevel_raises(self):  # E23
        sub = os.path.join(self.work, "dir")
        with self.assertRaises(GateError):
            evidence_errors(self.closed_with(self.c + ":src/x.py"), sub, self.cfg, [], self.tracked)


class PinTests(EvidenceBase):
    def pinned(self, transcript, owner=None, evidence=None):
        ev = [self.c + ":" + R] if evidence is None else evidence
        return {**mk("pinned"), "pin": {"test": "t", "transcript": transcript}, "owner": owner or OWNER,
                "evidence": ev}

    def test_pinned_needs_pin_and_review(self):  # E13
        good = self.pinned(self.c + ":" + T)
        self.assertEqual(self.ev(good), [])
        self.assertEqual(self.ev({**good, "pin": None}), ["pin: a pinned finding needs a pin"])
        want = "evidence: a pinned finding needs a review report cited as <sha>:docs/strict-delivery/reviews/<plan>/<file>"
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T, evidence=[])), [want])
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T, evidence=[self.c])), [want])  # bare sha
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T, evidence=[self.c + ":src/x.py"])), [want])
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T, evidence=["docs/strict-delivery/reviews/p/r.md"]))[0],
                         "evidence.0: docs/strict-delivery/reviews/p/r.md is under docs/strict-delivery/reviews, "
                         "which is cleaned; cite it as <sha>:<path>")

    def test_transcript_form_and_existence(self):  # E16
        form = ["pin.transcript: must be <sha>:<normalised repo-relative path>"]
        self.assertEqual(self.ev(self.pinned(T)), form)  # a plain path
        self.assertEqual(self.ev(self.pinned(self.c)), form)
        self.assertEqual(self.ev(self.pinned(self.c + ":a#b")), form)
        self.assertEqual(self.ev(self.pinned("f" * 40 + ":" + T)), ["pin.transcript: %s is not a commit" % ("f" * 40)])
        self.assertEqual(self.ev(self.pinned(self.c + ":" + PLAN_STATE + "/p/mutations/none.txt")),
                         ["pin.transcript: %s/p/mutations/none.txt is not a regular file at %s" % (PLAN_STATE, self.c)])

    def test_transcript_location_plan_owner(self):  # E14, Q-plan-4
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T)), [])
        self.assertEqual(self.ev(self.pinned(self.c + ":" + PLAN_STATE + "/p/mutations/a/F.txt")), [])
        for p in (PLAN_STATE + "/q/mutations/F.txt", PLAN_STATE + "/p/F.txt"):
            with self.subTest(p):
                self.assertEqual(self.ev(self.pinned(self.c + ":" + p)),
                                 ["pin.transcript: %s must be under %s/p/mutations/" % (p, PLAN_STATE)])

    def test_transcript_location_other_owners(self):  # E15
        for owner in ({"kind": "issue", "number": 3}, {"kind": "roadmap", "plan": "z"}):
            with self.subTest(owner["kind"]):
                self.assertEqual(self.ev(self.pinned(self.c + ":" + PLAN_STATE + "/q/mutations/F.txt", owner)), [])
                self.assertEqual(self.ev(self.pinned(self.c + ":" + T, owner)), [])
                for p in (PLAN_STATE + "/mutations/F.txt", PLAN_STATE + "/a/b/mutations/F.txt",
                          PLAN_STATE + "/p/F.txt"):
                    self.assertEqual(self.ev(self.pinned(self.c + ":" + p, owner)),
                                     ["pin.transcript: %s must be under %s/<plan>/mutations/" % (p, PLAN_STATE)], p)

    def test_transcript_needs_a_file_below_mutations(self):  # E15
        owner = {"kind": "issue", "number": 3}
        p = PLAN_STATE + "/z/mutations"  # a regular file named mutations: no folder below it
        self.assertEqual(self.ev(self.pinned(self.c + ":" + p, owner)),
                         ["pin.transcript: %s must be under %s/<plan>/mutations/" % (p, PLAN_STATE)])

    def test_transcript_base_is_plan_state(self):  # E15
        owner = {"kind": "roadmap", "plan": "z"}
        p = "other/state/plans/q/mutations/F.txt"  # same depth and shape, another base
        self.assertEqual(self.ev(self.pinned(self.c + ":" + p, owner)),
                         ["pin.transcript: %s must be under %s/<plan>/mutations/" % (p, PLAN_STATE)])

    def test_transcript_owner_unusable(self):  # E23
        for owner in ({"kind": "team"}, {"kind": "plan", "plan": "a/b", "task": "t"}, "x"):
            with self.subTest(repr(owner)):
                self.assertEqual(self.ev(self.pinned(self.c + ":" + T, owner)),
                                 ["pin.transcript: cannot be located: owner has no usable kind or plan"])

    def test_pin_checked_on_other_statuses(self):  # E17
        row = {**CLOSED, "evidence": [self.c], "pin": {"test": "t", "transcript": T}}
        self.assertEqual(self.ev(row), ["pin.transcript: must be <sha>:<normalised repo-relative path>"])
        row = {**CLOSED, "evidence": [self.c], "pin": {"test": "t", "transcript": self.c + ":" + T}}
        self.assertEqual(self.ev(row), [])
        self.assertEqual(self.ev({**FINDING, "pin": {"test": "t", "transcript": T}}),
                         ["pin.transcript: must be <sha>:<normalised repo-relative path>"])

    def test_transcript_survives_cleanup(self):
        git(self.work, "rm", "-q", T)
        commit_all(self.work, "drop transcript")
        self.assertEqual(self.ev(self.pinned(self.c + ":" + T), tracked=gitinfo.tracked_files(self.work)), [])


class RulingTests(EvidenceBase):
    def deferred(self, ruling):
        return mk("deferred", ruling=ruling)

    def test_deferred_needs_answered_ruling(self):  # E18, E19, E20
        recs = [rec(dec(DA, "answered")), rec(dec(DB, "open")), rec(dec(DC, "withdrawn"))]
        self.assertEqual(self.ev(self.deferred(DA), recs), [])
        self.assertEqual(self.ev(self.deferred(None), recs),
                         ["ruling: a deferred finding needs a ruling naming an answered decision"])
        self.assertEqual(self.ev(self.deferred("DEC-20261031-zzzz"), recs),
                         ["ruling: no decision record for DEC-20261031-zzzz"])
        for d in (DB, DC):
            with self.subTest(d):
                self.assertEqual(self.ev(self.deferred(d), recs),
                                 ["ruling: %s is not an answered, valid decision of a class other than merge-grant" % d])

    def test_merge_grant_is_not_a_ruling(self):  # Q-1b3r-1
        self.assertEqual(self.ev(self.deferred(DA), [grant(DA)]),
                         ["ruling: %s is not an answered, valid decision of a class other than merge-grant" % DA])
        self.assertEqual(self.ev(self.deferred(DA), [rec(dec(DA, "answered", **{"class": "triage"}))]), [])

    def test_superseded_ruling_counts(self):  # E19, Q-1b3-1
        recs = [rec(dec(DA, "answered")), rec(dec(DB, "answered", supersedes=DA))]
        self.assertEqual(self.ev(self.deferred(DA), recs), [])

    def test_invalid_ruling_record(self):  # E20
        recs = [rec(dec(DA, "answered", answer=None))]
        self.assertEqual(self.ev(self.deferred(DA), recs), ["ruling: %s is not an answered, valid decision of a class other than merge-grant" % DA])
        recs = [Record(DA, {"status": "answered"}, "x.yml")]
        self.assertEqual(len(self.ev(self.deferred(DA), recs)), 1)

    def test_ruling_on_other_statuses(self):  # E21
        self.assertEqual(self.ev({**FINDING, "ruling": DA}, [rec(dec(DB))]), ["ruling: no decision record for %s" % DA])
        self.assertEqual(self.ev({**FINDING, "ruling": DA}, [rec(dec(DA, "open"))]), [])
        self.assertEqual(self.ev(FINDING, []), [])


class EpicTests(Base):
    def test_parent_shapes(self):  # P2, P4, P5, P1
        a, b = {**FINDING, "id": F1, "parent": F2}, {**FINDING, "id": F2, "parent": F1}
        self.assertEqual(epic_errors([rec({**FINDING, "parent": F2})]),
                         [("parent." + F1, "parent: %s has no record" % F2)])
        self.assertEqual(epic_errors([rec({**FINDING, "parent": F1})]),
                         [("parent." + F1, "parent: a finding cannot be its own parent")])
        self.assertEqual(epic_errors([rec(a), rec(b)]),
                         [("parent." + F1, "parent: %s leads back to %s: a parent cycle" % (F2, F1)),
                          ("parent." + F2, "parent: %s leads back to %s: a parent cycle" % (F1, F2))])
        x, y, z = ({**FINDING, "id": F1, "parent": F2}, {**FINDING, "id": F2, "parent": F3},
                   {**FINDING, "id": F3, "parent": F1})
        self.assertEqual([s for s, _ in epic_errors([rec(x), rec(y), rec(z)])],
                         ["parent." + F1, "parent." + F2, "parent." + F3])
        # a row that only leads into a cycle is not on it
        w = {**FINDING, "id": F4, "parent": F1}
        self.assertEqual([s for s, _ in epic_errors([rec(a), rec(b), rec(w)])], ["parent." + F1, "parent." + F2])

    def test_resolved_parent_with_open_child_fails(self):  # P6
        parent = {**CLOSED, "id": F2}
        for status in ("open", "deferred"):
            child = {**mk(status), "parent": F2}
            with self.subTest(status):
                self.assertEqual(epic_errors([rec(parent), rec(child)]),
                                 [("epic." + F1, "parent: %s is resolved but this finding is not" % F2)])

    def test_allowed_shapes(self):  # P7
        open_p, closed_p = {**FINDING, "id": F2}, {**CLOSED, "id": F2}
        for p, c in ((open_p, {**CLOSED, "parent": F2}), (closed_p, {**CLOSED, "parent": F2}),
                     (open_p, {**FINDING, "parent": F2})):
            self.assertEqual(epic_errors([rec(p), rec(c)]), [])
        self.assertEqual(epic_errors([rec(FINDING)]), [])
        self.assertEqual(epic_errors([]), [])

    def test_grandchild(self):  # P8
        gp = {**CLOSED, "id": F2}
        p = {**CLOSED, "id": F3, "parent": F2}
        g = {**FINDING, "id": F1, "parent": F3}
        self.assertEqual([s for s, _ in epic_errors([rec(gp), rec(p), rec(g)])], ["epic." + F1])

    def test_resolved_child_missing_parent_is_fine(self):  # P3, Q-1b3-2
        self.assertEqual(epic_errors([rec({**CLOSED, "parent": F2})]), [])
        self.assertEqual(epic_errors([rec({**CLOSED, "parent": F1})]),
                         [("parent." + F1, "parent: a finding cannot be its own parent")])
        a, b = {**CLOSED, "id": F1, "parent": F2}, {**CLOSED, "id": F2, "parent": F1}
        self.assertEqual(len(epic_errors([rec(a), rec(b)])), 2)

    def test_malformed_records(self):  # P9
        recs = [Record(None, {"parent": F2}, "a.yml"), Record(F1, "x", "b.yml"), Record(F2, {"parent": 5}, "c.yml"),
                Record(F3, {**FINDING, "id": F3, "parent": DA}, "d.yml"), Record("", {"parent": F1}, "e.yml")]
        self.assertEqual(epic_errors(recs), [("parent." + F3, "parent: %s has no record" % DA)])
        self.assertEqual(epic_errors([object()]), [])


class ResolutionTests(Base):
    def test_is_resolved(self):  # D1
        for s in STATUSES:
            self.assertIs(is_resolved(mk(s)), s in ("closed", "merged"), s)
        for bad in ({"status": None}, {"status": ["closed"]}, {}, None, [], "closed"):
            self.assertIs(is_resolved(bad), False, repr(bad))

    def test_may_delete(self):  # OQ-5, D2-D5
        self.assertIs(may_delete(CLOSED, "/x", self.cfg, [grant(DA)]), True)
        self.assertIs(may_delete(mk("merged"), "/x", self.cfg, [grant(DA)]), True)
        for name, decs in (("none", []), ("open", [grant(DA, "open")]), ("withdrawn", [grant(DA, "withdrawn")]),
                           ("other plan", [grant(DA, plan="other")]),
                           ("not a grant", [rec(dec(DA, "answered", plan="p"))]),
                           ("invalid grant", [rec(dec(DA, "answered", **{"class": "merge-grant", "plan": "p",
                                                                         "answer": None}))])):
            with self.subTest(name):
                self.assertIs(may_delete(CLOSED, "/x", self.cfg, decs), False)
        self.assertIs(may_delete(FINDING, "/x", self.cfg, [grant(DA)]), False)  # unresolved
        for st in STATUSES:  # F-1b3r-1: an unresolved row that carries resolved_by must still be refused
            if st not in RESOLVED:
                with self.subTest("unresolved " + st):
                    self.assertIs(may_delete({**mk(st), "resolved_by": "p"}, "/x", self.cfg, [grant(DA)]), False)
        self.assertIs(may_delete(drop(CLOSED, "resolved_by"), "/x", self.cfg, [grant(DA)]), False)
        self.assertIs(may_delete({**CLOSED, "resolved_by": 5}, "/x", self.cfg, [grant(DA)]), False)
        self.assertIs(may_delete(CLOSED, "/x", self.cfg, [Record(DA, "x", "a.yml")]), False)


if __name__ == "__main__":
    unittest.main()
