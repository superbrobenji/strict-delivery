"""Tests of gates/gate_evidence.py through ``gate_evidence.main`` on real fixture repositories (Task 6E.2 input-domain
table: producers 1-11 and version rows V1-V7, controller decisions D-2-Q1..Q21). Every test names its table rows in its
docstring ("Rows: ..."). Expected lines are written by hand from the fixture text; the 200-fixture generator computes its
expected lines with a model of its own that never imports ``gates.lib.evidence``."""
import builtins
import contextlib
import io
import json
import os
import random
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_evidence, producers, run_all
from gates.lib import gitinfo, ids, schema
from tests.helpers import (E128, INT_LIMITS, TOP, GitIsolatedTestCase, commit_all, git, int_limit, make_repo)
from gates.lib.yamlsub import emit
from tests.tipkinds import BAD_KINDS, refusal, set_entry

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FS = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
FTAG = "%s/%d" % (_FS.kind, _FS.version)
TTAG = "<!-- schema: mutation-transcript/1 -->"
RTAG = "<!-- schema: review-report/1 -->"
PS = ".strict-delivery/state/plans"
FIND = ".strict-delivery/state/findings"
REV = "docs/strict-delivery/reviews"
TDIR = PS + "/p/mutations"
F = "F-20261031-k3f9"
F2 = "F-20261031-m4n5"
F3 = "F-20261031-p6q7"
D = "sh check.sh t"
SHA = "a1b2c3d"
CHECK = "grep -q fixed fix.txt\n"
GOOD_RUNS = ((1, "fix", 0), (2, "mutant", 1), (3, "fix", 0))
PATHS_OF = {"open": ["open"], "planned": ["open", "planned"], "in-progress": ["open", "planned", "in-progress"],
            "fixed-unpinned": ["open", "planned", "in-progress", "fixed-unpinned"],
            "pinned": ["open", "planned", "in-progress", "pinned"], "deferred": ["open", "deferred"],
            "closed": ["open", "closed"], "merged": ["open", "planned", "in-progress", "pinned", "merged"]}
UEXC = "ࡰ"  # Cn on Unicode 13 (3.9), Lo on 3.13
U2C2F = "Ⱟ"  # Cn on 3.9, Lu on 3.13: lower() differs


def hist(*statuses):
    return [{"status": s, "sha": SHA, "by": "agent"} for s in statuses]


def frow(id_, status="pinned", **kw):
    r = {"schema": FTAG, "id": id_, "status": status, "source": "review", "severity": "HIGH", "class": "bug",
         "siblings": [], "cites": [{"file": "src/x.py", "lines": "1-2", "sha": SHA}], "repro": None,
         "owner": {"kind": "plan", "plan": "p", "task": "1a.2"}, "pin": None, "ruling": None, "evidence": [],
         "history": hist(*PATHS_OF[status])}
    if status in ("closed", "merged"):
        r.update(resolved_by="p")
    r.update(kw)
    return {k: v for k, v in r.items() if v is not ...}


def T(fid=F, test="t", cmd=D, runs=GOOD_RUNS, mutant="revert", tag=TTAG, extra=()):
    lines = [tag, "FINDING " + fid, "TEST " + test, "MUTANT " + mutant]
    lines += ["RUN %d %s exit=%d command=%s" % (n, ph, ex, cmd) for n, ph, ex in runs]
    return "\n".join(lines + list(extra)) + "\n"


def RP(fid, transcript, test="t", cmd=D, tag=RTAG, extra=()):
    lines = [tag, "review prose", "PIN %s transcript=%s" % (fid, transcript), "PIN-TEST %s %s" % (fid, test),
             "PIN-COMMAND %s %s" % (fid, cmd)]
    return "\n".join(lines + list(extra)) + "\n"


class Info:
    def __init__(self, tsha, rsha, tpath, rpath):
        self.tsha, self.rsha, self.tpath, self.rpath = tsha, rsha, tpath, rpath
        self.transcript = "%s:%s" % (tsha, tpath)
        self.entry = "%s:%s" % (rsha, rpath)


def run_argv(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate_evidence.main(argv)
    return out.getvalue(), code


def line(out, ident):
    """The whole line of ``evidence.<ident>``, or None."""
    for ln in out.splitlines():
        if ln.startswith("PASS evidence.%s" % ident) and ln == "PASS evidence.%s" % ident:
            return ln
        if ln.startswith("FAIL evidence.%s: " % ident):
            return ln
    return None


def ok(out, ident):
    return line(out, ident) == "PASS evidence." + ident


def bad(out, ident):
    ln = line(out, ident)
    return ln is not None and ln.startswith("FAIL")


def idsof(out):
    return [ln.split(" ", 2)[1].split(":")[0][len("evidence."):] for ln in out.splitlines()]


class Base(GitIsolatedTestCase):
    def cfg(self, profile="strict", **extra):
        c = {"schema": "config/2", "framework_version": "0.0.0", "profile": profile,
             "commands": {"test_one": "sh check.sh {id}"}}
        c.update(extra)
        return c

    def put(self, rel, data):
        path = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def make(self, profile="strict", **extra):
        root = make_repo(self.work, self.cfg(profile, **extra))
        self.put("check.sh", CHECK)
        self.put("fix.txt", "fixed\n")
        self.put("src/x.py", "x\n")
        commit_all(root, "base")
        return root

    def set_config(self, profile="strict", **extra):
        with open(os.path.join(self.work, ".strict-delivery/config.yml"), "w", encoding="utf-8") as fh:
            fh.write(emit(self.cfg(profile, **extra)))

    def pin(self, fid=F, test="t", *, cmd=D, runs=GOOD_RUNS, ttext=None, tpath=None, rtext=None, rpath=None, pkg=None,
            status="pinned", ev=None, pin_t=None, commit=True, pin_test=None, mutant="revert", **rowkw):
        tpath = tpath or "%s/%s.md" % (TDIR, fid)
        rpath = rpath or "%s/p/%s.md" % (REV, fid)
        self.put(tpath, ttext if ttext is not None else T(fid, test, cmd, runs, mutant))
        tsha = commit_all(self.work, "transcript " + fid)
        vals = {"transcript": "%s:%s" % (tsha, tpath), "test": test, "command": cmd}
        vals.update(pkg or {})
        if rtext is None:
            rtext = RP(fid, vals["transcript"], vals["test"], vals["command"])
        elif callable(rtext):
            rtext = rtext(tsha)
        self.put(rpath, rtext)
        rsha = commit_all(self.work, "report " + fid)
        info = Info(tsha, rsha, tpath, rpath)
        pin = {"test": pin_test if pin_test is not None else test, "transcript": pin_t or info.transcript}
        row = frow(fid, status, pin=pin, evidence=ev(info) if ev else [info.entry], **rowkw)
        self.put("%s/%s.yml" % (FIND, fid), emit(row))
        if commit:
            commit_all(self.work, "finding " + fid)
        return info

    def fresh(self):
        self.work = os.path.join(self.tmp, "w%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def run_(self, *args, root=None):
        return run_argv(["--root", root or self.work] + list(args))

    def input_fail(self, out, code, needle=""):
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertTrue(out.startswith("FAIL evidence.input: "), out)
        self.assertIn(needle, out)

    def standard_branch(self, profile="standard"):
        git(self.work, "checkout", "-q", "-b", "feat")

    def valid_ids(self, fid=F):
        return ["config", "scope", "package." + fid, "transcript." + fid, "rerun." + fid]


# ======================================================================== producer 9, 1: the whole path
class StrictPath(Base):
    def test_strict_valid_pin_passes(self):
        """Rows: G1 T1 R1 O1 O6 S1 S4. The plan test, with literal expected text."""
        self.make()
        self.pin()
        out, code = self.run_()
        self.assertEqual(out, "PASS evidence.config\nPASS evidence.scope\nPASS evidence.package.%s\n"
                              "PASS evidence.transcript.%s\nPASS evidence.rerun.%s\n" % (F, F, F))
        self.assertEqual(code, 0)

    def test_rerun_fails_on_broken_tree(self):
        """Rows: R2 O6."""
        self.make()
        self.pin()
        self.put("fix.txt", "broken\n")
        out, code = self.run_()
        self.assertIn("FAIL evidence.rerun.%s: sh check.sh t: exit 1\n" % F, out)
        self.assertTrue(ok(out, "package." + F) and ok(out, "transcript." + F))
        self.assertEqual(code, 1)

    def test_transcript_with_passing_mutant_fails(self):
        """Rows: T8 T9."""
        self.make()
        self.pin(runs=((1, "fix", 0), (2, "mutant", 0), (3, "fix", 0)))
        out, code = self.run_()
        self.assertTrue(bad(out, "transcript." + F), out)
        self.assertIn("RUN 2: exit 0", out)
        self.assertEqual(code, 1)

    def test_nested_transcript_refused(self):
        """Rows: T2."""
        self.make()
        self.pin(tpath=TDIR + "/d/t.md")
        out, code = self.run_()
        self.assertTrue(bad(out, "transcript." + F), out)
        self.assertIn("mutations/", line(out, "transcript." + F))
        self.assertEqual(code, 1)

    def test_package_command_mismatch_fails(self):
        """Rows: G12 G15 (one cause, two lines, D-2-Q12)."""
        self.make()
        self.pin(pkg={"command": D + " "})
        out, code = self.run_()
        self.assertTrue(bad(out, "package." + F))
        self.assertIn("command", line(out, "package." + F))
        self.assertTrue(bad(out, "transcript." + F))
        self.assertIn("command", line(out, "transcript." + F))
        self.assertTrue(ok(out, "rerun." + F))

    def test_changed_test_one(self):
        """Rows: T11 D-2-Q21 (Q-B6plan-4 (b)): after test_one changes, package and transcript still pass and the re-run
        decides (it passes with the new command here, fails with a failing one)."""
        self.make()
        self.pin()
        self.set_config(commands={"test_one": "sh check.sh --new {id}"})
        out, _ = self.run_()
        self.assertTrue(ok(out, "package." + F) and ok(out, "transcript." + F), out)
        self.assertTrue(ok(out, "rerun." + F), out)  # the new command passes: the re-run decides
        self.set_config(commands={"test_one": "exit 1 # {id}"})
        out, code = self.run_()
        self.assertTrue(ok(out, "package." + F) and ok(out, "transcript." + F), out)
        self.assertIn("FAIL evidence.rerun.%s: exit 1 # t: exit 1\n" % F, out)
        self.assertEqual(code, 1)

    def test_light_not_run(self):
        """Rows: P1 S1."""
        self.make("light")
        self.pin()
        out, code = self.run_()
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
        self.assertEqual(code, 0)

    def test_empty_register_passes(self):
        """Rows: I4 S2 (never an empty run) K1."""
        for prof in ("light", "standard", "strict"):
            with self.subTest(prof):
                self.fresh()
                self.make(prof)
                out, code = self.run_()
                self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
                self.assertEqual(code, 0)

    def fresh(self):
        self.work = os.path.join(self.tmp, "w%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def test_produces_both_kinds(self):
        """Rows: X1."""
        self.assertEqual(gate_evidence.PRODUCES, ("mutation-transcript", "review-report"))


# ======================================================================== producer 3: scope
class Scope(Base):
    def standard_pair(self):
        """F2 pinned and committed on main (unchanged on the branch); then a branch."""
        self.make("standard")
        self.pin(F2)
        self.standard_branch()

    def test_standard_skips_unchanged_rows(self):
        """Rows: P2 P6 (a run on the base branch checks none)."""
        self.make("standard")
        self.pin()
        self.put("fix.txt", "broken\n")
        out, code = self.run_()  # on main: every row is unchanged vs the merge base (HEAD)
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
        self.assertEqual(code, 0)
        self.standard_branch()
        out, code = self.run_()
        self.assertIsNone(line(out, "rerun." + F))
        self.assertEqual(code, 0)

    def test_standard_checks_new_row(self):
        """Rows: P3 P4 test_standard_checks_changed_rows."""
        self.standard_pair()
        self.pin(F)
        self.put("fix.txt", "broken\n")
        out, code = self.run_()
        self.assertTrue(bad(out, "rerun." + F), out)
        self.assertEqual(idsof(out), self.valid_ids(F))  # F2 is unchanged on the branch: no line at all
        self.assertEqual(code, 1)

    def test_standard_checks_changed_row(self):
        """Rows: P4 (a committed change), P5 (working tree edit, untracked, staged only)."""
        self.standard_pair()
        for how in ("commit", "edit", "staged"):
            with self.subTest(how):
                path = "%s/%s.yml" % (FIND, F2)
                full = os.path.join(self.work, path)
                with open(full, encoding="utf-8") as fh:
                    orig = fh.read()
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(orig.replace("severity: HIGH", "severity: LOW"))
                if how == "commit":
                    commit_all(self.work, "change")
                if how == "staged":
                    git(self.work, "add", path)
                out, code = self.run_()
                self.assertEqual(idsof(out), self.valid_ids(F2), out)
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(orig)
                git(self.work, "add", "-A")
                if how == "commit":
                    git(self.work, "commit", "-q", "-m", "undo")  # back to the merge base's text
                    git(self.work, "reset", "-q", "--hard", "HEAD")
                    # a revert leaves F2 equal to the merge base: out of scope again
                    out, _ = self.run_()
                    self.assertEqual(idsof(out), ["config", "scope"])
                git(self.work, "reset", "-q")

    def test_standard_rename_is_changed(self):
        """Rows: P7 (a renamed record file is new)."""
        self.standard_pair()
        old = os.path.join(self.work, FIND, F2 + ".yml")
        with open(old, encoding="utf-8") as fh:
            text = fh.read()
        git(self.work, "mv", "%s/%s.yml" % (FIND, F2), "%s/%s.yml" % (FIND, F3))
        with open(os.path.join(self.work, FIND, F3 + ".yml"), "w", encoding="utf-8") as fh:
            fh.write(text.replace(F2, F3, 1))  # same row text, new id and file: new at the merge base
        commit_all(self.work, "rename")
        out, code = self.run_()
        self.assertTrue(line(out, "package." + F3) is not None and line(out, "package." + F2) is None, out)

    def test_standard_base_forms(self):
        """Rows: P8 A6 (a sha, a tag, a detached HEAD)."""
        self.standard_pair()
        head = git(self.work, "rev-parse", "HEAD")
        git(self.work, "tag", "v1")
        for base in ("main", head, "v1", "HEAD"):
            with self.subTest(base):
                out, code = self.run_("--base", base)
                self.assertEqual(code, 0, out)
        git(self.work, "checkout", "-q", "--detach")
        out, code = self.run_("--base", "main")
        self.assertEqual(code, 0, out)

    def test_standard_unrelated_base(self):
        """Rows: P9 A6."""
        self.make("standard")
        git(self.work, "checkout", "-q", "--orphan", "other")
        git(self.work, "commit", "-q", "--allow-empty", "-m", "orphan")
        git(self.work, "checkout", "-q", "main")
        out, code = self.run_("--base", "other")
        self.input_fail(out, code, "git merge-base failed (exit 1)")

    def test_strict_checks_unchanged_rows(self):
        """Rows: P10 P15 O2 (row by row in sorted register order; one run per row; config renders with the first row)."""
        self.make()
        self.pin(F2)
        self.pin(F)
        self.standard_branch()
        out, code = self.run_()
        self.assertEqual(idsof(out), ["config", "scope", "package." + F, "transcript." + F, "rerun." + F,
                                      "package." + F2, "transcript." + F2, "rerun." + F2])  # O2: row by row, sorted
        self.assertEqual(code, 0)

    def test_row_without_pin_has_no_lines(self):
        """Rows: P11 P12."""
        self.make()
        self.put("%s/%s.yml" % (FIND, F3), emit(frow(F3, "open")))
        self.put("%s/%s.yml" % (FIND, F2), emit({k: v for k, v in frow(F2, "open").items() if k != "pin"}))
        for pinval in (5, ["a"]):  # P12: fails findings.validate: skipped
            self.put("%s/%s.yml" % (FIND, F), emit(frow(F, "open", pin=pinval)))
            commit_all(self.work, "rows")
            out, code = self.run_()
            self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
            self.assertEqual(code, 0)

    def test_status_with_pin(self):
        """Rows: P13 (in scope for every status findings.validate accepts; merged is skipped)."""
        for status in ("pinned", "closed", "open", "planned", "in-progress", "fixed-unpinned", "deferred", "merged"):
            with self.subTest(status):
                self.fresh()
                self.make()
                self.pin(status=status, **({"resolved_by": "p"} if status in ("closed", "merged") else {}))
                out, code = self.run_()
                if status == "merged":
                    self.assertEqual(idsof(out), ["config", "scope"])
                else:
                    self.assertEqual(idsof(out), self.valid_ids(), out)

    def test_closed_row_reads_blob_at_sha(self):
        """Rows: P14 T13 (the verdict comes from the object at the sha, not from the working tree)."""
        self.make()
        info = self.pin(status="closed", resolved_by="p")
        os.remove(os.path.join(self.work, info.tpath))  # tests may delete inside their own temp dirs
        self.put(info.tpath, "tampered\n")
        out, code = self.run_()
        self.assertEqual(idsof(out), self.valid_ids(), out)
        self.assertEqual(code, 0)

    def test_status_alias_rows(self):
        """Rows: I5 I6 (rows that fail findings.validate are skipped, the others are checked)."""
        self.make()
        self.pin(F2)
        for why, over in (("empty test", {"pin_test": ""}), ("short sha", {"pin_t": "abcdef:%s/x.md" % TDIR}),
                          ("no path", {"pin_t": "a1b2c3d:"}), ("merged", {"status": "merged", "resolved_by": "p"})):
            with self.subTest(why):
                self.pin(F, **over)
                out, code = self.run_()
                self.assertEqual(idsof(out), ["config", "scope"] + self.valid_ids(F2)[2:], out)
                self.assertEqual(code, 0)
                os.remove(os.path.join(self.work, "%s/%s.yml" % (FIND, F)))
        # I6: every row invalid
        os.remove(os.path.join(self.work, "%s/%s.yml" % (FIND, F2)))
        self.pin(F, pin_test="")
        out, code = self.run_()
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
        self.assertEqual(code, 0)

    def test_config_uses_first_valid_row(self):
        """Rows: I7 Q3 (a): an invalid first row does not decide evidence.config."""
        self.make()
        self.pin(F, pin_test="")
        self.pin(F2)
        self.set_config(commands={"test_one": "sh check.sh {id}"})
        out, code = self.run_()
        self.assertEqual(idsof(out), self.valid_ids(F2), out)

    def test_many_rows_lines(self):
        """Rows: P15 (0, 1, 2 rows; three lines per row)."""
        self.make()
        for n, fid in enumerate((F, F2, F3)[:2]):
            self.pin(fid)
            out, _ = self.run_()
            self.assertEqual(len(out.splitlines()), 2 + 3 * (n + 1))

    def test_one_row_failing_does_not_hide_the_next(self):
        """Rows: O7."""
        self.make()
        self.pin(F, pkg={"test": "other"})
        self.pin(F2)
        out, code = self.run_()
        self.assertTrue(bad(out, "package." + F))
        self.assertEqual([ok(out, "package." + F2), ok(out, "transcript." + F2), ok(out, "rerun." + F2)],
                         [True, True, True])
        self.assertEqual(code, 1)

    def test_line_ids_use_key_rule(self):
        """Rows: O8 (a valid unique id names the line; an invalid id names the record file)."""
        self.make()
        self.pin(F)
        row_path = "%s/%s.yml" % (FIND, F)
        with open(os.path.join(self.work, row_path), encoding="utf-8") as fh:
            text = fh.read()
        out, code = self.run_()
        self.assertEqual(idsof(out), self.valid_ids(F))
        # the same id in a second file: neither key is unique, so each line names its record file
        self.put("%s/%s.yml" % (FIND, F2), text)
        out, code = self.run_()
        for name in (F, F2):
            self.assertTrue(ok(out, "package.%s/%s.yml" % (FIND, name)), out)
            self.assertTrue(ok(out, "transcript.%s/%s.yml" % (FIND, name)), out)
        self.assertNotIn("package." + F + "\n", out)


# ======================================================================== producer 4: evidence.config
class Config(Base):
    def test_config_absent_no_rows(self):
        """Rows: K1 K2 O5 I2 (any shape of commands is PASS while no row is in scope)."""
        for cmds in (..., {"x": 1}, {"test_one": ""}, {"test_one": []}, {"test_one": 5}, {"test_one": "no placeholder"}, 5, ["a"]):
            with self.subTest(str(cmds)[:20]):
                self.fresh()
                c = self.cfg()
                if cmds is ...:
                    del c["commands"]
                else:
                    c["commands"] = cmds
                root = make_repo(self.work, c)
                out, code = self.run_()
                self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"], out)
                self.assertEqual(code, 0)

    def fresh(self):
        self.work = os.path.join(self.tmp, "c%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def test_missing_test_one_with_pin_fails(self):
        """Rows: K3 K4 K10 O4 S1 (no other line of the row is printed, D-2-Q7)."""
        forms = [..., {"x": 1}, {"test_one": "no placeholder"}, {"test_one": ""}, {"test_one": []}, {"test_one": [1]},
                 {"test_one": 3}, {"test_one": True}, {"test_one": None}, {"test_one": "9" * 4301 + "x"}, 5, ["a"]]
        for cmds in forms:
            with self.subTest(str(cmds)[:20]):
                self.fresh()
                self.make()
                self.pin()
                c = self.cfg()
                if cmds is ...:
                    del c["commands"]
                else:
                    c["commands"] = cmds
                with open(os.path.join(self.work, ".strict-delivery/config.yml"), "w", encoding="utf-8") as fh:
                    fh.write(emit(c))
                out, code = self.run_()
                lines = out.splitlines()
                self.assertTrue(lines[0].startswith("FAIL evidence.config: "), out)
                self.assertIn("commands.test_one", lines[0])
                self.assertEqual(lines[1:], ["PASS evidence.scope"])
                self.assertEqual(code, 1)

    def test_config_valid_forms_pass(self):
        """Rows: K5 K8 (a string with one {id}, with two, a list; odd ids are data)."""
        self.make()
        self.pin()
        for tmpl in ("sh check.sh {id}", "sh check.sh {id} {id}", ["sh", "check.sh", "{id}"]):
            with self.subTest(str(tmpl)):
                self.set_config(commands={"test_one": tmpl})
                out, _ = self.run_()
                self.assertTrue(ok(out, "config"), out)

    def test_config_odd_ids_pass(self):
        """Rows: K8 R10 (the id is data, quoted for a shell string and literal in a list)."""
        marker = os.path.join(self.tmp, "marker")
        self.make()
        odd = ["a b", "a;touch " + marker, "$(touch %s)" % marker, "'q", "café ü", "x-y"]
        for test in odd:
            for tmpl in ("sh check.sh {id}", ["sh", "check.sh", "{id}"]):
                with self.subTest(test=test, tmpl=str(tmpl)):
                    self.fresh()
                    self.make()
                    self.pin(test=test)
                    self.set_config(commands={"test_one": tmpl})
                    out, code = self.run_()
                    self.assertTrue(ok(out, "config") and ok(out, "rerun." + F), out)
                    self.assertFalse(os.path.exists(marker))

    def fresh(self):
        self.work = os.path.join(self.tmp, "c%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def test_first_row_newline_test_id(self):
        """Rows: K6 (a newline in the first row's id fails evidence.config; findings.validate accepts it)."""
        self.make()
        self.pin(test="a\nb")
        out, code = self.run_()
        self.assertTrue(line(out, "config").startswith("FAIL evidence.config: "), out)
        self.assertEqual(code, 1)

    def test_nul_in_test_id(self):
        """Rows: K7 R12 (D-2-Q6 (a): render_pin refuses NUL; the run continues)."""
        self.make()
        self.pin(test="a\x00b")
        out, code = self.run_()
        self.assertTrue(bad(out, "config"), out)
        self.assertEqual(code, 1)
        self.assertNotIn("input", out)

    def test_second_row_unrenderable(self):
        """Rows: K9 R14 (D-2-Q5 (a): that row's rerun fails with the render reason; the others continue)."""
        self.make()
        self.pin(F)
        self.pin(F2, test="a\nb")
        out, code = self.run_()
        self.assertTrue(ok(out, "config"), out)
        self.assertTrue(ok(out, "rerun." + F))
        self.assertTrue(bad(out, "rerun." + F2), out)
        self.assertEqual(idsof(out).count("rerun." + F2), 1, out)  # one line: a render failure never also runs a command
        self.assertEqual(code, 1)

    def test_config_fail_skips_row_lines(self):
        """Rows: K10 O4 (standard: rows not in scope are unaffected)."""
        self.make("standard", commands={"x": 1})
        self.pin(F2)
        self.standard_branch()
        out, code = self.run_()
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
        self.pin(F)
        out, code = self.run_()
        self.assertTrue(bad(out, "config") and ok(out, "scope"), out)
        self.assertEqual(len(out.splitlines()), 2)


# ======================================================================== producer 2, 10: input failures
class InputFailures(Base):
    def test_config_unreadable_is_input(self):
        """Rows: I1 C8 S3."""
        root = self.make()
        path = os.path.join(root, ".strict-delivery/config.yml")
        for why, text in (("not a mapping", "- a\n- b\n"), ("unknown key", emit({**self.cfg(), "bogus": 1})),
                          ("bad profile", emit(self.cfg("bogus")))):
            with self.subTest(why):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                out, code = self.run_()
                self.input_fail(out, code)
        os.remove(path)
        out, code = self.run_()
        self.input_fail(out, code, "config.yml")

    def test_register_unreadable_is_input(self):
        """Rows: I3 C7."""
        self.make()
        self.pin()
        for why, name, text in (("yaml error", "%s.yml" % F2, "a: [\n"), 
                                ("list", "%s.yml" % F3, "- 1\n")):
            with self.subTest(why):
                self.put("%s/%s" % (FIND, name), text)
                out, code = self.run_()
                self.input_fail(out, code)
                os.remove(os.path.join(self.work, FIND, name))
        d = os.path.join(self.work, FIND)
        os.rename(d, d + "x")
        self.put(FIND, "a file\n")
        out, code = self.run_()
        self.input_fail(out, code)

    def test_no_findings_directory(self):
        """Rows: I4 C7."""
        self.make()
        out, code = self.run_()
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])

    def test_strict_unknown_base(self):
        """Rows: I8 O3 A6 (D-2-Q1 (b): resolved under every profile; one line only)."""
        for prof in ("light", "standard", "strict"):
            with self.subTest(prof):
                self.fresh()
                self.make(prof)
                out, code = self.run_("--base", "nosuch")
                self.input_fail(out, code, "git merge-base failed (exit 128)")

    def fresh(self):
        self.work = os.path.join(self.tmp, "i%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def test_digits_in_row_field(self):
        """Rows: I9 V1(b) (under every int limit)."""
        for lim in INT_LIMITS:
            for n in (1000, 1001, 4300, 4301):
                with self.subTest(lim=lim, digits=n), int_limit(lim):
                    self.fresh()
                    self.make()
                    self.pin(review_round=int("9" * 1) if False else ...)
                    path = os.path.join(self.work, FIND, F + ".yml")
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text + "review_round: " + "9" * n + "\n")
                    out, code = self.run_()
                    if n == 1000 and lim != 640:  # under limit 640 yamlsub itself fails 1000 digits (unrelated finding U-1)
                        self.assertEqual(idsof(out)[:2], ["config", "scope"], out)
                    else:
                        self.input_fail(out, code, "integer too large")

    def test_digits_in_config(self):
        """Rows: I10 K11 V1(c)."""
        self.make()
        self.pin()
        path = os.path.join(self.work, ".strict-delivery/config.yml")
        for lim in INT_LIMITS:
            for n in (4300, 4301):
                with self.subTest(lim=lim, digits=n, where="unquoted"), int_limit(lim):
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(emit(self.cfg()) + "paths:\n  reviews: " + "9" * n + "\n")
                    out, code = self.run_()
                    self.input_fail(out, code, "integer too large")
            with self.subTest(lim=lim, where="quoted"), int_limit(lim):
                self.set_config(commands={"test_one": "9" * 4301})
                out, code = self.run_()
                self.assertTrue(bad(out, "config"), out)
                self.assertIn("commands.test_one", out)

    def test_git_missing(self):
        """Rows: I11."""
        self.make()
        empty = os.path.join(self.tmp, "nopath")
        os.mkdir(empty)
        with mock.patch.dict(os.environ, {"PATH": empty}):
            out, code = self.run_()
        self.input_fail(out, code, "git not found on PATH")

    def test_show_sha_forms(self):
        """Rows: C1 C4 C5 (consumed gitinfo calls: a commit-resolving sha returns the text, a name that resolves to no
        commit raises GateError, never None)."""
        self.make()
        info = self.pin()
        p = info.tpath
        self.assertIn("FINDING", gitinfo.show(self.work, info.tsha, p))
        self.assertIn("FINDING", gitinfo.show(self.work, info.tsha[:7], p))
        self.assertIn("FINDING", gitinfo.show(self.work, info.tsha[:6], p))
        with self.assertRaises(gate_evidence.GateError):
            gitinfo.show(self.work, "a1b2c3d", p)
        self.assertTrue(gitinfo.commit_exists(self.work, info.tsha[:7]))
        self.assertFalse(gitinfo.commit_exists(self.work, "a1b2c3d"))
        self.assertFalse(gitinfo.commit_exists(self.work, ""))
        self.assertFalse(gitinfo.blob_exists(self.work, "a1b2c3d", p))
        self.assertTrue(gitinfo.blob_exists(self.work, info.tsha, p))

    def test_show_path_and_blob_kinds(self):
        """Rows: C2 C3 (the gate feeds show only pin paths that findings.validate accepted)."""
        self.make()
        info = self.pin()
        head = git(self.work, "rev-parse", "HEAD")
        for bad_path in ("p/../x", "/p/x", "p//x", "./p"):
            with self.assertRaises(gate_evidence.GateError):
                gitinfo.show(self.work, head, bad_path)
        self.assertIsNone(gitinfo.show(self.work, head, "nosuch"))
        self.assertIsNone(gitinfo.show(self.work, head, "src"))
        self.assertEqual(gitinfo.show(self.work, head, "src/x.py"), "x\n")

    def test_merge_base_forms(self):
        """Rows: C6."""
        self.make()
        self.assertEqual(gitinfo.merge_base(self.work, "main", "HEAD"), git(self.work, "rev-parse", "HEAD"))
        with self.assertRaises(gate_evidence.GateError) as c:
            gitinfo.merge_base(self.work, "-x", "HEAD")
        self.assertIn("-", str(c.exception))
        with self.assertRaises(gate_evidence.GateError):
            gitinfo.merge_base(self.work, "9" * 41, "HEAD")

    def test_store_load_forms(self):
        """Rows: C7 (rows come back in sorted file-name order)."""
        self.make()
        self.pin(F2)
        self.pin(F)
        out, _ = self.run_()
        self.assertEqual([i for i in idsof(out) if i.startswith("package")], ["package." + F, "package." + F2])

    def test_gate_writes_nothing(self):
        """Rows: C10 (git status is unchanged after a run)."""
        self.make()
        self.pin()
        before = git(self.work, "status", "--porcelain", "--untracked-files=all")
        self.run_()
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), before)


# ======================================================================== producer 1: argv
class Argv(Base):
    def test_argv_root_default(self):
        """Rows: A1."""
        self.make()
        self.pin()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.work)
        out, code = run_argv([])
        self.assertEqual(idsof(out), self.valid_ids())
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        os.chdir(outside)
        out, code = run_argv([])
        self.input_fail(out, code, "git rev-parse --show-toplevel failed (exit 128); run /strict-delivery:init")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.work}):
            out, code = run_argv([])
            self.assertEqual(idsof(out), self.valid_ids())
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.work, "check.sh")}):
            out, code = run_argv([])
            self.input_fail(out, code, "CLAUDE_PROJECT_DIR is not a directory")

    def test_argv_root_forms(self):
        """Rows: A2."""
        self.make()
        self.pin()
        os.mkdir(os.path.join(self.work, "sub"))
        link = os.path.join(self.tmp, "link")
        os.symlink(self.work, link)
        for name, path, want in (("top", self.work, "ok"), ("symlink", link, "ok"),
                                 ("sub", os.path.join(self.work, "sub"), TOP),
                                 ("missing", os.path.join(self.tmp, "none"), E128 + "; run /strict-delivery:init"),
                                 ("empty", "", "git rev-parse --show-toplevel"),
                                 ("file", os.path.join(self.work, "check.sh"), "")):
            with self.subTest(name):
                out, code = run_argv(["--root", path])
                if want == "ok":
                    self.assertEqual(idsof(out), self.valid_ids())
                else:
                    self.input_fail(out, code, want)

    def test_argv_root_twice(self):
        """Rows: A3."""
        self.make()
        r = self.work
        for argv in (["--root", r, "--root", r], ["--root=" + r, "--root", r], ["--root", r, "--root=" + r],
                     ["--roo", r, "--root", r]):
            with self.subTest(argv[0]):
                out, code = run_argv(argv)
                self.input_fail(out, code, "invalid arguments: --root given more than once")

    def test_argv_base_default(self):
        """Rows: A4 (the default is config base_branch)."""
        self.make("standard", base_branch="nosuch")
        out, code = self.run_()
        self.input_fail(out, code, "git merge-base failed (exit 128)")
        out, code = self.run_("--base", "main")
        self.assertEqual(code, 0)

    def test_argv_base_twice(self):
        """Rows: A5 (every profile)."""
        for prof in ("light", "strict"):
            for argv in (["--base", "main", "--base", "main"], ["--base=main", "--base", "main"],
                         ["--bas", "main", "--base", "main"]):
                with self.subTest(prof, argv=argv[0]):
                    self.fresh()
                    self.make(prof)
                    out, code = self.run_(*argv)
                    self.input_fail(out, code, "invalid arguments: --base given more than once")

    def fresh(self):
        self.work = os.path.join(self.tmp, "a%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def test_argv_base_values(self):
        """Rows: A6 A10 (also the abbreviation --bas)."""
        self.make()
        head = git(self.work, "rev-parse", "HEAD")
        git(self.work, "tag", "tg")
        for base in ("main", head, "HEAD", "tg"):
            with self.subTest(base):
                out, code = self.run_("--base", base)
                self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])
        for base, needle in (("nosuch", "git merge-base failed (exit 128)"), ("", "evidence.input"),
                             ("9" * 41, "ref must not hold more than 40 hex digits in a row"),
                             ("a:b", "git merge-base failed (exit 128)")):
            with self.subTest(base):
                out, code = self.run_("--base", base)
                self.input_fail(out, code, needle)
        for base in ("-x", "--x"):
            with self.subTest(base):
                out, code = self.run_("--base", base)
                self.input_fail(out, code, "expected one argument")
        out, code = self.run_("--bas", "main")
        self.assertEqual(code, 0)

    def test_argv_base_missing_value(self):
        """Rows: A7."""
        self.make()
        for argv in (["--base"], ["--base", "--root", self.work]):
            out, code = run_argv(["--root", self.work] + argv if argv == ["--base"] else argv)
            self.input_fail(out, code, "argument --base: expected one argument")

    def test_argv_unknown(self):
        """Rows: A8."""
        self.make()
        for argv in (["--bogus"], ["extra"], ["--root", self.work, "extra"], ["--no-rerun"]):
            out, code = run_argv(argv)
            self.input_fail(out, code, "invalid arguments: unrecognized arguments")

    def test_argv_json_and_help(self):
        """Rows: A9 O9."""
        self.make()
        self.pin()
        out, code = run_argv(["--json", "--root", self.work])
        data = json.loads(out)
        self.assertEqual(data["gate"], "evidence")
        self.assertTrue(data["ok"])
        self.assertEqual([x["id"] for x in data["lines"]], ["evidence." + i for i in self.valid_ids()])
        self.assertEqual(set(data["lines"][0]), {"status", "id", "reason"})
        out, code = run_argv(["--root", self.work, "--json"])
        self.input_fail(out, code, "unrecognized arguments: --json")
        for argv in (["--help"], ["--root", self.work, "--help"]):
            out, code = run_argv(argv)
            self.input_fail(out, code, "help requested; no gate was run")

    def test_light_base_resolution(self):
        """Rows: A11 (D-2-Q1 (b): a light run resolves the base too)."""
        self.make("light")
        out, code = self.run_("--base", "nosuch")
        self.input_fail(out, code, "git merge-base failed (exit 128)")
        out, code = self.run_("--base", "main")
        self.assertEqual(out.splitlines(), ["PASS evidence.config", "PASS evidence.scope"])

    def test_bad_base_yields_only_input_line(self):
        """Rows: O3."""
        self.make("standard")
        self.pin()
        out, code = self.run_("--base", "nosuch")
        self.input_fail(out, code)

    def test_check_evidence_registered(self):
        """Rows: A12 X2."""
        if "evidence" not in gates_main.GATES:
            self.skipTest("Rq-6-1 not on this branch")
        self.make()
        p = subprocess.run([sys.executable, "-m", "gates", "check", "evidence", "--root", self.work],
                           cwd=REPO, stdout=subprocess.PIPE, universal_newlines=True)
        self.assertTrue(p.stdout.startswith("PASS evidence.config"))


# ======================================================================== producer 6: package
class Package(Base):
    def fresh(self):
        self.work = os.path.join(self.tmp, "g%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def case(self, **kw):
        self.fresh()
        self.make(**kw.pop("cfg", {}))
        info = self.pin(**kw)
        out, code = self.run_()
        return info, out, code

    def test_package_no_entry(self):
        """Rows: G2 G3 G4 G5 (candidates: <sha>:<reviews>/<dir>/<name>.md only)."""
        cases = {
            "empty": lambda i: [],
            "plain path": lambda i: ["src/x.py"],
            "bare sha": lambda i: [i.rsha],
            "other dir": lambda i: [i.rsha + ":docs/other/r.md"],
            "src": lambda i: [i.rsha + ":src/x.py"],
            "prefix": lambda i: [i.rsha + ":docs/strict-delivery/reviewsX/p/r.md"],
            "reviews itself": lambda i: [i.rsha + ":" + REV],
            "one level": lambda i: [i.rsha + ":" + REV + "/r.md"],
            "two levels": lambda i: [i.rsha + ":" + REV + "/p/q/r.md"],
            "txt": lambda i: [i.rsha + ":" + REV + "/p/r.txt"],
        }
        for name, ev in cases.items():
            with self.subTest(name):
                info, out, code = self.case(ev=ev)
                self.assertTrue(bad(out, "package." + F), out)
                self.assertIn("review report", line(out, "package." + F))
                self.assertEqual(code, 1)

    def test_package_custom_reviews_dir(self):
        """Rows: G4."""
        self.fresh()
        self.make(paths={"reviews": "docs/rev"})
        self.pin(rpath="docs/rev/p/r.md")
        out, _ = self.run_()
        self.assertTrue(ok(out, "package." + F), out)
        self.fresh()
        self.make(paths={"reviews": "docs/rev"})
        self.pin()  # the report is at the default path, outside the configured directory
        out, _ = self.run_()
        self.assertTrue(bad(out, "package." + F), out)

    def test_package_entry_shapes_accepted(self):
        """Rows: G5 G17 (a path with a colon splits at the first colon)."""
        info, out, code = self.case(rpath=REV + "/p/a:b.md")
        self.assertTrue(ok(out, "package." + F), out)

    def test_package_entry_sha_not_commit(self):
        """Rows: G6 (D-2-Q9 (a): a failed show is this row's line, the run goes on)."""
        info, out, code = self.case(ev=lambda i: ["a1b2c3d:" + i.rpath])
        self.assertTrue(bad(out, "package." + F), out)
        self.assertEqual(idsof(out)[:2], ["config", "scope"])
        self.assertNotIn("input", out)

    def test_package_blob_missing(self):
        """Rows: G7."""
        info, out, code = self.case(ev=lambda i: [i.rsha + ":" + REV + "/p/none.md"])
        self.assertIn("is not a regular file", line(out, "package." + F))
        info, out, code = self.case(ev=lambda i: [i.rsha + ":" + REV + "/p"])  # a directory (one level: not a report shape)
        self.assertTrue(bad(out, "package." + F))

    def test_package_non_utf8_blob(self):
        """Rows: G8 (a FAIL on the row, not input)."""
        info, out, code = self.case(rtext=lambda t: "x")
        self.fresh()
        self.make()
        info = self.pin(rtext=lambda t: "x")
        self.put(info.rpath, b"\xff\xfe\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "bytes")
        sha = git(self.work, "rev-parse", "HEAD")
        row = os.path.join(self.work, FIND, F + ".yml")
        with open(row, encoding="utf-8") as fh:
            text = fh.read()
        with open(row, "w", encoding="utf-8") as fh:
            fh.write(text.replace(info.rsha, sha))
        out, code = self.run_()
        self.assertIn("not valid UTF-8", line(out, "package." + F))
        self.assertEqual(idsof(out), self.valid_ids())

    def test_package_report_schema_error(self):
        """Rows: G9 G11 (first line missing, a BOM, CRLF-only bodies are the schema's; a group without PIN-COMMAND)."""
        for name, make in (("no tag", lambda t: "prose\nPIN %s transcript=%s\nPIN-TEST %s t\nPIN-COMMAND %s %s\n" % (F, t, F, F, D)),
                           ("other tag", lambda t: RP(F, t, tag="<!-- schema: review-plan/1 -->")),
                           ("bom", lambda t: "﻿" + RP(F, t)),
                           ("no command", lambda t: RTAG + "\nPIN %s transcript=%s\nPIN-TEST %s t\n" % (F, t, F)),
                           ("test twice", lambda t: RP(F, t, extra=["PIN-TEST %s t" % F]))):
            with self.subTest(name):
                info, out, code = self.case(rtext=lambda t, m=make: m("%s:%s/%s.md" % (t, TDIR, F)))
                self.assertTrue(bad(out, "package." + F), out)

    def test_package_group_absent(self):
        """Rows: G10 G18."""
        info, out, code = self.case(rtext=lambda t: RTAG + "\nno group\n")
        self.assertIn("holds no PIN group for " + F, line(out, "package." + F))
        info, out, code = self.case(rtext=lambda t: RP(F2, "%s:x" % t))
        self.assertIn("holds no PIN group", line(out, "package." + F))

    def test_package_group_incomplete(self):
        """Rows: G11 (Q10 (a): a broken group of another finding fails the whole report)."""
        info, out, code = self.case(rtext=lambda t: RP(F, "%s:%s/%s.md" % (t, TDIR, F),
                                                       extra=["PIN %s transcript=%s:x/y" % (F2, t), "PIN-TEST %s t" % F2]))
        self.assertTrue(bad(out, "package." + F), out)

    def test_package_field_mismatch(self):
        """Rows: G12 G13 G14 (each field one character off; sha spelling; no case folding)."""
        for field in ("test", "command", "transcript"):
            with self.subTest(field):
                if field == "transcript":
                    info, out, code = self.case(rtext=lambda t: RP(F, "%s:%s/%s.md" % (t[:7], TDIR, F)))
                else:
                    info, out, code = self.case(pkg={field: {"test": "t ", "command": D + "x"}[field]})
                ln = line(out, "package." + F)
                self.assertTrue(ln.startswith("FAIL"), out)
                self.assertIn(field, ln)

    def test_package_test_id_no_case_folding(self):
        """Rows: G14 V2 (U+2C2F vs its lower case, NFC vs NFD)."""
        for a, b in ((U2C2F, "ⱟ"), ("é", "é")):
            with self.subTest(a=a.encode("unicode_escape")):
                info, out, code = self.case(test=a, pkg={"test": b})
                self.assertTrue(bad(out, "package." + F), out)

    def test_command_mismatch_double_report(self):
        """Rows: G15 (both directions)."""
        info, out, code = self.case(runs=GOOD_RUNS, cmd=D + " ", pkg={"command": D})
        self.assertTrue(bad(out, "package." + F) and bad(out, "transcript." + F), out)
        info, out, code = self.case(pkg={"command": D + " "})
        self.assertTrue(bad(out, "package." + F) and bad(out, "transcript." + F), out)

    def test_package_report_shape_enforced(self):
        """Rows: G5 (D-2-Q8 (a): a report holding a valid group is still refused outside <reviews>/<dir>/<name>.md, and
        the reason names the shape)."""
        for name, rpath in (("one level", REV + "/" + F + ".md"), ("two levels", REV + "/p/q/" + F + ".md"),
                            ("txt", REV + "/p/" + F + ".txt")):
            with self.subTest(name):
                info, out, code = self.case(rpath=rpath)
                self.assertTrue(bad(out, "package." + F), out)
                self.assertIn("not that shape: " + rpath, line(out, "package." + F))

    def test_package_valid_report_wrongly_located(self):
        """Rows: G3 G4 G5 (a report holding a VALID group is refused when it is not <reviews>/<dir>/<name>.md: another
        directory of the same length, a directory whose name only starts with <reviews>, a second level whose first
        part ends in .md)."""
        other = REV.replace("reviews", "xxxxxxx")
        for name, rpath, shape in (("same length other dir", other + "/p/" + F + ".md", False),
                                   ("reviews prefix", REV + "X/p/" + F + ".md", False),
                                   ("no md leaf", REV + "/q.md/" + F, True),
                                   ("three levels", REV + "/p/q.md/" + F + ".md", True)):
            with self.subTest(name):
                info, out, code = self.case(rpath=rpath)
                self.assertEqual(code, 1)
                self.assertTrue(bad(out, "package." + F), out)
                if shape:
                    self.assertIn("not that shape: " + rpath, line(out, "package." + F))
                else:
                    self.assertIn("no evidence entry is a review report", line(out, "package." + F))
                    self.assertNotIn("not that shape", line(out, "package." + F))  # not even named as a near miss

    def reports(self, a, b):
        """Two reports for F, cited in the order a, b; each is (test, command)."""
        self.fresh()
        self.make()
        info = self.pin(ev=lambda i: [])
        for name, (test, cmd) in (("a", a), ("b", b)):
            self.put("%s/p/%s.md" % (REV, name), RP(F, info.transcript, test, cmd))
        sha = commit_all(self.work, "reports")
        self.sha, self.info = sha, info
        row = os.path.join(self.work, FIND, F + ".yml")
        with open(row, encoding="utf-8") as fh:
            text = fh.read()
        ev = "evidence:\n  - %s:%s/p/a.md\n  - %s:%s/p/b.md\n" % (sha, REV, sha, REV)
        with open(row, "w", encoding="utf-8") as fh:
            fh.write(text.replace("evidence: []\n", ev))
        return self.run_()[0]

    def test_command_source_prefers_matching_group(self):
        """Rows: G16 T10 (the transcript is compared with the command of the first report whose test and transcript
        match, else with the first report holding a group)."""
        # a: wrong test, command equal to the runs; b: right test, command differs from the runs
        out = self.reports(("z", D), ("t", D + "x"))
        self.assertTrue(bad(out, "package." + F) and bad(out, "transcript." + F), out)
        self.assertIn("expected %s," % (D + "x"), line(out, "transcript." + F))
        # both right, both differ from the runs: the first report's command
        out = self.reports(("t", D + "y"), ("t", D + "x"))
        self.assertIn("expected %s," % (D + "y"), line(out, "transcript." + F))
        self.assertNotIn("expected %s," % (D + "x"), line(out, "transcript." + F))
        # both wrong: the first report's command
        out = self.reports(("z", D + "y"), ("w", D + "x"))
        self.assertIn("expected %s," % (D + "y"), line(out, "transcript." + F))

    def test_package_reason_names_every_problem(self):
        """Rows: G12 G13 G15 G16 (F-20261121-whj8: the package reason holds every differing field of a report and the
        problem of every candidate report, in order, each exactly once; mutants E1 (first problem only) and E2 (first
        differing field only))."""
        # one report, the test and the transcript both differ: both fields are named, in that order
        info, out, code = self.case(rtext=lambda t: RP(F, "%s:%s/%s.md" % (t[:7], TDIR, F), test="z"))
        self.assertEqual(line(out, "package." + F),
                         "FAIL evidence.package.%s: review report %s:%s: test: expected t, got z; transcript: expected %s, "
                         "got %s:%s/%s.md" % (F, info.rsha, info.rpath, info.transcript, info.tsha[:7], TDIR, F))
        # one report, the test differs and so does the command: the command is not compared once a field differs, so the
        # reason names the field only (a fail-closed order, not a verdict about the command)
        info, out, code = self.case(cmd=D + "x", pkg={"command": D, "test": "z"}, pin_test="t")
        self.assertEqual(line(out, "package." + F),
                         "FAIL evidence.package.%s: review report %s:%s: test: expected t, got z" % (F, info.rsha, info.rpath))
        # two reports, each failing: the reasons of both, in the order the evidence lists them
        out = self.reports(("z", D), ("w", D))
        self.assertEqual(line(out, "package." + F),
                         "FAIL evidence.package.%s: review report %s:%s/p/a.md: test: expected t, got z; review report "
                         "%s:%s/p/b.md: test: expected t, got w" % (F, self.sha, REV, self.sha, REV))
        # two reports, a field problem and a command problem
        out = self.reports(("z", D), ("t", D + "x"))
        self.assertEqual(line(out, "package." + F),
                         "FAIL evidence.package.%s: review report %s:%s/p/a.md: test: expected t, got z; review report "
                         "%s:%s/p/b.md: command: %sx differs from the transcript's RUN 1, 2, 3" % (F, self.sha, REV, self.sha, REV, D))
        # two reports, a command problem and a field problem
        out = self.reports(("t", D + "x"), ("z", D))
        self.assertEqual(line(out, "package." + F),
                         "FAIL evidence.package.%s: review report %s:%s/p/a.md: command: %sx differs from the transcript's "
                         "RUN 1, 2, 3; review report %s:%s/p/b.md: test: expected t, got z" % (F, self.sha, REV, D, self.sha, REV))

    def test_package_two_reports(self):
        """Rows: G16 (Q13 (a): pass if at least one report matches in full)."""
        self.make()
        info = self.pin(ev=lambda i: [])
        self.put(REV + "/p/a.md", RP(F2, "x:y"))
        self.put(REV + "/p/b.md", RP(F, info.transcript))
        sha = commit_all(self.work, "reports")
        row = os.path.join(self.work, FIND, F + ".yml")
        with open(row, encoding="utf-8") as fh:
            text = fh.read()
        for first, second, want in (("a", "b", True), ("b", "a", True)):
            with self.subTest(first):
                ev = "evidence:\n  - %s:%s/p/%s.md\n  - %s:%s/p/%s.md\n" % (sha, REV, first, sha, REV, second)
                with open(row, "w", encoding="utf-8") as fh:
                    fh.write(text.replace("evidence: []\n", ev))
                out, code = self.run_()
                self.assertTrue(ok(out, "package." + F), out)
        ev = "evidence:\n  - %s:%s/p/a.md\n" % (sha, REV)  # only the wrong one
        with open(row, "w", encoding="utf-8") as fh:
            fh.write(text.replace("evidence: []\n", ev))
        out, code = self.run_()
        self.assertTrue(bad(out, "package." + F), out)

    def test_package_digit_and_unicode_text(self):
        """Rows: G19 V1(e) V2 (equal strings pass; a mismatch shows the same text on both interpreters)."""
        for lim in INT_LIMITS:
            with int_limit(lim):
                big = "9" * 4301
                info, out, code = self.case(test=big, cmd=D + " " + UEXC, pin_test=big)
                self.assertTrue(ok(out, "package." + F), out)
                info, out, code = self.case(test="a" + UEXC, pkg={"test": "a" + UEXC + "x"})
                self.assertIn("a\\u0870", out)  # the frozen print table renders U+0870 as an escape on both interpreters


# ======================================================================== producer 7: transcript
class Transcript(Base):
    def fresh(self):
        self.work = os.path.join(self.tmp, "t%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def case(self, **kw):
        self.fresh()
        self.make(**kw.pop("cfg", {}))
        info = self.pin(**kw)
        out, code = self.run_()
        return info, out, code

    def test_transcript_location(self):
        """Rows: T2 T3 (D-2-Q14 (a): exactly <plan_state>/<one dir>/mutations/<file>, whatever the owner kind)."""
        good = PS + "/p/mutations/t.md"
        cases = [(good, True), (PS + "/p/mutations/d/t.md", False), (PS + "/mutations/t.md", False),
                 ("x/mutations/t.md", False), (PS + "/p/q/mutations/t.md", False), (PS + "/p/mutations", False),
                 (PS + "/p/Mutations/t.md", False), ("x/y/z/p/mutations/t.md", False), (PS + "/mutations/mutations/t.md", True)]
        for path, want in cases:
            with self.subTest(path):
                info, out, code = self.case(tpath=path)
                self.assertEqual(ok(out, "transcript." + F), want, out)
                if not want:
                    self.assertIn("mutations/", line(out, "transcript." + F) or "")

    def test_transcript_location_by_owner(self):
        """Rows: T3 (the same rule for owner kinds issue and roadmap)."""
        for owner in ({"kind": "issue", "number": 1}, {"kind": "roadmap", "plan": "p"}):
            for path, want in ((PS + "/p/mutations/t.md", True), (PS + "/p/mutations/d/t.md", False)):
                with self.subTest(owner["kind"], path=path):
                    info, out, code = self.case(tpath=path, owner=owner)
                    self.assertEqual(ok(out, "transcript." + F), want, out)

    def test_transcript_missing_at_sha(self):
        """Rows: T4 T5."""
        info, out, code = self.case(pin_t="a1b2c3d:%s/%s.md" % (TDIR, F))
        self.assertTrue(bad(out, "transcript." + F), out)
        self.assertNotIn("input", out)
        self.fresh()
        self.make()
        self.put(TDIR + "/sub/x.txt", "x\n")
        commit_all(self.work, "a directory")
        info = self.pin()
        head = git(self.work, "rev-parse", "HEAD")
        for target in (TDIR + "/gone.md", TDIR + "/sub"):  # missing; a directory
            row = os.path.join(self.work, FIND, F + ".yml")
            with open(row, encoding="utf-8") as fh:
                text = fh.read()
            with open(row, "w", encoding="utf-8") as fh:
                fh.write(text.replace(info.transcript, "%s:%s" % (info.tsha, target)))
            out, _ = self.run_()
            self.assertTrue(bad(out, "transcript." + F), out)
            if target == TDIR + "/gone.md":  # the missing target's text is unchanged: the edb6aa7 assertion, kept
                self.assertIn("is not a regular file", line(out, "transcript." + F))
            else:  # R4-3, 5b.3 F15: the directory is refused by name through tipread.show_file
                self.assertEqual(line(out, "transcript." + F), "FAIL evidence.transcript.%s: transcript %s:%s: %s"
                                 % (F, info.tsha, target, refusal(info.tsha, target)))
            with open(row, "w", encoding="utf-8") as fh:
                fh.write(text)

    def test_transcript_non_utf8_blob(self):
        """Rows: T6."""
        info, out, code = self.case(ttext="x")
        self.fresh()
        self.make()
        self.put(TDIR + "/" + F + ".md", b"\xff\xfe")
        tsha = commit_all(self.work, "bytes")
        self.put(REV + "/p/r.md", RP(F, "%s:%s/%s.md" % (tsha, TDIR, F)))
        rsha = commit_all(self.work, "report")
        self.put("%s/%s.yml" % (FIND, F), emit(frow(F, pin={"test": "t", "transcript": "%s:%s/%s.md" % (tsha, TDIR, F)},
                                                    evidence=["%s:%s/p/r.md" % (rsha, REV)])))
        commit_all(self.work, "finding")
        out, code = self.run_()
        self.assertIn("not valid UTF-8", line(out, "transcript." + F))

    def test_transcript_schema_error(self):
        """Rows: T7 T12 (first line missing; exit= empty; exit=+1)."""
        good_body = T()
        cases = {"no first line": "\n".join(good_body.split("\n")[1:]),
                 "exit empty": good_body.replace("RUN 1 fix exit=0", "RUN 1 fix exit="),
                 "exit plus": good_body.replace("RUN 1 fix exit=0", "RUN 1 fix exit=+1")}
        for name, text in cases.items():
            with self.subTest(name):
                info, out, code = self.case(ttext=text)
                self.assertTrue(bad(out, "transcript." + F), out)
                self.assertTrue(ok(out, "package." + F), out)  # the package does not compare an unreadable transcript

    def test_transcript_each_failure(self):
        """Rows: T8 T12 T14 (every transcript_errors failure fails the line; D-2-Q15 (a): all errors on one line)."""
        cases = {
            "two FINDING": T(extra=["FINDING " + F]),
            "other finding": T(fid=F2),
            "decision prefix": T(fid="DEC-20261031-k3f9"),
            "no MUTANT": T().replace("MUTANT revert\n", ""),
            "other test": T(test="u"),
            "test trailing space": T(test="t "),
            "2 runs": T(runs=GOOD_RUNS[:2]),
            "4 runs": T(runs=GOOD_RUNS + ((3, "fix", 0),)),
            "runs 2-1-3": T(runs=((2, "mutant", 1), (1, "fix", 0), (3, "fix", 0))),
            "phases": T(runs=((1, "fix", 0), (2, "fix", 1), (3, "fix", 0))),
            "command off": T(cmd=D + "x"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                info, out, code = self.case(ttext=text)
                self.assertTrue(bad(out, "transcript." + F), out)
                self.assertEqual(len(out.splitlines()), 5)
        info, out, code = self.case(ttext=T(runs=((1, "fix", 1), (2, "mutant", 0), (3, "fix", 1))))
        self.assertIn("RUN 1", line(out, "transcript." + F))
        self.assertIn("RUN 2", line(out, "transcript." + F))
        self.assertIn("RUN 3", line(out, "transcript." + F))

    def test_transcript_exit_set(self):
        """Rows: T9 (run 2: 1 2 125 255 -11 pass; 0 126 127 fail; runs 1 and 3 must exit 0)."""
        for code_, want in ((1, True), (2, True), (125, True), (255, True), (-11, True), (0, False), (126, False),
                            (127, False)):
            with self.subTest(code_):
                info, out, code = self.case(runs=((1, "fix", 0), (2, "mutant", code_), (3, "fix", 0)))
                self.assertEqual(ok(out, "transcript." + F), want, out)
        for runs in (((1, "fix", 1), (2, "mutant", 1), (3, "fix", 0)), ((1, "fix", 0), (2, "mutant", 1), (3, "fix", 1))):
            info, out, code = self.case(runs=runs)
            self.assertTrue(bad(out, "transcript." + F))

    def test_reasons_escaped_once(self):
        """Rows: T8 G12 G13 V2 (F-20261121-7gp8, F-20261121-j2wv: Result.render's one safe_text pass is the only
        escaping, plan Task 1C; a character of the transcript's TEST text or RUN command, or of the report's PIN-TEST or
        PIN-COMMAND, prints escaped once on the transcript and on the package line; a backslash prints as two)."""
        for name, ch, esc in (("backslash", "\\", "\\\\"), ("control", "\x01", "\\x01"), ("escape", "\x1b", "\\x1b"),
                              ("delete", "\x7f", "\\x7f"), ("non-printable", UEXC, "\\u0870")):
            with self.subTest(name):
                info, out, code = self.case(ttext=T(F, "t" + ch))  # the transcript's TEST text differs from the pin's
                want = "test: expected t, got t" + esc
                self.assertIn(want, line(out, "transcript." + F))
                info, out, code = self.case(pkg={"test": "t" + ch})  # the report's PIN-TEST differs from the pin's
                self.assertIn(want, line(out, "package." + F))
                info, out, code = self.case(runs=GOOD_RUNS, cmd=D + ch, pkg={"command": D})  # the runs' command differs
                for n in (1, 2, 3):
                    self.assertIn("RUN %d: command: expected %s, got %s" % (n, D, D + esc), line(out, "transcript." + F))
                info, out, code = self.case(pkg={"command": D + ch})  # the report's command differs from the runs'
                self.assertIn("command: %s differs from the transcript's RUN 1, 2, 3" % (D + esc), line(out, "package." + F))
                self.assertIn("RUN 1: command: expected %s, got %s" % (D + esc, D), line(out, "transcript." + F))
                if ch == "\\":
                    self.assertNotIn("\\" * 3, out)  # never four where one is meant; two is the escape

    def test_transcript_without_package_command(self):
        """Rows: T10 (Q17 (a): FAIL naming that no package command exists)."""
        info, out, code = self.case(ev=lambda i: [])
        self.assertIn("no package command", line(out, "transcript." + F))
        info, out, code = self.case(rtext=lambda t: RTAG + "\nnothing\n")
        self.assertIn("no package command", line(out, "transcript." + F))

    def test_transcript_foreign_prefix(self):
        """Rows: T12."""
        info, out, code = self.case(ttext=T(fid="DEC-20261031-k3f9"))
        self.assertTrue(bad(out, "transcript." + F), out)

    def test_transcript_read_from_object_not_tree(self):
        """Rows: T13 (tree copy edited after commit)."""
        self.make()
        info = self.pin()
        self.put(info.tpath, "garbage\n")
        out, code = self.run_()
        self.assertEqual(idsof(out), self.valid_ids())
        self.assertEqual(code, 0)

    def test_transcript_shared_by_two_rows(self):
        """Rows: T14 (FINDING must equal the row's id: at most one row passes)."""
        self.make()
        info = self.pin(F)
        self.pin(F2, tpath=info.tpath, ttext=None, pin_t=info.transcript, cmd=D,
                 rtext=lambda t: RP(F2, info.transcript))
        out, code = self.run_()
        passes = [ok(out, "transcript." + F), ok(out, "transcript." + F2)]
        self.assertEqual(sorted(passes), [False, True], out)

    def test_digit_limits_same_on_both(self):
        """Rows: V1(a) V7 T15 T9 (an exit of 4300 or 4301 digits is a schema FAIL on the line; the reason holds no
        interpreter text; every int limit gives the same output)."""
        outs = {}
        for lim in INT_LIMITS:
            with int_limit(lim):
                for n in (3, 4, 4300, 4301):
                    text = T().replace("RUN 2 mutant exit=1", "RUN 2 mutant exit=" + "9" * n)
                    info, out, code = self.case(ttext=text)
                    self.assertEqual(bad(out, "transcript." + F), n != 3, out)  # three digits is the bound
                    self.assertNotIn("Exceeds", out)
                    outs.setdefault(n, set()).add(out.replace(info.tsha, "S").replace(info.rsha, "S"))
        for n, s in outs.items():
            self.assertEqual(len(s), 1, n)

    def test_unicode_same_on_both(self):
        """Rows: V2 T15 (U+0870, U+1FAE8, U+2C2F in TEST, MUTANT, a command: the verdict does not depend on the
        interpreter's Unicode tables, and the reason shows escapes)."""
        for ch in (UEXC, "\U0001fae8", U2C2F):
            with self.subTest(ch.encode("unicode_escape")):
                self.fresh()
                self.make()
                self.pin(test="a" + ch, cmd="sh check.sh a" + ch, mutant="m" + ch)
                self.put("fix.txt", "broken\n")
                out, code = self.run_()
                self.assertTrue(ok(out, "package." + F) and ok(out, "transcript." + F), out)
                esc = "\\u%04x" % ord(ch) if ord(ch) < 0x10000 else "\\U%08x" % ord(ch)
                # the frozen print table escapes all three characters on both interpreters
                self.assertIn("FAIL evidence.rerun.%s: sh check.sh 'a%s': exit 1" % (F, esc), out)


# ======================================================================== producer 8: rerun
class Rerun(Base):
    def fresh(self):
        self.work = os.path.join(self.tmp, "r%d" % len(os.listdir(self.tmp)))
        os.mkdir(self.work)

    def with_cmd(self, tmpl, **kw):
        self.fresh()
        self.make()
        self.pin(**kw)
        self.set_config(commands={"test_one": tmpl})
        return self.run_()

    def test_rerun_exit_codes(self):
        """Rows: R1 R3 R11 (any non-zero fails and shows its code; a list needs no shell)."""
        for tmpl, want in (("exit 0 # {id}", 0), ("exit 2 # {id}", 2), ("exit 3 # {id}", 3), ("exit 255 # {id}", 255),
                           ("./noexec # {id}", 126), ("nosuchprog {id}", 127), ("exit 256 # {id}", 0)):
            with self.subTest(tmpl):
                self.fresh()
                self.make()
                self.pin()
                self.put("noexec", "#!/bin/sh\n")
                self.set_config(commands={"test_one": tmpl})
                out, code = self.run_()
                if want == 0:
                    self.assertTrue(ok(out, "rerun." + F), out)
                else:
                    self.assertIn("exit %d\n" % want, line(out, "rerun." + F) + "\n")
        out, code = self.with_cmd(["sh", "-c", "exit 4", "{id}"])
        self.assertIn(": exit 4", line(out, "rerun." + F))

    def test_rerun_list_template_runs_without_a_shell(self):
        """Rows: R3 R4 (a list template is executed directly, not as its shlex.join string through sh: the shell builtin
        exit is no program, so the list fails with 127 where the joined string would exit 0)."""
        out, code = self.with_cmd(["exit", "{id}"], test="0")
        self.assertIn(": exit 127", line(out, "rerun." + F))
        self.assertEqual(code, 1)
        out, code = self.with_cmd("exit {id}", test="0")  # the same words as a string go through sh
        self.assertTrue(ok(out, "rerun." + F), out)

    def test_rerun_missing_program_list(self):
        """Rows: R4 C9."""
        out, code = self.with_cmd(["/no/such/prog", "{id}"])
        self.assertIn("exit 127", line(out, "rerun." + F))
        self.assertEqual(code, 1)

    def test_rerun_signal_exit(self):
        """Rows: R5 C9."""
        for sig, num in (("SEGV", -11), ("KILL", -9)):
            with self.subTest(sig):
                out, code = self.with_cmd("kill -%s $$ # {id}" % sig)
                self.assertIn("exit %d" % num, line(out, "rerun." + F))
        for sig, num in (("SEGV", -11), ("KILL", -9)):  # a list runs with no shell: the child itself is signalled
            with self.subTest("list " + sig):
                out, code = self.with_cmd(["sh", "-c", "kill -%s $$" % sig, "{id}"])
                self.assertIn("exit %d" % num, line(out, "rerun." + F))

    def test_rerun_dirty_tree_not_checked(self):
        """Rows: R6."""
        out, code = self.with_cmd("echo x > out.txt && grep -q fixed fix.txt # {id}")
        self.assertTrue(ok(out, "rerun." + F), out)
        self.assertTrue(os.path.exists(os.path.join(self.work, "out.txt")))
        self.assertEqual(code, 0)

    def test_rerun_cwd_is_root(self):
        """Rows: R7 (a root with a space; a symlinked root)."""
        self.work = os.path.join(self.tmp, "with space")
        os.mkdir(self.work)
        self.make()
        self.pin()
        self.set_config(commands={"test_one": "test -f check.sh # {id}"})
        out, _ = self.run_()
        self.assertTrue(ok(out, "rerun." + F), out)
        link = os.path.join(self.tmp, "lnk")
        os.symlink(self.work, link)
        out, _ = run_argv(["--root", link])
        self.assertTrue(ok(out, "rerun." + F), out)

    def test_rerun_environment_and_stdin(self):
        """Rows: R8 (D-2-Q18: stdin is /dev/null; the environment is inherited)."""
        with mock.patch.dict(os.environ, {"EVIDENCE_PROBE": "yes"}):
            out, _ = self.with_cmd('test "$EVIDENCE_PROBE" = yes && ! read x # {id}')
        self.assertTrue(ok(out, "rerun." + F), out)

    def test_rerun_display_and_no_injection(self):
        """Rows: R10 (display forms)."""
        marker = os.path.join(self.tmp, "m")
        for test, disp in (("plain", "sh -c 'exit 1' plain"), ("a b", "sh -c 'exit 1' 'a b'"),
                           ("a;touch " + marker, "sh -c 'exit 1' 'a;touch %s'" % marker)):
            with self.subTest(test):
                out, code = self.with_cmd("sh -c 'exit 1' {id}", test=test)
                self.assertIn("FAIL evidence.rerun.%s: %s: exit 1" % (F, disp), out)
                self.assertFalse(os.path.exists(marker))
        out, code = self.with_cmd(["sh", "-c", "exit 1", "{id}"], test="a b")
        self.assertIn("FAIL evidence.rerun.%s: sh -c 'exit 1' 'a b': exit 1" % F, out)
        big = "9" * 4301
        out, code = self.with_cmd("sh -c 'exit 1' {id}", test=big)
        self.assertIn(big, line(out, "rerun." + F))

    def test_rerun_argument_too_long(self):
        """Rows: R16 C9 (OSError E2BIG is exit 127)."""
        out, code = self.with_cmd(["sh", "-c", "exit 0", "{id}"], test="x" * 2000000)
        self.assertIn("exit 127", line(out, "rerun." + F))

    def test_rerun_independent_of_other_lines(self):
        """Rows: R13 (D-2-Q19 (a): the re-run runs although package and transcript fail)."""
        self.make()
        self.pin(pkg={"test": "z"}, ttext=T(test="u"))
        self.put("fix.txt", "broken\n")
        out, code = self.run_()
        self.assertTrue(bad(out, "package." + F) and bad(out, "transcript." + F) and bad(out, "rerun." + F), out)

    def test_run_pin_exceptions_via_gate(self):
        """Rows: C9 V4 (the gate lets only render_pin-checked commands reach run_pin)."""
        self.make()
        self.pin()
        with mock.patch("gates.lib.evidence.run_pin", side_effect=ValueError("embedded null byte")):
            out, code = self.run_()
        self.input_fail(out, code, "ValueError")

    def test_run_pin_behaviour_same_on_both(self):
        """Rows: V4 (exit and signal codes of a shell string and of a list)."""
        out, _ = self.with_cmd("exit 3 # {id}")
        self.assertIn(": exit 3", out)

    def test_exit_code(self):
        """Rows: O6."""
        self.make()
        self.pin()
        self.assertEqual(self.run_()[1], 0)
        self.put("fix.txt", "broken\n")
        self.assertEqual(self.run_()[1], 1)

    def test_pass_lines_are_bare(self):
        """Rows: S4."""
        self.make()
        self.pin()
        out, _ = self.run_()
        for ln in out.splitlines():
            self.assertNotIn(":", ln)


# ======================================================================== version rows, producers 11
class Versions(Base):
    def test_exception_groups(self):
        """Rows: V3."""
        if not hasattr(builtins, "BaseExceptionGroup"):
            self.skipTest("BaseExceptionGroup is absent on this interpreter (3.9)")
        self.make()
        self.pin()
        group = getattr(builtins, "ExceptionGroup")("g", [ValueError()])
        # R4-3: the edb6aa7 target gitinfo.show (the pinned transcript is a regular entry, so its read reaches it) is kept
        for target in ("gates.lib.evidence.run_pin", "gates.lib.gitinfo.show", "gates.lib.tipread.show_file"):
            with self.subTest(target), mock.patch(target, side_effect=group):
                out, code = self.run_()
                self.assertTrue(out.startswith("FAIL evidence.input: ExceptionGroup: g (1 sub-exception)"), out)
        base = getattr(builtins, "BaseExceptionGroup")("g", [KeyboardInterrupt()])
        with mock.patch("gates.lib.evidence.run_pin", side_effect=base), self.assertRaises(BaseException):
            self.run_()

    def test_gate_source_is_version_neutral(self):
        """Rows: V3 (no except*, no bare ExceptionGroup name)."""
        with open(os.path.join(REPO, "gates", "gate_evidence.py"), encoding="utf-8") as fh:
            src = fh.read()
        compile(src, "gate_evidence.py", "exec")
        self.assertNotIn("except*", src)
        self.assertNotIn("ExceptionGroup", src)
        for banned in (".isprintable(", ".lower(", ".upper(", "unicodedata", ".casefold("):
            self.assertNotIn(banned, src)

    def test_argv_text_same_on_both(self):
        """Rows: V5 (the texts of A3-A9 are literal in Argv)."""
        self.make()
        out, _ = run_argv(["--root", self.work, "--root", self.work])
        self.assertEqual(out, "FAIL evidence.input: invalid arguments: --root given more than once\n")

    def test_row_order_same_on_both(self):
        """Rows: V6 (ids are ASCII; order is the sorted file name)."""
        self.make()
        for fid in (F3, F, F2):
            self.pin(fid)
        out, _ = self.run_()
        self.assertEqual([i for i in idsof(out) if i.startswith("package")], ["package." + x for x in (F, F2, F3)])

    def test_output_same_on_both_interpreters(self):
        """Rows: O10 (literal text for a failing fixture, as run on each interpreter)."""
        self.make()
        self.pin(pkg={"test": "z"})
        out, _ = self.run_()
        self.assertEqual(out.splitlines()[:3], ["PASS evidence.config", "PASS evidence.scope",
                                                "FAIL evidence.package.%s: review report %s: test: expected t, got z"
                                                % (F, "%s:%s/p/%s.md" % (git(self.work, "rev-parse", "HEAD~1"), REV, F))])

    def test_gate_schema_reads_evidence_kinds(self):
        """Rows: X3."""
        if "gates.gate_evidence" not in producers.PRODUCER_MODULES:
            self.skipTest("Rq-6-2 not on this branch")
        self.assertIn("gates.gate_evidence", producers.PRODUCER_MODULES)

    def test_run_all_lists_evidence(self):
        """Rows: X4."""
        if "evidence" not in run_all.BASE_GATES:
            self.skipTest("Rq-6-3 not on this branch")
        self.assertIn("evidence", run_all.PROFILE_GATES["standard"])
        self.assertIn("evidence", run_all.PROFILE_GATES["strict"])
        self.assertNotIn("evidence", run_all.PROFILE_GATES["light"])

    def test_run_all_forwards_base_to_evidence(self):
        """Rows: X5."""
        if "evidence" not in run_all.BASE_GATES:
            self.skipTest("Rq-6-4 not on this branch")
        self.assertIn("evidence", run_all.BASE_GATES)

    def test_self_adoption_has_evidence_lines(self):
        """Rows: X6."""
        if "evidence" not in run_all.PROFILE_GATES["strict"]:
            self.skipTest("Rq-6-3 not on this branch")
        out, _ = run_argv(["--root", REPO, "--base", "origin/main"])
        self.assertTrue(out.startswith("PASS evidence.config\nPASS evidence.scope"))


# ======================================================================== the 200-fixture generator (PC2)
class Generator(Base):
    DEFECTS = ("none", "pkg_test", "pkg_command", "pkg_transcript", "mutant_passes", "nested", "broken_tree", "no_evidence")

    def test_generated_fixtures(self):
        """Rows: oracle. 200 seeded findings in one strict repository, each with one defect; the expected lines come
        from a model that never imports gates.lib.evidence."""
        rng = random.Random(20261110)
        alphabet = "23456789abcdefghjkmnpqrstuvwxyz"
        seen = set()
        fixtures = []
        while len(fixtures) < 200:
            fid = "F-20261031-" + "".join(rng.choice(alphabet) for _ in range(4))
            if fid in seen:
                continue
            seen.add(fid)
            fixtures.append((fid, rng.choice(self.DEFECTS)))
        self.make()
        self.put("check.sh", 'case "$1" in broken*) exit 1;; esac\ngrep -q fixed fix.txt\n')
        commit_all(self.work, "check")
        for fid, defect in fixtures:
            test = "broken-" + fid if defect == "broken_tree" else "t-" + fid
            cmd = "sh check.sh " + test
            runs = ((1, "fix", 0), (2, "mutant", 0 if defect == "mutant_passes" else 1), (3, "fix", 0))
            tpath = (TDIR + "/d/" if defect == "nested" else TDIR + "/") + fid + ".md"
            self.put(tpath, T(fid, test, cmd, runs))
        tsha = commit_all(self.work, "transcripts")
        for fid, defect in fixtures:
            test = "broken-" + fid if defect == "broken_tree" else "t-" + fid
            tpath = (TDIR + "/d/" if defect == "nested" else TDIR + "/") + fid + ".md"
            ptest = test + "x" if defect == "pkg_test" else test
            pcmd = "sh check.sh " + test + ("x" if defect == "pkg_command" else "")
            ptr = "%s:%s" % (tsha[:7] if defect == "pkg_transcript" else tsha, tpath)
            self.put("%s/p/%s.md" % (REV, fid), RP(fid, ptr, ptest, pcmd))
        rsha = commit_all(self.work, "reports")
        for fid, defect in fixtures:
            test = "broken-" + fid if defect == "broken_tree" else "t-" + fid
            tpath = (TDIR + "/d/" if defect == "nested" else TDIR + "/") + fid + ".md"
            ev = [] if defect == "no_evidence" else ["%s:%s/p/%s.md" % (rsha, REV, fid)]
            self.put("%s/%s.yml" % (FIND, fid), emit(frow(fid, pin={"test": test, "transcript": "%s:%s" % (tsha, tpath)},
                                                          evidence=ev)))
        commit_all(self.work, "findings")
        out, code = self.run_()
        expect = ["PASS evidence.config", "PASS evidence.scope"]
        want_fail = False
        for fid, defect in sorted(fixtures):
            pk = defect in ("pkg_test", "pkg_command", "pkg_transcript", "no_evidence")
            tr = defect in ("pkg_command", "mutant_passes", "nested", "no_evidence")
            rr = defect == "broken_tree"
            want_fail = want_fail or pk or tr or rr
            for kind, failed in (("package", pk), ("transcript", tr), ("rerun", rr)):
                expect.append("%s evidence.%s.%s" % ("FAIL" if failed else "PASS", kind, fid))
        got = [ln.split(":", 1)[0] for ln in out.splitlines()]
        self.assertEqual(got, expect)
        self.assertEqual(code, 1 if want_fail else 0)


class ShowKinds(GitIsolatedTestCase):
    """Task 5b.3 row F15: ``gate_evidence._show`` on each entry kind at a revision."""

    def test_show_entry_kinds(self):
        root = make_repo(self.work)
        path = "docs/x.md"
        sha = set_entry(root, "refs/heads/main", path, "regular", "text\n")
        self.assertEqual(gate_evidence._show(root, sha, path), ("text\n", ""))
        absent = set_entry(root, "refs/heads/main", path, "absent")
        self.assertEqual(gate_evidence._show(root, absent, path), (None, "%s is not a regular file at %s" % (path, absent)))
        for kind, mode in BAD_KINDS:
            with self.subTest(kind):
                sha = set_entry(root, "refs/heads/main", path, kind, "text\n")
                self.assertEqual(gate_evidence._show(root, sha, path), (None, "%s:%s: %s" % (sha, path, refusal(sha, path))))


if __name__ == "__main__":
    unittest.main()
