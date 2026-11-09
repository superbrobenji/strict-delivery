"""Tests for the claim schema and claim rules (gates.lib.claims) and gitinfo.blob_ids, through the production call
paths: rows are written with ``write_record`` and read back with ``yamlsub.load``; freshness and base checks run
on real git repositories. Blob ids in fixtures are read from git (``rev-parse``, ``hash-object`` run by the test),
never from ``blob_id`` itself. Expected values are written out literally, never derived from the code under test.
Row ids in comments refer to the Task 2a.2 input-domain table, revision 2."""
import copy
import inspect
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gates import gate_schema
from gates.lib import claims, config, gitinfo, migrations, schema, yamlsub
from gates.lib.claims import (ClaimFile, base_errors, document_errors, file_errors, load, slug, stale_errors,
                              validate)
from gates.lib.result import GateError, run_check
from tests.helpers import GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo, root_forms, write_record

# The tag comes from the kind's schema file (Global Constraints "Test fixtures"); literal tags below are wrong-tag
# tests, which are exempt.
TAG = "claim/%d" % migrations.current_version("claim")
CID = "C-20261031-k3f9"
CID2 = "C-20261031-m4n5"
CID3 = "C-20261031-p6q7"
BLOB = "0123456789abcdef0123456789abcdef01234567"
CITE = {"path": "src/x.txt", "lines": "3-5", "blob": BLOB}
CLAIM = {"id": CID, "text": "x holds", "cites": [CITE], "direct": "grep -n x src/x.txt",
         "contradiction": "grep -c y src/x.txt", "by": "implementer"}
CLAIM_FILE = {"schema": TAG, "document": "docs/a.md", "claims": [CLAIM]}
CDIR = ".strict-delivery/state/claims"
DOC_ERR = "document: must be a .md path with no '--'"
DASH_ERR = "document: no path component may start or end with '-'"
PATH_ERR = "must be a normalised repo-relative path with no '#'"
BLOB_ERR = "must be 40 lowercase hex characters"
LINES_ERR = "must be <n> or <first>-<last>: positive decimals without a leading zero, first <= last"


class S(str):
    pass


def cfg_defaults() -> dict:
    return copy.deepcopy(config.DEFAULTS)


def with_claim(**kw) -> dict:
    row = copy.deepcopy(CLAIM_FILE)
    row["claims"][0].update(kw)
    return row


def with_cite(**kw) -> dict:
    row = copy.deepcopy(CLAIM_FILE)
    row["claims"][0]["cites"][0].update(kw)
    return row


class ValidateTests(GitIsolatedTestCase):
    """``validate`` on rows written with ``emit`` and read back with ``yamlsub.load`` (oracle PC2)."""

    def setUp(self) -> None:
        super().setUp()
        self.cfg = cfg_defaults()

    def rt(self, row: object) -> list:
        path = write_record(self.work, "c.yml", row)
        return validate(yamlsub.load(path, "c.yml"), self.cfg)

    def test_valid_claim_file(self):  # C1
        self.assertEqual(self.rt(CLAIM_FILE), [])

    def test_both_commands_required(self):  # C2 (spec 8); MM1 paths
        for k in ("direct", "contradiction"):
            with self.subTest(k):
                row = copy.deepcopy(CLAIM_FILE)
                del row["claims"][0][k]
                self.assertTrue(any(e.startswith("claims.0.%s:" % k) for e in self.rt(row)))

    def test_every_required_key_missing(self):  # C2
        cases = [((), "document"), ((), "claims"), (("claims", 0), "id"), (("claims", 0), "text"),
                 (("claims", 0), "cites"), (("claims", 0), "direct"), (("claims", 0), "contradiction"),
                 (("claims", 0), "by"), (("claims", 0, "cites", 0), "path"), (("claims", 0, "cites", 0), "blob")]
        for where, key in cases:
            with self.subTest(key=key, where=where):
                row = copy.deepcopy(CLAIM_FILE)
                d = row
                for p in where:
                    d = d[p]
                del d[key]
                prefix = "".join("%s." % p for p in where)
                self.assertEqual(self.rt(row), ["%s%s: required key is missing" % (prefix, key)])

    def test_lines_is_optional(self):  # C7 absent
        row = copy.deepcopy(CLAIM_FILE)
        del row["claims"][0]["cites"][0]["lines"]
        self.assertEqual(self.rt(row), [])

    def test_wrong_types(self):  # C3, C13: the schema error at that path, never an exception
        str_paths = [((), "document"), (("claims", 0), "text"), (("claims", 0), "direct"),
                     (("claims", 0), "contradiction"), (("claims", 0), "by"), (("claims", 0, "cites", 0), "path"),
                     (("claims", 0, "cites", 0), "lines")]
        for where, key in str_paths:
            for v in (1, True, None, [], {}, S("docs/a.md"), ""):
                with self.subTest(key=key, v=repr(v)):
                    row = copy.deepcopy(CLAIM_FILE)
                    d = row
                    for p in where:
                        d = d[p]
                    d[key] = v
                    prefix = "".join("%s." % p for p in where)
                    want = "must not be null" if v is None else "must be a non-empty string"
                    self.assertEqual(validate(row, self.cfg), ["%s%s: %s" % (prefix, key, want)])
        for v in (1, True, None, [], {}, S(BLOB)):
            with self.subTest(key="blob", v=repr(v)):
                want = "must not be null" if v is None else "must be 7 to 40 lowercase hex digits"
                self.assertEqual(validate(with_cite(blob=v), self.cfg), ["claims.0.cites.0.blob: " + want])
        for v in (1, True, None, [], {}, S(CID)):
            with self.subTest(key="id", v=repr(v)):
                errs = validate(with_claim(id=v), self.cfg)
                self.assertEqual(len(errs), 1)
                self.assertTrue(errs[0].startswith("claims.0.id: "), errs)
        self.assertEqual(validate({**CLAIM_FILE, "claims": {"a": 1}}, self.cfg), ["claims: must be a list"])
        self.assertEqual(validate(with_claim(cites="src/x.txt"), self.cfg), ["claims.0.cites: must be a list"])
        self.assertEqual(validate({**CLAIM_FILE, "claims": [[CLAIM]]}, self.cfg), ["claims.0: must be a mapping"])
        self.assertEqual(validate(with_claim(cites=["src/x.txt"]), self.cfg),
                         ["claims.0.cites.0: must be a mapping"])
        self.assertEqual(validate({**CLAIM_FILE, "claims": None}, self.cfg), ["claims: must not be null"])

    def test_claims_empty_missing_not_a_list(self):  # C4
        self.assertEqual(self.rt({**CLAIM_FILE, "claims": []}), ["claims: must hold at least 1 items"])
        row = copy.deepcopy(CLAIM_FILE)
        del row["claims"]
        self.assertEqual(self.rt(row), ["claims: required key is missing"])
        self.assertEqual(self.rt({**CLAIM_FILE, "claims": "x"}), ["claims: must be a list"])
        self.assertEqual(self.rt(with_claim(cites=[])), ["claims.0.cites: must hold at least 1 items"])

    def test_unknown_key_refused(self):  # C5 (OQ-16; MM1)
        self.assertIn("claims.0.x: unknown key", self.rt(with_claim(x="y")))
        self.assertEqual(self.rt({**CLAIM_FILE, "x": "y"}), ["x: unknown key"])
        self.assertEqual(self.rt(with_cite(x="y")), ["claims.0.cites.0.x: unknown key"])
        for k in ("expected", "outcome", "sha"):  # Y6: no expected outcomes, no claim-level sha
            with self.subTest(k):
                self.assertEqual(self.rt(with_claim(**{k: "y"})), ["claims.0.%s: unknown key" % k])

    def test_blob_must_be_40_lowercase_hex(self):  # C6 (MM2)
        self.assertEqual(self.rt(with_cite(blob="f" * 40)), [])
        for v in ("a" * 7, "a" * 39):
            with self.subTest(v):
                self.assertEqual(self.rt(with_cite(blob=v)), ["claims.0.cites.0.blob: " + BLOB_ERR])
        for v in ("a" * 41, "A" * 40, "g" * 40, "a" * 64):
            with self.subTest(v):
                self.assertEqual(self.rt(with_cite(blob=v)), ["claims.0.cites.0.blob: must be 7 to 40 lowercase "
                                                              "hex digits", "claims.0.cites.0.blob: " + BLOB_ERR])

    def test_lines_forms(self):  # C7
        for v in ("3", "3-5", "3-3", "12-120"):
            with self.subTest(v):
                self.assertEqual(self.rt(with_cite(lines=v)), [])
        for v in ("0", "5-3", "3-", "-3", "a", "03", "3-05", " 3", "3 ", "3-0", "0-3", "3--5", "3-5-7", "١"):
            with self.subTest(v):
                self.assertEqual(self.rt(with_cite(lines=v)), ["claims.0.cites.0.lines: " + LINES_ERR])
        self.assertEqual(self.rt(with_cite(lines="")), ["claims.0.cites.0.lines: must be a non-empty string"])
        self.assertEqual(self.rt(with_cite(lines=3)), ["claims.0.cites.0.lines: must be a non-empty string"])

    def test_document_path_form(self):  # C8
        self.assertEqual(self.rt({**CLAIM_FILE, "document": "docs/a.md"}), [])
        for v in ("/abs.md", "a/../b.md", "./a.md", "a//b.md", "docs/a.md#x", "a\tb.md", "a/b.md/"):
            with self.subTest(v):
                self.assertIn("document: " + PATH_ERR, validate({**CLAIM_FILE, "document": v}, self.cfg))
        self.assertEqual(validate({**CLAIM_FILE, "document": "docs/"}, self.cfg),
                         ["document: " + PATH_ERR, DOC_ERR])

    def test_document_must_be_md_without_double_dash(self):  # C9 (owner Q-2a2-1 (a))
        for doc in ("a/b.txt", "a--b.md", "a/b", "docs/a.txt", "X.MD", "a/b--c.md", "--.md", "a.md.txt", ".md",
                    "docs/.md", "a.md-"):
            with self.subTest(doc):
                self.assertIn(DOC_ERR, self.rt({**CLAIM_FILE, "document": doc}))
        for doc in ("a.md", "a-b.md", "a.md/b.md", "é.md", "a-b/c-d/e-f.md", "a/b-.md", "a/b.-.md"):
            with self.subTest(doc):
                self.assertEqual(self.rt({**CLAIM_FILE, "document": doc}), [])

    def test_document_component_dash_ends(self):  # C9, G5 (owner Q-2a2r1-1 (a)); class: a component with a '-' end
        # First, middle and last component; a leading or a trailing '-'; a component that is exactly '-'. Each such
        # document gets exactly DASH_ERR, plus DOC_ERR where the .md / '--' rule fails too.
        for doc in ("-a/b.md", "a-/b.md", "x/-a/b.md", "x/a-/b.md", "a/-b.md", "a/b/-c.md", "-/b.md", "a/-/b.md",
                    "-.md", "-a.md", "a/-b-/c.md", "-a-/b.md"):
            with self.subTest(doc):
                self.assertEqual(self.rt({**CLAIM_FILE, "document": doc}), [DASH_ERR])
        for doc in ("a/b-", "a/-", "a-", "a--/b.md", "a/--b.md"):
            with self.subTest(doc):
                self.assertEqual(self.rt({**CLAIM_FILE, "document": doc}), [DOC_ERR, DASH_ERR])
        # The collision the rule removes: both documents slug to a---b, and neither can carry claims now.
        self.assertEqual(slug("a-/b.md"), "a---b")
        self.assertEqual(slug("a/-b.md"), "a---b")

    def test_cite_path_form(self):  # C10
        self.assertEqual(self.rt(with_cite(path="a:b.md")), [])
        self.assertEqual(self.rt(with_cite(path="a--b.txt")), [])
        for v in ("/abs", "a/../b", "./a", "a//b", "a#x", "a\nb", "a/"):
            with self.subTest(v):
                self.assertEqual(validate(with_cite(path=v), self.cfg), ["claims.0.cites.0.path: " + PATH_ERR])

    def test_top_level_not_a_mapping(self):  # C11
        for v in (None, [], "x", [CLAIM_FILE]):
            with self.subTest(repr(v)):
                self.assertEqual(validate(v, self.cfg), ["top level: must be a mapping"])

    def test_tag_errors_only(self):  # C12; literal wrong tags are exempt
        bad = {**CLAIM_FILE, "document": "/x", "claims": "y"}
        self.assertEqual(validate({**bad, "schema": "claim/2"}, self.cfg),
                         ["schema: expected %s, got claim/2; run /strict-delivery:upgrade" % TAG])
        self.assertEqual(validate({**bad, "schema": "decision/1"}, self.cfg),
                         ["schema: expected %s, got decision/1" % TAG])
        row = dict(bad)
        del row["schema"]
        self.assertEqual(validate(row, self.cfg), ["schema: expected %s, got (missing)" % TAG])

    def test_extra_checks_skip_malformed_parts(self):  # C13
        for row in ({**CLAIM_FILE, "claims": "x"}, {**CLAIM_FILE, "claims": [[1]]}, with_claim(cites={"a": 1}),
                    with_claim(cites=[1, None]), with_cite(lines=3), with_cite(blob=5), with_cite(path=None),
                    {**CLAIM_FILE, "document": 5}, {**CLAIM_FILE, "document": None}):
            with self.subTest(repr(row)[:60]):
                errs = validate(row, self.cfg)
                self.assertTrue(errs)
                self.assertFalse(any(e.startswith(("document: must be a .md", "document: must be a norm")) or
                                     e.endswith((BLOB_ERR, LINES_ERR, PATH_ERR)) for e in errs), errs)

    def test_duplicate_cites_pass(self):  # C14
        self.assertEqual(self.rt(with_claim(cites=[CITE, CITE])), [])

    def test_extra_checks_on_second_claim_and_cite(self):  # the error paths carry each index
        row = copy.deepcopy(CLAIM_FILE)
        second = copy.deepcopy(CLAIM)
        second["id"] = CID2
        second["cites"] = [CITE, {"path": "a//b", "lines": "0", "blob": "a" * 7}]
        row["claims"].append(second)
        self.assertEqual(self.rt(row), ["claims.1.cites.1.path: " + PATH_ERR, "claims.1.cites.1.lines: " + LINES_ERR,
                                        "claims.1.cites.1.blob: " + BLOB_ERR])

    def test_id_prefix_from_config(self):
        self.cfg["ids"]["claim"] = "CL"
        errs = validate(CLAIM_FILE, self.cfg)
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].startswith("claims.0.id: id does not match the form; expected CL-"), errs)


class SchemaFileTests(GitIsolatedTestCase):
    def test_schema_file_shape(self):  # Y1-Y4, Y6
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "claim.yml"))
        self.assertEqual((s.kind, s.version, s.format, s.files),
                         ("claim", 1, "yaml", [{"dir": "claims", "glob": "*.yml"}]))
        cite = {"type": "map", "fields": {"path": {"type": "str"}, "lines": {"type": "str", "required": False},
                                          "blob": {"type": "sha"}}}
        item = {"type": "map", "fields": {
            "id": {"type": "id", "id_kind": "claim"}, "text": {"type": "str"},
            "cites": {"type": "list", "min": 1, "items": cite}, "direct": {"type": "str"},
            "contradiction": {"type": "str"}, "by": {"type": "str"}}}
        self.assertEqual(s.fields, {"schema": {"type": "str"}, "document": {"type": "str"},
                                    "claims": {"type": "list", "min": 1, "items": item}})

    def test_check_schema_does_not_check_claim_files(self):  # Y5
        root = make_repo(self.work)
        os.makedirs(os.path.join(root, CDIR))
        without = run_check("schema", gate_schema.check, ["--root", root]).render(False)
        with open(os.path.join(root, CDIR, "bad.yml"), "w", encoding="utf-8") as fh:
            fh.write("schema: other/1\n")
        commit_all(root, "bad claim file")
        out = run_check("schema", gate_schema.check, ["--root", root]).render(False)
        # U-1: the oracle is the same gate on the same repository without the claim file, so a schema line another
        # task adds (PR-1c: overview, in-force, decision-index, finding-index) does not change the verdict.
        self.assertEqual(out, without)
        self.assertTrue(out.startswith("PASS schema.kinds\nPASS schema.config\n"), out)
        self.assertNotIn("FAIL", out)
        self.assertNotIn("bad.yml", out)
        self.assertIn("claim", schema.schemas())


class SlugTests(unittest.TestCase):
    def test_slug(self):  # G1
        self.assertEqual(slug("docs/strict-delivery/plans/x.md"), "docs--strict-delivery--plans--x")

    def test_slug_forms(self):  # G2, G3, G4, G6
        cases = [("a.md/b.md", "a.md--b"), ("docs/a", "docs--a"), ("a.md", "a"), ("A.MD", "A.MD"),
                 ("x.md.md", "x.md"), ("docs/é.md", "docs--é"), ("docs/é.md", "docs--é")]
        for doc, want in cases:
            with self.subTest(doc):
                self.assertEqual(slug(doc), want)
        self.assertNotEqual(slug("docs/é.md"), slug("docs/é.md"))

    def test_slug_one_to_one_on_valid_documents(self):  # G5 (Q-2a2-1 (a))
        cfg = cfg_defaults()
        self.assertEqual(slug("a--b.md"), slug("a/b.md"))
        self.assertIn(DOC_ERR, validate({**CLAIM_FILE, "document": "a--b.md"}, cfg))
        for doc in ("a/b.md", "docs/x-y/z.md", "a.md/b.md", "q.md"):
            with self.subTest(doc):
                self.assertEqual(validate({**CLAIM_FILE, "document": doc}, cfg), [])
                self.assertEqual(slug(doc).replace("--", "/") + ".md", doc)


class RepoCase(GitIsolatedTestCase):
    """A fixture repository whose git config sets colour and a short abbrev (Global Constraints "Git calls"),
    holding docs/a.md and src/x.txt; ``self.blob`` is git's own blob id of src/x.txt."""

    def setUp(self) -> None:
        super().setUp()
        self.root = make_repo(self.work)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", k, v)
        self.put("docs/a.md", "# a\n")
        self.put("docs/b.md", "# b\n")
        self.put("src/x.txt", "".join("line %d\n" % i for i in range(1, 11)))
        self.put("src/y.txt", "y\n")
        commit_all(self.root, "docs")
        self.blob = git(self.root, "rev-parse", "HEAD:src/x.txt")
        self.cfg = config.load(self.root)

    def put(self, rel: str, text: str) -> None:
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def row(self, ids=(CID,), document="docs/a.md", path="src/x.txt", blob=None, **kw) -> dict:
        items = []
        for i in ids:
            c = copy.deepcopy(CLAIM)
            c["id"] = i
            c["cites"] = [{"path": path, "lines": "3-5", "blob": blob or self.blob}]
            c.update(kw)
            items.append(c)
        return {"schema": TAG, "document": document, "claims": items}

    def write(self, name: str, row: dict) -> str:
        write_record(self.root, "%s/%s" % (CDIR, name), row)
        return "%s/%s" % (CDIR, name)


class LoadTests(RepoCase):
    def test_missing_directory_is_empty(self):  # D1
        self.assertEqual(load(self.root, self.cfg), [])

    def test_result_sorted_and_repo_relative(self):  # D6
        b = self.write("docs--b.yml", self.row(document="docs/b.md"))
        a = self.write("docs--a.yml", self.row())
        got = load(self.root, self.cfg)
        self.assertEqual(got, [ClaimFile(a, self.row()), ClaimFile(b, self.row(document="docs/b.md"))])
        with self.assertRaises(Exception):
            got[0].file = "x"  # frozen

    def test_configured_path(self):  # D5
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["claims"] = "other/claims"
        write_record(self.root, "other/claims/docs--a.yml", self.row())
        self.write("docs--b.yml", self.row(document="docs/b.md"))
        self.assertEqual(load(self.root, cfg), [ClaimFile("other/claims/docs--a.yml", self.row())])

    def test_entries_that_are_not_regular_yml_files(self):  # D2
        for name in ("x.yml", "s.yml", "dangling.yml", "f.yml", "x.yaml", ".x.yml", "README.md"):
            with self.subTest(name):
                sub = os.path.join(self.tmp, "d2-%d" % len(os.listdir(self.tmp)))
                os.mkdir(sub)
                root = make_repo(sub)
                write_record(root, CDIR + "/docs--a.yml", self.row())
                cdir = os.path.join(root, *CDIR.split("/"))
                p = os.path.join(cdir, name)
                if name == "x.yml":
                    os.mkdir(p)
                elif name == "s.yml":
                    os.symlink(os.path.join(cdir, "docs--a.yml"), p)
                elif name == "dangling.yml":
                    os.symlink(os.path.join(cdir, "nowhere"), p)
                elif name == "f.yml":
                    os.mkfifo(p)
                else:
                    write_record(root, CDIR + "/" + name, self.row())
                with mock.patch.object(yamlsub, "load", wraps=yamlsub.load) as ld:
                    with self.assertRaises(GateError) as cm:
                        load(root, config.load(root))
                self.assertIn(CDIR + "/" + name, str(cm.exception))
                self.assertNotIn(p, [c.args[0] for c in ld.call_args_list])  # never opened

    def test_component_symlink_or_file(self):  # D3
        state = os.path.join(self.root, ".strict-delivery", "state")
        real = os.path.join(self.tmp, "real")
        os.makedirs(os.path.join(real, "claims"))
        os.symlink(real, state)
        with self.assertRaises(GateError) as cm:
            load(self.root, self.cfg)
        self.assertIn(".strict-delivery/state: is a symlink", str(cm.exception))
        os.rename(state, os.path.join(self.tmp, "gone"))
        os.mkdir(state)
        with open(os.path.join(state, "claims"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        with self.assertRaises(GateError) as cm:
            load(self.root, self.cfg)
        self.assertIn(".strict-delivery/state/claims: is not a directory", str(cm.exception))

    def test_file_that_does_not_load(self):  # D4
        d = os.path.join(self.root, *CDIR.split("/"))
        os.makedirs(d)
        cases = [(b"a: 1\n  b: 2\n", "(line 2)"), (b"a: \xff\n", "not valid UTF-8"),
                 (b"- 1\n", "the top level must be a mapping"), (b"", "the top level must be a mapping")]
        for data, want in cases:
            with self.subTest(want):
                with open(os.path.join(d, "docs--a.yml"), "wb") as fh:
                    fh.write(data)
                with self.assertRaises(GateError) as cm:
                    load(self.root, self.cfg)
                self.assertIn(CDIR + "/docs--a.yml", str(cm.exception))
                self.assertIn(want, str(cm.exception))

    def test_root_forms(self):  # D7, L2
        check_root_forms(self, root_forms(self.tmp, self.root), {"load": lambda r: load(r, self.cfg)})


class FileErrorsTests(unittest.TestCase):
    def test_file_name_must_be_slug(self):  # F1
        rel = CDIR + "/x.yml"
        errs = file_errors([ClaimFile(rel, CLAIM_FILE)], "C")
        self.assertEqual(errs, [("name." + rel, "file name x.yml differs from docs--a.yml, the slug of the "
                                                "document docs/a.md")])
        self.assertEqual(file_errors([ClaimFile(CDIR + "/docs--a.yml", CLAIM_FILE)], "C"), [])

    def test_unicode_form_mismatch(self):  # G4
        row = {**CLAIM_FILE, "document": "docs/é.md"}
        rel = CDIR + "/docs--é.yml"
        self.assertEqual([s for s, _ in file_errors([ClaimFile(rel, row)], "C")], ["name." + rel])

    def test_bad_ids_one_line_per_file(self):  # F2, L3
        row = copy.deepcopy(CLAIM_FILE)
        row["claims"] = [{**CLAIM, "id": "C-20261031-K3F9"}, {**CLAIM, "id": "DEC-20261031-k3f9"},
                         {**CLAIM, "id": 5}, {**CLAIM, "id": CID2}]
        rel = CDIR + "/docs--a.yml"
        errs = file_errors([ClaimFile(rel, row)], "C")
        self.assertEqual([s for s, _ in errs], ["id." + rel])
        reason = errs[0][1]
        for bad in ("C-20261031-K3F9: id does not match the form", "DEC-20261031-k3f9: id does not match the form",
                    "5: id is not a string (int)"):
            self.assertIn(bad, reason)
        self.assertNotIn(CID2, reason)
        self.assertEqual(reason.count("; expected C-"), 3)

    def test_duplicate_id_across_files(self):  # F3
        f1, f2 = CDIR + "/docs--a.yml", CDIR + "/docs--b.yml"
        errs = file_errors([ClaimFile(f1, CLAIM_FILE), ClaimFile(f2, {**CLAIM_FILE, "document": "docs/b.md"})], "C")
        self.assertEqual(len(errs), 1)
        suffix, reason = errs[0]
        self.assertTrue(suffix == "duplicate." + CID and f1 in reason and f2 in reason)
        self.assertEqual(reason, "id %s appears 2 times: %s, %s" % (CID, f1, f2))

    def test_duplicate_id_in_one_file(self):  # F3
        row = {**CLAIM_FILE, "claims": [CLAIM, CLAIM, {**CLAIM, "id": CID2}]}
        f1 = CDIR + "/docs--a.yml"
        self.assertEqual(file_errors([ClaimFile(f1, row)], "C"),
                         [("duplicate." + CID, "id %s appears 2 times: %s, %s" % (CID, f1, f1))])

    def test_malformed_rows_never_raise(self):  # F4
        rel = CDIR + "/docs--a.yml"
        for row in ({"schema": TAG}, {**CLAIM_FILE, "document": 5}, {**CLAIM_FILE, "document": S("docs/b.md")},
                    {**CLAIM_FILE, "claims": "x"}, {**CLAIM_FILE, "claims": [1, {"text": "no id"}]}, {}):
            with self.subTest(repr(row)[:50]):
                self.assertEqual(file_errors([ClaimFile(rel, row)], "C"), [])

    def test_prefix(self):  # F5
        rel = CDIR + "/docs--a.yml"
        row = {**CLAIM_FILE, "claims": [{**CLAIM, "id": "CL-20261031-k3f9"}]}
        self.assertEqual(file_errors([ClaimFile(rel, row)], "CL"), [])
        self.assertEqual([s for s, _ in file_errors([ClaimFile(rel, CLAIM_FILE)], "CL")], ["id." + rel])


class DocumentErrorsTests(RepoCase):
    def cf(self, **kw) -> ClaimFile:
        return ClaimFile(CDIR + "/docs--a.yml", self.row(**kw))

    def test_tracked(self):  # E1
        self.assertEqual(document_errors(self.cf(), gitinfo.tracked_files(self.root)), [])

    def test_document_not_tracked(self):  # E2, E4
        self.put("docs/new.md", "n\n")
        git(self.root, "rm", "-q", "docs/b.md")
        tracked = gitinfo.tracked_files(self.root)
        for doc in ("docs/new.md", "docs", "docs/b.md", "docs/none.md"):
            with self.subTest(doc):
                self.assertEqual(document_errors(self.cf(document=doc), tracked),
                                 ["document %s is not a tracked file" % doc])

    def test_cited_path_not_tracked(self):  # E3, E4
        self.put("src/new.txt", "n\n")
        tracked = gitinfo.tracked_files(self.root)
        for p in ("src/new.txt", "src", "src/none.txt"):
            with self.subTest(p):
                self.assertEqual(document_errors(self.cf(path=p), tracked),
                                 ["claim %s: cited path %s is not a tracked file" % (CID, p)])

    def test_symlink_and_gitlink_are_untracked(self):  # E5
        os.symlink("x.txt", os.path.join(self.root, "src", "link"))
        git(self.root, "add", "src/link")
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,src/sub" % git(self.root, "rev-parse",
                                                                                           "HEAD"))
        tracked = gitinfo.tracked_files(self.root)
        for p in ("src/link", "src/sub"):
            with self.subTest(p):
                self.assertEqual(document_errors(self.cf(path=p), tracked),
                                 ["claim %s: cited path %s is not a tracked file" % (CID, p)])

    def test_malformed_never_raises(self):  # F4 for this function
        tracked = gitinfo.tracked_files(self.root)
        for row in ({}, {**CLAIM_FILE, "claims": "x"}, {**CLAIM_FILE, "claims": [1, {"cites": "x"},
                                                                                 {"cites": [1, {"path": 3}]}]}):
            with self.subTest(repr(row)[:50]):
                errs = document_errors(ClaimFile("f", row), tracked)
                self.assertTrue(all("src/x.txt" not in e for e in errs))


class BlobIdTests(RepoCase):
    def check_matches_add(self, rel: str, data: bytes) -> None:
        path = os.path.join(self.root, *rel.split("/"))
        with open(path, "wb") as fh:
            fh.write(data)
        got = gitinfo.blob_id(self.root, rel)
        git(self.root, "add", "--", rel)
        self.assertEqual(got, git(self.root, "rev-parse", ":" + rel))

    def test_blob_id_matches_git_add(self):  # H1
        git(self.root, "config", "core.autocrlf", "true")
        self.put(".gitattributes", "*.flt filter=up\n")
        git(self.root, "config", "filter.up.clean", "tr a-z A-Z")
        git(self.root, "add", ".gitattributes")
        cases = [("src/t.txt", b"text\n"), ("src/b.bin", b"\x00\x01\xff\xfe"), ("src/u.txt", b"\xff\xfe bad\n"),
                 ("src/crlf.txt", b"a\r\nb\r\n"), ("src/nonl.txt", b"no newline"), ("src/f.flt", b"lower\n"),
                 ("src/dash -x.txt", b"x\n"), ("src/a:b.txt", b"colon\n")]
        for rel, data in cases:
            with self.subTest(rel):
                self.check_matches_add(rel, data)
        self.assertNotEqual(gitinfo.blob_id(self.root, "src/crlf.txt"), git(self.root, "hash-object",
                                                                              "--no-filters", "src/crlf.txt"))

    def test_git_argument_list(self):  # Global Constraints "Git calls": an argument list, `--` before the path
        with mock.patch.object(gitinfo, "_run", wraps=gitinfo._run) as run:
            gitinfo.blob_id(self.root, "src/x.txt")
        calls = [(c.args[1], c.args[2], c.kwargs.get("literal"), c.kwargs.get("opts"), bool(c.kwargs.get("index")))
                 for c in run.call_args_list[-3:]]
        self.assertEqual(calls, [
            ("rev-parse --git-path", ["rev-parse", "--git-path", "index"], None, None, False),
            ("add", ["add", "--", "src/x.txt"], True, ["-c", "core.safecrlf=false", "-c", "core.splitIndex=false"],
             True),
            ("ls-files", ["ls-files", "-z", "--stage", "--", "src/x.txt"], True, None, True)])
        with mock.patch.dict(os.environ, {"LC_ALL": "fr_FR.UTF-8", "GIT_DIR": "/nowhere"}):
            self.assertEqual(gitinfo.blob_id(self.root, "src/x.txt"), self.blob)

    def test_leading_dash_paths_match_git_add(self):  # R2-1 (fix round 2): `--` keeps a '-' path a path
        os.mkdir(os.path.join(self.root, "-x"))
        for rel, data in (("-a.txt", b"a\n"), ("-x/y.txt", b"y\n"), ("src/-b.txt", b"b\n"), ("--c.txt", b"c\n")):
            with self.subTest(rel):
                self.check_matches_add(rel, data)

    def test_path_forms_refused_before_git(self):  # H2
        for p in ("/abs", "a/../b", "./a", "", "a//b", "a/", ".", "..", "a/./b", 5, None):
            with self.subTest(repr(p)):
                with mock.patch.object(gitinfo, "_run", side_effect=AssertionError("git ran")):
                    with self.assertRaises(GateError):
                        gitinfo.blob_id(self.root, p)

    def test_path_kinds_refused(self):  # H3
        os.mkfifo(os.path.join(self.root, "src", "fifo"))
        os.symlink("x.txt", os.path.join(self.root, "src", "link"))
        os.symlink("src", os.path.join(self.root, "lsrc"))
        for p in ("src/missing", "src", "src/fifo", "src/link", "lsrc/x.txt", "src/x.txt/y"):
            with self.subTest(p):
                with self.assertRaises(GateError) as cm:
                    gitinfo.blob_id(self.root, p)
                self.assertIn(p.split("/")[0], str(cm.exception))
                self.assertNotIn(self.root, str(cm.exception))

    def test_root_forms(self):  # H4, L2
        check_root_forms(self, root_forms(self.tmp, self.root), {"blob_id": lambda r: gitinfo.blob_id(r, "file.txt")})

    def test_existing_signatures_unchanged(self):  # H5
        want = {"toplevel": "(root: 'str') -> 'str'", "head_sha": "(root: 'str') -> 'str'",
                "commit_exists": "(root: 'str', sha: 'str') -> 'bool'",
                "blob_exists": "(root: 'str', sha: 'str', path: 'str') -> 'bool'",
                "tracked_files": "(root: 'str') -> 'frozenset'",
                "show": "(root: 'str', ref: 'str', path: 'str') -> 'Optional[str]'",
                "ls_tree": "(root: 'str', ref: 'str', directory: 'str') -> 'list'",
                "merge_base": "(root: 'str', a: 'str', b: 'str') -> 'str'",
                "user_email": "(root: 'str') -> 'Optional[str]'",
                "blob_id": "(root: 'str', path: 'str') -> 'str'",
                "blob_ids": "(root: 'str', paths: 'list') -> 'dict'"}
        for name, sig in want.items():
            with self.subTest(name):
                self.assertEqual(str(inspect.signature(getattr(gitinfo, name))), sig)

    def test_sha256_repository_fails_closed(self):  # H6
        sub = os.path.join(self.tmp, "s256")
        os.mkdir(sub)
        git(sub, "init", "-q", "--object-format=sha256", "-b", "main")
        with open(os.path.join(sub, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("a\n")
        bid = gitinfo.blob_id(sub, "a.txt")
        self.assertEqual(len(bid), 64)
        self.assertIn("claims.0.cites.0.blob: " + BLOB_ERR, validate(with_cite(blob=bid), cfg_defaults()))


class StaleTests(RepoCase):
    def cf(self, **kw) -> ClaimFile:
        return ClaimFile(CDIR + "/docs--a.yml", self.row(**kw))

    def test_unchanged_cite_is_fresh(self):  # S1
        self.assertEqual(stale_errors(self.cf(), self.root, None), [])

    def test_changed_cite_with_updated_blob_is_fresh(self):  # S2 (F-B2p-1)
        self.put("src/x.txt", "line 1\nline 2\nline X\n")
        git(self.root, "add", "src/x.txt")
        new = git(self.root, "rev-parse", ":src/x.txt")
        self.assertEqual(stale_errors(self.cf(blob=new), self.root, None), [])

    def test_changed_cite_without_update_is_stale(self):  # S3
        self.put("src/x.txt", "line 1\nline 2\nline X\n")
        git(self.root, "add", "src/x.txt")
        new = git(self.root, "rev-parse", ":src/x.txt")
        errs = stale_errors(self.cf(), self.root, None)
        self.assertEqual([i for i, _ in errs], [CID])
        self.assertEqual(errs[0][1], "cites.0: src/x.txt has blob %s; the claim records %s" % (new, self.blob))

    def test_unstaged_change_is_stale(self):  # S3: the working tree is what is compared
        self.put("src/x.txt", "changed\n")
        self.assertEqual([i for i, _ in stale_errors(self.cf(), self.root, None)], [CID])

    def test_deleted_or_renamed_is_stale(self):  # S4
        for how in ("rm", "mv", "unstaged-delete"):
            with self.subTest(how):
                sub = os.path.join(self.tmp, "s4-" + how)
                os.mkdir(sub)
                root = make_repo(sub)
                os.makedirs(os.path.join(root, "src"))
                with open(os.path.join(root, "src", "x.txt"), "w", encoding="utf-8") as fh:
                    fh.write("x\n")
                commit_all(root, "x")
                blob = git(root, "rev-parse", "HEAD:src/x.txt")
                if how == "rm":
                    git(root, "rm", "-q", "src/x.txt")
                elif how == "mv":
                    git(root, "mv", "src/x.txt", "src/z.txt")
                else:
                    os.rename(os.path.join(root, "src", "x.txt"), os.path.join(self.tmp, "away"))
                row = self.row(blob=blob)
                why = "absent or not a regular file" if how == "unstaged-delete" else "absent or untracked"
                self.assertEqual(stale_errors(ClaimFile("f", row), root, None), [(CID, "cites.0: src/x.txt is " + why)])

    def test_claim_added_with_its_file_is_fresh(self):  # S5
        self.put("src/new.txt", "new\n")
        git(self.root, "add", "src/new.txt")
        blob = git(self.root, "rev-parse", ":src/new.txt")
        self.assertEqual(stale_errors(self.cf(path="src/new.txt", blob=blob), self.root, None), [])

    def test_change_outside_cited_lines_is_stale(self):  # S6
        self.put("src/x.txt", "".join("line %d\n" % i for i in range(1, 9)) + "edited 9\nline 10\n")
        self.assertEqual([i for i, _ in stale_errors(self.cf(), self.root, None)], [CID])

    def test_several_stale_cites_one_entry(self):  # S7
        row = self.row(ids=(CID, CID2))
        row["claims"][0]["cites"].append({"path": "src/y.txt", "blob": "f" * 40})
        row["claims"][0]["cites"].append({"path": "src/none.txt", "blob": "f" * 40})
        y = git(self.root, "rev-parse", "HEAD:src/y.txt")
        self.assertEqual(stale_errors(ClaimFile("f", row), self.root, None), [
            (CID, "cites.1: src/y.txt has blob %s; the claim records %s; cites.2: src/none.txt is absent or "
                  "untracked" % (y, "f" * 40))])

    def test_base_has_no_effect(self):  # S8
        self.put("src/x.txt", "changed\n")
        want = stale_errors(self.cf(), self.root, None)
        self.assertEqual(stale_errors(self.cf(), self.root, "main"), want)
        self.assertEqual(stale_errors(self.cf(), self.root, "no-such-ref"), want)

    def test_malformed_rows_never_raise(self):  # S9
        for row in ({}, {**CLAIM_FILE, "claims": "x"}, {**CLAIM_FILE, "claims": [1, {"cites": "x"}]},
                    {**CLAIM_FILE, "claims": [{"id": 5, "cites": [{"path": "src/x.txt", "blob": "f" * 40}]}]},
                    {**CLAIM_FILE, "claims": [{"id": CID, "cites": [1, {"path": 3, "blob": BLOB},
                                                                    {"path": "src/x.txt", "blob": 5},
                                                                    {"path": "src/x.txt"}]}]}):
            with self.subTest(repr(row)[:60]):
                self.assertEqual(stale_errors(ClaimFile("f", row), self.root, None), [])
        row = {**CLAIM_FILE, "claims": [{"id": CID, "cites": [{"path": "/abs", "blob": BLOB}]}]}
        self.assertEqual(stale_errors(ClaimFile("f", row), self.root, None),
                         [(CID, "cites.0: /abs is absent or untracked")])

    def test_untracked_present_file_is_stale_without_hashing(self):  # S10
        self.put("src/new.txt", "new\n")
        blob = git(self.root, "hash-object", "--", "src/new.txt")
        with mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("hashed")):
            self.assertEqual(stale_errors(self.cf(path="src/new.txt", blob=blob), self.root, None),
                             [(CID, "cites.0: src/new.txt is absent or untracked")])

    def test_tracked_path_replaced_by_non_regular_is_stale(self):  # S4: a symlink or directory on disk
        os.rename(os.path.join(self.root, "src", "x.txt"), os.path.join(self.tmp, "x"))
        os.symlink("y.txt", os.path.join(self.root, "src", "x.txt"))
        self.assertEqual(stale_errors(self.cf(), self.root, None),
                         [(CID, "cites.0: src/x.txt is absent or not a regular file")])

    def test_root_forms(self):  # L2
        cf = self.cf()
        check_root_forms(self, root_forms(self.tmp, self.root), {"stale": lambda r: stale_errors(cf, r, None)})


class BaseTests(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.fa = self.write("docs--a.yml", self.row(ids=(CID, CID2)))
        self.fb = self.write("docs--b.yml", self.row(ids=(CID3,), document="docs/b.md"))
        commit_all(self.root, "claims")

    def errs(self, base: str = "HEAD") -> list:
        return base_errors(self.root, self.cfg, load(self.root, self.cfg), base)

    def test_clean_passes(self):
        self.assertEqual(self.errs(), [])

    def test_deleted_claim_file_fails(self):  # B1
        git(self.root, "rm", "-q", self.fb)
        self.assertEqual(self.errs(), [("deleted." + self.fb, "%s exists on HEAD and its document docs/b.md is "
                                                             "kept; claim files are never deleted" % self.fb)])

    def test_claim_file_cleaned_with_document_passes(self):  # B2 (Q-B2plan-5 (a))
        git(self.root, "rm", "-q", self.fb, "docs/b.md")
        self.assertEqual(self.errs(), [])

    def test_document_absent_at_merge_base(self):  # B3
        f = self.write("docs--never.yml", self.row(ids=("C-20261101-k3f9",), document="docs/never.md"))
        bad = self.write("x.yml", self.row(ids=("C-20261101-m4n5",), document="/abs.md"))
        commit_all(self.root, "claims about absent documents")
        git(self.root, "rm", "-q", f, bad)
        self.assertEqual([s for s, _ in self.errs()], ["deleted." + f, "deleted." + bad])

    def test_document_deleted_on_disk_only_is_kept(self):  # B4
        git(self.root, "rm", "-q", self.fb)
        os.rename(os.path.join(self.root, "docs", "b.md"), os.path.join(self.tmp, "b.md"))
        self.assertEqual([s for s, _ in self.errs()], ["deleted." + self.fb])

    def test_removed_claim_id_fails(self):  # B5
        self.write("docs--a.yml", self.row(ids=(CID2,)))
        self.assertEqual(self.errs(), [("removed." + CID, "%s was in %s on HEAD and is in no claim file now; "
                                                          "claim ids are never removed" % (CID, self.fa))])

    def test_id_moved_to_another_file(self):  # B6
        self.write("docs--a.yml", self.row(ids=(CID2,)))
        self.write("docs--b.yml", self.row(ids=(CID3, CID), document="docs/b.md"))
        self.assertEqual(self.errs(), [])

    def test_removed_id_of_a_cleaned_file_is_not_reported(self):  # B2 with B5: the file is gone with its document
        git(self.root, "rm", "-q", self.fa, "docs/a.md")
        self.assertEqual(self.errs(), [])

    def test_collision_with_base(self):  # B7
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "checkout", "-q", "main")
        self.write("docs--b.yml", self.row(ids=(CID3, "C-20261102-k3f9"), document="docs/b.md"))
        commit_all(self.root, "base adds an id")
        git(self.root, "checkout", "-q", "feature")
        for text, want in (("x holds", []), ("other text", ["collision.C-20261102-k3f9"])):
            with self.subTest(text):
                row = self.row(ids=(CID, CID2), text="x holds")
                extra = copy.deepcopy(row["claims"][0])
                extra.update(id="C-20261102-k3f9", text=text)
                row["claims"].append(extra)
                self.write("docs--a.yml", row)
                self.assertEqual([s for s, _ in self.errs("main")], want)
        self.assertEqual(self.errs("main")[0][1], "id C-20261102-k3f9 already exists on main with other content; "
                                                  "mint a new id")

    def test_collision_compares_parsed_values(self):  # B7: 1 and true differ
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "checkout", "-q", "main")
        nid = "C-20261102-k3f9"
        self.write("docs--b.yml", {**self.row(ids=(CID3,), document="docs/b.md"),
                                   "claims": self.row(ids=(CID3,))["claims"] + [{"id": nid, "text": 1}]})
        commit_all(self.root, "base")
        git(self.root, "checkout", "-q", "feature")
        row = self.row(ids=(CID, CID2))
        row["claims"].append({"id": nid, "text": True})
        self.write("docs--a.yml", row)
        self.assertEqual([s for s, _ in self.errs("main")], ["collision." + nid])
        row["claims"][-1]["text"] = 1
        self.write("docs--a.yml", row)
        self.assertEqual(self.errs("main"), [])

    def test_collision_against_every_tip_copy_once(self):  # B7: the id twice at the tip, twice now
        nid = "C-20261102-k3f9"
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "checkout", "-q", "main")
        base_a = self.row(ids=(CID, CID2, nid))
        self.write("docs--a.yml", base_a)
        b = self.row(ids=(CID3, nid), document="docs/b.md")
        b["claims"][1]["text"] = "other"
        self.write("docs--b.yml", b)
        commit_all(self.root, "base holds the id twice")
        git(self.root, "checkout", "-q", "feature")
        self.write("docs--a.yml", base_a)  # equal to one tip copy, not the other
        self.write("docs--b.yml", self.row(ids=(CID3, nid), document="docs/b.md"))
        self.assertEqual([s for s, _ in self.errs("main")], ["collision." + nid])

    def test_file_vanishing_between_listing_and_show(self):  # B10: show() giving None is a GateError
        with mock.patch.object(gitinfo, "show", return_value=None):
            with self.assertRaises(GateError) as cm:
                self.errs()
        self.assertIn("HEAD:%s (at the merge base): missing" % self.fa, str(cm.exception))

    def test_base_without_claims_directory(self):  # B8
        sub = os.path.join(self.tmp, "b8")
        os.mkdir(sub)
        root = make_repo(sub)
        write_record(root, CDIR + "/docs--a.yml", self.row())
        cfg = config.load(root)
        self.assertEqual(base_errors(root, cfg, load(root, cfg), "main"), [])

    def test_absent_base_ref_is_gate_error(self):  # B9
        for ref in ("no-such-ref", "-x", "^main"):
            with self.subTest(ref):
                with self.assertRaises(GateError):
                    self.errs(ref)
        with self.assertRaises(GateError):
            base_errors(self.root, self.cfg, [], 5)

    def test_unparsable_file_at_merge_base(self):  # B10
        for data, want in (("a: 1\n  b: 2\n", "(line 2)"), ("- 1\n", "the top level must be a mapping")):
            with self.subTest(want):
                with open(os.path.join(self.root, *self.fb.split("/")), "w", encoding="utf-8") as fh:
                    fh.write(data)
                commit_all(self.root, "bad")
                git(self.root, "rm", "-q", self.fb)
                with self.assertRaises(GateError) as cm:
                    base_errors(self.root, self.cfg, [], "HEAD")
                self.assertIn("HEAD:%s (at the merge base)" % self.fb, str(cm.exception))
                self.assertIn(want, str(cm.exception))
                git(self.root, "reset", "-q", "--hard")

    def test_non_yml_entries_at_merge_base_ignored(self):  # B11
        self.put(CDIR + "/README.md", "r\n")
        self.put(CDIR + "/.hidden.yml", "- not a map\n")
        commit_all(self.root, "notes")
        git(self.root, "rm", "-q", CDIR + "/README.md", CDIR + "/.hidden.yml")
        self.assertEqual(self.errs(), [])

    def test_index_named_claim_file_is_checked(self):  # B1 for a document named index.md
        self.put("index.md", "i\n")
        f = self.write("index.yml", self.row(ids=("C-20261103-k3f9",), document="index.md"))
        commit_all(self.root, "index")
        git(self.root, "rm", "-q", f)
        self.assertEqual([s for s, _ in self.errs()], ["deleted." + f])

    def test_changed_content_is_not_immutable(self):  # B12
        self.write("docs--a.yml", self.row(ids=(CID, CID2), text="new text"))
        self.assertEqual(self.errs(), [])

    def test_rows_are_migrated(self):  # B13
        git(self.root, "checkout", "-q", "-b", "feature")
        with mock.patch.object(migrations, "migrate", wraps=migrations.migrate) as mg:
            self.errs("main")
        kinds = [c.args[0] for c in mg.call_args_list]
        self.assertEqual(kinds, ["claim"] * 4)  # two files at the merge base, two at the tip
        self.assertEqual([c.args[1]["document"] for c in mg.call_args_list],
                         ["docs/a.md", "docs/b.md", "docs/a.md", "docs/b.md"])

    def test_migrated_row_is_what_is_compared(self):  # B13: a migration's output decides
        nid = "C-20261102-k3f9"
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "checkout", "-q", "main")
        self.write("docs--b.yml", {**self.row(ids=(CID3, nid), document="docs/b.md")})
        commit_all(self.root, "base")
        git(self.root, "checkout", "-q", "feature")
        row = self.row(ids=(CID, CID2, nid))
        row["claims"][2]["text"] = "mine"
        self.write("docs--a.yml", row)

        def fake(kind, r):
            out = copy.deepcopy(r)
            for c in out.get("claims", []):
                c["text"] = "mine"
            return out
        with mock.patch.object(migrations, "migrate", side_effect=fake):
            self.assertEqual(self.errs("main"), [])
        self.assertEqual([s for s, _ in self.errs("main")], ["collision." + nid])

    def test_malformed_rows_at_merge_base_never_raise(self):  # B14
        write_record(self.root, self.fa, {"schema": TAG, "document": "docs/a.md", "claims": "x"})
        write_record(self.root, self.fb, {"schema": TAG, "document": 5,
                                          "claims": [1, {"text": "no id"}, {"id": 7}]})
        commit_all(self.root, "malformed")
        self.write("docs--a.yml", self.row())
        self.assertEqual(self.errs(), [])
        git(self.root, "rm", "-q", self.fb)
        self.assertEqual([s for s, _ in self.errs()], ["deleted." + self.fb])

    def test_root_forms(self):  # B15, L2
        check_root_forms(self, root_forms(self.tmp, self.root),
                         {"base": lambda r: base_errors(r, self.cfg, [], "HEAD")})

    def test_deleted_reason_is_true_in_every_case(self):  # F3 (fix round 1); class: deleted.<file> reason text
        short = "%s exists on HEAD; claim files are never deleted"
        long_ = "%s exists on HEAD and its document %s is kept; claim files are never deleted"
        cases = [("docs--never.yml", "docs/never.md", None), ("x.yml", "/abs.md", None), ("y.yml", 5, None),
                 ("z.yml", None, None), ("w.yml", ["docs/a.md"], None),
                 ("docs--late.yml", "docs/late.md", "docs/late.md")]
        rels = []
        for n, (name, doc, _) in enumerate(cases):
            row = self.row(ids=("C-2026110%d-k3f9" % (n + 1),))
            if doc is None:
                del row["document"]
            else:
                row["document"] = doc
            rels.append(self.write(name, row))
        commit_all(self.root, "claims about absent, malformed and late documents")
        self.put("docs/late.md", "late\n")  # absent at the merge base, tracked now
        git(self.root, "add", "docs/late.md")
        git(self.root, "rm", "-q", *rels)
        want = sorted(("deleted." + rel, long_ % (rel, kept) if kept else short % rel)
                      for rel, (_, _, kept) in zip(rels, cases))
        self.assertEqual(sorted(self.errs()), want)


def limited_int(x, *args):
    """``int`` as on Python 3.11+: a decimal string of more than 4300 digits is refused, on every interpreter."""
    if type(x) is str and len(x.strip().lstrip("+-")) > 4300:
        raise ValueError("Exceeds the limit (4300 digits) for integer string conversion")
    return int(x, *args)


class DigitLimitTests(unittest.TestCase):  # FD1 (fix round 1); class: digit-limit int()
    def check(self, value: str, ok: bool) -> None:
        for patched in (False, True):
            with self.subTest(n=len(value), patched=patched):
                if patched:
                    with mock.patch.object(claims, "int", limited_int, create=True):
                        errs = validate(with_cite(lines=value), cfg_defaults())
                else:
                    errs = validate(with_cite(lines=value), cfg_defaults())
                self.assertEqual(errs, [] if ok else ["claims.0.cites.0.lines: " + LINES_ERR])

    def test_lines_bounds_at_the_digit_limit(self):
        for n in (4300, 4301, 5000):
            self.check("1" * n, True)
            self.check("1-" + "2" * n, True)
            self.check("2" * n + "-1", False)
            self.check("1" * n + "-" + "1" * n, True)
            self.check("2" * n + "-" + "1" * n, False)
            self.check("1" * n + "-" + "2" * n, True)
            self.check("9" * (n - 1) + "-" + "1" * n, True)
            self.check("1" * n + "-" + "9" * (n - 1), False)
            self.check("0" + "1" * n, False)

    def test_tag_version_at_the_digit_limit(self):  # PC1: the tag is compared as text, never parsed
        for n in (4300, 4301, 5000):
            tag = "claim/" + "9" * n
            with self.subTest(n=n):
                with mock.patch.object(claims, "int", limited_int, create=True):
                    self.assertEqual(validate({**CLAIM_FILE, "schema": tag}, cfg_defaults()),
                                     ["schema: expected %s, got %s; run /strict-delivery:upgrade" % (TAG, tag)])


def c17_refused() -> bool:
    """Row C17's expected verdict on the running interpreter: U+1F6DD is refused exactly when the Unicode database
    has it unassigned (category Cn), the only non-printable category it can have (Python: Cn is not printable)."""
    import unicodedata
    return unicodedata.category("\U0001F6DD") == "Cn"


class InterpreterSkeletonTests(unittest.TestCase):  # PC1 skeleton rows (owner Q-D30C2-1 (A+))
    def test_c17_expectation_for_every_unidata_version(self):  # R2-2 (fix round 2)
        # U+1F6DD was added in Unicode 14.0 as So. For each member the expectation is computed with the version and
        # category patched; it never raises, and only 13.0.0 (category Cn) expects a refusal.
        import unicodedata
        cats = {"13.0.0": "Cn", "14.0.0": "So", "15.0.0": "So", "15.1.0": "So", "16.0.0": "So"}
        for version, cat in cats.items():
            with self.subTest(version):
                with mock.patch.object(unicodedata, "unidata_version", version), \
                        mock.patch.object(unicodedata, "category", lambda c, cat=cat: cat):
                    self.assertEqual(c17_refused(), version == "13.0.0")
        if unicodedata.unidata_version in cats:  # cross-check the running database against the member table
            self.assertEqual(unicodedata.category("\U0001F6DD"), cats[unicodedata.unidata_version])

    def test_code_point_printable_on_one_interpreter_only(self):
        # U+1F6DD is unassigned in Unicode 13.0 (Python 3.9) and assigned in 15.1 (3.13). The verdict follows
        # schema._path_ok (isprintable), frozen later by Task 1d2.1 (owner Q-RCp-2 (a)); derived per interpreter.
        refused = c17_refused()
        self.assertEqual("\U0001F6DD".isprintable(), not refused)  # schema._path_ok's rule: str.isprintable
        doc, path = "docs/\U0001F6DD.md", "src/\U0001F6DD.txt"
        errs = validate({**CLAIM_FILE, "document": doc}, cfg_defaults())
        self.assertEqual(errs, ["document: " + PATH_ERR] if refused else [])
        errs = validate(with_cite(path=path), cfg_defaults())
        self.assertEqual(errs, ["claims.0.cites.0.path: " + PATH_ERR] if refused else [])
        self.assertEqual(slug(doc), "docs--\U0001F6DD")

    def test_no_handler_needs_an_exception_group(self):
        # Every except clause in claims.py, migrations.py and gitinfo's blob-id functions names a class that exists
        # on 3.9 and is not an exception group; none is bare and none is except*.
        import ast
        got = {}
        for mod, func in ((claims, None), (migrations, None), (gitinfo, "blob_id"), (gitinfo, "blob_ids"),
                          (gitinfo, "_staged"), (gitinfo, "_drop"), (gitinfo, "_stage_entries")):
            tree = ast.parse(inspect.getsource(getattr(mod, func) if func else mod))
            names = []
            for node in ast.walk(tree):
                self.assertNotEqual(type(node).__name__, "TryStar")
                if isinstance(node, ast.ExceptHandler):
                    self.assertIsNotNone(node.type, "bare except in %s" % mod.__name__)
                    names.append(ast.unparse(node.type) if hasattr(ast, "unparse") else ast.dump(node.type))
            got[mod.__name__ + ("." + func if func else "")] = sorted(set(names))
        self.assertEqual(got, {"gates.lib.claims": ["FileNotFoundError", "GateError", "OSError", "yamlsub.YamlError"],
                               "gates.lib.migrations": [], "gates.lib.gitinfo.blob_id": [],
                               "gates.lib.gitinfo.blob_ids": ["OSError"], "gates.lib.gitinfo._drop": ["OSError"],
                               "gates.lib.gitinfo._staged": ["FileNotFoundError", "OSError"],
                               "gates.lib.gitinfo._stage_entries": []})
        for names in got.values():
            for n in names:
                self.assertNotIn("ExceptionGroup", n)


# Row H7's members (RV3-1): a leading '-' at the top level, in a nested first component and in a later component, a
# leading '--', and names git would read as options without the '--' before the path.
DASH_PATHS = ("-a.txt", "-x/y.txt", "src/-b.txt", "--c.txt", "-", "--", "-n", "--stdin", "--path=x",
              "-x/--stdin-paths")


class BlobIdPreconditionTests(GitIsolatedTestCase):
    """R2-1 (fix round 2); class: a precondition of blob_id that stale_errors does not establish before the call."""

    def setUp(self) -> None:
        super().setUp()
        self.root = make_repo(self.work)
        for d in ("-x", "src"):
            os.mkdir(os.path.join(self.root, d))
        for rel in DASH_PATHS:
            with open(os.path.join(self.root, *rel.split("/")), "w", encoding="utf-8") as fh:
                fh.write(rel + "\n")
        commit_all(self.root, "dash paths")

    def cf(self, path: str, blob: object) -> ClaimFile:
        return ClaimFile("f", {"schema": TAG, "document": "docs/a.md",
                               "claims": [{**CLAIM, "cites": [{"path": path, "blob": blob}]}]})

    def test_leading_dash_cites_get_a_verdict(self):  # H7; RV3-1 (fix round 3): every member, fresh then stale
        for rel in DASH_PATHS:
            with self.subTest(rel):
                blob = git(self.root, "rev-parse", "HEAD:" + rel)
                cf = self.cf(rel, blob)
                self.assertEqual(validate(cf.row, cfg_defaults()), [])
                self.assertEqual(stale_errors(cf, self.root, None), [])
                with open(os.path.join(self.root, *rel.split("/")), "a", encoding="utf-8") as fh:
                    fh.write("more\n")
                now = git(self.root, "hash-object", "--", rel)
                self.assertEqual(stale_errors(cf, self.root, None),
                                 [(CID, "cites.0: %s has blob %s; the claim records %s" % (rel, now, blob))])

    def test_unreachable_members_refused_by_validate_and_never_hashed(self):
        # Non-normalised forms and non-str paths never reach blob_id: validate refuses them, and stale_errors finds
        # them untracked (or skips a non-str) without calling it.
        for p in (".", "..", "a/./b", "a/../b", "a//b", "/abs", "./a", "a/", ""):
            with self.subTest(p):
                cf = self.cf(p, BLOB)
                errs = validate(cf.row, cfg_defaults())
                self.assertEqual(len(errs), 1)
                self.assertTrue(errs[0].startswith("claims.0.cites.0.path: "), errs)
                with mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("hashed")):
                    self.assertEqual(stale_errors(cf, self.root, None),
                                     [(CID, "cites.0: %s is absent or untracked" % p)])
        for p in (5, None, ["-a.txt"]):
            with self.subTest(repr(p)):
                cf = self.cf(p, BLOB)
                self.assertTrue(validate(cf.row, cfg_defaults()))
                with mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("hashed")):
                    self.assertEqual(stale_errors(cf, self.root, None), [])


class StagedBlobIdTests(RepoCase):
    """F1 (review 1), owner Q-2a2r1-2 (a); class: index-dependent content conversion (core.autocrlf true/input,
    text=auto, eol attributes). The id is what ``git add`` stores, read after staging into a copy of the index; the
    real index never changes. The oracle is ``git add`` on the real index, run by the test after the call."""

    def index_bytes(self) -> bytes:
        with open(os.path.join(self.root, ".git", "index"), "rb") as fh:
            return fh.read()

    def write_bytes(self, rel: str, data: bytes) -> None:
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def verdict(self, rel: str, blob: str) -> list:
        row = self.row(path=rel, blob=blob)
        before = self.index_bytes()
        got = stale_errors(ClaimFile("f", row), self.root, None)
        self.assertEqual(self.index_bytes(), before, "the real index changed")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git", "index.lock")))
        return got

    def oracle(self, rel: str) -> str:
        git(self.root, "add", "--", rel)
        return git(self.root, "rev-parse", ":" + rel)

    def crlf_in_index(self, rel: str) -> str:
        """Commit ``rel`` with CRLF stored in the index and HEAD (no conversion then); return its blob."""
        self.write_bytes(rel, b"a\r\nb\r\n")
        git(self.root, "-c", "core.autocrlf=false", "add", "--", rel)
        git(self.root, "commit", "-q", "-m", "crlf")
        return git(self.root, "rev-parse", "HEAD:" + rel)

    def test_conversion_cases_match_git_add(self):
        # (setting, attributes, file, content now): each a CRLF-in-index case unless named otherwise.
        cases = [("core.autocrlf=true", None), ("core.autocrlf=input", None), (None, "* text=auto\n"),
                 (None, "* text=auto eol=lf\n"), (None, "* text=auto eol=crlf\n"), (None, "* eol=crlf\n"),
                 (None, "* text eol=lf\n"), ("core.autocrlf=true", "* -text\n")]
        for n, (setting, attrs) in enumerate(cases):
            with self.subTest(setting=setting, attrs=attrs):
                rel = "src/c%d.txt" % n
                head = self.crlf_in_index(rel)
                if setting:
                    git(self.root, "config", *setting.split("="))
                if attrs:
                    self.put(".gitattributes", attrs)
                # Unchanged on disk: the verdict is git add's (fresh exactly when git add keeps the HEAD blob).
                got = self.verdict(rel, head)
                want = self.oracle(rel)
                self.assertEqual(got, [] if want == head else
                                 [(CID, "cites.0: %s has blob %s; the claim records %s" % (rel, want, head))])
                # Changed on disk, still CRLF: the recorded id in the stale reason is git add's.
                git(self.root, "reset", "-q", "--", rel)
                self.write_bytes(rel, b"a\r\nb\r\nc\r\n")
                got = self.verdict(rel, "f" * 40)
                want = self.oracle(rel)
                self.assertEqual(got, [(CID, "cites.0: %s has blob %s; the claim records %s" % (rel, want, "f" * 40))])
                git(self.root, "config", "--unset-all", "core.autocrlf", check=False)
                if attrs:
                    os.unlink(os.path.join(self.root, ".gitattributes"))

    def test_f1_reproducer_crlf_in_index_is_fresh(self):  # F1 exactly: hash-object would call this stale
        head = self.crlf_in_index("src/crlf.txt")
        git(self.root, "config", "core.autocrlf", "true")
        self.assertNotEqual(git(self.root, "hash-object", "--", "src/crlf.txt"), head)
        self.assertEqual(self.verdict("src/crlf.txt", head), [])

    def test_lf_file_and_spaces_and_dash(self):  # the normal LF case; a path with spaces; a leading '-'
        for rel in ("src/x.txt", "src/a b.txt", "-lead.txt", "sp ace/-x .txt"):
            with self.subTest(rel):
                if rel != "src/x.txt":
                    self.write_bytes(rel, b"lf\n")
                    commit_all(self.root, rel)
                head = git(self.root, "rev-parse", "HEAD:" + rel)
                self.assertEqual(self.verdict(rel, head), [])
                self.write_bytes(rel, b"lf\nmore\n")
                got = self.verdict(rel, head)
                self.assertEqual(got, [(CID, "cites.0: %s has blob %s; the claim records %s"
                                        % (rel, self.oracle(rel), head))])

    def test_tab_and_newline_paths(self):  # PC1: -z output keeps a tab or newline inside the path
        rels = ["src/t\tab.txt", "src/n\nl.txt", "src/q\"uote.txt", "src/é.txt"]
        for rel in rels:
            self.write_bytes(rel, b"x\r\n")
        git(self.root, "config", "core.autocrlf", "true")
        before = self.index_bytes()
        got = gitinfo.blob_ids(self.root, rels)
        self.assertEqual(self.index_bytes(), before)
        self.assertEqual(sorted(got), sorted(rels))
        for rel in rels:
            self.assertEqual(got[rel], self.oracle(rel))

    def test_no_index_entry_yet(self):  # a path git add would add new; stale_errors itself never asks (S10)
        self.write_bytes("src/new.txt", b"n\r\n")
        git(self.root, "config", "core.autocrlf", "true")
        before = self.index_bytes()
        got = gitinfo.blob_ids(self.root, ["src/new.txt"])
        self.assertEqual(self.index_bytes(), before)
        self.assertEqual(git(self.root, "ls-files", "--", "src/new.txt"), "")
        self.assertEqual(got, {"src/new.txt": self.oracle("src/new.txt")})

    def test_repository_without_index_file(self):  # no index yet: the copy starts empty
        sub = os.path.join(self.tmp, "fresh")
        os.mkdir(sub)
        git(sub, "init", "-q", "-b", "main")
        with open(os.path.join(sub, "a.txt"), "wb") as fh:
            fh.write(b"a\n")
        self.assertFalse(os.path.exists(os.path.join(sub, ".git", "index")))
        got = gitinfo.blob_ids(sub, ["a.txt"])
        self.assertFalse(os.path.exists(os.path.join(sub, ".git", "index")))
        self.assertEqual(got, {"a.txt": git(sub, "hash-object", "--", "a.txt")})

    def test_non_regular_is_stale_and_never_staged(self):  # kept as today
        os.rename(os.path.join(self.root, "src", "x.txt"), os.path.join(self.tmp, "x"))
        os.symlink("y.txt", os.path.join(self.root, "src", "x.txt"))
        with mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("staged")):
            self.assertEqual(self.verdict("src/x.txt", self.blob),
                             [(CID, "cites.0: src/x.txt is absent or not a regular file")])

    def test_index_from_git_index_file_is_read_and_unchanged(self):  # GIT_INDEX_FILE stays inherited
        head = self.crlf_in_index("src/c.txt")
        alt = os.path.join(self.tmp, "alt-index")
        with open(os.path.join(self.root, ".git", "index"), "rb") as src, open(alt, "wb") as dst:
            dst.write(src.read())
        self.write_bytes("src/c.txt", b"a\nb\n")
        git(self.root, "add", "--", "src/c.txt")  # the real .git/index now holds LF; alt still holds CRLF
        self.write_bytes("src/c.txt", b"a\r\nb\r\n")
        git(self.root, "config", "core.autocrlf", "true")
        with open(alt, "rb") as fh:
            alt_before = fh.read()
        before = self.index_bytes()
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            got = gitinfo.blob_ids(self.root, ["src/c.txt"])
        self.assertEqual(got, {"src/c.txt": head})  # alt's CRLF entry decides: no conversion
        with open(alt, "rb") as fh:
            self.assertEqual(fh.read(), alt_before)
        self.assertEqual(self.index_bytes(), before)
        self.assertNotEqual(gitinfo.blob_ids(self.root, ["src/c.txt"]), {"src/c.txt": head})  # .git/index: LF

    def test_racy_entry_is_rehashed(self):  # the copy keeps the index mtime, so git's racy-entry check holds
        git(self.root, "config", "core.trustctime", "false")
        path = os.path.join(self.root, "src", "y.txt")
        past = os.stat(path).st_mtime_ns - 100 * 10 ** 9
        os.utime(path, ns=(past, past))
        git(self.root, "update-index", "--really-refresh")  # the entry now records `past`, well before the index
        with open(path, "wb") as fh:
            fh.write(b"z\n")  # same size, same inode
        os.utime(path, ns=(past, past))  # stat matches the entry again
        index = os.path.join(self.root, ".git", "index")
        os.utime(index, ns=(past, past))  # the entry is racy: its mtime is not older than the index
        # Without the racy check git add would trust the stat data and keep y's old id.
        self.assertEqual(git(self.root, "ls-files", "-s", "--", "src/y.txt").split()[1],
                         git(self.root, "rev-parse", "HEAD:src/y.txt"))
        got = gitinfo.blob_ids(self.root, ["src/y.txt"])
        self.assertEqual(got, {"src/y.txt": git(self.root, "hash-object", "--", "src/y.txt")})

    def test_one_copy_and_one_add_per_call(self):
        row = self.row(ids=(CID, CID2))
        row["claims"][0]["cites"].append({"path": "src/y.txt", "blob": "f" * 40})
        row["claims"][1]["cites"].append({"path": "docs/a.md", "blob": "f" * 40})
        import shutil
        with mock.patch.object(shutil, "copy2", wraps=shutil.copy2) as cp, \
                mock.patch.object(gitinfo, "_run", wraps=gitinfo._run) as run:
            errs = stale_errors(ClaimFile("f", row), self.root, None)
        self.assertEqual([i for i, _ in errs], [CID, CID2])
        self.assertEqual(cp.call_count, 1)
        adds = [c for c in run.call_args_list if c.args[1] == "add"]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0].args[2], ["add", "--", "src/x.txt", "src/y.txt", "docs/a.md"])
        self.assertTrue(adds[0].kwargs["literal"])
        ls = [c for c in run.call_args_list if c.args[1] == "ls-files"][-1]
        self.assertEqual(ls.args[2], ["ls-files", "-z", "--stage", "--", "src/x.txt", "src/y.txt", "docs/a.md"])
        with mock.patch.object(gitinfo, "blob_ids", wraps=gitinfo.blob_ids) as bi:
            stale_errors(ClaimFile("f", row), self.root, None)
        self.assertEqual(bi.call_count, 1)
        self.assertEqual(gitinfo.blob_ids(self.root, []), {})

    def temp_dirs(self):
        import tempfile
        made = []
        real = tempfile.mkdtemp

        def spy(*a, **kw):
            made.append(real(*a, **{**kw, "dir": self.tmp}))  # inside the test's TemporaryDirectory
            return made[-1]
        return made, mock.patch.object(tempfile, "mkdtemp", side_effect=spy)

    def test_temp_index_removed_on_every_exit(self):
        import shutil
        import tempfile
        made, spy = self.temp_dirs()
        with spy:
            gitinfo.blob_ids(self.root, ["src/x.txt"])
        self.put(".gitignore", "ign.txt\n")
        self.put("ign.txt", "i\n")
        failures = {"git add fails": None,
                    "copy fails": mock.patch.object(shutil, "copy2", side_effect=PermissionError(13, "denied")),
                    "ls-files output lacks the path": mock.patch.object(gitinfo, "_stage_entries", return_value=[]),
                    "interrupted": mock.patch.object(gitinfo, "_staged", side_effect=KeyboardInterrupt)}
        for name, patch in failures.items():
            with self.subTest(name):
                before = self.index_bytes()
                with spy:
                    if patch:
                        with patch:
                            with self.assertRaises(KeyboardInterrupt if name == "interrupted" else GateError):
                                gitinfo.blob_ids(self.root, ["src/x.txt"])
                    else:
                        with self.assertRaises(GateError) as cm:
                            gitinfo.blob_ids(self.root, ["ign.txt"])
                        self.assertEqual(str(cm.exception), "git add failed (exit 1)")
                self.assertEqual(self.index_bytes(), before)
        self.assertEqual(len(made), 1 + len(failures))
        for d in made:
            self.assertFalse(os.path.exists(d), d)
        with mock.patch.object(tempfile, "mkdtemp", side_effect=OSError(28, "full")):
            with self.assertRaises(GateError) as cm:
                gitinfo.blob_ids(self.root, ["src/x.txt"])
        self.assertEqual(str(cm.exception), "blob id: cannot make a temporary index (full)")
        made, spy = self.temp_dirs()
        with spy, mock.patch.object(os, "rmdir", side_effect=OSError(16, "busy")):
            with self.assertRaises(GateError) as cm:
                gitinfo.blob_ids(self.root, ["src/x.txt"])
        self.assertEqual(str(cm.exception), "blob id: cannot remove the temporary index (busy)")

    def test_failure_messages(self):
        with mock.patch.object(gitinfo, "_stage_entries", return_value=[]):
            with self.assertRaises(GateError) as cm:
                gitinfo.blob_ids(self.root, ["src/x.txt"])
        self.assertEqual(str(cm.exception), "git ls-files: no stage-0 entry for src/x.txt after git add")
        import shutil
        with mock.patch.object(shutil, "copy2", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(GateError) as cm:
                gitinfo.blob_ids(self.root, ["src/x.txt"])
        self.assertEqual(str(cm.exception), "blob id: cannot copy the index (denied)")
        for bad in ("src/x.txt", None, 5, {"src/x.txt": 1}, ("src/x.txt",), ["src/x.txt", 5], [b"src/x.txt"]):
            with self.subTest(repr(bad)):
                with mock.patch.object(gitinfo, "_run", side_effect=AssertionError("git ran")):
                    with self.assertRaises(GateError) as cm:
                        gitinfo.blob_ids(self.root, bad)
                self.assertEqual(str(cm.exception), "add: paths must be a list of strings")

    def test_only_a_regular_stage_0_entry_counts(self):  # a link or a conflict stage never gives the id
        sha = "e" * 40
        for entries in ([("120000", sha, "0", "src/x.txt")], [("100644", sha, "2", "src/x.txt")],
                        [("100644", sha, "0", "src/x.txt.bak")]):
            with self.subTest(entries):
                with mock.patch.object(gitinfo, "_stage_entries", return_value=entries):
                    with self.assertRaises(GateError) as cm:
                        gitinfo.blob_ids(self.root, ["src/x.txt"])
                self.assertEqual(str(cm.exception), "git ls-files: no stage-0 entry for src/x.txt after git add")
        with mock.patch.object(gitinfo, "_stage_entries", return_value=[("100755", sha, "0", "src/x.txt")]):
            self.assertEqual(gitinfo.blob_ids(self.root, ["src/x.txt"]), {"src/x.txt": sha})

    def test_color_and_abbrev_config_ignored(self):  # Git calls: the fixture sets color.ui=always, core.abbrev=7
        got = gitinfo.blob_ids(self.root, ["src/x.txt", "src/x.txt"])
        self.assertEqual(got, {"src/x.txt": self.blob})
        self.assertEqual(len(got["src/x.txt"]), 40)


class AncestorTests(GitIsolatedTestCase):  # F2 (fix round 1); class: kind of an ancestor of a tracked cited path
    def repo(self, name: str) -> tuple:
        sub = os.path.join(self.tmp, name)
        os.mkdir(sub)
        root = make_repo(sub)
        os.makedirs(os.path.join(root, "d", "e"))
        with open(os.path.join(root, "d", "e", "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("f\n")
        commit_all(root, "f")
        blob = git(root, "rev-parse", "HEAD:d/e/f.txt")
        row = {"schema": TAG, "document": "docs/a.md",
               "claims": [{**CLAIM, "cites": [{"path": "d/e/f.txt", "blob": blob}]}]}
        return root, ClaimFile(CDIR + "/docs--a.yml", row)

    def test_ancestor_kinds_give_a_stale_entry(self):
        want = [(CID, "cites.0: d/e/f.txt is absent or not a regular file")]
        for level in ("d", "d/e"):
            for kind in ("symlink-in-repo", "symlink-elsewhere", "dangling-symlink", "regular-file", "missing"):
                with self.subTest(level=level, kind=kind):
                    root, cf = self.repo("%s-%s" % (level.replace("/", "_"), kind))
                    anc = os.path.join(root, *level.split("/"))
                    away = os.path.join(root, "moved") if kind == "symlink-in-repo" else \
                        os.path.join(self.tmp, "away-%s-%s" % (level.replace("/", "_"), kind))
                    os.rename(anc, away)
                    if kind in ("symlink-in-repo", "symlink-elsewhere"):
                        os.symlink(away, anc)  # the target holds the same, unchanged f.txt
                    elif kind == "dangling-symlink":
                        os.symlink(os.path.join(self.tmp, "nowhere"), anc)
                    elif kind == "regular-file":
                        with open(anc, "w", encoding="utf-8") as fh:
                            fh.write("x\n")
                    self.assertEqual(stale_errors(cf, root, None), want)

    def test_real_directories_still_fresh_and_git_problems_raise(self):  # invariants of the replaced code
        root, cf = self.repo("plain")
        self.assertEqual(stale_errors(cf, root, None), [])
        with mock.patch.object(gitinfo, "blob_ids", side_effect=GateError("git add failed (exit 128)")):
            with self.assertRaises(GateError):
                stale_errors(cf, root, None)
        with self.assertRaises(GateError):
            stale_errors(cf, os.path.join(root, "d"), None)


def argv_bytes(argv: list) -> int:
    """The bytes an argv takes in the kernel's argument area: each argument and its NUL."""
    return sum(len(a.encode("utf-8")) + 1 for a in argv)


def git_sub(argv: list) -> str:
    """The git subcommand of a recorded ``git [opts] [--literal-pathspecs] -C root <sub> ...`` argv."""
    return argv[argv.index("-C") + 2]


def path_args(argv: list) -> list:
    """The paths of a recorded argv: every argument after the first ``--`` that follows the subcommand."""
    return argv[argv.index("--", argv.index("-C") + 2) + 1:]


class IndexCopyTests(RepoCase):
    """Owner Q-2a2r4-1 (a); class: index copies per gate run (rows H14-H17). The copy count is the number of
    ``shutil.copy2`` calls, which is how ``_staged`` copies the index, wrapped so the real copy still runs."""

    def row3(self) -> dict:
        row = self.row(ids=(CID, CID2))
        row["claims"][0]["cites"].append({"path": "src/y.txt", "blob": "f" * 40})
        row["claims"][1]["cites"] += [{"path": "docs/a.md", "blob": git(self.root, "rev-parse", "HEAD:docs/a.md")},
                                      {"path": "src/none.txt", "blob": BLOB}, {"path": 5, "blob": BLOB},
                                      {"path": "src/x.txt", "blob": self.blob}]
        return row

    def want3(self) -> list:
        y = git(self.root, "rev-parse", "HEAD:src/y.txt")
        return [(CID, "cites.1: src/y.txt has blob %s; the claim records %s" % (y, "f" * 40)),
                (CID2, "cites.2: src/none.txt is absent or untracked")]

    def test_stale_paths_are_the_tracked_plain_cites_once(self):  # H14
        os.symlink("x.txt", os.path.join(self.root, "src", "l.txt"))
        git(self.root, "add", "src/l.txt")
        row = self.row3()
        row["claims"][0]["cites"].append({"path": "src/l.txt", "blob": BLOB})
        other = self.row(ids=(CID3,), path="src/y.txt")
        other["claims"][0]["cites"].append({"path": "docs/b.md", "blob": BLOB})  # only in the second file
        self.assertEqual(claims.stale_paths([ClaimFile("f", row), ClaimFile("g", other)], self.root),
                         ["src/x.txt", "src/y.txt", "docs/a.md", "docs/b.md"])
        self.assertEqual(claims.stale_paths([], self.root), [])
        with self.assertRaises(GateError):
            claims.stale_paths([ClaimFile("f", row)], os.path.join(self.root, "src"))  # tracked_files' root check

    def test_without_a_map_one_copy_per_call(self):  # H15: today's behaviour for other consumers
        cf = ClaimFile("f", self.row3())
        with mock.patch.object(shutil, "copy2", wraps=shutil.copy2) as cp, \
                mock.patch.object(gitinfo, "blob_ids", wraps=gitinfo.blob_ids) as bi:
            self.assertEqual(stale_errors(cf, self.root, None), self.want3())
            self.assertEqual(stale_errors(cf, self.root, None, blob_ids=None), self.want3())
        self.assertEqual((cp.call_count, bi.call_count), (2, 2))

    def test_full_map_makes_no_copy_and_is_used(self):  # H16
        cf = ClaimFile("f", self.row3())
        full = gitinfo.blob_ids(self.root, ["src/x.txt", "src/y.txt", "docs/a.md"])
        extra = dict(full, **{"src/zzz.txt": "0" * 40, "src/none.txt": "1" * 40})  # extra keys are ignored
        for given in (full, extra):
            with self.subTest(len(given)):
                with mock.patch.object(shutil, "copy2", side_effect=AssertionError("index copied")), \
                        mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("blob_ids called")):
                    self.assertEqual(stale_errors(cf, self.root, None, blob_ids=given), self.want3())
        fake = dict(full, **{"src/x.txt": "e" * 40})  # the map's id is the one compared: nothing recomputes it
        errs = stale_errors(cf, self.root, None, blob_ids=fake)
        self.assertEqual(errs[0], (CID, "cites.0: src/x.txt has blob %s; the claim records %s; %s"
                                   % ("e" * 40, self.blob, self.want3()[0][1])))

    def test_map_missing_a_needed_path_is_a_gate_error(self):  # H17 (Decision, owner delegation 2026-11-09)
        cf = ClaimFile("f", self.row3())
        full = gitinfo.blob_ids(self.root, ["src/x.txt", "src/y.txt", "docs/a.md"])
        for gone in ("src/x.txt", "src/y.txt", "docs/a.md"):
            with self.subTest(gone):
                part = {k: v for k, v in full.items() if k != gone}
                with mock.patch.object(gitinfo, "blob_ids", side_effect=AssertionError("blob_ids called")):
                    with self.assertRaises(GateError) as cm:
                        stale_errors(cf, self.root, None, blob_ids=part)
                self.assertEqual(str(cm.exception), "stale: no blob id for %s in the given map" % gone)
        for bad in ([], ("src/x.txt",), "src/x.txt", 0):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError) as cm:
                    stale_errors(cf, self.root, None, blob_ids=bad)
                self.assertEqual(str(cm.exception), "stale: blob_ids must be a dict or None")
        empty = ClaimFile("f", self.row(path="src/none.txt"))  # nothing to look up: an empty map is enough
        self.assertEqual([i for i, _ in stale_errors(empty, self.root, None, blob_ids={})], [CID])

    def test_signature(self):  # the plan's positional signature is kept; the map is keyword-only
        sig = inspect.signature(stale_errors)
        self.assertEqual(list(sig.parameters), ["cf", "root", "base", "blob_ids"])
        self.assertEqual(sig.parameters["blob_ids"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(sig.parameters["blob_ids"].default)


class ArgvChunkTests(RepoCase):
    """F1 (review 5); class: argv size above ARG_MAX in every subprocess call of ``blob_ids`` that takes a path
    list (``git add`` and ``git ls-files``; rows H18-H21). Every argv is recorded at ``subprocess.run`` (the real
    call still runs); the oracle ids are git's own from the real index after a real ``git add``."""

    def index_state(self):
        path = os.path.join(self.root, ".git", "index")
        with open(path, "rb") as fh:
            return fh.read(), os.stat(path).st_mtime_ns

    def recorded(self):
        rec = []
        real = subprocess.run

        def spy(argv, *a, **kw):
            rec.append(list(argv))
            return real(argv, *a, **kw)
        return rec, mock.patch.object(subprocess, "run", side_effect=spy)

    def path_calls(self, rec: list) -> dict:
        """The recorded path-list calls (``tracked_files``'s ``ls-files`` takes no path list and is left out)."""
        return {sub: [a for a in rec if git_sub(a) == sub and "--" in a[a.index("-C") + 2:]]
                for sub in ("add", "ls-files")}

    def head_ids(self, paths: list) -> dict:
        return {p: git(self.root, "rev-parse", "HEAD:" + p) for p in paths}

    def test_large_claim_file_gives_verdicts(self):  # H18: the reviewer's reproducer, 6000 paths of 204 characters
        rels = []
        os.makedirs(os.path.join(self.root, "c"))
        for i in range(6000):
            rel = "c/%04d" % i + "x" * 198
            self.assertEqual(len(rel), 204)
            with open(os.path.join(self.root, "c", rel[2:]), "w", encoding="utf-8") as fh:
                fh.write("%d\n" % i)
            rels.append(rel)
        git(self.root, "config", "gc.auto", "0")  # no detached auto-gc writing into .git while the test cleans up
        git(self.root, "config", "maintenance.auto", "false")
        commit_all(self.root, "many")
        staged = {}
        for line in git(self.root, "ls-files", "-s", "--", "c").split("\n"):
            head, _, p = line.partition("\t")
            staged[p] = head.split(" ")[1]  # the real index after a real git add
        self.assertEqual(sorted(staged), sorted(rels))
        self.assertGreater(argv_bytes(rels), 1048576)  # above macOS ARG_MAX (1 MiB) by the paths alone
        row = self.row(path="c/none")
        row["claims"][0]["cites"] = [{"path": p, "blob": staged[p]} for p in rels]
        row["claims"][0]["cites"][17]["blob"] = "f" * 40
        before = self.index_state()
        rec, spy = self.recorded()
        with spy, mock.patch.object(shutil, "copy2", wraps=shutil.copy2) as cp:
            errs = stale_errors(ClaimFile("f", row), self.root, None)
        self.assertEqual(errs, [(CID, "cites.17: %s has blob %s; the claim records %s"
                                 % (rels[17], staged[rels[17]], "f" * 40))])
        self.assertEqual(self.index_state(), before)
        self.assertEqual(cp.call_count, 1)
        calls = self.path_calls(rec)
        for sub in ("add", "ls-files"):
            self.assertGreater(len(calls[sub]), 1, sub)
            self.assertEqual([p for a in calls[sub] for p in path_args(a)], rels, sub)  # each once, in order
            for a in calls[sub]:
                self.assertLessEqual(argv_bytes(a), gitinfo.ARGV_BYTES)

    def test_chunk_boundaries(self):  # H19: exactly at, one under, one over the bound; a path above it alone
        paths = ["src/x.txt", "src/y.txt", "docs/a.md"]
        want = self.head_ids(paths)  # committed LF files, unchanged: the staged id is HEAD's
        rec, spy = self.recorded()
        with spy:
            self.assertEqual(gitinfo.blob_ids(self.root, paths), want)
        calls = self.path_calls(rec)
        sizes = {sub: argv_bytes(calls[sub][0]) for sub in calls}
        self.assertEqual([len(calls[s]) for s in sorted(calls)], [1, 1])
        for sub in ("add", "ls-files"):
            last = argv_bytes(paths[-1:])
            # the argv is exactly at the bound; one under it; one over it; the first two exactly at it; one over
            for bound, want_chunks in ((sizes[sub], [paths]), (sizes[sub] + 1, [paths]),
                                       (sizes[sub] - 1, [paths[:2], paths[2:]]),
                                       (sizes[sub] - last, [paths[:2], paths[2:]]),
                                       (sizes[sub] - last - 1, [paths[:1], paths[1:2], paths[2:]])):
                with self.subTest(sub=sub, over=sizes[sub] - bound):
                    rec, spy = self.recorded()
                    with spy, mock.patch.object(gitinfo, "ARGV_BYTES", bound):
                        self.assertEqual(gitinfo.blob_ids(self.root, paths), want)
                    got = self.path_calls(rec)[sub]
                    self.assertEqual([path_args(a) for a in got], want_chunks)
                    for a in got:
                        self.assertLessEqual(argv_bytes(a), bound)

    def test_path_above_the_bound_gets_its_own_chunk(self):  # H19
        long_rel = "src/" + "l" * 200 + ".txt"
        self.put(long_rel, "long\n")
        self.put("src/z.txt", "z\n")
        commit_all(self.root, "long")
        paths = ["src/x.txt", "src/y.txt", long_rel, "src/z.txt"]
        want = self.head_ids(paths)
        rec, spy = self.recorded()
        with spy:
            gitinfo.blob_ids(self.root, paths)
        for sub in ("add", "ls-files"):
            fixed = argv_bytes(self.path_calls(rec)[sub][0]) - argv_bytes(paths)
            bound = fixed + argv_bytes(paths[:2])  # the two short paths fit; the long one alone is above it
            with self.subTest(sub):
                rec2, spy2 = self.recorded()
                with spy2, mock.patch.object(gitinfo, "ARGV_BYTES", bound):
                    self.assertEqual(gitinfo.blob_ids(self.root, paths), want)
                got = self.path_calls(rec2)[sub]
                self.assertEqual([path_args(a) for a in got], [paths[:2], [long_rel], ["src/z.txt"]])
                self.assertGreater(argv_bytes(got[1]), bound)
            with self.subTest(sub, bound="below the fixed arguments"):
                rec2, spy2 = self.recorded()
                with spy2, mock.patch.object(gitinfo, "ARGV_BYTES", 1):
                    self.assertEqual(gitinfo.blob_ids(self.root, paths), want)
                self.assertEqual([path_args(a) for a in self.path_calls(rec2)[sub]], [[p] for p in paths])

    def test_invariants_hold_across_chunks(self):  # H20: the replaced code's invariants, every path its own chunk
        git(self.root, "config", "core.autocrlf", "true")
        with open(os.path.join(self.root, "src", "c.txt"), "wb") as fh:
            fh.write(b"a\r\nb\r\n")
        git(self.root, "-c", "core.autocrlf=false", "add", "--", "src/c.txt")
        git(self.root, "commit", "-q", "-m", "crlf")
        paths = ["src/x.txt", "src/c.txt", "src/y.txt", "src/x.txt", "src/c.txt"]
        before = self.index_state()
        made = []
        real_mkdtemp = tempfile.mkdtemp

        def mk(*a, **kw):
            made.append(real_mkdtemp(*a, **{**kw, "dir": self.tmp}))
            return made[-1]
        rec, spy = self.recorded()
        with spy, mock.patch.object(gitinfo, "ARGV_BYTES", 1), \
                mock.patch.object(shutil, "copy2", wraps=shutil.copy2) as cp, \
                mock.patch.object(tempfile, "mkdtemp", side_effect=mk):
            got = gitinfo.blob_ids(self.root, paths)
        self.assertEqual(self.index_state(), before)  # the real index: bytes and mtime unchanged
        self.assertEqual(cp.call_count, 1)  # one index copy per call, every chunk into it
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))
        calls = self.path_calls(rec)
        for sub in ("add", "ls-files"):
            self.assertEqual([path_args(a) for a in calls[sub]], [["src/x.txt"], ["src/c.txt"], ["src/y.txt"]])
            self.assertEqual({a[a.index("-C") + 1] for a in calls[sub]}, {self.root})
        self.assertEqual(list(got), ["src/x.txt", "src/c.txt", "src/y.txt"])  # repeats given once
        for p in ("src/x.txt", "src/c.txt", "src/y.txt"):
            git(self.root, "add", "--", p)
            self.assertEqual(got[p], git(self.root, "rev-parse", ":" + p), p)  # git's staged id, conversions on

    def test_failure_in_a_later_chunk(self):  # H21: GateError, temporary index gone, real index unchanged
        self.put(".gitignore", "ign.txt\n")
        self.put("ign.txt", "i\n")
        commit_all(self.root, "ignore")
        before = self.index_state()
        made = []
        real_mkdtemp = tempfile.mkdtemp

        def mk(*a, **kw):
            made.append(real_mkdtemp(*a, **{**kw, "dir": self.tmp}))
            return made[-1]
        rec, spy = self.recorded()
        with spy, mock.patch.object(gitinfo, "ARGV_BYTES", 1), \
                mock.patch.object(tempfile, "mkdtemp", side_effect=mk):
            with self.assertRaises(GateError) as cm:
                gitinfo.blob_ids(self.root, ["src/x.txt", "src/y.txt", "ign.txt"])
        self.assertEqual(str(cm.exception), "git add failed (exit 1)")
        self.assertEqual([path_args(a) for a in self.path_calls(rec)["add"]], [["src/x.txt"], ["src/y.txt"],
                                                                            ["ign.txt"]])
        self.assertEqual(self.path_calls(rec)["ls-files"], [])
        self.assertEqual(self.index_state(), before)
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))

    def test_bound_constant(self):  # Decision (owner delegation 2026-11-09): 30000 bytes per argv
        self.assertEqual(gitinfo.ARGV_BYTES, 30000)


if __name__ == "__main__":
    unittest.main()
