"""Tests of gates/tools/doctor.py (Task 4d.3): extras, git hooks, CI workflow and the two blocks. Every test runs the production path (``doctor.main`` / ``doctor.check``) on
a fixture repository; every ``gh`` is a fake script first on PATH; expected texts are hand-written from the plan lines and
the task-4d.3 domain table, whose row ids are named in each comment."""
import os
import shutil
from unittest import mock

from gates.lib import plugin, templates
from gates.tools import githooks
from tests.helpers import commit_all, git, make_repo
from tests.doctor_base import Base, PV, ROOT_ID, SHA40, WF, clear, put


# ---------------------------------------------------------------------------------------------------- extras, hooks, ci
class TestExtras(Base):
    def test_neither_extra_says_so(self):  # EX1 (plan), EX24
        self.assertIn("PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions",
                      self.run_doctor()[1])
        lines = [ln for ln in self.lines() if "githooks" in ln or "doctor.ci" in ln]
        self.assertEqual(lines, [])

    def test_doctor_extras_combinations(self):  # EX2, EX3, EX4, EX5, EX6, EX8, EX14, EX15, OUT2, OUT3, GH1, CI3
        self.shims()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: not installed")
        ids = [ln.split(":")[0].split(" ")[1] for ln in self.lines()]
        self.assertEqual(ids[4:7], ["doctor.extras", "doctor.githooks.pre-commit", "doctor.githooks.pre-push"])
        self.assertEqual(self.line("githooks.pre-push"), "PASS doctor.githooks.pre-push")
        self.managed_ci()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: installed")
        ids = [ln.split(":")[0].split(" ")[1] for ln in self.lines()]
        self.assertEqual(ids[4:8], ["doctor.extras", "doctor.githooks.pre-commit", "doctor.githooks.pre-push", "doctor.ci"])
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        hooks = os.path.join(self.r, ".git", "hooks")
        os.unlink(os.path.join(hooks, "pre-push"))  # one hook of two
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: installed")
        self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: missing")
        os.unlink(os.path.join(hooks, "pre-commit"))
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: not installed; CI: installed")
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])  # GH7

    def test_doctor_extras_foreign_and_stale_hooks(self):  # EX6, EX7, EX8, EX9, EX10, GH3, GH4, GH5, GH14
        hooks = os.path.join(self.r, ".git", "hooks")
        for n in githooks.NAMES:
            self.write(".git/hooks/" + n, "#!/bin/sh\necho hi\n", mode=0o755)
        self.write(".git/hooks/pre-commit.sample", "#!/bin/sh\n")
        self.assertEqual(self.line("extras"), "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions")
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])
        for n in githooks.NAMES:
            os.unlink(os.path.join(hooks, n))
        self.shims()
        self.write(".git/hooks/pre-commit", "#!/bin/sh\necho mine\n", mode=0o755)
        self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: foreign")
        self.assertEqual(self.line("githooks.pre-push"), "PASS doctor.githooks.pre-push")
        self.shims() if False else None
        os.unlink(os.path.join(hooks, "pre-commit"))
        self.shims()
        path = os.path.join(hooks, "pre-push")
        with open(path, "a") as fh:
            fh.write("# more\n")
        self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: stale")
        self.assertIn("git hooks: installed", self.line("extras"))
        self.shims() if False else os.unlink(path)
        self.shims()
        for mode in (0o644, 0o700, 0o775, 0o777):
            os.chmod(path, mode)
            self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: stale", oct(mode))
        os.chmod(path, 0o755)
        with open(path) as fh:
            first, header, rest = fh.read().split("\n", 2)
        for name, text in (("line1", header + "\n" + first + "\n" + rest), ("line3", "#!/bin/sh\n\n" + header + "\n"),
                           ("trailing", first + "\n" + header + " \n" + rest), ("crlf", first + "\r\n" + header + "\r\n" + rest),
                           ("bom", "﻿" + first + "\n" + header.upper() + "\n")):
            for n in githooks.NAMES:
                self.write(".git/hooks/" + n, text, mode=0o755)
            with self.subTest(form=name):
                self.assertIn("neither extra installed", self.line("extras"))

    def test_doctor_extras_hook_file_states(self):  # EX9, EX11, FS5, GH16
        hooks = os.path.join(self.r, ".git", "hooks")
        target = os.path.join(self.tmp, "t")
        self.write("t", "x", root=self.tmp)
        for name, make in (("symlink", lambda p: os.symlink(target, p)), ("dangling", lambda p: os.symlink(target + "x", p)),
                           ("dir", os.mkdir), ("fifo", os.mkfifo)):
            for n in githooks.NAMES:
                make(os.path.join(hooks, n))
            with self.subTest(state=name):
                self.assertIn("neither extra installed", self.line("extras"))
            for n in githooks.NAMES:
                p = os.path.join(hooks, n)
                clear(p)
        for n in githooks.NAMES:  # EX11: no hooks directory
            pass
        shutil.rmtree(hooks)
        self.assertIn("neither extra installed", self.line("extras"))

    def test_doctor_hooks_path_bypass_and_set(self):  # GH8, GH9, GH10, GH11
        self.shims()
        git(self.r, "config", "core.hooksPath", "other")
        lines = self.lines()
        self.assertIn("FAIL doctor.githooks.hooks-path: core.hooksPath is set (other); unset it to install the hooks", lines)
        self.assertIn("PASS doctor.extras: git hooks: installed; CI: not installed", lines)
        git(self.r, "config", "--unset", "core.hooksPath")
        git(self.r, "config", "core.hooksPath", "myhooks")
        os.makedirs(os.path.join(self.r, "myhooks"))
        for n in githooks.NAMES:
            self.write("myhooks/" + n, githooks.shim(n, githooks.framework_dir()).decode() if isinstance(githooks.shim(n, githooks.framework_dir()), bytes) else githooks.shim(n, githooks.framework_dir()), mode=0o755)
        lines = self.lines()
        self.assertIn("PASS doctor.githooks.pre-commit", lines)
        self.assertIn("FAIL doctor.githooks.hooks-path: core.hooksPath is set (myhooks); unset it to install the hooks", lines)
        git(self.r, "config", "core.hooksPath", "")
        self.assertIn("hooks-path: core.hooksPath is set ()", "\n".join(self.lines()))
        git(self.r, "config", "--unset", "core.hooksPath")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                                          "GIT_CONFIG_VALUE_0": "envhooks"}):
            self.assertIn("doctor.githooks.hooks-path", "\n".join(self.lines()))
        self.assertNotIn("hooks-path", "\n".join(self.lines()))

    def test_doctor_githooks_bad_framework_path(self):  # GH13, GH6
        self.shims()
        with mock.patch.object(githooks, "framework_dir", return_value="relative/path"):
            lines = self.lines()
        self.assertIn("FAIL doctor.githooks.framework: the framework path must be absolute and hold no control character", lines)
        self.assertEqual(len(lines), 14)
        with mock.patch.object(githooks, "framework_dir", return_value="/some/other/framework"):
            self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: stale")

    def test_doctor_extras_project_workflow_named(self):  # EX13, EX14, EX15, EX18, EX19, EX21, CI2
        self.write(WF, "name: strict-delivery\non: push\n")
        named = "CI: .github/workflows/strict-delivery.yml is a project workflow, not the framework template"
        self.assertEqual(self.line("extras"),
                         "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions; " + named)
        self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])
        self.shims()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; " + named)
        for text in ("", "﻿# strict-delivery: generated by x; do not edit\n", "# strict-delivery: generated by x; do not edit\r\n",
                     "  # strict-delivery: generated by x; do not edit\n", "# Strict-Delivery: generated by x; do not edit\n",
                     "a\nb\n# strict-delivery: generated by x; do not edit\n"):
            self.write(WF, text)
            with self.subTest(text=text):
                self.assertIn("project workflow", self.line("extras"))
        self.write(WF, "#!/usr/bin/env x\n# strict-delivery: generated by x; do not edit\n")  # EX16, EX17
        self.assertIn("CI: installed", self.line("extras"))
        self.write(WF, "# strict-delivery: generated by other-tool; do not edit\n")
        self.assertIn("CI: installed", self.line("extras"))
        os.unlink(os.path.join(self.r, WF))
        self.write(".github/workflows/strict-delivery.yaml", "x")
        self.assertIn("CI: not installed", self.line("extras"))

    def test_doctor_extras_workflow_file_states(self):  # EX20, CI20, FS4
        p = os.path.join(self.r, WF)
        os.makedirs(os.path.dirname(p))
        cases = [("symlink", lambda: os.symlink(os.path.join(self.tmp, "x"), p), "is a symlink"),
                 ("directory", lambda: os.mkdir(p), "is not a regular file"),
                 ("fifo", lambda: os.mkfifo(p), "is not a regular file"),
                 ("nonutf8", lambda: put(p, b"\xff\xfe"), "is not valid UTF-8")]
        if os.geteuid() != 0:
            cases.append(("mode000", lambda: (put(p), os.chmod(p, 0)), "cannot be read (Permission denied)"))
        self.shims()
        for name, make, frag in cases:
            if os.path.lexists(p):
                clear(p)
            make()
            with self.subTest(state=name):
                self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: %s" % (WF, frag))
                self.assertIn("PASS doctor.githooks.pre-commit", self.lines())
                self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])
        os.unlink(p)
        os.rmdir(os.path.dirname(p))
        os.rmdir(os.path.dirname(os.path.dirname(p)))
        self.write(".github", "a file")
        self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: parent .github is not a directory" % WF)

    def test_ci_pin_mismatch(self):  # CI5 (plan), CI6, CI9, CI10, CI11, CI12, CI13, CI14, CI21
        self.managed_ci(pin="v0.0.9")
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.9 differs from v0.1.0")
        self.managed_ci(pin=SHA40)
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin %s differs from v0.1.0" % SHA40)
        text = self.managed_ci()
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        for name, edited in (("deleted", text.replace("\n", "", 1) if False else "\n".join(text.split("\n")[:-3]) + "\n"),
                             ("added", text + "# x\n"), ("space", text.replace("\n", " \n", 6).replace(" \n", "\n", 1)),
                             ("nofinal", text.rstrip("\n")),
                             ("tab", text.replace("  ", "\t", 1))):
            self.write(WF, edited)
            with self.subTest(edit=name):
                got = self.line("ci") if "managed" else ""
                self.assertIn(got, ("FAIL doctor.ci: stale",) if name not in ("crlf",) else (got,))
        self.write(WF, text.replace("v0.1.0", "v0.0.9") + "# edit\n")  # CI10: the pin message wins
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.9 differs from v0.1.0")
        lines = text.split("\n")
        fetch = [i for i, ln in enumerate(lines) if "git fetch --depth 1" in ln]
        self.assertEqual(len(fetch), 1)
        for name, edited in (("nofetch", "\n".join(lines[:fetch[0]] + lines[fetch[0] + 1:])),
                             ("two", "\n".join(lines + [lines[fetch[0]]])),
                             ("branch", text.replace("v0.1.0", "main")), ("short", text.replace("v0.1.0", "v0.1"))):
            self.write(WF, edited)
            with self.subTest(pin=name):
                self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin not found differs from v0.1.0")
        self.managed_ci(repo="a/b")  # CI12
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
        text = self.managed_ci()  # CI14 diverges: ci_workflow renders cfg base_branch, so the verdict follows it
        self.set_cfg(base_branch="develop")
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
        self.managed_ci()
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        self.write(WF, text.replace("\n", "\r\n"))  # EX18: CRLF text has no header line, so a project workflow
        self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])

    def test_doctor_ci_sha_pin_and_framework_moved(self):  # CI4, CI7, CI8, CI16, CI17, CI18
        self.fw = self.mkfw("0.0.0", name="fwgit")
        git(self.fw, "init", "-q", "-b", "main")
        sha1 = commit_all(self.fw, "one")
        self.set_cfg(framework_version="0.0.0")
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            git(self.fw, "config", "color.ui", "always")
            git(self.fw, "config", "core.abbrev", "7")
            self.managed_ci(pin=sha1)
            self.assertEqual(self.line("ci"), "PASS doctor.ci")
            self.managed_ci(pin="v0.0.0")
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.0 differs from %s" % sha1)
            self.managed_ci(pin=sha1)
            sha2 = commit_all(self.fw, "two")
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin %s differs from %s" % (sha1, sha2))
        self.fw = self.mkfw("0.0.0", name="fwplain")  # not a git checkout, no pin possible
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: no release tag and no framework commit to pin")
        outer = os.path.join(self.tmp, "outer")  # CI17: the framework is a subdirectory of another repository
        os.makedirs(outer)
        make_repo(outer)
        inner = self.mkfw("0.0.0", name="outer/inner")
        with mock.patch.object(plugin, "framework_dir", return_value=inner):
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: no release tag and no framework commit to pin")

    def test_doctor_ci_plugin_unreadable(self):  # CI15
        self.managed_ci()
        self.fw = self.mkfw(PV, repository="http://x")
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            self.assertTrue(self.line("ci").startswith("FAIL doctor.ci: .claude-plugin/plugin.json: repository"))


# ---------------------------------------------------------------------------------------------------- blocks
class TestBlocks(Base):
    def cases(self):
        return (("claude-block", "CLAUDE.md", self.claude, "<!-- ", " -->"),
                ("gitignore-block", ".gitignore", self.ignore, "# ", ""))

    def test_blocks_current_missing_malformed(self):  # CB1, CB2, CB3, CB4, CB11, GI1, GI2, GI3, GI4, OUT1
        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: missing")
        self.assertEqual(self.line("gitignore-block"), "FAIL doctor.gitignore-block: missing")
        self.green()
        code, out, _ = self.run_doctor()
        self.assertEqual((code, [ln.split(":")[0] for ln in out.splitlines()]), (0, ["PASS " + i for i in ROOT_ID]))
        for id_, rel, build, op, cl in self.cases():
            begin = "%sstrict-delivery:begin schema=%s/1 version=%s%s\n" % (op, id_, PV, cl)
            end = "%sstrict-delivery:end%s\n" % (op, cl)
            for name, text, want in (("empty", "", "missing"), ("plain", "my text mentions strict-delivery\n", "missing"),
                                     ("beginonly", begin, "malformed: block: no end marker"),
                                     ("endonly", end, "malformed: block: end marker before begin marker: line 1"),
                                     ("two", begin + begin + end, "malformed: block: more than one begin marker"),
                                     ("twoends", begin + end + end, "malformed: block: more than one end marker"),
                                     ("reversed", end + begin, "malformed: block: end marker before begin marker: line 1"),
                                     ("indent", " " + begin + end, "malformed: block: begin marker malformed: line 1"),
                                     ("crlf", begin.replace("\n", "\r\n") + end, "malformed: block: begin marker malformed: line 1"),
                                     ("endtrail", begin + end.rstrip("\n") + " x\n", "malformed: block: end marker malformed: line 2")):
                self.write(rel, text)
                with self.subTest(file=rel, form=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: %s" % (id_, want))
            self.write(rel, build(outside="project text\r\n\x00\n") + "after\n")  # CB11, GI8: outside text is free
            self.assertEqual(self.line(id_), "PASS doctor.%s" % id_)

    def test_blocks_schema_tag_version_stale(self):  # CB5, CB6, CB7, CB8, CB9, CB10, GI5, GI6, GI7
        for id_, rel, build, op, cl in self.cases():
            other = "gitignore-block" if id_ == "claude-block" else "claude-block"
            for tag in ("%s/0" % id_, "%s/2" % id_, "%s/7" % id_, "%s/1" % id_ + "0" * 5, "%s/1" % other):
                self.write(rel, build().replace("schema=%s/1" % id_, "schema=" + tag))
                with self.subTest(file=rel, tag=tag):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: malformed: schema: expected %s/1, got %s; run /strict-delivery:upgrade" % (id_, id_, tag))
            for pv in ("0.0.0", "0.2.0", "01.1.0"):
                self.write(rel, build(pv=pv))
                self.assertEqual(self.line(id_), "FAIL doctor.%s: version %s differs from the plugin 0.1.0" % (id_, pv))
            good = build()
            lines = good.split("\n")
            body = templates.claude_block_body(self.cfg()) if id_ == "claude-block" else templates.gitignore_block_body(self.cfg())
            bl = body.split("\n")
            for name, new in (("changed", [bl[0] + "x"] + bl[1:]), ("added", bl[:-1] + ["extra", ""]),
                              ("removed", bl[1:]), ("reordered", [bl[1], bl[0]] + bl[2:]),
                              ("trailing", [bl[0] + " "] + bl[1:]), ("empty", [""]), ("nul", [bl[0] + "\x00"] + bl[1:])):
                self.write(rel, build(body="\n".join(new)))
                with self.subTest(file=rel, edit=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: stale; run /strict-delivery:upgrade" % id_)
            self.write(rel, build(pv="0.0.0", body="x\n"))  # CB8: version before stale
            self.assertIn("version 0.0.0 differs", self.line(id_))

    def test_stale_block_fails_naming_upgrade(self):  # CB10 (plan)
        self.write("CLAUDE.md", self.claude(body=templates.claude_block_body(self.cfg()) + "extra line\n"))
        self.assertIn("FAIL doctor.claude-block: stale; run /strict-delivery:upgrade", self.run_doctor()[1])
        self.set_cfg(paths={"specs": "elsewhere/specs"})  # CB10: a config path changed after the block was written
        self.write("CLAUDE.md", self.claude())
        self.set_cfg(paths={"specs": "docs/other"})
        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: stale; run /strict-delivery:upgrade")

    def test_blocks_file_states_and_render_refused(self):  # CB13, GI9, CB14, GI10, CB12, FS2, FS3
        if os.geteuid() == 0:
            self.skipTest("root")
        for id_, rel, build, op, cl in self.cases():
            p = os.path.join(self.r, rel)
            for name, make, frag in (("symlink", lambda: os.symlink(os.path.join(self.tmp, "x"), p), "is a symlink"),
                                     ("dir", lambda: os.mkdir(p), "is not a regular file"),
                                     ("fifo", lambda: os.mkfifo(p), "is not a regular file"),
                                     ("nonutf8", lambda: put(p, b"\xff"), "is not valid UTF-8"),
                                     ("mode000", lambda: (put(p), os.chmod(p, 0)), "cannot be read (Permission denied)")):
                if os.path.lexists(p):
                    clear(p)
                make()
                with self.subTest(file=rel, state=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: %s: %s" % (id_, rel, frag))
            os.chmod(p, 0o644)
            os.unlink(p)
        self.write("CLAUDE.md", "```\n" + self.claude() + "```\n")  # CB12: markers in a code fence still read
        self.assertEqual(self.line("claude-block"), "PASS doctor.claude-block")
        self.set_cfg(paths={"specs": "a`b"})
        self.write("CLAUDE.md", self.claude(body="x\n"))
        self.assertTrue(self.line("claude-block").startswith("FAIL doctor.claude-block: cannot render the block: "))
        self.set_cfg(paths={"index": "#bad"})
        self.write(".gitignore", self.ignore(body="x\n"))
        self.assertTrue(self.line("gitignore-block").startswith("FAIL doctor.gitignore-block: cannot render the block: "))
