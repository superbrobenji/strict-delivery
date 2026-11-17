"""Tests of gates/tools/claims_cli.py (plan Task 2c.1; input-domain table task-2c.1-domain.md with its binding controller
decisions D-Q1..D-Q30) through ``main(argv)`` and ``python3 -m gates claims`` on real fixture repositories. Expected
ids, blob ids, texts and exit codes are written by hand from the plan, the spec and the table; blob ids come from
``git hash-object`` and an independent ``git add`` into a throwaway index, never from ``gitinfo``; records are read back
with ``claims.load``. Row ids (R1, F5, W3, V-4, X1 ...) are the table's."""
import ast
import builtins
import contextlib
import io
import itertools
import os
import random
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_claims, producers
from gates.lib import claims, config, gitinfo, ids, migrations, yamlsub
from gates.lib.result import GateError
from gates.tools import claims_cli, githooks
from tests.helpers import E128, TOP, GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, root_forms, \
    write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIMS = ".strict-delivery/state/claims"
DEC = ".strict-delivery/state/decisions"
DOC = "docs/a.md"
HAS_EG = hasattr(builtins, "BaseExceptionGroup")
DAY = "20261231"
ZEROS = "0" * 40


def ctag():  # the tag comes from the schema (plan P:32)
    return "claim/%d" % migrations.current_version("claim")


def blob(root, rel):
    """The blob id of a work-tree file by an independent ``git hash-object`` (no conversion configured)."""
    return git(root, "hash-object", "--", rel)


class Seq:
    """A stand-in for the mint's generator: ``choice`` yields the given characters in order."""

    def __init__(self, chars):
        self.chars = iter(chars)

    def choice(self, seq):
        return next(self.chars)


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.put("docs/a.md", "doc\n")
        self.put("src/x.py", "x = 1\n")
        self.put("src/y.py", "y = 2\n")
        commit_all(self.root, "files")

    def put(self, rel, data):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        return p

    def cfg(self):
        return config.load(self.root)

    def argv(self, document=DOC, text="T", cites=("src/x.py",), direct="D", contradiction="C", by="me", extra=()):
        a = ["add", "--document", document, "--text", text]
        for c in cites:
            a += ["--cite", c]
        return a + ["--direct", direct, "--contradiction", contradiction, "--by", by] + list(extra)

    def cli(self, *args, root=True):
        argv = list(args) + (["--root", self.root] if root and "--root" not in args else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = claims_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def snap(self):
        out = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x != ".git"]
            out.update({os.path.relpath(os.path.join(d, f), self.root): None for f in dirs})
            for f in files:
                p = os.path.join(d, f)
                if os.path.islink(p) or not os.path.isfile(p):  # a FIFO would block the open
                    out[os.path.relpath(p, self.root)] = None
                    continue
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.root)] = fh.read()
        return out

    def refused(self, args, needle, root=True):
        before = self.snap()
        code, out, err = self.cli(*args, root=root)
        self.assertEqual((code, out), (1, ""), err)
        self.assertTrue(err.startswith("claims %s: " % args[0]), err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn(needle, err)
        self.assertEqual(self.snap(), before)
        return err

    def usage(self, args):
        before = self.snap()
        code, out, err = self.cli(*args)
        self.assertEqual((code, out), (2, ""), err)
        self.assertIn("usage:", err)
        self.assertEqual(self.snap(), before)

    def add(self, *args, **kw):
        code, out, err = self.cli(*self.argv(*args, **kw))
        self.assertEqual((code, err), (0, ""), err)
        self.assertEqual(out.count("\n"), 1)
        return out.strip()

    def load(self):
        return {cf.file: cf.row for cf in claims.load(self.root, self.cfg())}

    def claim(self, cid, file="%s/docs--a.yml" % CLAIMS):
        return [c for c in self.load()[file]["claims"] if c["id"] == cid][0]

    def verify(self, cid, by="me", extra=()):
        return self.cli("verify", cid, "--by", by, *extra)

    def sub(self, *args, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("COLUMNS",)}
        env.update(PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        p = subprocess.run([sys.executable, "-m", "gates"] + list(args), cwd=cwd or self.root, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


# ---------------------------------------------------------------- Producer 1: dispatch and shell (R1-R10)

class ShellTests(Base):
    def test_claims_cli_usage_errors(self):  # R1, R2, R3
        for args in ([], ["delete"], ["ADD"], ["Add"], ["add "], ["verify "], ["--help"], ["-h"]):
            with self.subTest(args=args):
                code, out, err = self.cli(*args, root=False)
                self.assertEqual(code, 2 if args not in (["--help"], ["-h"]) else code)
                self.assertEqual(out, "")
                self.assertIn("usage: claims", err)
        code, _, err = self.cli("delete", root=False)
        self.assertIn("{add,verify}", err)

    def test_claims_command_registered(self):  # R4
        self.assertIn("claims", gates_main.COMMANDS)
        code, out, err = self.sub("claims")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage: claims", err)
        code, out, err = self.sub("nonesuch")
        self.assertEqual(code, 2)
        self.assertIn("claims", err.splitlines()[-1].split(", "))

    def test_claims_cli_imported_lazily(self):  # R5
        with open(os.path.join(REPO, "gates", "__main__.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        top = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                top += [(node.module or "") + "." + a.name for a in node.names]
        self.assertFalse([m for m in top if "claims_cli" in m], top)
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_claims"][0]
        self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "gates.tools" for n in ast.walk(fn)))

    def test_produces_claim(self):  # R6
        self.assertEqual(claims_cli.PRODUCES, ("claim",))
        self.assertEqual(gate_claims.PRODUCES, ())

    def test_producer_registered(self):  # R6
        self.assertIn("gates.tools.claims_cli", producers.PRODUCER_MODULES)

    def test_gate_schema_checks_claims_now(self):  # R7
        code, out, err = self.sub("check", "schema")
        self.assertEqual(code, 0, out + err)
        self.assertIn("PASS schema.claim", out)

    def test_root_refused_forms(self):  # R8
        for name, path, verdict in root_forms(self.tmp, self.root):
            if verdict == "ok":
                continue
            with self.subTest(form=name):
                code, out, err = self.cli(*self.argv(), "--root", path, root=False)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(verdict, err)
        self.refused(self.argv(extra=["--root", self.root, "--root", self.root]), "--root given more than once",
                     root=False)
        self.refused(self.argv(extra=["--root="]), "--root: must not be empty", root=False)

    def test_only_gateerror_is_a_refusal(self):  # R9
        with mock.patch.object(claims, "load", side_effect=GateError("boom")):
            code, out, err = self.cli(*self.argv())
        self.assertEqual((code, out, err), (1, "", "claims add: boom\n"))
        for exc in (KeyboardInterrupt, SystemExit, MemoryError, RuntimeError):
            with self.subTest(exc=exc.__name__):
                with mock.patch.object(claims, "load", side_effect=exc("x")):
                    with self.assertRaises(exc):
                        self.cli(*self.argv())

    def test_refusal_text_escaped(self):  # R10
        with mock.patch.object(claims, "load", side_effect=GateError("a\nb\\c\x00d")):
            code, out, err = self.cli(*self.argv())
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "claims add: a\\nb\\\\c\\x00d\n")

    def test_exception_groups(self):  # X3
        if not HAS_EG:
            self.skipTest("ExceptionGroup is absent before Python 3.11")
        for exc in (ExceptionGroup("x", [ValueError()]), BaseExceptionGroup("x", [KeyboardInterrupt()])):  # noqa: F821
            for target in ((claims, "load"), (gitinfo, "blob_ids"), (ids, "mint")):
                with self.subTest(exc=type(exc).__name__, target=target[1]):
                    before = self.snap()
                    with mock.patch.object(target[0], target[1], side_effect=exc):
                        with self.assertRaises(type(exc)):
                            self.cli(*self.argv())
                    self.assertEqual(self.snap(), before)

    def test_main_argument_types(self):  # F14 (D-Q11)
        class S(str):
            pass
        before = self.snap()
        for argv in (("add",), [b"add"], ["add", 1], [S("add")], ["add", True], "add"):
            with self.subTest(argv=repr(argv)):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(claims_cli.main(argv), 2)
                self.assertEqual(err.getvalue(), "claims: argv must be a list of str\n")
        self.assertEqual(self.snap(), before)


# ---------------------------------------------------------------- Producer 2: add flags (F1-F14)

FLAG_NAMES = ("--document", "--text", "--direct", "--contradiction", "--by")


class AddFlagTests(Base):
    def drop(self, flag):
        a = self.argv()
        i = a.index(flag)
        return a[:i] + a[i + 2:]

    def test_add_without_contradiction_writes_nothing(self):  # F1 (plan P:1942)
        before = self.snap()
        code, out, err = self.cli(*self.drop("--contradiction"))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(os.path.exists(os.path.join(self.root, CLAIMS)), False)
        self.assertEqual(self.snap(), before)

    def test_add_each_missing_flag(self):  # F1
        for flag in FLAG_NAMES + ("--cite",):
            with self.subTest(flag=flag):
                self.refused(self.drop(flag), "%s is required" % flag)

    def test_add_requires_a_cite(self):  # F11
        self.refused(self.argv(cites=()), "--cite is required")

    def test_add_flag_repeated(self):  # F2: in full, with =, abbreviated
        abbr = {"--document": "--do", "--text": "--t", "--direct": "--di", "--contradiction": "--cont",
                "--by": "--b"}
        for flag in FLAG_NAMES:
            for form, extra in (("full", [flag, "x"]), ("equals", [flag + "=x"]), ("abbrev", [abbr[flag], "x"])):
                with self.subTest(flag=flag, form=form):
                    self.refused(self.argv(extra=extra), "%s given more than once" % flag)

    def test_add_empty_flag_refused(self):  # F3
        for flag in FLAG_NAMES + ("--cite",):
            with self.subTest(flag=flag):
                a = self.argv()
                a[a.index(flag) + 1] = ""
                self.refused(a, "%s: must not be empty" % flag)

    def test_add_unknown_flag_usage(self):  # F4
        for extra in (["--nonsuch", "x"], ["--overrides", "SD-R2"], ["--recommend", "a"], ["--c", "x"], ["stray"],
                      ["--cit"] if False else ["--source", "x"]):
            with self.subTest(extra=extra):
                self.usage(self.argv(extra=extra))

    def test_add_document_forms(self):  # F5
        for rel in ("a.md", "a b.md"):
            self.put(rel, "d\n")
        commit_all(self.root, "more docs")
        good = ["a.md", "a b.md", DOC]
        bad = {"a.MD": claims.DOC_ERR, "docs/a--b.md": claims.DOC_ERR, "docs/.md": claims.DOC_ERR,
               ".md": claims.DOC_ERR, "-a/b.md": claims.DASH_ERR, "a/-b.md": claims.DASH_ERR,
               "a-/b.md": claims.DASH_ERR, "a.md#x": "document: " + claims.PATH_ERR,
               "/a.md": "document: " + claims.PATH_ERR, "./a.md": "document: " + claims.PATH_ERR,
               "a//b.md": "document: " + claims.PATH_ERR, "docs/a.md/": "document: " + claims.PATH_ERR,
               "": "--document: must not be empty", "café.md": "U+00E9 is not allowed",
               "a\nb.md": "U+000A is not allowed", " a.md": "must not start or end with a space"}
        for doc in good:
            with self.subTest(good=doc):
                self.add(document=doc)
        for doc, needle in bad.items():
            with self.subTest(bad=doc):
                a = self.argv(document=doc)
                a[a.index("--document") + 1] = "--document=" + doc if doc.startswith("-") else doc
                if doc.startswith("-"):
                    a = ["add", "--document=" + doc] + a[3:]
                self.refused(a, needle)

    def test_add_untracked_document(self):  # F6 (D-Q6)
        self.put("docs/u.md", "u\n")
        self.refused(self.argv(document="docs/u.md"), "docs/u.md: is not a tracked file")
        os.unlink(os.path.join(self.root, DOC))
        self.refused(self.argv(), "docs/a.md: does not exist")
        os.symlink("src/x.py", os.path.join(self.root, DOC))
        self.refused(self.argv(), "docs/a.md: is not a regular file")

    def test_add_cite_forms(self):  # F7 (D-Q7)
        cid = self.add(cites=("src/x.py", "src/y.py:3", "src/x.py:1-2"))
        c = self.claim(cid)
        self.assertEqual([(x["path"], x.get("lines")) for x in c["cites"]],
                         [("src/x.py", None), ("src/y.py", "3"), ("src/x.py", "1-2")])
        self.refused(self.argv(cites=("src/x.py:1:2",)), "--cite: at most one ':'")
        self.refused(self.argv(cites=(":1",)), "--cite: the path must not be empty")
        self.refused(self.argv(cites=("src/x.py:",)), "--cite: the lines must not be empty")

    def test_add_cite_path_refused(self):  # F8
        os.symlink("x.py", os.path.join(self.root, "src", "link.py"))
        os.mkfifo(os.path.join(self.root, "src", "pipe"))
        for cite, needle in (("../x", "normalised"), ("/abs", "normalised"), ("a/./b", "normalised"),
                             ("a//b", "normalised"), ("x/", "normalised"), ("src/x.py#L1", "normalised"),
                             ("src", "is not tracked"), ("src/missing.py", "is not tracked"),
                             ("src/link.py", "is not tracked"), ("src/pipe", "is not tracked"),
                             ("src/café.py", "U+00E9 is not allowed")):
            with self.subTest(cite=cite):
                self.refused(self.argv(cites=(cite,)), needle)

    def test_add_cite_untracked(self):  # F8, D-Q8
        self.put("src/new.py", "n\n")
        self.refused(self.argv(cites=("src/new.py",)), "src/new.py: is not tracked")

    def test_add_cite_tracked_but_deleted(self):  # F8: tracked, gone from the work tree
        os.unlink(os.path.join(self.root, "src", "x.py"))
        self.refused(self.argv(), "src/x.py: has unstaged changes")

    def test_add_cite_lines_forms(self):  # F9
        nines = "9" * 4300
        good = ("1", "1-2", nines, nines + "9-" + nines + "9", "1-" + nines + "9")
        bad = ("0", "01", "2-1", "1-", "-1", "1-2-3", "1 ", "+1", "１", nines + "9-1")
        for lines in good:
            with self.subTest(good=lines[:12] + str(len(lines))):
                cid = self.add(cites=("src/x.py:" + lines,))
                self.assertEqual(self.claim(cid)["cites"][0]["lines"], lines)
        for lines in bad:
            with self.subTest(bad=lines[:12] + str(len(lines))):
                self.assertEqual(self.cli(*self.argv(cites=("src/x.py:" + lines,)))[0], 1)

    def test_digit_limits_same_on_both(self):  # X1, F9: no int() of argv text, the verdict is the same on both
        with open(os.path.join(REPO, "gates", "tools", "claims_cli.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("int", names)
        nines = "9" * 4301
        for flag in ("--text", "--direct", "--contradiction", "--by"):
            with self.subTest(flag=flag):
                a = self.argv()
                a[a.index(flag) + 1] = nines
                cid = None
                code, out, err = self.cli(*a)
                self.assertEqual((code, err), (0, ""))
                row = self.claim(out.strip())
                self.assertEqual(row[flag[2:]], nines)

    def test_add_two_cites(self):  # F10
        cid = self.add(cites=("src/x.py", "src/y.py"))
        c = self.claim(cid)
        self.assertEqual([x["path"] for x in c["cites"]], ["src/x.py", "src/y.py"])
        self.assertEqual([x["blob"] for x in c["cites"]], [blob(self.root, "src/x.py"), blob(self.root, "src/y.py")])
        cid = self.add(cites=("src/x.py:1", "src/x.py:1-2"))
        c = self.claim(cid)
        self.assertEqual(c["cites"][0]["blob"], c["cites"][1]["blob"])

    def test_add_duplicate_cite(self):  # F10 (D-Q9)
        self.refused(self.argv(cites=("src/x.py", "src/x.py")), "--cite: src/x.py given twice")
        self.refused(self.argv(cites=("src/x.py:1", "src/x.py:1")), "--cite: src/x.py:1 given twice")

    def test_add_text_character_classes(self):  # F12, F13 (D-Q5), X2
        ok = ["a: b", "a #b", "-x", "- x", "--", "-1", "null", "true", "9", "'q'", '"d"', "a\\b", "x" * 100000]
        for field in ("--text", "--direct", "--contradiction", "--by"):
            for value in ok:
                with self.subTest(field=field, ok=value[:12], n=len(value)):
                    a = self.argv()
                    i = a.index(field)
                    a[i:i + 2] = [field + "=" + value]
                    code, out, err = self.cli(*a)
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(self.claim(out.strip())[field[2:]], value)
            for value, cp in (("a\nb", "U+000A"), ("a\rb", "U+000D"), ("a\tb", "U+0009"), ("a\x00b", "U+0000"),
                              ("a\x7fb", "U+007F"), ("café", "U+00E9"), ("\U0001fae8", "U+1FAE8"),
                              ("ࡰ", "U+0870"), ("\ud800", "U+D800")):
                with self.subTest(field=field, bad=cp):
                    a = self.argv()
                    i = a.index(field)
                    a[i:i + 2] = [field + "=" + value]
                    self.refused(a, "%s: %s is not allowed" % (field, cp))
            for value in (" a", "a ", "  "):
                with self.subTest(field=field, space=repr(value)):
                    a = self.argv()
                    a[a.index(field) + 1] = value
                    self.refused(a, "%s: must not start or end with a space" % field)
            with self.subTest(field=field, form="-x as a separate argument"):
                a = self.argv()
                a[a.index(field) + 1] = "-x"
                self.usage(a)

    def test_unicode_version_independent(self):  # X2: no Unicode-data call decides a verdict in claims_cli
        with open(os.path.join(REPO, "gates", "tools", "claims_cli.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"lower", "upper", "isprintable", "isspace", "isdigit", "isalpha", "isalnum", "isnumeric",
                  "isdecimal", "casefold", "strip", "lstrip", "rstrip", "normalize", "category"}
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertEqual(used & banned, set())
        self.assertNotIn("unicodedata", {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
        for text in ("\U0001fae8", "ࡰ"):  # assigned in Unicode 15 and 14: the same refusal on every interpreter
            self.refused(self.argv(text=text), "--text: U+%04X is not allowed" % ord(text))

    def test_add_text_fuzz(self):  # PC2 fuzz: each value is written as given, or refused naming its first bad code point
        alphabet = ["\n", "\r", "\t", " ", "-", ":", "#", '"', "'", "a", "b", "Z", "7", "é", "\U0001fae8"]
        rng = random.Random(20261118)
        for n in range(30):
            value = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
            with self.subTest(n=n, value=ascii(value)):
                bad = [c for c in value if not 0x20 <= ord(c) <= 0x7E]
                code, out, err = self.cli("add", "--document", DOC, "--text=" + value, "--cite", "src/x.py",
                                          "--direct", "D", "--contradiction", "C", "--by", "me")
                if bad:
                    self.assertEqual(code, 1)
                    self.assertIn("--text: U+%04X is not allowed" % ord(bad[0]), err)
                elif value[0] == " " or value[-1] == " ":
                    self.assertEqual(code, 1)
                    self.assertIn("--text: must not start or end with a space", err)
                else:
                    self.assertEqual((code, err), (0, ""))
                    self.assertEqual(yamlsub.parse(yamlsub.emit({"t": self.claim(out.strip())["text"]}))["t"], value)
                    self.assertEqual(self.claim(out.strip())["text"], value)


# ---------------------------------------------------------------- Producer 3: add effect (W1-W14)

class AddEffectTests(Base):
    def test_add_writes_fresh_claim(self):  # W1
        cid = self.add()
        self.assertEqual(ids.id_problem(cid, "C"), "")
        rel = "%s/docs--a.yml" % CLAIMS
        row = self.load()[rel]
        self.assertEqual(row, {"schema": ctag(), "document": DOC, "claims": [
            {"id": cid, "text": "T", "cites": [{"path": "src/x.py", "blob": blob(self.root, "src/x.py")}],
             "direct": "D", "contradiction": "C", "by": "me"}]})
        self.assertEqual(claims.validate(row, self.cfg()), [])
        res = gate_claims.check(["--root", self.root])
        self.assertTrue(res.ok(), res.render(False))

    def test_add_subprocess_production_path(self):  # W1 through python3 -m gates
        code, out, err = self.sub(*(["claims"] + self.argv() + ["--root", self.root]))
        self.assertEqual((code, err), (0, ""))
        cid = out.splitlines()[-1]
        self.assertEqual(ids.id_problem(cid, "C"), "")
        self.assertEqual(self.claim(cid)["cites"][0]["blob"], blob(self.root, "src/x.py"))

    def test_add_output_shape(self):  # W2, V-10 (D-Q12)
        code, out, err = self.cli(*self.argv())
        self.assertEqual((code, err), (0, ""))
        self.assertRegex(out, r"\AC-[0-9]{8}-[a-z2-9]{4}\n\Z")

    def test_add_appends_to_existing_file(self):  # W3
        a = self.add(text="first")
        rel = "%s/docs--a.yml" % CLAIMS
        with open(os.path.join(self.root, rel), "rb") as fh:
            first = fh.read()
        b = self.add(text="second", cites=("src/y.py:2",))
        c = self.add(text="third")
        rows = self.load()[rel]["claims"]
        self.assertEqual([x["id"] for x in rows], [a, b, c])
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual([x["text"] for x in rows], ["first", "second", "third"])
        self.assertEqual(yamlsub.parse(first.decode())["claims"][0], rows[0])
        self.assertEqual(claims.validate(self.load()[rel], self.cfg()), [])

    def claim_file(self, name="docs--a.yml", data="", sub=CLAIMS):
        p = os.path.join(self.root, *sub.split("/"), name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        return p

    def good_row(self, cid="C-20260101-a2b3", doc=DOC):
        return {"schema": ctag(), "document": doc, "claims": [
            {"id": cid, "text": "T", "cites": [{"path": "src/x.py", "blob": blob(self.root, "src/x.py")}],
             "direct": "D", "contradiction": "C", "by": "me"}]}

    def test_add_refuses_bad_existing_file(self):  # W4, D-Q14
        bad_rows = {"malformed": "key: [\n", "list": "- a\n", "schema": yamlsub.emit(dict(self.good_row(), claims=[])),
                    "name": yamlsub.emit(self.good_row(doc="docs/b.md"))}
        for name, data in bad_rows.items():
            with self.subTest(kind=name):
                p = self.claim_file(data=data)
                self.refused(self.argv(), "")
                os.unlink(p)
        with self.subTest(kind="other file bad"):  # a validation error in another document's file blocks too
            self.claim_file("docs--zz.yml", "- a\n")
            self.refused(self.argv(), "docs--zz.yml")
        with self.subTest(kind="stray entry"):
            self.claim_file("docs--zz.yml", yamlsub.emit(self.good_row(doc="docs/zz.md")))
            self.claim_file("notes.txt", "x")
            self.refused(self.argv(), "notes.txt")
            os.unlink(os.path.join(self.root, CLAIMS, "notes.txt"))
        with self.subTest(kind="duplicate id"):
            self.claim_file("docs--b.yml", yamlsub.emit(self.good_row(doc="docs/b.md")))
            self.claim_file("docs--c.yml", yamlsub.emit(self.good_row(doc="docs/c.md")))
            self.refused(self.argv(), "duplicate.C-20260101-a2b3")

    def test_add_refuses_noncanonical_file(self):  # W3, D-Q13
        self.claim_file(data="# a hand comment\n" + yamlsub.emit(self.good_row()))
        self.refused(self.argv(), "docs--a.yml: not in canonical form; rewrite it with the claims tool")

    def test_add_claims_directory_missing(self):  # W5 (D-Q15)
        self.assertFalse(os.path.exists(os.path.join(self.root, CLAIMS)))
        self.add()
        self.assertTrue(os.path.isfile(os.path.join(self.root, CLAIMS, "docs--a.yml")))

    def test_add_claims_directory_not_a_directory(self):  # W5
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"), exist_ok=True)
        p = os.path.join(self.root, CLAIMS)
        with open(p, "w") as fh:
            fh.write("x")
        self.refused(self.argv(), "%s: is not a directory" % CLAIMS)
        os.unlink(p)
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), p)
        self.refused(self.argv(), "%s: is a symlink; the claims directory must be a real directory" % CLAIMS)

    def test_add_claims_directory_unwritable(self):  # W5, W12
        os.makedirs(os.path.join(self.root, CLAIMS))
        os.chmod(os.path.join(self.root, CLAIMS), 0o500)
        self.addCleanup(os.chmod, os.path.join(self.root, CLAIMS), 0o700)
        if os.access(os.path.join(self.root, CLAIMS), os.W_OK):
            self.skipTest("the directory stays writable (running as root)")
        before = self.snap()
        code, out, err = self.cli(*self.argv())
        self.assertEqual((code, out), (1, ""))
        self.assertIn("cannot create", err)
        self.assertEqual(self.snap(), before)

    def test_add_custom_claims_path(self):  # W6
        cfg = dict(minimal_config(), paths={"claims": "other/claims"})
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        commit_all(self.root, "cfg")
        cid = self.add()
        self.assertTrue(os.path.isfile(os.path.join(self.root, "other", "claims", "docs--a.yml")))
        self.assertFalse(os.path.exists(os.path.join(self.root, CLAIMS)))
        self.assertEqual(self.claim(cid, "other/claims/docs--a.yml")["id"], cid)

    def test_add_mint_is_systemrandom(self):  # W7
        self.assertIs(type(claims_cli._rng), random.SystemRandom)
        with mock.patch.object(claims_cli, "_rng", Seq("a2b3")), \
                mock.patch.object(ids, "utc_today", return_value=__import__("datetime").date(2026, 12, 31)):
            self.assertEqual(self.add(), "C-%s-a2b3" % DAY)

    def test_add_id_date_is_utc(self):  # W7: the date is ids.utc_today()'s
        import datetime
        for day in (datetime.date(2026, 12, 31), datetime.date(2027, 1, 1)):
            with self.subTest(day=day.isoformat()), mock.patch.object(ids, "utc_today", return_value=day):
                self.assertTrue(self.add().startswith("C-%04d%02d%02d-" % (day.year, day.month, day.day)))

    def test_add_mint_collision_redraws(self):  # W8, W9
        import datetime
        day = datetime.date(2026, 12, 31)
        self.put("docs/b.md", "b\n")
        commit_all(self.root, "b")
        existing = "C-%s-aaaa" % DAY
        with mock.patch.object(ids, "utc_today", return_value=day):
            with mock.patch.object(claims_cli, "_rng", Seq("aaaa")):
                self.assertEqual(self.add(document="docs/b.md"), existing)
            with mock.patch.object(claims_cli, "_rng", Seq("aaaabbbb")):  # first draw collides in another file
                self.assertEqual(self.add(), "C-%s-bbbb" % DAY)
        # an unloadable decision register blocks the add (D-Q16)
        os.makedirs(os.path.join(self.root, DEC))
        with open(os.path.join(self.root, DEC, "DEC-%s-cccc.yml" % DAY), "w") as fh:
            fh.write("key: [\n")
        self.refused(self.argv(), "")

    def test_add_mint_exhausted(self):  # W9
        import datetime
        day = datetime.date(2026, 12, 31)
        self.put("docs/b.md", "b\n")
        commit_all(self.root, "b")
        with mock.patch.object(ids, "utc_today", return_value=day):
            with mock.patch.object(claims_cli, "_rng", Seq("aaaa")):
                self.add(document="docs/b.md")
            with mock.patch.object(ids, "_SUFFIX_COUNT", 1):
                self.refused(self.argv(), "no free id: all 1 suffixes of C on 20261231 are taken")

    def test_add_blob_matches_git_add(self):  # W10
        git(self.root, "config", "core.autocrlf", "true")
        self.put("src/crlf.txt", "a\r\nb\r\n")
        self.put("src/empty.txt", "")
        with open(os.path.join(self.root, "src", "bin.dat"), "wb") as fh:
            fh.write(b"\x00\x01\x02\xff")
        commit_all(self.root, "conv")
        for rel in ("src/crlf.txt", "src/empty.txt", "src/bin.dat", "src/x.py"):
            with self.subTest(rel=rel):
                idx = os.path.join(self.tmp, "idx-" + os.path.basename(rel))
                env = {"GIT_INDEX_FILE": idx}
                git(self.root, "read-tree", "HEAD", env=env)
                git(self.root, "add", "--", rel, env=env)
                want = git(self.root, "ls-files", "-s", "--", rel, env=env).split()[1]
                cid = self.add(cites=(rel,))
                got = self.claim(cid)["cites"][0]["blob"]
                self.assertEqual(got, want)
                self.assertRegex(got, r"\A[0-9a-f]{40}\Z")
        self.assertTrue(gate_claims.check(["--root", self.root]).ok())

    def test_add_cited_file_unstaged(self):  # W11 (D-Q17, D-Q23)
        self.put("src/x.py", "changed\n")
        self.refused(self.argv(), "src/x.py: has unstaged changes")
        self.refused(self.argv(cites=("src/y.py", "src/x.py")), "src/x.py: has unstaged changes")
        git(self.root, "add", "src/x.py")
        self.add()  # staged: accepted
        git(self.root, "update-index", "--assume-unchanged", "src/y.py")
        self.refused(self.argv(cites=("src/y.py",)), "src/y.py: is flagged assume-unchanged or skip-worktree")
        git(self.root, "update-index", "--no-assume-unchanged", "src/y.py")
        git(self.root, "update-index", "--skip-worktree", "src/y.py")
        self.refused(self.argv(cites=("src/y.py",)), "src/y.py: is flagged assume-unchanged or skip-worktree")

    def test_add_failure_leaves_no_partial_file(self):  # W12 (patched fsync and replace)
        for existing in (False, True):
            if existing:
                self.add()
            rel = "%s/docs--a.yml" % CLAIMS
            for what, kw in (("fsync", dict(target=os, attr="fsync", side=OSError(5, "io"))),
                             ("fsync-interrupt", dict(target=os, attr="fsync", side=KeyboardInterrupt())),
                             ("replace", dict(target=os, attr="replace", side=OSError(5, "io")))):
                if what == "replace" and not existing:
                    continue
                with self.subTest(existing=existing, what=what):
                    before = self.snap()
                    with mock.patch.object(kw["target"], kw["attr"], side_effect=kw["side"]):
                        if isinstance(kw["side"], KeyboardInterrupt):
                            with self.assertRaises(KeyboardInterrupt):
                                self.cli(*self.argv())
                        else:
                            code, out, err = self.cli(*self.argv())
                            self.assertEqual((code, out), (1, ""))
                            self.assertIn(rel, err)
                    after = self.snap()
                    self.assertEqual({k: v for k, v in after.items() if v is not None},
                                     {k: v for k, v in before.items() if v is not None})
                    self.assertEqual([k for k in after if k.endswith(".tmp")], [])

    def test_add_validates_whole_file(self):  # W13
        cid = self.add()
        files = claims.load(self.root, self.cfg())
        self.assertEqual(claims.file_errors(files, "C"), [])
        self.assertEqual(claims.document_errors(files[0], gitinfo.tracked_files(self.root)), [])
        self.assertEqual(claims.validate(files[0].row, self.cfg()), [])
        self.refused(self.argv(cites=("src/x.py:2-1",)), claims.LINES_ERR)
        self.assertEqual(self.claim(cid)["id"], cid)

    def test_add_writes_only_the_claim_file(self):  # W14
        before = set(self.snap())
        self.add()
        new = set(self.snap()) - before
        self.assertEqual({n for n in new if not n.endswith("claims") and not n.endswith("state")},
                         {"%s/docs--a.yml" % CLAIMS})

    def test_add_then_gates_pass(self):  # I3
        self.add()
        for gate in ("claims", "schema", "register"):
            with self.subTest(gate=gate):
                code, out, err = self.sub("check", gate)
                self.assertEqual(code, 0, out + err)
        code, out, err = self.sub("check", "claims")
        for cat in ("schema", "store", "document", "stale", "base"):
            self.assertIn("PASS claims." + cat, out)
        code, out, err = self.sub("run_all")
        self.assertEqual(code, 0, out + err)

    def test_add_default_root(self):  # I4
        sub = os.path.join(self.root, "src")
        code, out, err = self.sub(*(["claims"] + self.argv()), cwd=sub)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(os.path.isfile(os.path.join(self.root, CLAIMS, "docs--a.yml")))


# ---------------------------------------------------------------- Producer 4: verify (V-1 .. V-13)

class VerifyTests(Base):
    def setUp(self):
        super().setUp()
        self.cid = self.add(cites=("src/x.py", "src/y.py"))
        commit_all(self.root, "claim")

    def edit_and_stage(self, rel="src/x.py", data="x = 2\n"):
        self.put(rel, data)
        git(self.root, "add", "--", rel)

    def file_bytes(self):
        with open(os.path.join(self.root, CLAIMS, "docs--a.yml"), "rb") as fh:
            return fh.read()

    def test_verify_flags(self):  # V-1
        self.refused(["verify", "--by", "me"], "ID is required")
        self.refused(["verify", self.cid], "--by is required")
        self.refused(["verify"], "ID is required")
        self.refused(["verify", self.cid, "--by", "me", "--by", "you"], "--by given more than once")
        self.refused(["verify", self.cid, "--by", ""], "--by: must not be empty")
        self.refused(["verify", self.cid, "--by", "me", "--root", self.root, "--root", self.root],
                     "--root given more than once", root=False)
        self.usage(["verify", self.cid, "other", "--by", "me"])
        self.usage(["verify", self.cid, "--by", "me", "--document", DOC])
        self.usage(["verify", self.cid, "--by", "me", "--text", "x"])

    def test_verify_unknown_id_refused(self):  # V-2
        self.refused(["verify", "C-20260101-a2b3", "--by", "me"], "C-20260101-a2b3: no such claim")

    def test_verify_malformed_id_refused(self):  # V-2
        for bad in ("C-1", "C-20261031-ABCD", "c-20261031-a2b3", "C-20260230-a2b3", "DEC-20261031-a2b3",
                    "F-20261031-a2b3", "C-20261031-a2b3x", "C-" + "9" * 4301):
            with self.subTest(id=bad[:20]):
                self.refused(["verify", bad, "--by", "me"], "ID: ")
        self.refused(["verify", "", "--by", "me"], "ID: must not be empty")
        self.refused(["verify", "C-20261031-café", "--by", "me"], "ID: U+00E9 is not allowed")
        self.usage(["verify", "-x", "--by", "me"])

    def test_verify_rerecords_blob(self):  # V-3
        self.edit_and_stage()
        before = self.load()["%s/docs--a.yml" % CLAIMS]
        code, out, err = self.verify(self.cid, "other")
        self.assertEqual((code, out, err), (0, self.cid + "\n", ""))
        row = self.load()["%s/docs--a.yml" % CLAIMS]
        want = dict(before["claims"][0], by="other")
        want["cites"] = [dict(before["claims"][0]["cites"][0], blob=blob(self.root, "src/x.py")),
                         before["claims"][0]["cites"][1]]
        self.assertEqual(row, dict(before, claims=[want]))
        self.assertEqual(list(row["claims"][0]), list(before["claims"][0]))
        self.assertEqual(claims.validate(row, self.cfg()), [])
        self.assertTrue(gate_claims.check(["--root", self.root]).ok())

    def test_verify_refuses_unstaged_cited_file(self):  # V-4, I2
        self.put("src/x.py", "x = 3\n")
        before = self.file_bytes()
        self.put("src/y.py", "y = 3\n")
        err = self.refused(["verify", self.cid, "--by", "me"], "src/x.py, src/y.py: has unstaged changes")
        self.assertEqual(self.file_bytes(), before)
        git(self.root, "add", "src/x.py")  # modified then staged passes for that path; y still refuses
        self.refused(["verify", self.cid, "--by", "me"], "src/y.py: has unstaged changes")
        os.unlink(os.path.join(self.root, "src", "y.py"))  # deleted and unstaged
        self.refused(["verify", self.cid, "--by", "me"], "src/y.py: has unstaged changes")
        git(self.root, "checkout", "--", "src/y.py")
        git(self.root, "add", "-N", "src/y.py")  # intent-to-add of a tracked file lists nothing: staged clean
        self.assertEqual(self.verify(self.cid)[0], 0)

    def test_verify_ignores_unrelated_unstaged_file(self):  # V-5
        self.put("docs/a.md", "changed doc\n")
        self.assertEqual(self.verify(self.cid)[0], 0)

    def test_verify_flagged_cited_path(self):  # V-6 (D-Q23)
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                git(self.root, "update-index", flag, "src/y.py")
                self.refused(["verify", self.cid, "--by", "me"], "src/y.py: is flagged assume-unchanged")
                git(self.root, "update-index", "--no-" + flag[2:], "src/y.py")

    def test_verify_cited_path_states(self):  # V-7 (D-Q8)
        git(self.root, "rm", "-q", "--cached", "src/y.py")
        self.refused(["verify", self.cid, "--by", "me"], "src/y.py: is not tracked")

    def test_verify_idempotent(self):  # V-8 (D-Q24)
        before = self.file_bytes()
        mtime = os.stat(os.path.join(self.root, CLAIMS, "docs--a.yml")).st_mtime_ns
        code, out, err = self.verify(self.cid)
        self.assertEqual((code, out, err), (0, self.cid + "\n", ""))
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(os.stat(os.path.join(self.root, CLAIMS, "docs--a.yml")).st_mtime_ns, mtime)

    def test_verify_by(self):  # V-9 (D-Q25)
        self.assertEqual(self.verify(self.cid, "someone")[0], 0)
        self.assertEqual(self.claim(self.cid)["by"], "someone")
        self.refused(["verify", self.cid, "--by", "café"], "--by: U+00E9 is not allowed")

    def test_verify_output_shape(self):  # V-10 (D-Q12)
        self.assertEqual(self.verify(self.cid), (0, self.cid + "\n", ""))

    def test_verify_validates_before_write(self):  # V-11
        self.edit_and_stage()
        before = self.file_bytes()
        with mock.patch.object(claims, "validate", side_effect=[[], ["claims.0: boom"]]):
            self.refused(["verify", self.cid, "--by", "me"], "claims.0: boom")
        self.assertEqual(self.file_bytes(), before)

    def test_verify_failure_leaves_no_partial_file(self):  # V-11, W12
        self.edit_and_stage()
        before = self.snap()
        for side in (OSError(5, "io"),):
            with mock.patch.object(os, "replace", side_effect=side):
                code, out, err = self.verify(self.cid)
            self.assertEqual((code, out), (1, ""))
        with mock.patch.object(os, "fsync", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.verify(self.cid)
        self.assertEqual({k: v for k, v in self.snap().items() if v is not None},
                         {k: v for k, v in before.items() if v is not None})

    def test_verify_register_states(self):  # V-12
        import shutil
        shutil.rmtree(os.path.join(self.root, CLAIMS))
        self.refused(["verify", self.cid, "--by", "me"], "%s: no such claim" % self.cid)
        os.makedirs(os.path.join(self.root, CLAIMS))
        with open(os.path.join(self.root, CLAIMS, "docs--a.yml"), "w") as fh:
            fh.write("key: [\n")
        self.refused(["verify", self.cid, "--by", "me"], "")

    def test_verify_duplicate_id_refused(self):  # D-Q22: an id in two files is a load error, so nothing is verified
        row = yamlsub.parse(self.file_bytes().decode())
        other = dict(row, document="docs/b.md")
        p = os.path.join(self.root, CLAIMS, "docs--b.yml")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(yamlsub.emit(other))
        before = self.snap()
        self.refused(["verify", self.cid, "--by", "me"], "duplicate.%s" % self.cid)
        self.assertEqual(self.snap(), before)
        os.unlink(p)
        with open(os.path.join(self.root, CLAIMS, "docs--zz.yml"), "w", encoding="utf-8", newline="") as fh:
            fh.write(yamlsub.emit(row))  # the file name differs from the slug of its document
        self.refused(["verify", self.cid, "--by", "me"], "name.%s/docs--zz.yml" % CLAIMS)

    def test_verify_never_runs_claim_commands(self):  # V-13: git is the only process the tool starts
        started = []
        real = subprocess.Popen

        def spy(args, *a, **kw):
            started.append(args[0] if isinstance(args, (list, tuple)) else args)
            return real(args, *a, **kw)

        self.edit_and_stage()
        with mock.patch.object(subprocess, "Popen", spy):
            self.assertEqual(self.verify(self.cid)[0], 0)
            self.assertEqual(self.cli(*self.argv(direct="touch /tmp/never", contradiction="touch /tmp/never"))[0], 0)
        self.assertTrue(started)
        self.assertEqual(set(started), {"git"})

    def test_change_and_verify_in_one_commit(self):  # F-B2p-1, I1: edit, git add, verify, commit through the hook
        bin_dir = os.path.join(self.tmp, "bin")
        os.mkdir(bin_dir)
        os.symlink(sys.executable, os.path.join(bin_dir, "python3"))
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), commands={"test": "true"}))
        commit_all(self.root, "config with a test command")
        self.assertEqual(githooks.install(self.root, REPO), [])
        self.edit_and_stage()
        self.assertEqual(self.verify(self.cid)[0], 0)
        git(self.root, "add", "--", CLAIMS)
        env = dict(os.environ, LC_ALL="C", PATH=bin_dir + os.pathsep + os.environ["PATH"])
        for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            env[k] = "Fixture"
        p = subprocess.run(["git", "-C", self.root, "commit", "-q", "-m", "change"], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        self.assertEqual(git(self.root, "ls-tree", "HEAD", "--", "src/x.py").split()[2], blob(self.root, "src/x.py"))
        code, out, err = self.sub("check", "claims")
        self.assertEqual(code, 0, out + err)
        self.assertIn("PASS claims.stale", out)


if __name__ == "__main__":
    unittest.main()
