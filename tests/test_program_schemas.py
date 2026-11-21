"""Tests of the five program schema files (gates/schemas/streams.yml, request.yml, status.yml, sync-log.yml,
merged-log.yml; Task P2.1 part i: rows SK1-SK16, RK1-RK12, ST1-ST12, SY1-SY7, ML1-ML7, KK1-KK4 of the part A table;
decisions D-A1 to D-A5, D-A21). Rows are written by hand; the files are the production path (``load_schema``,
``validate``, ``validate_markdown``, ``entries_of``)."""
import copy
import os
import subprocess
import sys
import unittest

from gates.lib import config, migrations, schema, yamlsub
from gates.lib.schema import KNOWN_KINDS, SchemaError, entries_of, load_schema, validate, validate_markdown
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, int_limit, make_repo, minimal_config

CFG = copy.deepcopy(config.DEFAULTS)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H7 = "abcdef0"
H40 = "0123456789abcdef0123456789abcdef01234567"
H40B = "fedcba9876543210fedcba9876543210fedcba98"
RID = "R-20261101-k3f9"
DID = "DEC-20261101-k3f9"


def sch(kind):
    return load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))


def stream(sid="a", owns=None, order=1, **over):
    row = {"id": sid, "purpose": "does a thing", "plan": "docs/strict-delivery/plans/%s-plan.md" % sid,
           "owns": owns if owns is not None else ["%s-owned.py" % sid], "estimate": 5, "depends_on": [],
           "merge_order": order}
    row.update(over)
    return row


def streams_row(**over):
    row = {"schema": "streams/1", "program": "20261101-x", "plan": "docs/strict-delivery/plans/program.md",
           "specs": ["docs/strict-delivery/specs/s.md"], "worktrees": "../w",
           "streams": [stream("a", order=1), stream("b", order=2)], "shared": []}
    row.update(over)
    return row


def request_row(**over):
    row = {"schema": "request/1", "id": RID, "from_stream": "a", "to_stream": "b", "files": ["b-owned.py"],
           "interface": "docs/strict-delivery/specs/s.md#api", "need": "a function", "status": "open",
           "raised_at": {"sha": H7, "by": "a-controller"}}
    row.update(over)
    return row


def put(row, dotted, value):
    """A deep copy of ``row`` with the value at ``dotted`` (a path of keys and list indexes) replaced."""
    out = copy.deepcopy(row)
    node = out
    keys = dotted.split(".")
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node[k]
    last = keys[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


def drop(row, dotted):
    out = copy.deepcopy(row)
    node = out
    keys = dotted.split(".")
    for k in keys[:-1]:
        node = node[int(k)] if isinstance(node, list) else node[k]
    del node[keys[-1]]
    return out


class _Sub(str):
    pass


class StreamsSchema(unittest.TestCase):
    def setUp(self):
        self.s = sch("streams")

    def errs(self, row):
        return validate(self.s, row, CFG)

    def test_streams_schema_loads(self):  # SK1
        self.assertEqual((self.s.kind, self.s.version, self.s.format), ("streams", 1, "yaml"))
        self.assertEqual(self.s.files, [{"dir": "programs", "glob": "*/streams.yml"}])

    def test_streams_valid_row(self):  # SK2
        self.assertEqual(self.errs(streams_row()), [])
        full = streams_row(streams=[
            stream("a", owns=["src/", {"path": "docs/", "from": "merged:b/3d"}, {"path": "x/", "until": "program-close"},
                              {"path": "y/", "from": "program-start", "until": "merged:b"}],
                   period={"from": "program-start", "until": "program-close"}, stacked_on="b"),
            stream("b", order=2), stream("residual", order=3, owns=None, residual=True)],
            shared=[{"path": "CLAUDE.md", "rule": "append-rows"}, {"path": "x.md", "rule": "own-row"}])
        del full["streams"][2]["owns"]
        self.assertEqual(self.errs(full), [])

    def test_streams_field_types(self):  # SK3
        must_str, must_int = "must be a non-empty string", "must be an integer"
        cases = []
        for top in ("program", "plan", "worktrees"):
            cases += [(top, v, "%s: %s" % (top, must_str)) for v in (5, "", True, ["x"])]
            cases.append((top, None, "%s: must not be null" % top))
        cases += [("specs", "x", "specs: must be a list"), ("specs", {"a": 1}, "specs: must be a list"),
                  ("specs.0", 5, "specs.0: " + must_str), ("specs.0", "", "specs.0: " + must_str),
                  ("streams", "x", "streams: must be a list"), ("streams", {"a": 1}, "streams: must be a list"),
                  ("streams", [], "streams: must hold at least 1 items"),
                  ("streams.0", 5, "streams.0: must be a mapping"),
                  ("shared", "x", "shared: must be a list"), ("shared.0", 5, "shared.0: must be a mapping")]
        for f in ("id", "purpose", "plan"):
            cases += [("streams.0." + f, v, "streams.0.%s: %s" % (f, must_str)) for v in (5, "")]
            cases.append(("streams.0." + f, None, "streams.0.%s: must not be null" % f))
        cases += [("streams.0.estimate", v, "streams.0.estimate: " + must_int) for v in ("5", 1.5, True)]
        cases += [("streams.0.estimate", -1, "streams.0.estimate: must be at least 0"),
                  ("streams.0.estimate", None, "streams.0.estimate: must not be null"),
                  ("streams.0.depends_on", "a", "streams.0.depends_on: must be a list"),
                  ("streams.0.depends_on", [5], "streams.0.depends_on.0: " + must_str)]
        cases += [("streams.0.merge_order", v, "streams.0.merge_order: " + must_int) for v in ("1", True)]
        cases += [("streams.0.merge_order", 0, "streams.0.merge_order: must be at least 1"),
                  ("streams.0.merge_order", -1, "streams.0.merge_order: must be at least 1"),
                  ("streams.0.stacked_on", 5, "streams.0.stacked_on: " + must_str),
                  ("streams.0.stacked_on", "", "streams.0.stacked_on: " + must_str),
                  ("streams.0.residual", "yes", "streams.0.residual: must be true or false"),
                  ("streams.0.residual", 1, "streams.0.residual: must be true or false")]
        base = streams_row(shared=[{"path": "CLAUDE.md", "rule": "own-row"}])
        cases += [("shared.0.rule", "other", "shared.0.rule: must be one of append-rows, own-row"),
                  ("shared.0.rule", "Append-Rows", "shared.0.rule: must be one of append-rows, own-row"),
                  ("shared.0.path", "", "shared.0.path: " + must_str)]
        for dotted, value, want in cases:
            with self.subTest(dotted=dotted, value=repr(value)):
                self.assertIn(want, self.errs(put(base, dotted, value)))
        # a missing optional key, written out: shared and the estimate bounds
        self.assertEqual(self.errs(put(base, "streams.0.estimate", 0)), [])

    def test_streams_unknown_keys(self):  # SK4
        base = streams_row(shared=[{"path": "CLAUDE.md", "rule": "own-row"}])
        for dotted, owner in (("extra", ""), ("streams.0.foo", "streams.0."), ("shared.0.extra", "shared.0.")):
            with self.subTest(dotted=dotted):
                row = copy.deepcopy(base)
                node = row
                for k in dotted.split(".")[:-1]:
                    node = node[int(k)] if isinstance(node, list) else node[k]
                node[dotted.split(".")[-1]] = 1
                self.assertEqual(self.errs(row), ["%s: unknown key" % dotted])
        row = put(base, "streams.0.period", {"from": "program-start", "until": "program-close", "extra": 1})
        self.assertEqual(self.errs(row), ["streams.0.period.extra: unknown key"])
        row = put(base, "streams.0.owns", [{"path": "a/", "extra": 1}])
        self.assertEqual(self.errs(row), ["streams.0.owns.0.extra: unknown key"])

    def test_streams_missing_keys(self):  # SK5
        for dotted in ("program", "plan", "specs", "worktrees", "streams", "shared", "streams.0.id", "streams.0.purpose",
                       "streams.0.plan", "streams.0.estimate", "streams.0.depends_on", "streams.0.merge_order"):
            with self.subTest(dotted=dotted):
                self.assertEqual(self.errs(drop(streams_row(), dotted)), ["%s: required key is missing" % dotted])
        for dotted in ("streams.0.stacked_on", "streams.0.residual", "streams.0.period"):  # optional: absent is valid
            self.assertEqual(self.errs(streams_row()), [])
        self.assertEqual(self.errs(drop(streams_row(), "schema")), ["schema: expected streams/1, got (missing)"])

    def test_streams_schema_tag(self):  # SK6
        for tag, want in (("streams/2", "schema: expected streams/1, got streams/2; run /strict-delivery:upgrade"),
                          ("streams/1 ", "schema: expected streams/1, got streams/1 "),
                          ("Streams/1", "schema: expected streams/1, got Streams/1"),
                          ("streams", "schema: expected streams/1, got streams"),
                          ("request/1", "schema: expected streams/1, got request/1")):
            with self.subTest(tag=tag):
                self.assertEqual(self.errs(streams_row(schema=tag)), [want])
        for tag in (5, None):
            self.assertEqual(len(self.errs(streams_row(schema=tag))), 1)

    def test_streams_owns_item_shapes(self):  # SK7, D-A1
        ok = (["src/"], [{"path": "src/", "from": "merged:a"}], [{"path": "src/", "until": "program-close"}],
              [{"path": "src/"}], [{"path": "src/", "from": "merged:a", "until": "merged:b"}], ["a", {"path": "b"}])
        for owns in ok:
            with self.subTest(owns=owns):
                self.assertEqual(self.errs(put(streams_row(), "streams.0.owns", owns)), [])
        want = {"5": "streams.0.owns.0: must be a string or a mapping", "[]": "streams.0.owns.0: must be a string or a mapping",
                "None": "streams.0.owns.0: must not be null", "''": "streams.0.owns.0: must be a non-empty string"}
        for value, msg in ((5, want["5"]), ([], want["[]"]), (None, want["None"]), ("", want["''"]),
                           (True, want["5"]), (_Sub("a"), want["5"]), (1.5, want["5"])):
            with self.subTest(value=repr(value)):
                self.assertEqual(self.errs(put(streams_row(), "streams.0.owns", [value])), [msg])
        for item, msg in (({"from": "merged:a"}, "streams.0.owns.0.path: required key is missing"),
                          ({"path": ""}, "streams.0.owns.0.path: must be a non-empty string"),
                          ({"path": "src/", "from": 5}, "streams.0.owns.0.from: must be a non-empty string"),
                          ({"path": "src/", "until": ""}, "streams.0.owns.0.until: must be a non-empty string")):
            with self.subTest(item=item):
                self.assertEqual(self.errs(put(streams_row(), "streams.0.owns", [item])), [msg])

    def test_streams_owns_presence(self):  # SK8, D-A2
        no_owns = drop(streams_row(), "streams.0.owns")
        self.assertEqual(self.errs(put(no_owns, "streams.0.residual", False)),
                         ["streams.0.owns: required key is missing (required_when matches)"])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.owns", [])), ["streams.0.owns: must hold at least 1 items"])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.residual", True)),
                         ["streams.0.owns: must be absent (absent_when matches)"])
        self.assertEqual(self.errs(put(no_owns, "streams.0.residual", True)), [])
        # the schema cannot see an absent residual key: streams_errors (delivery ii) refuses it (D-A2)
        self.assertEqual(self.errs(no_owns), [])

    def test_streams_two_residuals(self):  # SK9: not countable by the schema; streams_errors refuses (D-A2)
        row = streams_row()
        for i in (0, 1):
            row = put(drop(row, "streams.%d.owns" % i), "streams.%d.residual" % i, True)
        self.assertEqual(self.errs(row), [])

    def test_streams_period_shapes(self):  # SK10, D-A3
        both = {"from": "program-start", "until": "program-close"}
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", both)), [])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", {"from": "program-start"})),
                         ["streams.0.period.until: required key is missing"])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", {"until": "program-close"})),
                         ["streams.0.period.from: required key is missing"])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", {})),
                         ["streams.0.period.from: required key is missing", "streams.0.period.until: required key is missing"])
        for bound in (5, ""):
            self.assertEqual(self.errs(put(streams_row(), "streams.0.period", {"from": bound, "until": "x"})),
                             ["streams.0.period.from: must be a non-empty string"])
        # a bound that is not an event is event_problem's (delivery ii): the schema takes any non-empty string
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", {"from": "later", "until": "x"})), [])
        self.assertEqual(self.errs(put(streams_row(), "streams.0.period", "program-start")),
                         ["streams.0.period: must be a mapping"])

    def test_streams_window_shapes(self):  # SK11
        for item in ({"path": "p", "from": "merged:a/R2", "until": "merged:b"}, {"path": "p", "from": "merged:a"},
                     {"path": "p", "until": "merged:b"}, {"path": "p"}):
            self.assertEqual(self.errs(put(streams_row(), "streams.0.owns", [item])), [], item)

    def test_streams_shared(self):  # SK12
        for shared in ([], [{"path": "CLAUDE.md", "rule": "append-rows"}], [{"path": "x", "rule": "own-row"}]):
            self.assertEqual(self.errs(streams_row(shared=shared)), [])
        self.assertEqual(self.errs(streams_row(shared=[{"path": "x", "rule": "Append-Rows"}])),
                         ["shared.0.rule: must be one of append-rows, own-row"])
        self.assertEqual(self.errs(streams_row(shared=[{"path": "", "rule": "own-row"}])),
                         ["shared.0.path: must be a non-empty string"])
        self.assertEqual(self.errs(streams_row(shared=[{"rule": "own-row"}])), ["shared.0.path: required key is missing"])

    def test_streams_control_characters_reach_rules(self):  # SK13: the schema takes any non-empty string
        for value in ("a\nb", "a\x00b", "a\rb", "\ufeffa", "a\tb", "caf\u00e9"):
            row = put(put(put(streams_row(), "program", value), "plan", value), "streams.0.id", value)
            self.assertEqual(self.errs(row), [], repr(value))

    def test_streams_duplicate_keys(self):  # SK14
        for text in ("schema: streams/1\nschema: streams/1\n", "streams:\n  - id: a\nstreams:\n  - id: b\n",
                     "program: x\nprogram: y\n"):
            with self.assertRaises(yamlsub.YamlError):
                yamlsub.parse(text)

    def test_streams_digit_limits_same_on_both(self):  # SK15, V1
        for limit in INT_LIMITS:
            with int_limit(limit):
                for digits in (1000, 1001, 4300, 4301):
                    for field in ("estimate", "merge_order"):
                        text = "x:\n  %s: %s\n" % (field, "9" * digits)
                        # the parser caps a numeral at 1000 digits, and under a lower interpreter limit (the 3.11+
                        # int() limit) at that limit; any refusal is a YamlError, never another exception
                        if digits == 1000 and limit in (None, 0):
                            self.assertEqual(yamlsub.parse(text), {"x": {field: 10 ** 1000 - 1}})
                        elif digits > 1000:
                            with self.assertRaises(yamlsub.YamlError):
                                yamlsub.parse(text)
                        else:
                            try:
                                yamlsub.parse(text)
                            except yamlsub.YamlError:
                                pass
                row = put(streams_row(), "streams.0.estimate", 10 ** 1000 - 1)
                self.assertEqual(self.errs(row), [])

    def test_streams_text_is_the_production_read_path(self):  # SK2 through emit and parse
        row = streams_row(streams=[stream("a", owns=["a/", {"path": "b/", "from": "merged:a"}])])
        self.assertEqual(self.errs(yamlsub.parse(yamlsub.emit(row))), [])


class RequestSchema(unittest.TestCase):
    def setUp(self):
        self.s = sch("request")

    def errs(self, row):
        return validate(self.s, row, CFG)

    def test_request_schema_loads(self):  # RK1
        self.assertEqual((self.s.kind, self.s.version, self.s.format), ("request", 1, "yaml"))
        self.assertEqual(self.s.files, [{"dir": "programs", "glob": "*/requests/*.yml"}])

    def test_request_valid_rows(self):  # RK2
        for status in ("open", "accepted", "disputed", "withdrawn"):
            self.assertEqual(self.errs(request_row(status=status)), [], status)
        done = request_row(status="done", resolution={"commits": [H7, H40], "at": H7, "by": "b-controller"})
        self.assertEqual(self.errs(done), [])
        self.assertEqual(self.errs(request_row(decision=DID)), [])
        self.assertEqual(self.errs(yamlsub.parse(yamlsub.emit(done))), [])

    def test_request_id_forms(self):  # RK3
        for value in (DID, "R-20261301-k3f9", "R-20261101-k3f0", "r-20261101-k3f9", RID + "\n", 5, None, "", "R-20261101-k3f"):
            with self.subTest(value=repr(value)):
                errs = self.errs(request_row(id=value))
                self.assertEqual(len(errs), 1)
                self.assertTrue(errs[0].startswith("id: ") or errs[0] == "id: must not be null", errs)
        self.assertEqual(self.errs(request_row(id=DID))[0][:4], "id: ")

    def test_request_files(self):  # RK4
        self.assertEqual(self.errs(request_row(files=[])), ["files: must hold at least 1 items"])
        self.assertEqual(self.errs(request_row(files=[""])), ["files.0: must be a non-empty string"])
        self.assertEqual(self.errs(request_row(files="a")), ["files: must be a list"])
        self.assertEqual(self.errs(request_row(files=[5])), ["files.0: must be a non-empty string"])
        # the schema takes any non-empty string: duplicates and path shapes are request_errors' (delivery ii)
        for files in (["a", "a"], ["a\nb"], ["../x"], ["/x"]):
            self.assertEqual(self.errs(request_row(files=files)), [], files)

    def test_request_interface_cite(self):  # RK5
        for value in ("docs/x.md", "docs/x.md#sec"):
            self.assertEqual(self.errs(request_row(interface=value)), [], value)
        msg = "interface: must be a normalised repo-relative path with an optional non-empty #anchor"
        for value in ("docs/x.md#", "/abs", "a/../b", "docs/x.md#a#b", "", "docs/x.md#a\x07"):
            self.assertEqual(self.errs(request_row(interface=value)), [msg], repr(value))

    def test_request_status_enum(self):  # RK6
        msg = "status: must be one of open, accepted, done, disputed, withdrawn"
        for value in ("Open", "closed", 5, "", "done "):
            self.assertEqual(self.errs(request_row(status=value)), [msg], repr(value))
        self.assertEqual(self.errs(request_row(status=None)), ["status: must not be null"])

    def test_request_raised_at(self):  # RK7
        msg = "raised_at.sha: must be 7 to 40 lowercase hex digits"
        for value in ("ABCDEF0", "abcdef", "a" * 41, ""):
            self.assertEqual(self.errs(request_row(raised_at={"sha": value, "by": "x"})), [msg], value)
        self.assertEqual(self.errs(request_row(raised_at={"sha": H7, "by": ""})), ["raised_at.by: must be a non-empty string"])
        self.assertEqual(self.errs(request_row(raised_at={"sha": H7, "by": "x", "extra": 1})), ["raised_at.extra: unknown key"])
        self.assertEqual(self.errs(request_row(raised_at="abcdef0")), ["raised_at: must be a mapping"])

    def test_request_resolution_required_when_done(self):  # RK8, D-A3
        res = {"commits": [H7], "at": H7, "by": "b"}
        self.assertEqual(self.errs(request_row(status="done")), ["resolution: required key is missing (required_when matches)"])
        self.assertEqual(self.errs(request_row(status="done", resolution=res)), [])
        self.assertEqual(self.errs(request_row(status="done", resolution={**res, "commits": []})),
                         ["resolution.commits: must hold at least 1 items"])
        self.assertEqual(self.errs(request_row(status="done", resolution={**res, "commits": ["ZZ"]})),
                         ["resolution.commits.0: must be 7 to 40 lowercase hex digits"])
        self.assertEqual(self.errs(request_row(status="done", resolution={**res, "at": "x"})),
                         ["resolution.at: must be 7 to 40 lowercase hex digits"])
        self.assertEqual(self.errs(request_row(status="done", resolution={"commits": [H7], "at": H7})),
                         ["resolution.by: required key is missing"])
        for status in ("open", "accepted", "disputed", "withdrawn"):
            self.assertEqual(self.errs(request_row(status=status, resolution=res)),
                             ["resolution: must be absent (absent_when matches)"], status)

    def test_request_decision_field(self):  # RK9
        self.assertEqual(self.errs(request_row()), [])
        self.assertEqual(self.errs(request_row(decision=DID)), [])
        for value in (RID, "", None, 5):
            self.assertEqual(len(self.errs(request_row(decision=value))), 1, repr(value))

    def test_request_unknown_missing_tag(self):  # RK10
        self.assertEqual(self.errs(request_row(extra=1)), ["extra: unknown key"])
        for key in ("id", "from_stream", "to_stream", "files", "interface", "need", "status", "raised_at"):
            self.assertEqual(self.errs(drop(request_row(), key)), ["%s: required key is missing" % key], key)
        self.assertEqual(self.errs(request_row(schema="request/2")),
                         ["schema: expected request/1, got request/2; run /strict-delivery:upgrade"])

    def test_request_stream_fields_are_str(self):  # RK11
        for key in ("from_stream", "to_stream", "need"):
            for value in ("", 5, None):
                self.assertEqual(len(self.errs(request_row(**{key: value}))), 1, (key, value))
        self.assertEqual(self.errs(request_row(from_stream="b", to_stream="b")), [])  # from.<id> is request_errors'


class ProgramFiles(GitIsolatedTestCase):
    """Rows SK16, RK12, ST12, SY7 (the file lists) and KK4 (the real tree)."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)

    def touch(self, rel):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("a: 1\n")

    def listed(self, kind):
        return [rel for rel, _ in entries_of(sch(kind), self.root, self.cfg)]

    def test_streams_files_of(self):  # SK16
        base = ".strict-delivery/state/programs/"
        for rel in ("20261101-x/streams.yml", "20261102-y/streams.yml", "stray.yml", "20261101-x/other.yml"):
            self.touch(base + rel)
        self.assertEqual(self.listed("streams"), [base + "20261101-x/streams.yml", base + "20261102-y/streams.yml"])
        link = os.path.join(self.root, base + "20261103-z")
        os.symlink(os.path.join(self.root, base + "20261101-x"), link)
        with self.assertRaises(schema.LayoutError):
            self.listed("streams")

    def test_request_files_of(self):  # RK12
        base = ".strict-delivery/state/programs/20261101-x/requests/"
        for rel in ("R-20261101-k3f9.yml", "index.yml", ".hidden.yml", "sub/x.yml", "note.md"):
            self.touch(base + rel)
        self.assertEqual(self.listed("request"), [base + ".hidden.yml", base + "R-20261101-k3f9.yml", base + "index.yml"])

    def test_markdown_files_of(self):  # ST12, SY7, ML-files (decision D-A4)
        base = ".strict-delivery/state/programs/20261101-x/"
        for rel in ("status.md", "sync-log.md", "merged.md", "streams.yml"):
            self.touch(base + rel)
        self.assertEqual(self.listed("status"), [base + "status.md"])
        self.assertEqual(self.listed("sync-log"), [base + "sync-log.md"])
        self.assertEqual(self.listed("merged-log"), [base + "merged.md"])

    def test_check_schema_real_tree_still_passes(self):  # KK4: no producer declares the five kinds in this task
        env = dict(os.environ)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema"], cwd=REPO, env=env, check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode("utf-8")
        self.assertEqual(p.returncode, 0, out + p.stderr.decode("utf-8"))
        for kind in ("streams", "request", "status", "sync-log", "merged-log", "breakdown"):
            self.assertIn("PASS schema." + kind, out)  # declared and unchecked: no program folder, no breakdown.yml
        self.assertNotIn("FAIL", out)


FIRST_STATUS = "<!-- schema: status/1 -->"
HEADER = ("| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions "
          "| delivers |")
SEP = "|---|---|---|---|---|---|---|---|---|---|---|"
ROW = "| a | 3d | p/a/main | ../w/p/a/main | 3d.1 | 5 | 0 | ready | none | none | x |"


def page(*lines, header=HEADER, sep=SEP, first=FIRST_STATUS):
    return "\n".join([first, "", header, sep, ROW, ""] + list(lines)) + "\n"


class StatusSchema(unittest.TestCase):
    def setUp(self):
        self.s = sch("status")

    def errs(self, text):
        return validate_markdown(self.s, text)

    def line_verdicts(self, word, cases):
        for line, ok in cases:
            with self.subTest(line=line):
                got = self.errs(page(line))
                if ok:
                    self.assertEqual(got, [])
                else:
                    self.assertEqual(len(got), 1, got)
                    self.assertTrue(got[0].startswith("line 7: '%s' line does not match " % word), got)

    def test_status_schema_loads(self):  # ST1
        self.assertEqual((self.s.kind, self.s.version, self.s.format), ("status", 1, "markdown"))
        self.assertEqual(self.s.first_line, FIRST_STATUS)
        self.assertEqual(self.s.table, ["stream", "block", "branch", "worktree", "next task", "estimate", "used", "status",
                                        "blockers", "pending decisions", "delivers"])
        self.assertEqual(sorted(self.s.rules), ["Agent", "Batch-cut", "Integration"])
        self.assertEqual(self.s.files, [{"dir": "programs", "glob": "*/status.md"}])

    def test_status_page_valid(self):  # ST2
        self.assertEqual(self.errs(page()), [])
        self.assertEqual(self.errs(page("Batch-cut: none", "Integration: head=" + H7,
                                        "Agent: a1b2 stream=a task=3d.1 transcript=/t/x.jsonl last=R-20261101-k3f9 jobs=none")), [])

    def test_status_header_exact(self):  # ST3, plan :2694
        want = "table: header must be '%s', got '%s'"
        for bad in (HEADER.replace("next task", "next  task"), HEADER.replace("next task", "Next task"),
                    HEADER.replace(" | delivers |", " |"), HEADER[:-1] + "| extra |", HEADER + " ",
                    HEADER.replace("| stream | block |", "| block | stream |")):
            with self.subTest(bad=bad):
                self.assertEqual(self.errs(page(header=bad)), [want % (HEADER, bad)])

    def test_status_separator(self):  # ST4
        want = "table: the line after the header must be '%s'" % SEP
        for bad in ("|---|---|", "|" + "|".join(["---"] * 12) + "|", "| --- |" + "|".join(["---"] * 10) + "|",
                    "|:--|" + "|".join(["---"] * 10) + "|"):
            self.assertEqual(self.errs(page(sep=bad)), [want], bad)

    def test_status_first_line_and_missing_table(self):  # ST5
        for first in ("<!-- schema: status/2 -->", "<!-- schema: status/1 --> ", "\ufeff" + FIRST_STATUS, ""):
            self.assertEqual(self.errs(page(first=first)), ["first line: expected '%s'" % FIRST_STATUS], repr(first))
        self.assertEqual(self.errs(FIRST_STATUS + "\r\n" + "\n".join(["", HEADER, SEP])),
                         ["first line: expected '%s'" % FIRST_STATUS])
        self.assertEqual(self.errs(FIRST_STATUS + "\n\nno table\n"),
                         ["table: missing; expected a header '%s'" % HEADER])
        self.assertEqual(self.errs(""), ["first line: expected '%s'" % FIRST_STATUS])

    def test_status_rows_not_checked_by_schema(self):  # ST6: status_errors (delivery ii) owns the rows
        short = "| a | 3d | p/a/main | ../w | 3d.1 | 5 | 0 | ready | none | none |"
        long_ = ROW + " extra |"
        self.assertEqual(self.errs("\n".join([FIRST_STATUS, HEADER, SEP, short, long_]) + "\n"), [])

    def test_status_fact_line_patterns(self):  # ST7
        self.line_verdicts("Batch-cut", [
            ("Batch-cut: none", True), ("Batch-cut: " + H7, True), ("Batch-cut: " + H40, True),
            ("Batch-cut: ABCDEF1", False), ("Batch-cut: abc", False), ("Batch-cut: " + "a" * 41, False),
            ("Batch-cut:  none", False), ("Batch-cut: none ", False), ("Batch-cut: None", False), ("Batch-cut: ", False)])
        # not keyword-led: prose, never checked (D-Q13)
        for prose in ("Batch-cut:none", "batch-cut: none", " Batch-cut: x", "x Batch-cut: x", "The Batch-cut: x"):
            self.assertEqual(self.errs(page(prose)), [], prose)

    def test_status_integration_pattern(self):  # ST8
        self.line_verdicts("Integration", [
            ("Integration: head=" + H7, True), ("Integration: head=" + H40, True), ("Integration: head=ABCDEF1", False),
            ("Integration: head=abc", False), ("Integration: head=", False), ("Integration: head=" + "a" * 41, False),
            ("Integration: " + H7, False), ("Integration: head=" + H7 + " ", False)])

    def test_status_agent_pattern(self):  # ST9, D-A5 (b)
        head = "Agent: a1b2 stream=a task=3d.1 transcript=/t/x.jsonl last=R-20261101-k3f9 jobs="
        jobs_ok = ["none", "bu75:running", "bu75:running,x_2:finished", "a:stopped,b.c:finished,d-e:running",
                   "a:running,b:running,c:running,d:running"]
        jobs_bad = ["", "a:done", "a:running,", "a:running,,b:running", ",a:running", ":running", "a:", "a",
                    "a:running b:running", "a:Running", "none,a:running", "a:running,b:running,c:running,d:running,e:running"]
        self.line_verdicts("Agent", [(head + j, True) for j in jobs_ok] + [(head + j, False) for j in jobs_bad])
        for stream_id in ("program", "a-b"):
            self.assertEqual(self.errs(page(head.replace("stream=a", "stream=" + stream_id) + "none")), [])
        self.line_verdicts("Agent", [
            ("Agent: a1b2 stream=a task=3d.1 transcript=/t/x.jsonl last=R jobs=none extra=1", False),
            ("Agent: a1b2 stream=a task=3d.1 transcript=/t/x.jsonl jobs=none", False),
            ("Agent: a1b2 stream= task=3d.1 transcript=/t/x.jsonl last=R jobs=none", False),
            ("Agent: a1b2 stream=a task= transcript=/t/x.jsonl last=R jobs=none", False),
            ("Agent: a1b2 stream=a task=3d.1 transcript= last=R jobs=none", False),
            ("Agent: a1b2 stream=a task=3d.1 transcript=/t/x.jsonl last= jobs=none", False),
            ("Agent:  stream=a task=3d.1 transcript=/t/x.jsonl last=R jobs=none", False),
            ("Agent: stream=a task=3d.1 transcript=/t/x.jsonl last=R jobs=none", False),
            ("Agent: a1b2 stream=a task=3d.1 transcript=/a b last=R jobs=none", False)])

    def test_status_agent_field_classes(self):  # ST10: tokens of printable ASCII, no space
        base = "Agent: %s stream=%s task=%s transcript=%s last=%s jobs=none"
        for vals, ok in ((("a1", "a", "t", "/p", "r"), True), (("a\x7f", "a", "t", "/p", "r"), False),
                         (("a1", "a", "t", "caf\u00e9", "r"), False), (("a1", "a", "t", "/p\t", "r"), False)):
            got = self.errs(page(base % vals))
            self.assertEqual(got == [], ok, vals)

    def test_status_digit_limits_same_on_both(self):  # ST11: no int() in this schema; the lengths are the patterns'
        for limit in INT_LIMITS:
            with int_limit(limit):
                for digits in (600, 601, 4300, 4301):
                    line = "Agent: a1 stream=a task=%s transcript=/p last=r jobs=none" % ("9" * digits)
                    self.assertEqual(self.errs(page(line)), [])  # a token of any length: no numeral is read
                    self.assertEqual(len(self.errs(page("Integration: head=" + "9" * digits))), 1)


FIRST_SYNC = "<!-- schema: sync-log/1 -->"
SYNC = ("SYNC integration=%s main=%s merged-main=%s updated=%s combined=%s tests=%s questions=%s")


def sync_line(integration=H7, main=H7, merged="yes", updated="none", combined="none", tests="PASS", questions="none"):
    return SYNC % (integration, main, merged, updated, combined, tests, questions)


class SyncLogSchema(unittest.TestCase):
    def setUp(self):
        self.s = sch("sync-log")

    def errs(self, *lines, first=FIRST_SYNC):
        return validate_markdown(self.s, "\n".join([first] + list(lines)) + "\n")

    def verdicts(self, cases):
        for line, ok in cases:
            with self.subTest(line=line):
                got = self.errs(line)
                if ok:
                    self.assertEqual(got, [])
                else:
                    self.assertEqual(len(got), 1, got)
                    self.assertTrue(got[0].startswith("line 2: 'SYNC' line does not match "), got)

    def test_sync_log_schema_loads(self):  # SY1
        self.assertEqual((self.s.kind, self.s.version, self.s.format), ("sync-log", 1, "markdown"))
        self.assertEqual(self.s.first_line, FIRST_SYNC)
        self.assertEqual(sorted(self.s.rules), ["SYNC"])
        self.assertEqual(self.s.files, [{"dir": "programs", "glob": "*/sync-log.md"}])

    def test_sync_line_valid(self):  # SY2
        self.assertEqual(self.errs(sync_line()), [])
        self.assertEqual(self.errs(sync_line(H40, H40, "no", "a,b", "a", "FAIL", DID)), [])

    def test_sync_line_fields(self):  # SY3
        self.verdicts([(sync_line(integration=v), False) for v in ("ABCDEF0", "abcdef", "a" * 41, "")]
                      + [(sync_line(main=v), False) for v in ("ABCDEF0", "abcdef", "a" * 41, "")]
                      + [(sync_line(merged=v), False) for v in ("Yes", "maybe", "")]
                      + [(sync_line(tests=v), False) for v in ("pass", "n/a", "")]
                      + [(sync_line(merged="no"), True), (sync_line(tests="FAIL"), True)])
        good = sync_line()
        self.verdicts([
            ("SYNC main=%s integration=%s merged-main=yes updated=none combined=none tests=PASS questions=none" % (H7, H7), False),
            (good.replace(" questions=none", ""), False), (good + " extra=1", False), (good.replace(" main=", "  main="), False),
            (good + " ", False), (good.replace(" main=", "\tmain="), False), (good + "\r", False),
            (good.replace("SYNC ", "SYNC  "), False)])

    def test_sync_line_lists(self):  # SY4, D-A5 (a)
        ok = ["none", "a", "a,b", "a-b,c0", "a,none", "x1,y2,z3,w4,v5,u6,t7,s8,r9,q10"]
        bad = ["", ",a", "a,", "a,,b", "a b", "a,-b", "-a", "A", "a_b", "a,B", ",", "a;b"]
        for key in ("updated", "combined"):
            self.verdicts([(sync_line(**{key: v}), True) for v in ok] + [(sync_line(**{key: v}), False) for v in bad])
        q_ok = ["none", DID, DID + "," + "DEC-20261101-k3fa", "R-20261101-k3f9"]
        q_bad = ["", ",", DID + ",", "," + DID, DID + ",,x", "a b", "-x", "a,-b", "a_b"]
        self.verdicts([(sync_line(questions=v), True) for v in q_ok] + [(sync_line(questions=v), False) for v in q_bad])

    def test_sync_line_id_classes(self):  # SY5: a stated limit; the prefix of a decision id is the config's
        self.verdicts([(sync_line(updated="A"), False), (sync_line(updated="a_b"), False),
                       (sync_line(questions="x"), True)])  # any token of the list class (the pattern is static)

    def test_sync_prose_lines_free(self):  # SY6
        for prose in ("see SYNC integration=x", "sync integration=x", "Note: x", "", "# heading", "SYNC:integration=x",
                      " SYNC integration=x"):
            self.assertEqual(self.errs(prose), [], prose)
        self.assertEqual(len(self.errs("SYNC: integration=x")), 1)  # keyword SYNC (one trailing colon removed)

    def test_sync_first_line(self):  # SY7
        for first in ("<!-- schema: sync-log/2 -->", "", FIRST_SYNC + " ", "\ufeff" + FIRST_SYNC):
            self.assertEqual(self.errs(sync_line(), first=first), ["first line: expected '%s'" % FIRST_SYNC], repr(first))


FIRST_MERGED = "<!-- schema: merged-log/1 -->"


def merged_line(pr="7", approval=None, stream="a", block="3d", final="no", at="2026-11-18T10:00:00Z", head=H40,
                merge=H40B, by="owner"):
    sb = " stream=%s block=%s" % (stream, block) if stream is not None else ""
    ap = approval if approval is not None else "host"
    return "MERGED pr=%s head=%s merge=%s merged_by=%s at=%s final=%s%s approval=%s" % (pr, head, merge, by, at, final, sb, ap)


CHAT = "chat pr=7 head=%s words=merge it" % H40


class MergedLogSchema(unittest.TestCase):
    def setUp(self):
        self.s = sch("merged-log")

    def errs(self, *lines, first=FIRST_MERGED):
        return validate_markdown(self.s, "\n".join([first] + list(lines)) + "\n")

    def verdicts(self, cases):
        for line, ok in cases:
            with self.subTest(line=line[:100]):
                got = self.errs(line)
                if ok:
                    self.assertEqual(got, [])
                else:
                    self.assertEqual(len(got), 1, got)
                    self.assertTrue(got[0].startswith("line 2: 'MERGED' line does not match "), got)

    def test_merged_log_schema_loads(self):  # ML1
        self.assertEqual((self.s.kind, self.s.version, self.s.format), ("merged-log", 1, "markdown"))
        self.assertEqual(self.s.first_line, FIRST_MERGED)
        self.assertEqual(sorted(self.s.rules), ["MERGED"])
        self.assertEqual(self.s.files, [{"dir": "programs", "glob": "*/merged.md"}])

    def test_merged_log_valid(self):  # ML2
        self.verdicts([(merged_line(), True), (merged_line(approval=CHAT), True), (merged_line(final="yes"), True),
                       (merged_line(stream="s-1", block="R2"), True)])

    def test_merged_log_requires_stream_and_block(self):  # ML3
        without = merged_line(stream=None)
        self.verdicts([(without, False), (merged_line().replace(" block=3d", ""), False),
                       (merged_line().replace(" stream=a", ""), False)])
        ledger = sch("ledger")  # the same line is valid in a ledger, where both fields are optional
        self.assertEqual(validate_markdown(ledger, "<!-- schema: ledger/1 -->\n" + without + "\n"), [])

    def test_merged_log_line_rules_match_ledger(self):  # ML4: the ledger's pattern with the optional group required
        optional = "(?: stream=[a-z0-9][a-z0-9-]* block=[0-9A-Za-z]+)?"
        required = " stream=[a-z0-9][a-z0-9-]* block=[0-9A-Za-z]+"
        ledger_pattern = sch("ledger").rules["MERGED"][0]
        self.assertEqual(ledger_pattern.count(optional), 1)
        self.assertEqual(ledger_pattern.replace(optional, required), self.s.rules["MERGED"][0])
        self.verdicts([(merged_line(head="abcdef0"), False), (merged_line(pr="0"), False), (merged_line(pr="01"), False),
                       (merged_line(approval="chat pr=7 head=abcdef0 words=x"), False),
                       (merged_line(final="maybe"), False), (merged_line(at="2026-11-18 10:00:00"), False),
                       (merged_line(by=""), False), (merged_line(approval="host (note)"), False),
                       (merged_line(approval="chat pr=7 head=%s words=" % H40), False),
                       (merged_line(approval="auto"), False), (merged_line(merge="a" * 39), False),
                       (merged_line(stream="A"), False), (merged_line(block="3d.1"), False)])

    def test_merged_log_no_cross_line_rules(self):  # ML5: stated limit; merged_lines and the program tool read them
        lines = [merged_line(pr="7"), merged_line(pr="7"), merged_line(pr="8", final="yes"), merged_line(pr="9", final="yes"),
                 merged_line(pr="10", at="2026-13-45T25:61:61Z")]
        self.assertEqual(self.errs(*lines), [])

    def test_merged_log_digit_limits_same_on_both(self):  # ML6, V1
        for limit in INT_LIMITS:
            with int_limit(limit):
                self.verdicts([(merged_line(pr="9" * 600), True), (merged_line(pr="9" * 601), False),
                               (merged_line(pr="9" * 4301), False),
                               (merged_line(approval="chat pr=%s head=%s words=x" % ("9" * 600, H40)), True),
                               (merged_line(approval="chat pr=%s head=%s words=x" % ("9" * 601, H40)), False)])

    def test_merged_log_prose(self):  # ML7
        for prose in ("Merged pr=7", "see MERGED pr=7", "merged pr=7", " MERGED x", "MERGEDx"):
            self.assertEqual(self.errs(prose), [], prose)

    def test_merged_log_first_line(self):
        self.assertEqual(self.errs(merged_line(), first="<!-- schema: sync-log/1 -->"),
                         ["first line: expected '%s'" % FIRST_MERGED])


class KindsAndVersions(unittest.TestCase):
    def test_known_kinds_hold_the_program_kinds(self):  # KK1
        self.assertIn("merged-log", KNOWN_KINDS)
        self.assertEqual(KNOWN_KINDS.index("merged-log"), KNOWN_KINDS.index("sync-log") + 1)  # D-A21
        self.assertEqual(len(KNOWN_KINDS), 24)  # 4a.1 appends profile and init-answers
        self.assertEqual(len(set(KNOWN_KINDS)), 24)
        self.assertEqual(KNOWN_KINDS.index("breakdown"), KNOWN_KINDS.index("merged-log") + 1)  # Task P2.2, D-Q20

    def test_schemas_dir_loads_and_stems_known(self):  # KK2
        loaded, problems = schema.scan_dir()
        self.assertEqual(problems, [])
        self.assertEqual(len(loaded), 20)  # 4a.1 adds claude-block, gitignore-block, profile, init-answers
        for kind in ("streams", "request", "status", "sync-log", "merged-log"):
            self.assertIn(kind, loaded)
            self.assertIn(kind, KNOWN_KINDS)

    def test_current_version_of_program_kinds(self):  # KK3
        for kind in ("streams", "request", "status", "sync-log", "merged-log"):
            self.assertEqual(migrations.current_version(kind), 1, kind)
        for kind, row in (("streams", streams_row()), ("request", request_row())):
            self.assertEqual(migrations.migrate(kind, copy.deepcopy(row)), row)

    def test_producers_declare_the_program_kinds(self):  # KK4 as changed by Task P2.2
        declared = schema.produced_kinds()
        for kind in ("streams", "request", "status", "sync-log", "merged-log", "breakdown"):
            self.assertIn(kind, declared)  # P2.2: gates.tools.program_cli declares them (RG1)

    def test_minimal_config_loads_for_these_tests(self):
        self.assertEqual(minimal_config()["schema"], "config/2")


if __name__ == "__main__":
    unittest.main()
