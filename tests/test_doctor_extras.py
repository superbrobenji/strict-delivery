"""Tests of gates/tools/doctor.py (Task 4d.3): extras, git hooks, CI workflow and the two blocks. Every test runs the production path (``doctor.main`` / ``doctor.check``) on
a fixture repository; every ``gh`` is a fake script first on PATH; expected texts are hand-written from the plan lines and
the task-4d.3 domain table, whose row ids are named in each comment."""
import os
import shutil
from unittest import mock

from gates.lib import plugin, templates
from gates.lib.result import GateError
from gates.tools import doctor, githooks
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
        for name, edited in (("deleted", "\n".join(text.split("\n")[:-3]) + "\n"),
                             ("added", text + "# x\n"), ("space", text.replace("\n", " \n", 6).replace(" \n", "\n", 1)),
                             ("nofinal", text.rstrip("\n")),
                             ("tab", text.replace("  ", "\t", 1))):
            self.write(WF, edited)
            with self.subTest(edit=name):
                self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
        # CI13: an older template, the current render with the P3 step "Create the local base branch" removed
        step = "      - name: Create the local base branch\n"
        self.assertEqual(text.count(step), 2)  # the matrix job and the pull-request job each hold one (E16 :28-33, :54-58)
        rows = text.split("\n")
        at = [i for i, ln in enumerate(rows) if ln + "\n" == step]
        self.assertEqual(len(at), 2)
        self.assertEqual(rows[at[0] + 1], "        if: github.event_name == 'pull_request'")
        self.assertIn("git branch", rows[at[0] + 5])
        for name, drop in (("first", at[:1]), ("second", at[1:]), ("both", at)):
            kept = [ln for i, ln in enumerate(rows) if not any(a <= i < a + 6 for a in drop)]
            self.assertEqual(len(rows) - len(kept), 6 * len(drop))
            self.write(WF, "\n".join(kept))
            with self.subTest(removed=name):
                self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
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

    def by_id(self):
        return {ln.split(":")[0].split(" ", 1)[1]: ln for ln in self.lines()}

    def test_doctor_plugin_unreadable_dependents_include_ci(self):  # CD9, CB15, CI15 (survivor D115-ci-version-failed-line)
        # every state of the manifest that makes doctor.version fail (VE3, VE4), with a managed workflow installed: the
        # three lines that need the plugin value each say so and none of them is judged
        self.managed_ci()
        mpath = os.path.join(self.fw, ".claude-plugin", "plugin.json")
        gone = os.path.join(self.tmp, "gone.json")
        cases = [("absent", None), ("directory", "dir"), ("dangling-symlink", "link"),
                 ("invalid-json", b"{"), ("non-utf8", b"\xff\xfe"),
                 ("duplicate-keys", b'{"version": "0.1.0", "version": "0.1.0"}'), ("no-version", b'{"name": "x"}'),
                 ("int", b'{"version": 1}'), ("v-prefix", b'{"version": "v0.1.0"}'),
                 ("leading-zero", b'{"version": "01.0.0"}'), ("two-parts", b'{"version": "0.1"}'),
                 ("leading-space", b'{"version": " 0.1.0"}'), ("trailing-newline", b'{"version": "0.1.0\\n"}'),
                 ("suffix", b'{"version": "0.1.0-rc1"}')]
        if os.geteuid() != 0:
            cases.append(("mode000", "mode000"))
        for name, how in cases:
            if os.path.lexists(mpath):
                clear(mpath)
            if how is None:
                pass
            elif how == "dir":
                os.mkdir(mpath)
            elif how == "link":
                os.symlink(gone, mpath)
            elif how == "mode000":
                put(mpath, b'{"version": "0.1.0", "repository": "https://github.com/o/n"}')
                os.chmod(mpath, 0)
            else:
                put(mpath, how)
            with self.subTest(manifest=name):
                found = self.by_id()
                self.assertTrue(found["doctor.version"].startswith("FAIL doctor.version: "), found["doctor.version"])
                self.assertEqual(found["doctor.extras"], "PASS doctor.extras: git hooks: not installed; CI: installed")
                for id_ in ("ci", "claude-block", "gitignore-block"):
                    self.assertEqual(found["doctor." + id_], "FAIL doctor.%s: not checked: doctor.version failed" % id_)
        if os.path.lexists(mpath):
            clear(mpath)
        # control: a symlink to a valid manifest loads (VE4), so the workflow is judged and passes
        put(gone, b'{"version": "0.1.0", "repository": "https://github.com/o/n"}')
        os.symlink(gone, mpath)
        found = self.by_id()
        self.assertEqual(found["doctor.version"], "PASS doctor.version")
        self.assertEqual(found["doctor.ci"], "PASS doctor.ci")

    def test_doctor_extras_gateerror_reason_is_its_own_text(self):  # CK7, CD4 (survivor D117-why-guard-text), real fixture
        # core.hooksPath holding bytes that are not UTF-8: gitinfo.hooks_dir raises GateError("git rev-parse --git-path
        # hooks gave output that is not valid UTF-8"); the extras line shows that text with no `GateError: ` prefix
        with open(os.path.join(self.r, ".git", "config"), "ab") as fh:
            fh.write(b"[core]\n\thooksPath = \xff\xfe\n")
        found = self.by_id()
        self.assertEqual(found["doctor.extras"], "FAIL doctor.extras: cannot be checked: git rev-parse --git-path hooks "
                                                 "gave output that is not valid UTF-8")
        self.assertEqual(len(found), len(ROOT_ID))  # the other lines are still computed; no githooks line follows
        self.assertEqual(found["doctor.version"], "PASS doctor.version")
        self.assertEqual(found["doctor.registers"], "PASS doctor.registers")

    def test_doctor_extras_gateerror_reason_per_producer(self):  # CK7, CD4 (survivor D117-why-guard-text), patched producers
        # the producers the extras computation calls that can raise GateError: gitinfo.hooks_dir (the real fixture above:
        # a non-UTF-8 hooksPath; a root that is not the top level is refused earlier, as doctor.input), `_locate` through
        # `_common_dir` (git answering non-UTF-8 for the git common dir needs a non-UTF-8 git dir, on which hooks_dir
        # fails first: patched), `_hooks_installed` and `_dir_safe` (no GateError in the code: patched, as CK7 allows).
        # `_extras` and the CI kind (`_Ci`, computed outside the guard) raise none.
        boom = GateError("no way to ask git")
        for name, target in (("hooks_dir", (doctor.gitinfo, "hooks_dir")), ("common_dir", (doctor, "_common_dir")),
                             ("hooks_installed", (doctor, "_hooks_installed")), ("dir_safe", (doctor, "_dir_safe"))):
            with self.subTest(producer=name), mock.patch.object(target[0], target[1], side_effect=boom):
                found = self.by_id()
                self.assertEqual(found["doctor.extras"], "FAIL doctor.extras: cannot be checked: no way to ask git")
                self.assertEqual(len(found), len(ROOT_ID))
                self.assertEqual(found["doctor.version"], "PASS doctor.version")

    def test_doctor_extras_other_exception_reason_names_its_class(self):  # CK7, CD4 (the other branch of `_why`)
        for name, target in (("hooks_dir", (doctor.gitinfo, "hooks_dir")), ("hooks_installed", (doctor, "_hooks_installed"))):
            with self.subTest(producer=name), mock.patch.object(target[0], target[1], side_effect=RuntimeError("boom")):
                self.assertEqual(self.line("extras"), "FAIL doctor.extras: cannot be checked: RuntimeError: boom")

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

    def test_blocks_stale_when_body_differs_only_at_its_end(self):  # CB10, GI7 (survivor D29-block-body-stripped)
        for id_, rel, build, op, cl in self.cases():
            body = templates.claude_block_body(self.cfg()) if id_ == "claude-block" else templates.gitignore_block_body(self.cfg())
            self.assertTrue(body.endswith("\n") and not body.endswith("\n\n"))
            want = "FAIL doctor.%s: stale; run /strict-delivery:upgrade" % id_
            # the last body line carries one trailing whitespace character (a CRLF ends it with "\r": lines split on "\n" only)
            for name, ws in (("space", " "), ("two-spaces", "  "), ("tab", "\t"), ("crlf", "\r"), ("vtab", "\x0b"),
                             ("formfeed", "\x0c"), ("nbsp", "\xa0"), ("emspace", " ")):
                self.write(rel, build(body=body[:-1] + ws + "\n"))
                with self.subTest(file=rel, last_line_ends_with=name):
                    self.assertEqual(self.line(id_), want)
            # extra whitespace-only lines after the last body line
            for name, extra in (("blank", "\n"), ("two-blank", "\n\n"), ("space-line", " \n"), ("tab-line", "\t\n"),
                                ("crlf-line", "\r\n")):
                self.write(rel, build(body=body + extra))
                with self.subTest(file=rel, extra_after_body=name):
                    self.assertEqual(self.line(id_), want)
            # the block format cannot hold a body without its final newline: the end marker then shares the last body
            # line, so find_block sees no end marker (malformed, not stale)
            self.write(rel, build(body=body[:-1]))
            with self.subTest(file=rel, final_newline_removed=True):
                self.assertEqual(self.line(id_), "FAIL doctor.%s: malformed: block: no end marker" % id_)
            self.write(rel, build(body=body))
            self.assertEqual(self.line(id_), "PASS doctor.%s" % id_)

    def test_blocks_stale_when_body_differs_at_its_start(self):  # CB10, GI7 (NR-1, survivor of D29: body.lstrip() compare)
        for id_, rel, build, op, cl in self.cases():
            body = templates.claude_block_body(self.cfg()) if id_ == "claude-block" else templates.gitignore_block_body(self.cfg())
            want = "FAIL doctor.%s: stale; run /strict-delivery:upgrade" % id_
            # one whitespace character in front of the first body line
            for name, ws in (("space", " "), ("two-spaces", "  "), ("tab", "\t"), ("vtab", "\x0b"), ("formfeed", "\x0c"),
                             ("nbsp", "\xa0"), ("emspace", " ")):
                self.write(rel, build(body=ws + body))
                with self.subTest(file=rel, first_line_starts_with=name):
                    self.assertEqual(self.line(id_), want)
            # one whitespace-only line in front of the first body line
            for name, extra in (("blank", "\n"), ("space-line", " \n"), ("tab-line", "\t\n"), ("crlf-line", "\r\n")):
                self.write(rel, build(body=extra + body))
                with self.subTest(file=rel, line_before_body=name):
                    self.assertEqual(self.line(id_), want)
            self.write(rel, build(body=body))
            self.assertEqual(self.line(id_), "PASS doctor.%s" % id_)

    def test_blocks_version_text_extension_differs(self):  # CB9 (NR-3, survivor: block.version.startswith(plugin version))
        # the marker's version pattern is [0-9]+.[0-9]+.[0-9]+, so the plugin text 0.1.0 can be extended only by more
        # digits of the last part: those are accepted by the marker and are unequal text
        for id_, rel, build, op, cl in self.cases():
            for pv in ("0.1.00", "0.1.01", "0.1.09", "0.1.0" + "0" * 10, "0.1.0" + "9" * 30):
                self.write(rel, build(pv=pv))
                with self.subTest(file=rel, version=pv):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: version %s differs from the plugin 0.1.0" % (id_, pv))
            # every other extension of 0.1.0 is refused by the marker pattern, before the version compare
            for pv in ("0.1.0.1", "0.1.0-rc1", "0.1.0 ", "0.1.0a", "0.1.0١", "0.1.0０"):
                self.write(rel, build(pv=pv))
                with self.subTest(file=rel, version=pv):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: malformed: block: begin marker malformed: line 1" % id_)
            # the other direction: the block's text a proper prefix of the plugin's (plugin 0.1.10, block 0.1.1)
            self.fw = self.mkfw("0.1.10", name="fw10")
            with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
                self.write(rel, build(pv="0.1.1"))
                with self.subTest(file=rel, version="0.1.1", plugin="0.1.10"):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: version 0.1.1 differs from the plugin 0.1.10" % id_)
            self.fw = self.mkfw(PV)

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
