"""Tests of gates/gate_schema.py through run_gate on real fixture repositories; rows K, P, C, N, A, F, M, E."""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_schema
from gates.lib import config, schema, yamlsub
from gates.lib.result import GateError, run_gate
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFGFILE = ".strict-delivery/config.yml"
INDEX = "docs/strict-delivery/INDEX.md"
DEC = ".strict-delivery/state/decisions"
CTX = ".strict-delivery/context.yml"
ID1 = "DEC-20261031-k3f9"
ID2 = "DEC-20261031-m4n5"
TAG = "<!-- schema: in-force/1 -->"

SCHEMA_TEXT = {
    "decision": '''kind: decision
version: 1
format: yaml
files:
  - dir: decisions
    glob: "*.yml"
    exclude:
      - index.yml
fields:
  schema:
    type: str
  id:
    type: id
    id_kind: decision
  status:
    type: enum
    values:
      - open
      - answered
''',
    "claim": '''kind: claim
version: 1
format: yaml
files:
  - dir: claims
    glob: "*.yml"
fields:
  schema:
    type: str
''',
    "context": '''kind: context
version: 1
format: yaml
files:
  - path: context
fields:
  schema:
    type: str
  x:
    type: str
''',
}
for _k in ("in-force", "overview", "decision-index", "finding-index"):
    SCHEMA_TEXT[_k] = '''kind: %s
version: 1
format: markdown
files:
  - path: index
first_line: "<!-- schema: %s/1 -->"
''' % (_k, _k)


class GateCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.sdir = os.path.join(self.tmp, "schemas")
        os.mkdir(self.sdir)
        shutil.copy(os.path.join(schema.SCHEMAS_DIR, "config.yml"), self.sdir)

    def kinds(self, *names, extra=None):
        for n in names:
            with open(os.path.join(self.sdir, n + ".yml"), "w") as fh:
                fh.write((extra or {}).get(n, SCHEMA_TEXT[n]))

    def run_g(self, args=None, producers=(), schemas_dir=True):
        argv = ["--root", self.root] if args is None else args
        out, err = io.StringIO(), io.StringIO()
        patches = [mock.patch("gates.producers.PRODUCER_MODULES", tuple("tests.fixtures." + p for p in producers))]
        if schemas_dir:
            patches.append(mock.patch.object(schema, "SCHEMAS_DIR", self.sdir))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for p in patches:
                p.start()
            try:
                code = run_gate("schema", gate_schema.check, argv)
            finally:
                for p in patches:
                    p.stop()
        return out.getvalue(), code

    def lines(self, *a, **kw):
        out, code = self.run_g(*a, **kw)
        return out.splitlines(), code

    def put(self, rel, text, root=None):
        path = os.path.join(root or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    def cfg_text(self, text):
        self.put(CFGFILE, text)

    def load_text(self):
        try:
            config.load(self.root)
        except GateError as e:
            return str(e)
        raise AssertionError("config.load accepted the tree")


class Config(GateCase):
    def test_C15_valid_config_passes(self):
        self.assertEqual(self.lines(schemas_dir=False), (["PASS schema.kinds", "PASS schema.config"], 0))
        self.assertEqual(self.lines(), (["PASS schema.kinds", "PASS schema.config"], 0))

    def test_C1_missing_config_is_input_fail_naming_init(self):
        bare = os.path.join(self.tmp, "bare")
        os.mkdir(bare)
        git(bare, "init", "-q", "-b", "main")
        out, code = self.run_g(["--root", bare])
        want = "FAIL schema.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n"
        self.assertEqual((out, code), (want, 1))
        with self.assertRaises(GateError) as cm:
            config.load(bare)
        self.assertEqual(str(cm.exception), want[len("FAIL schema.input: "):-1])

    def test_C1_unreadable_config_kinds_use_config_loads_text(self):
        for make in ("dir", "fifo", "chmod"):
            os.makedirs(os.path.join(self.root, ".strict-delivery"), exist_ok=True)
            path = os.path.join(self.root, CFGFILE)
            if os.path.lexists(path):
                os.replace(path, os.path.join(self.tmp, "moved-%s" % make))
            if make == "dir":
                os.mkdir(path)
            elif make == "fifo":
                os.mkfifo(path)
            else:
                self.put(CFGFILE, "x: 1\n")
                os.chmod(path, 0)
                self.addCleanup(os.chmod, path, stat.S_IRUSR | stat.S_IWUSR)
            want = self.load_text()
            self.assertEqual(self.run_g()[0], "FAIL schema.input: %s\n" % want, make)
            self.assertTrue(want.startswith(".strict-delivery/config.yml: cannot read file"), want)
            if make != "chmod":
                os.rmdir(path) if make == "dir" else os.replace(path, os.path.join(self.tmp, "gone"))

    def test_F5_symlinked_config_is_read(self):
        self.put("real-config.yml", "schema: config/1\nframework_version: \"0.0.0\"\nprofile: strict\n")
        os.replace(os.path.join(self.root, CFGFILE), os.path.join(self.tmp, "old"))
        os.symlink("../real-config.yml", os.path.join(self.root, CFGFILE))
        self.assertEqual(self.lines(), (["PASS schema.kinds", "PASS schema.config"], 0))

    def test_C2_yaml_error_and_not_utf8_are_input_fail(self):
        for body in (b"a: [b", b"schema: \xff\n"):
            self.cfg_text(body)
            out, code = self.run_g()
            self.assertEqual((out, code), ("FAIL schema.input: %s\n" % self.load_text(), 1), body)
            self.assertTrue(out.startswith("FAIL schema.input:"))
        self.cfg_text(b"a: [b")
        self.assertIn("(line 1)", self.run_g()[0])

    def test_C3_top_level_not_a_mapping(self):
        for body in ("", "[]\n", "x\n"):
            self.cfg_text(body)
            want = ["FAIL schema.config..strict-delivery/config.yml: top level: must be a mapping"]
            self.assertEqual(self.lines()[0][1:], want, repr(body))

    def test_C4_required_keys(self):
        for key in ("schema", "framework_version", "profile"):
            cfg = minimal_config()
            del cfg[key]
            write_record(self.root, CFGFILE, cfg)
            got = self.lines()[0]
            self.assertIn("FAIL schema.config..strict-delivery/config.yml: %s: required key is missing" % key
                          if key != "schema" else
                          "FAIL schema.config..strict-delivery/config.yml: schema: expected config/1, got (missing)", got)

    def test_C5_schema_tag(self):
        pre = "FAIL schema.config..strict-delivery/config.yml: schema: expected config/1, got "
        for tag, tail in (("config/2", "config/2; run /strict-delivery:upgrade"), ("decision/1", "decision/1"),
                          ("1", "1"), ("config/1 ", "config/1 ")):
            write_record(self.root, CFGFILE, dict(minimal_config(), schema=tag))
            self.assertEqual(self.lines()[0][1:], [pre + tail], tag)
        self.cfg_text("schema: 1\nframework_version: x\nprofile: strict\n")
        self.assertEqual(self.lines()[0][1:], [pre + "1"])

    def test_C6_profile(self):
        for prof in ("light", "standard", "strict"):
            write_record(self.root, CFGFILE, dict(minimal_config(), profile=prof))
            self.assertEqual(self.lines()[0], ["PASS schema.kinds", "PASS schema.config"], prof)
        for prof in ("loose", "Strict"):
            write_record(self.root, CFGFILE, dict(minimal_config(), profile=prof))
            self.assertEqual(self.lines()[0][1:], [
                "FAIL schema.config..strict-delivery/config.yml: profile: must be one of light, standard, strict"])

    def test_C7_framework_version(self):
        for v in ("", 1):
            write_record(self.root, CFGFILE, dict(minimal_config(), framework_version=v))
            self.assertEqual(self.lines()[0][1:], [
                "FAIL schema.config..strict-delivery/config.yml: framework_version: must be a non-empty string"])

    def test_C8_C9_unknown_keys(self):
        write_record(self.root, CFGFILE, dict(minimal_config(), profle="x", paths={"stat": "x"},
                                              ids={"width": "x"}, decisions={"scn": ["a"]},
                                              decision_classes={"owner": ["a"]}))
        pre = "FAIL schema.config..strict-delivery/config.yml: "
        self.assertEqual(self.lines()[0][1:], [pre + "paths.stat: unknown key", pre + "ids.width: unknown key",
                                               pre + "decisions.scn: unknown key",
                                               pre + "decision_classes.owner: unknown key",
                                               pre + "profle: unknown key"])

    def test_C10_optional_mappings_and_empty_maps(self):
        write_record(self.root, CFGFILE, dict(minimal_config(), paths={"state": "s"}, ids={"decision": "DX"}))
        self.assertEqual(self.lines()[0], ["PASS schema.kinds", "PASS schema.config"])
        # `decisions: {}` has no YAML source in the subset (flow mappings are refused), so the empty maps reach
        # validate as caller values, as config.load's yamlsub.load never produces them either.
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "config.yml"))
        value = dict(minimal_config(), decisions={}, decision_classes={}, paths={}, ids={})
        self.assertEqual(schema.validate(s, value, config.DEFAULTS), [])

    def test_C11_scan_and_owner_only(self):
        pre = "FAIL schema.config..strict-delivery/config.yml: "
        cases = [({"decisions": {"scan": []}}, []),
                 ({"decisions": {"scan": [""]}}, [pre + "decisions.scan.0: must be a non-empty glob"]),
                 ({"decision_classes": {"owner_only": []}}, [pre + "decision_classes.owner_only: must hold at least 1 items"]),
                 ({"decision_classes": {"owner_only": [""]}},
                  [pre + "decision_classes.owner_only.0: must be a non-empty string"]),
                 ({"decision_classes": {"owner_only": "triage"}}, [pre + "decision_classes.owner_only: must be a list"])]
        for extra, want in cases:
            write_record(self.root, CFGFILE, dict(minimal_config(), **extra))
            got = self.lines()[0]
            if not want:
                self.assertEqual(got, ["PASS schema.kinds", "PASS schema.config"])
            else:
                self.assertEqual(got[1:], want, extra)

    def test_C12_unlanded_keys(self):
        pre = "FAIL schema.config..strict-delivery/config.yml: "
        for key in ("commands", "models", "roles", "block", "rulings", "dispatch", "budgets", "drift", "overrides"):
            ok = {"models": {"tiers": {"tier1": "x"}}, "drift": {"estimate_factor_pct": 5}}.get(key, {"x": [1, {"y": 2}]})
            write_record(self.root, CFGFILE, dict(minimal_config(), **{key: ok}))
            self.assertEqual(self.lines()[0], ["PASS schema.kinds", "PASS schema.config"], key)
            write_record(self.root, CFGFILE, dict(minimal_config(), **{key: ["a"]}))
            self.assertEqual(self.lines()[0][1:], [pre + "%s: must be a mapping" % key], key)
        write_record(self.root, CFGFILE, dict(minimal_config(), top_tier_roles=["x"], top_tier_fallback="x"))
        self.assertEqual(self.lines()[0], ["PASS schema.kinds", "PASS schema.config"])
        write_record(self.root, CFGFILE, dict(minimal_config(), top_tier_roles="x", top_tier_fallback=1))
        self.assertEqual(self.lines()[0][1:], [pre + "top_tier_roles: must be a list",
                                               pre + "top_tier_fallback: must be a non-empty string"])

    def test_C13_raw_check_passes_config_load_refuses(self):
        cases = [{"paths": {"decisions": "/abs"}}, {"ids": {"decision": "dec"}},
                 {"ids": {"decision": "AB", "finding": "AB"}}, {"base_branch": "a" * 41},
                 {"models": {"tiers": {"tier1": ""}}}]
        for extra in cases:
            write_record(self.root, CFGFILE, dict(minimal_config(), **extra))
            want = self.load_text()
            out, code = self.run_g()
            self.assertEqual((out, code), ("FAIL schema.input: %s\n" % want, 1), extra)

    def test_C14_raw_failure_checks_no_other_kind_and_calls_no_config_load(self):
        self.kinds("claim")
        self.put(".strict-delivery/state/claims/bad.yml", "schema: other/1\n")
        write_record(self.root, CFGFILE, dict(minimal_config(), profile="loose", paths={"decisions": "/abs"}))
        with mock.patch.object(config, "load", side_effect=AssertionError("config.load called")):
            out, code = self.run_g(producers=["prod_claim"])
        self.assertEqual((out, code), (
            "PASS schema.kinds\nFAIL schema.config..strict-delivery/config.yml: profile: must be one of "
            "light, standard, strict\n", 1))


class Kinds(GateCase):
    def test_K2_P4_unknown_stem_and_unknown_produced_kind(self):
        with open(os.path.join(self.sdir, "widget.yml"), "w") as fh:
            fh.write(SCHEMA_TEXT["claim"].replace("claim", "widget"))
        self.assertEqual(self.lines()[0], ["FAIL schema.kinds.widget: widget.yml: kind 'widget' is not in KNOWN_KINDS",
                                           "PASS schema.config"])
        only = os.path.join(self.tmp, "only-upper")  # a fresh directory: Config.yml and config.yml are one file on macOS
        os.mkdir(only)
        with open(os.path.join(only, "Config.yml"), "w") as fh:
            fh.write(SCHEMA_TEXT["claim"].replace("claim", "Config"))
        with mock.patch.object(schema, "SCHEMAS_DIR", only):
            out, _ = self.run_g(schemas_dir=False)
        self.assertEqual(out.splitlines(), [
            "FAIL schema.kinds.Config: Config.yml: kind 'Config' is not in KNOWN_KINDS",
            "FAIL schema.kinds.config: gates/schemas/config.yml: missing"])
        os.replace(os.path.join(self.sdir, "widget.yml"), os.path.join(self.tmp, "widget.moved"))
        self.assertEqual(self.lines(producers=["prod_widget"])[0],
                         ["FAIL schema.kinds.widget: produced kind is not in KNOWN_KINDS", "PASS schema.config"])

    def test_K3_other_entries_fail_closed_and_never_block(self):
        os.mkfifo(os.path.join(self.sdir, "x.yml"))
        os.mkdir(os.path.join(self.sdir, "sub"))
        self.put("../schemas/README.md", "x")
        os.symlink(os.path.join(schema.SCHEMAS_DIR, "config.yml"), os.path.join(self.sdir, "decision.yml"))
        got = self.lines()[0]
        self.assertEqual(got, ["FAIL schema.kinds.README.md: README.md: not a regular *.yml schema file",
                               "FAIL schema.kinds.decision.yml: decision.yml: not a regular *.yml schema file",
                               "FAIL schema.kinds.sub: sub: not a regular *.yml schema file",
                               "FAIL schema.kinds.x.yml: x.yml: not a regular *.yml schema file",
                               "PASS schema.config"])

    def test_K4_checked_kind_without_schema_file(self):
        self.assertEqual(self.lines(producers=["prod_claim"])[0],
                         ["FAIL schema.kinds.claim: gates/schemas/claim.yml: missing", "PASS schema.config"])
        os.replace(os.path.join(self.sdir, "config.yml"), os.path.join(self.tmp, "config.moved"))
        out, code = self.run_g()
        self.assertEqual((out, code), ("FAIL schema.kinds.config: gates/schemas/config.yml: missing\n", 1))

    def test_K5_one_bad_schema_file_others_still_checked(self):
        self.kinds("claim")
        bad = os.path.join(self.sdir, "decision.yml")
        with open(bad, "w") as fh:
            fh.write(SCHEMA_TEXT["decision"].replace("version: 1", "version: 0"))
        self.assertEqual(self.lines(producers=["prod_claim_decision"])[0], [
            "FAIL schema.kinds.decision: %s: version: must be a positive integer" % bad,
            "PASS schema.config", "PASS schema.claim"])

    def test_K7_all_good_one_pass_line(self):
        self.kinds("decision", "claim")
        self.assertEqual(self.lines(producers=["prod_claim_decision"])[0], [
            "PASS schema.kinds", "PASS schema.config", "PASS schema.decision", "PASS schema.claim"])

    def test_P5_producer_errors_are_input_fail_and_nothing_else(self):
        out, code = self.run_g(producers=["raising_producer"])
        self.assertEqual((out, code), (
            "FAIL schema.input: producer module tests.fixtures.raising_producer cannot be imported "
            "(RuntimeError: boom)\n", 1))
        out, _ = self.run_g(producers=["prod_str"])
        self.assertEqual(out, "FAIL schema.input: producer module tests.fixtures.prod_str: "
                              "PRODUCES must be a tuple of strings\n")

    def test_A7_unproduced_kind_not_checked(self):
        self.kinds("claim")
        self.put(".strict-delivery/state/claims/bad.yml", "schema: other/1\n")
        out, _ = self.run_g()
        self.assertNotIn("schema.claim", out)
        self.assertEqual(out, "PASS schema.kinds\nPASS schema.config\n")

    def test_A9_produces_is_empty_tuple(self):
        self.assertEqual(gate_schema.PRODUCES, ())


class Generated(GateCase):
    def test_N1_N3_absent_generated_files_are_skipped(self):
        for kind in schema.GENERATED_KINDS:
            self.kinds(kind)
        self.assertEqual(self.lines(producers=["prod_inforce"])[0],
                         ["PASS schema.kinds", "PASS schema.config", "PASS schema.in-force"])
        self.assertEqual(sorted(schema.GENERATED_KINDS), ["decision-index", "finding-index", "in-force", "overview"])

    def test_N1_all_four_generated_kinds_skipped(self):
        for kind in schema.GENERATED_KINDS:
            self.kinds(kind)
        modules = []
        for kind in schema.GENERATED_KINDS:
            name = "prod_gen_" + kind.replace("-", "_")
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", name + ".py")) as fh:
                self.assertIn(kind, fh.read())
            modules.append(name)
        self.assertEqual(self.lines(producers=modules)[0][:2], ["PASS schema.kinds", "PASS schema.config"])
        self.assertEqual(self.lines(producers=modules)[0][2:],
                         ["PASS schema.overview", "PASS schema.in-force", "PASS schema.decision-index",
                          "PASS schema.finding-index"])

    def test_N2_present_generated_file_valid_and_invalid(self):
        self.kinds("in-force")
        self.put(INDEX, TAG + "\nbody\n")
        self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:], ["PASS schema.in-force"])
        self.put(INDEX, "<!-- schema: in-force/2 -->\nbody\n")
        self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:], [
            "FAIL schema.in-force.%s: first line: expected '%s'" % (INDEX, TAG)])

    def test_M5_markdown_read_raw(self):
        self.kinds("in-force")
        want = "FAIL schema.in-force.%s: first line: expected '%s'" % (INDEX, TAG)
        for body in ("﻿" + TAG + "\nx\n", TAG + "\r\nx\r\n"):
            self.put(INDEX, body)
            self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:], [want], repr(body))
        self.put(INDEX, b"\xff\xfe")
        self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:],
                         ["FAIL schema.in-force.%s: %s: not valid UTF-8" % (INDEX, INDEX)])
        os.replace(os.path.join(self.root, INDEX), os.path.join(self.tmp, "old-index"))
        os.mkfifo(os.path.join(self.root, INDEX))
        self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:],
                         ["FAIL schema.in-force.%s: %s: cannot read file (not a regular file)" % (INDEX, INDEX)])
        os.replace(os.path.join(self.root, INDEX), os.path.join(self.tmp, "fifo-moved"))
        self.put("real-index.md", TAG + "\n")
        os.symlink("../../real-index.md", os.path.join(self.root, INDEX))
        self.assertEqual(self.lines(producers=["prod_inforce"])[0][2:], ["PASS schema.in-force"])

    def test_N4_absent_non_generated_path_file_fails(self):
        self.kinds("context")
        self.assertEqual(self.lines(producers=["prod_context"])[0][2:],
                         ["FAIL schema.context.%s: missing" % CTX])
        self.put(CTX, "schema: context/1\nx: y\n")
        self.assertEqual(self.lines(producers=["prod_context"])[0][2:], ["PASS schema.context"])

    def test_N4_dangling_symlink_path_file_is_a_read_failure_not_missing(self):
        self.kinds("context")
        os.symlink("nowhere", os.path.join(self.root, CTX))
        self.assertEqual(self.lines(producers=["prod_context"])[0][2:], [
            "FAIL schema.context.%s: %s: cannot read file (No such file or directory)" % (CTX, CTX)])

    def test_K6_unreadable_schemas_directory_is_input_fail(self):
        afile = os.path.join(self.tmp, "afile")
        self.put("../afile", "x")
        with mock.patch.object(schema, "SCHEMAS_DIR", afile):
            out, code = self.run_g(schemas_dir=False)
        self.assertEqual((out, code), ("FAIL schema.input: %s: cannot read the schemas directory (Not a directory)\n"
                                       % afile, 1))

    def test_N5_empty_or_missing_register_passes(self):
        self.kinds("decision")
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], ["PASS schema.decision"])
        os.makedirs(os.path.join(self.root, DEC))
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], ["PASS schema.decision"])

    def test_A8_checked_data_file_errors(self):
        self.kinds("decision")
        rec = DEC + "/" + ID1 + ".yml"
        pre = "FAIL schema.decision." + rec + ": "
        self.put(rec, "schema: decision/1\nid: %s\nstatus: [open\n" % ID1)
        got = self.lines(producers=["prod_decision"])[0][2]
        self.assertTrue(got.startswith(pre + rec + ": ") and got.endswith(" (line 3)"), got)
        self.put(rec, b"schema: \xff\n")
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], [pre + rec + ": not valid UTF-8"])
        self.put(rec, "- a\n")
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], [pre + "top level: must be a mapping"])
        self.put(rec, "schema: decision/1\nid: DEC-20261031-K3F9\nstatus: done\nzzz: 1\n")
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], [
            pre + "id: id does not match the form; expected DEC-<YYYYMMDD>-<xxxx>: a valid calendar date and "
                  "four characters from 23456789abcdefghijkmnpqrstuvwxyz",
            pre + "status: must be one of open, answered", pre + "zzz: unknown key"])
        self.put(rec, "schema: decision/1\nid: %s\nstatus: open\n" % ID1)
        self.put(DEC + "/index.yml", "not: a record\n")  # excluded by the schema
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], ["PASS schema.decision"])

    def test_F4_non_regular_register_entries(self):
        self.kinds("decision")
        d = os.path.join(self.root, DEC)
        os.makedirs(d)
        self.put(DEC + "/real.yml", "schema: decision/1\nid: %s\nstatus: open\n" % ID1)
        os.symlink("real.yml", os.path.join(d, "link.yml"))
        os.symlink("nowhere", os.path.join(d, "dangling.yml"))
        os.mkfifo(os.path.join(d, "fifo.yml"))
        os.mkdir(os.path.join(d, "dir.yml"))
        msg = "is not a regular file (a directory, symlink or other entry is never followed)"
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], [
            "FAIL schema.decision.%s/%s: %s" % (DEC, n, msg) for n in ("dangling.yml", "dir.yml", "fifo.yml",
                                                                        "link.yml")])

    def test_F4_symlinked_directory_component(self):
        self.kinds("decision")
        other = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(other, "decisions"))
        os.makedirs(os.path.join(self.root, ".strict-delivery/state"))
        os.symlink(os.path.join(other, "decisions"), os.path.join(self.root, DEC))
        self.assertEqual(self.lines(producers=["prod_decision"])[0][2:], [
            "FAIL schema.decision.%s: is a symlink; directories must be real directories" % DEC])

    def test_F1_schema_naming_an_unknown_paths_key_fails_kinds(self):
        self.kinds("claim", extra={"claim": SCHEMA_TEXT["claim"].replace("dir: claims", "dir: stat")})
        got = self.lines(producers=["prod_claim"])[0]
        self.assertEqual(got[2], "FAIL schema.kinds.claim: %s: files: 'stat' is not a key of paths"
                         % os.path.join(self.sdir, "claim.yml"))
        self.assertEqual(len(got), 3)

    def test_A6_all_pass_line_set(self):
        self.kinds("decision", "claim", "context")
        self.put(DEC + "/" + ID1 + ".yml", "schema: decision/1\nid: %s\nstatus: answered\n" % ID1)
        self.put(CTX, "schema: context/1\nx: y\n")
        self.assertEqual(self.lines(producers=["prod_claim_decision", "prod_context"]), ([
            "PASS schema.kinds", "PASS schema.config", "PASS schema.decision", "PASS schema.claim",
            "PASS schema.context"], 0))


class Args(GateCase):
    def test_A1_root_default_and_spellings(self):
        want = ["PASS schema.kinds", "PASS schema.config"]
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            self.assertEqual(self.lines([])[0], want)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        self.assertEqual(self.lines([])[0], want)
        self.assertEqual(self.lines(["--root", self.root + "/"])[0], want)
        link = os.path.join(self.tmp, "link")
        os.symlink(self.root, link)
        self.assertEqual(self.lines(["--root", link])[0], want)
        self.assertEqual(self.lines(["--root=" + self.root])[0], want)

    def test_A2_root_not_the_toplevel(self):
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        top = "FAIL schema.input: git rev-parse --show-toplevel: root must be the repository top level"
        self.assertEqual(self.lines(["--root", sub]), ([top], 1))
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        init = "FAIL schema.input: git rev-parse --show-toplevel failed (exit 128); run /strict-delivery:init"
        self.assertEqual(self.lines(["--root", outside]), ([init], 1))
        self.assertEqual(self.lines(["--root", os.path.join(self.tmp, "missing")]), ([init], 1))
        self.assertEqual(self.lines(["--root", os.path.join(self.root, CFGFILE)]), ([init], 1))

    def test_A2_toplevel_check_comes_before_config(self):
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        self.put(CFGFILE, "x: [", root=sub)  # a config in the subdirectory must not be reached
        self.assertEqual(self.lines(["--root", sub])[0], [
            "FAIL schema.input: git rev-parse --show-toplevel: root must be the repository top level"])

    def test_A3_git_missing(self):
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "empty")}):
            self.assertEqual(self.lines(), (["FAIL schema.input: git not found on PATH; install git"], 1))

    def test_A4_other_arguments(self):
        for args in (["--root", self.root, "--bogus"], ["--root", self.root, "extra"], ["--help"],
                     ["--root", self.root, "--root", self.root], ["--root", "a", "--root", "b"], ["--root", "--root"]):
            got, code = self.lines(args)
            self.assertEqual(code, 1, args)
            self.assertEqual(len(got), 1, args)
            self.assertTrue(got[0].startswith("FAIL schema.input: "), got)
        self.assertEqual(self.lines(["--root", self.root, "--root", self.root])[0],
                         ["FAIL schema.input: invalid arguments: --root given more than once"])
        self.assertEqual(self.lines(["--root", self.root, "--bogus"])[0],
                         ["FAIL schema.input: invalid arguments: unrecognized arguments: --bogus"])
        self.assertEqual(self.lines(["--ro", self.root, "--roo", self.root])[0],
                         ["FAIL schema.input: invalid arguments: --root given more than once"])

    def test_A5_json_first_only(self):
        out, code = self.run_g(["--json", "--root", self.root])
        self.assertEqual(json.loads(out), {"gate": "schema", "ok": True, "lines": [
            {"status": "PASS", "id": "schema.kinds", "reason": ""},
            {"status": "PASS", "id": "schema.config", "reason": ""}]})
        self.assertEqual(code, 0)
        text, _ = self.lines(["--root", self.root])
        self.assertEqual(text, ["%s %s" % (ln["status"], ln["id"]) for ln in json.loads(out)["lines"]])
        self.assertEqual(self.lines(["--root", self.root, "--json"])[0],
                         ["FAIL schema.input: invalid arguments: unrecognized arguments: --json"])


class Enabling(unittest.TestCase):
    def test_E1_this_repository_config_and_check(self):
        with open(os.path.join(REPO, CFGFILE), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), 'schema: config/1\nframework_version: "0.0.0"\nprofile: strict\n')
        self.assertEqual(yamlsub.load(os.path.join(REPO, CFGFILE), CFGFILE),
                         {"schema": "config/1", "framework_version": "0.0.0", "profile": "strict"})
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "CLAUDE_PROJECT_DIR"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema", "--root", REPO], cwd=REPO, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        lines = p.stdout.decode().splitlines()
        self.assertEqual(lines[:2], ["PASS schema.kinds", "PASS schema.config"])
        self.assertTrue(all(ln.startswith("PASS ") for ln in lines), lines)

    def test_E2_check_command_form(self):
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(gates_main.main(["check"]), 2)
            self.assertEqual(gates_main.main(["check", "bogus"]), 2)
            self.assertEqual(gates_main.main(["bogus"]), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "usage: python3 -m gates check <gate> [args]\ngates: decisions, schema\n" * 2
                         + "usage: python3 -m gates <command> [args]\ncommands: check\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("gates.producers.PRODUCER_MODULES", ()):
            self.assertEqual(gates_main.main(["check", "schema", "--root", REPO]), 0)
        self.assertEqual(out.getvalue().splitlines()[:2], ["PASS schema.kinds", "PASS schema.config"])


if __name__ == "__main__":
    unittest.main()
