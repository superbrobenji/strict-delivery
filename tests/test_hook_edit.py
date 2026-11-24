"""Tests of the Edit/Write PreToolUse handler ``gates/hooks/pre_edit.py`` (Task 3c.1: rows T, U, HD, HS, HC, HA, V and the
hardening rows HR of ``task-3c.1-domain.md``). Entry verdicts run through ``tests/hookrun.py``, the production entry
``python3 -m gates hook PreToolUse``, on ``make_repo`` repositories; ``target`` and ``under_decisions`` are called
directly only for the pure rows. Expected values are written by hand from the plan and the table, never read from the
code. Failures that cannot be made with real files (a raising ``Store.load`` or ``session.locked``) are injected by a
``sitecustomize`` on the PYTHONPATH of the subprocess. Values are synthetic."""
import ast
import builtins
import fcntl
import itertools
import json
import os
import pathlib
import posixpath
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from gates.hooks import pre_edit
from gates.lib import decisions, yamlsub
from gates.lib.hookio import HookContext
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, git, make_repo, minimal_config, watched, write_record
from tests.hookrun import FW, payload, run_hook

D = ".strict-delivery/state/decisions"
DEC1, DEC2, DEC3 = "DEC-20261101-k3f9", "DEC-20261101-m4n5", "DEC-20261101-p6q7"
OPTS = [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}]
SHA = "a1b2c3d"
TAIL = "; the strict-delivery hook fails closed; the human can disable the plugin with /plugin, and !-prefixed commands still run"
IN_TAIL = ("; the Edit and Write tools need a non-empty string path in the tool's own field (file_path; notebook_path "
           "for NotebookEdit)")
TAG = "decision/%d" % decisions._schema().version


def DENY(p):
    return ("FAIL hook.edit.decisions: " + p + ": decision records are written only by python3 -m gates decisions "
            "(owner answer Q-16 (a)); answers and withdrawals come from the human\n")


def INP(r):
    return "FAIL hook.edit.input: " + r + IN_TAIL + "\n"


def IF(i, text="rule text", cites="CLAUDE.md"):
    return "in-force %s: %s; landed_in %s" % (i, text, cites)


def dec(i, status="answered", **over):
    r = {"schema": TAG, "id": i, "status": status, "class": "scope", "question": "Keep X?", "options": OPTS,
         "asked_at": SHA, "asked_by": "agent", "topics": ["ids"], "applies_to": ["src/*"], "checked_against": [],
         "effect": "lasting", "rule": "rule text", "landed_in": ["CLAUDE.md"]}
    if status == "answered":
        r.update(answer="Yes", answered_at={"at": SHA, "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": SHA, "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return {k: v for k, v in r.items() if v is not None}


def mkctx(tool, ti, cwd="/w/repo"):
    return HookContext(event="PreToolUse", tool_name=tool, tool_input=ti, session_id="sess-1", agent_id=None,
                       transcript_path=None, cwd=cwd, root=cwd, cfg=None, cfg_error=None, framework_dir=FW, env={},
                       raw={})


def ctx(p):
    """The ``additionalContext`` of a pass (exit 0, no stderr), ``""`` when stdout is empty."""
    assert p.returncode == 0 and p.stderr == "", (p.returncode, p.stderr)
    if p.stdout == "":
        return ""
    body = json.loads(p.stdout)
    assert list(body) == ["hookSpecificOutput"] and body["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert list(body["hookSpecificOutput"]) == ["hookEventName", "additionalContext"]
    return body["hookSpecificOutput"]["additionalContext"]


def ctx_lines(p):
    c = ctx(p)
    return c.split("\n") if c else []


SITE = ("import json, os\n"
        "spec = os.environ.get('HOOKTEST_PATCH')\n"
        "if spec:\n"
        "    import builtins, importlib\n"
        "    class EG(Exception):\n"
        "        pass\n"
        "    EG.__name__ = 'ExceptionGroup'\n"
        "    class BG(BaseException):\n"
        "        pass\n"
        "    BG.__name__ = 'BaseExceptionGroup'\n"
        "    def make(kind, msg):\n"
        "        if kind == 'Exception': return Exception(msg)\n"
        "        if kind == 'OSError': return OSError(msg)\n"
        "        if kind == 'ValueError': return ValueError(msg)\n"
        "        if kind == 'KeyboardInterrupt': return KeyboardInterrupt(msg)\n"
        "        if kind == 'SystemExit0': return SystemExit(0)\n"
        "        if kind == 'ExceptionGroup':\n"
        "            return builtins.ExceptionGroup(msg, [OSError('x')]) if hasattr(builtins, 'ExceptionGroup') else EG(msg)\n"
        "        if kind == 'BaseExceptionGroup':\n"
        "            return builtins.BaseExceptionGroup(msg, [KeyboardInterrupt()]) if hasattr(builtins, 'BaseExceptionGroup') else BG(msg)\n"
        "        raise ValueError(kind)\n"
        "    for modname, attrs, kind, msg in json.loads(spec):\n"
        "        obj = importlib.import_module(modname)\n"
        "        parts = attrs.split('.')\n"
        "        for part in parts[:-1]:\n"
        "            obj = getattr(obj, part)\n"
        "        def raiser(*a, _k=kind, _m=msg, **kw):\n"
        "            raise make(_k, _m)\n"
        "        setattr(obj, parts[-1], raiser)\n")

HAS_EG = hasattr(builtins, "ExceptionGroup")
HAS_BG = hasattr(builtins, "BaseExceptionGroup")


class Base(GitIsolatedTestCase):
    CFG = None

    def setUp(self):
        super().setUp()
        self.repo = self.newrepo("repo", self.CFG)
        self.data = os.path.join(self.tmp, "plugin-data")
        os.makedirs(self.data)
        self.fx = os.path.join(self.tmp, "fx")
        os.makedirs(self.fx)
        with open(os.path.join(self.fx, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write(SITE)

    def newrepo(self, name, cfg=None):
        root = os.path.join(self.work, name)
        os.makedirs(root)
        return make_repo(root, cfg)

    def env(self, data="", patch=None):
        e = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
        if data == "":
            e["CLAUDE_PLUGIN_DATA"] = self.data
        elif data is not None:
            e["CLAUDE_PLUGIN_DATA"] = data
        if patch:
            e["PYTHONPATH"] = self.fx + os.pathsep + FW
            e["HOOKTEST_PATCH"] = json.dumps(patch)
        return e

    def edit(self, path, tool="Edit", cwd=None, env=None, agent=False, session=None, root=None, ti=None):
        if session is None:   # one session per repository, so repositories sharing the plugin-data directory stay apart
            session = "sess-1" if root is None or root == self.repo else "s-" + os.path.basename(root)
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        fields = {"tool_name": tool, "tool_input": ti if ti is not None else {key: path}, "session_id": session}
        if agent:
            fields.update(agent_id="a-1", agent_type="general-purpose")
        pl = payload("PreToolUse", cwd or root or self.repo, **fields)
        return run_hook("PreToolUse", pl, env if env is not None else self.env(), FW)

    def put(self, *rows, root=None):
        for row in rows:
            write_record(root or self.repo, D + "/" + row["id"] + ".yml", row)

    def src(self, name="a.py"):
        return os.path.join(self.repo, "src", name)

    def state_path(self, session="sess-1"):
        return os.path.join(self.data, "sessions", session + ".yml")


# ====================================================================== target (direct, pure rows)

class TargetTest(unittest.TestCase):
    def test_target_tools(self):   # T1-T4
        for tool, field in (("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
                            ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                self.assertEqual(pre_edit.target(mkctx(tool, {field: "/w/repo/src/a.py"})), "/w/repo/src/a.py")
        self.assertEqual(pre_edit.target(mkctx("Write", {"file_path": "/w/repo/src/a.py", "content": "x"})), "/w/repo/src/a.py")
        self.assertEqual(pre_edit.target(mkctx("MultiEdit", {"file_path": "/w/repo/src/a.py", "edits": []})), "/w/repo/src/a.py")
        self.assertEqual(pre_edit.target(mkctx("NotebookEdit", {"notebook_path": "/w/repo/n.ipynb", "cell_id": "c",
                                                                "edit_mode": "replace", "new_source": "x"})), "/w/repo/n.ipynb")

    def test_target_wrong_field(self):   # T5, T6
        with self.assertRaises(GateError) as cm:
            pre_edit.target(mkctx("NotebookEdit", {"file_path": "/w/repo/n.ipynb"}))
        self.assertEqual(str(cm.exception), "hook.edit.input: tool_input.notebook_path is missing")
        for tool in ("Edit", "Write", "MultiEdit"):
            with self.subTest(tool=tool), self.assertRaises(GateError) as cm:
                pre_edit.target(mkctx(tool, {"notebook_path": "/w/repo/a.py"}))
            self.assertEqual(str(cm.exception), "hook.edit.input: tool_input.file_path is missing")

    def test_target_both_fields(self):   # T7, T16
        self.assertEqual(pre_edit.target(mkctx("NotebookEdit", {"notebook_path": "/w/n.ipynb", "file_path": "/w/f.py"})), "/w/n.ipynb")
        self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": "/w/f.py", "notebook_path": "/w/n.ipynb"})), "/w/f.py")
        self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": "/w/f.py", "notebook_path": "\u0000"})), "/w/f.py")
        self.assertEqual(pre_edit.target(mkctx("NotebookEdit", {"notebook_path": "/w/n.ipynb", "file_path": "\ud800"})), "/w/n.ipynb")

    def test_target_other_tool(self):   # T8
        for tool in ("Read", "Bash", "Agent", "Task", "edit", "", None):
            with self.subTest(tool=tool), self.assertRaises(GateError) as cm:
                pre_edit.target(mkctx(tool, {"file_path": "/w/repo/a.py"}))
            self.assertTrue(str(cm.exception).startswith("hook.edit.input: tool_name "), str(cm.exception))
            self.assertTrue(str(cm.exception).endswith(" is not an edit tool"), str(cm.exception))

    def test_target_ignores_other_keys(self):   # T9
        ti = {"file_path": "/w/repo/src/a.py", "old_string": ".strict-delivery/state/decisions/x.yml",
              "new_string": ".strict-delivery/state/decisions/x.yml", "replace_all": True}
        self.assertEqual(pre_edit.target(mkctx("Edit", ti)), "/w/repo/src/a.py")

    def test_target_field_invalid(self):   # T10, T11, T12
        values = [("missing", {}), ("other key", {"old_string": "a"}), ("near name", {"filepath": "x"})]
        for v in ("", None, 0, 5, True, False, 1.5, [], ["a.py"], {}, {"p": "a"}):
            values.append(("value %r" % (v,), {"FIELD": v}))
        for tool, field in (("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
                            ("NotebookEdit", "notebook_path")):
            for name, ti in values:
                ti = {(field if k == "FIELD" else k): v for k, v in ti.items()}
                with self.subTest(tool=tool, value=name), self.assertRaises(GateError) as cm:
                    pre_edit.target(mkctx(tool, ti))
                self.assertTrue(str(cm.exception).startswith("hook.edit.input: tool_input.%s " % field), str(cm.exception))

    def test_target_nul_surrogate(self):   # T14, T15, V4
        for field in ("a\u0000b", "/w/repo/a\u0000", "\u0000", "\ud800", "a\udfffb", "/w/repo/x\ud83d"):
            with self.subTest(field=field), self.assertRaises(GateError) as cm:
                pre_edit.target(mkctx("Edit", {"file_path": field}))
            self.assertEqual(str(cm.exception), "hook.edit.input: tool_input.file_path holds a NUL or a lone surrogate")

    def test_target_odd_names(self):   # T17
        for name in (" ", "\n", "\t", "a\nb", "a\rb"):
            with self.subTest(name=name):
                self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": name})), "/w/repo/" + name)

    def test_target_length(self):   # T18
        self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": "a" * 4096})), "/w/repo/" + "a" * 4096)
        self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": "é" * 2048})), "/w/repo/" + "é" * 2048)
        for field in ("a" * 4097, "é" * 2049, "a" * (1 << 20)):
            with self.subTest(n=len(field)), self.assertRaises(GateError) as cm:
                pre_edit.target(mkctx("Edit", {"file_path": field}))
            self.assertEqual(str(cm.exception), "hook.edit.input: tool_input.file_path is longer than 4096 bytes")

    def test_target_unicode(self):   # T19
        for p in ("/w/repo/é/x.py", "/w/repo/\U0001fae0/x.py", "/w/repo/Ⱟ/x.py"):
            with self.subTest(p=p):
                self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": p})), p)

    def test_target_shapes(self):   # T30-T38, T41
        rows = [
            ("/w/repo", "/w/repo/src/a.py", "/w/repo/src/a.py"), ("/w/repo", "src/a.py", "/w/repo/src/a.py"),
            ("/w/repo/a/b", "x.py", "/w/repo/a/b/x.py"), ("/w/repo/a/b", "../x.py", "/w/repo/a/x.py"),
            ("/w/repo/a/b", "../../x.py", "/w/repo/x.py"), ("/w/repo/a/b", "../../../x.py", "/w/x.py"),
            ("/w/repo", "/w/repo/src/../a.py", "/w/repo/a.py"), ("/w/repo", "/w/repo/./src//a.py", "/w/repo/src/a.py"),
            ("/w/repo", "../../../../../../../x.py", "/x.py"),
            ("/w/repo", ".", "/w/repo"), ("/w/repo", "./", "/w/repo"), ("/w/repo", "./src/a.py", "/w/repo/src/a.py"),
            ("/w/repo", "/w/repo//src///a.py", "/w/repo/src/a.py"), ("/w/repo", "//w/repo/src/a.py", "//w/repo/src/a.py"),
            ("/w/repo", "///w/repo/src/a.py", "/w/repo/src/a.py"),
            ("/w/repo", "/w/repo/src/", "/w/repo/src"), ("/w/repo", "/w/repo/src//", "/w/repo/src"),
            ("/w/repo", "/", "/"), ("/w/repo", "/..", "/"),
            ("/w/repo", "~/x.py", "/w/repo/~/x.py"), ("/w/repo", "$HOME/x.py", "/w/repo/$HOME/x.py"),
            ("/w/repo", "a\\b\\c", "/w/repo/a\\b\\c"),
            ("/w/repo", ".strict-delivery\\state\\decisions\\x.yml", "/w/repo/.strict-delivery\\state\\decisions\\x.yml"),
            ("/w/repo", "/w/repo/src", "/w/repo/src"), ("/w/repo", "/w/repo/nope/x.py", "/w/repo/nope/x.py"),
        ]
        for cwd, field, want in rows:
            with self.subTest(cwd=cwd, field=field):
                got = pre_edit.target(mkctx("Edit", {"file_path": field}, cwd))
                self.assertEqual(got, want)
                self.assertIs(type(got), str)

    def test_target_idempotent(self):   # T39
        for field in ("src/../a.py", "//x//y/", "./a/./b", "/", "../.."):
            with self.subTest(field=field):
                once = pre_edit.target(mkctx("Edit", {"file_path": field}))
                self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": once})), once)
                self.assertIs(type(once), str)

    def test_target_symlinked_cwd(self):   # T40
        self.assertEqual(pre_edit.target(mkctx("Edit", {"file_path": "src/a.py"}, "/w/link")), "/w/link/src/a.py")


# ====================================================================== under_decisions (direct, real trees)

class UnderTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.r = os.path.join(self.tmp, "r")
        for d in (D, "src", "a", "uu", ".strict-delivery/state/decisions-old", ".strict-delivery/state/findings"):
            os.makedirs(os.path.join(self.r, d))
        open(os.path.join(self.r, D, "DEC1.yml"), "w").close()
        self.rel = D

    def u(self, path, rel=D, raw=None):
        return pre_edit.under_decisions(path, rel, raw)

    def test_under_basic(self):   # U1, U2, U3, U21, U30, U32
        r = self.r
        for p in (r + "/" + D + "/DEC1.yml", r + "/" + D, r + "/" + D + "/sub/x.yml", r + "/" + D + "/D/x.yml",
                  r + "/" + D + "/index.yml", r + "/" + D + "/in-force.md", "/x/y/.strict-delivery/state/decisions/z/w",
                  "/x/.strict-delivery/state/decisions", "/.strict-delivery/state/decisions"):
            with self.subTest(p=p):
                self.assertTrue(self.u(p))
        for rel, yes, no in (("a/b", "/q/a/b/x", "/q/a/c/b"), ("a/b/c/d/e", "/q/a/b/c/d/e/f", "/q/a/b/c/d/x")):
            with self.subTest(rel=rel):
                self.assertTrue(self.u(yes, rel))
                self.assertFalse(self.u(no, rel))

    def test_under_relative_from_subdir(self):   # U4
        for field, want in (("../.strict-delivery/state/decisions/x.yml", self.r + "/" + D + "/x.yml"),
                            (".strict-delivery/state/decisions/x.yml", self.r + "/src/" + D + "/x.yml")):
            with self.subTest(field=field):
                got = pre_edit.target(mkctx("Edit", {"file_path": field}, self.r + "/src"))
                self.assertEqual(got, want)
                self.assertTrue(self.u(got))

    def test_under_dotdot(self):   # U5, U6
        r = self.r
        for raw in (r + "/src/../.strict-delivery/state/decisions/x.yml", r + "/" + D + "/../decisions/x.yml"):
            with self.subTest(raw=raw):
                self.assertTrue(self.u(posixpath.normpath(raw), raw=raw))
                self.assertTrue(self.u(posixpath.normpath(raw)))
        for raw in (r + "/" + D + "/../findings/x.yml", r + "/" + D + "/../decisions-old/x.yml"):
            with self.subTest(raw=raw):
                self.assertFalse(self.u(posixpath.normpath(raw), raw=raw))
                self.assertFalse(self.u(posixpath.normpath(raw)))

    def test_under_symlink_parent(self):   # U7, U8, U10
        r = self.r
        other = os.path.join(self.tmp, "other", D)
        os.makedirs(other)
        os.symlink(r + "/" + D, r + "/link")
        os.symlink(other, r + "/link2")
        os.symlink(r + "/" + D, r + "/a/b")
        self.assertTrue(self.u(r + "/link/x.yml"))
        self.assertTrue(self.u(r + "/link2/x.yml"))
        self.assertTrue(self.u(r + "/a/b/c/x.yml"))

    def test_under_lexical_only(self):   # U9
        store = os.path.join(self.tmp, "store", "sd", "state", "decisions")
        os.makedirs(store)
        os.rename(os.path.join(self.r, ".strict-delivery"), os.path.join(self.tmp, "moved"))
        os.symlink(os.path.join(self.tmp, "store", "sd"), os.path.join(self.r, ".strict-delivery"))
        self.assertTrue(self.u(self.r + "/" + D + "/x.yml"))

    def test_under_symlink_file(self):   # U11
        os.symlink(self.r + "/" + D + "/DEC1.yml", self.r + "/src/rec.yml")
        self.assertTrue(self.u(self.r + "/src/rec.yml"))

    def test_under_symlink_other(self):   # U12
        os.symlink(self.r + "/src", self.r + "/lnk")
        self.assertFalse(self.u(self.r + "/lnk/a.py"))

    def test_under_symlink_loop(self):   # U13
        os.symlink(self.r + "/lb", self.r + "/la")
        os.symlink(self.r + "/la", self.r + "/lb")
        self.assertFalse(self.u(self.r + "/la/x.yml"))
        os.makedirs(self.r + "/" + D + "/dir")
        os.symlink(self.r + "/" + D + "/lb", self.r + "/" + D + "/la")
        os.symlink(self.r + "/" + D + "/la", self.r + "/" + D + "/lb")
        self.assertTrue(self.u(self.r + "/" + D + "/la/x.yml"))

    def test_under_dangling_symlink(self):   # U14 (Q1 (c): a dangling link is followed)
        dr = os.path.join(self.tmp, "dr")
        os.makedirs(dr)
        os.symlink(dr + "/" + D, dr + "/innocent")
        self.assertTrue(self.u(dr + "/innocent/DEC1.yml"))

    def test_under_physical_dotdot(self):   # U17 (Q1 (c): the real path of the raw spelling)
        r = self.r
        os.symlink(r + "/" + D, r + "/uu/lnk")
        raw = r + "/uu/lnk/../decisions/x.yml"
        path = posixpath.normpath(raw)
        self.assertEqual(path, r + "/uu/decisions/x.yml")
        self.assertFalse(self.u(path))
        self.assertTrue(self.u(path, raw=raw))

    def test_under_near_misses(self):   # U18, U19
        r = self.r
        for p in (r + "/" + D + "-old/x.yml", r + "/.strict-delivery/state/decision/x", r + "/.strict-delivery/state/decisionsX/x",
                  r + "/.strict-delivery/state/Xdecisions/x", r + "/.strict-delivery/state", r + "/.strict-delivery/decisions/x.yml",
                  r + "/state/decisions/x.yml", r + "/.strict-delivery/x/state/decisions/y",
                  r + "/decisions/state/.strict-delivery/x", r + "/.strict-delivery/state/decisions.yml",
                  r + "/.strict-delivery-x/state/decisions/x", r + "/x.strict-delivery/state/decisions/x",
                  r + "/.strict-delivery/state-x/decisions/x", r + "/.strict-delivery/xstate/decisions/x"):   # F-se42 (b)
            with self.subTest(p=p):
                self.assertFalse(self.u(p))

    def test_under_symlinked_repo(self):   # U20
        link = os.path.join(self.tmp, "link")
        os.symlink(self.r, link)
        self.assertTrue(self.u(link + "/" + D + "/x.yml"))
        self.assertFalse(self.u(link + "/src/a.py"))

    def test_under_double_slash(self):   # U22
        p = "/" + self.r + "/" + D + "/x.yml"
        self.assertTrue(p.startswith("//") and posixpath.normpath(p) == p)
        self.assertTrue(self.u(p))

    def test_under_configured(self):   # U23
        self.assertTrue(self.u(self.r + "/records/decs/x.yml", "records/decs"))
        self.assertFalse(self.u(self.r + "/" + D + "/x.yml", "records/decs"))

    def test_under_unusable_ancestors(self):   # U24
        open(self.r + "/file.txt", "w").close()
        self.assertFalse(self.u(self.r + "/file.txt/x"))
        self.assertTrue(self.u(self.r + "/file.txt/" + D + "/x"))
        os.makedirs(self.r + "/locked/inner")
        os.chmod(self.r + "/locked", 0)
        self.addCleanup(os.chmod, self.r + "/locked", 0o700)
        self.assertFalse(self.u(self.r + "/locked/inner/x.yml"))
        self.assertTrue(self.u(self.r + "/locked/" + D + "/x.yml"))

    def test_under_long(self):   # U25
        pad = 4096 - len("/" + D + "/x")
        segs, n = [], 0
        while pad - n > 0:
            seg = "a" * min(200, pad - n - 1) if pad - n > 1 else "a"
            segs.append(seg)
            n += len(seg) + 1
        path = "/" + "/".join(segs) + "/" + D + "/x"
        self.assertEqual(len(path.encode("utf-8")), 4096)
        self.assertTrue(self.u(path))

    def test_under_backslash(self):   # U26
        self.assertFalse(self.u(self.r + "/.strict-delivery\\state\\decisions\\x.yml"))

    def test_under_one_segment(self):   # U31
        r = self.r
        for p in (r + "/" + D + "/x.yml", r + "/src/decisions/x.py", r + "/decisions"):
            with self.subTest(p=p):
                self.assertTrue(self.u(p, "decisions"))
        for p in (r + "/decisions-old/x", r + "/src/decisions.py"):
            with self.subTest(p=p):
                self.assertFalse(self.u(p, "decisions"))

    def test_under_rel_refused(self):   # U33-U38
        for rel in ("/abs/decisions", "a/../b", "../decisions", "..", "a/b/", "a//b", "./a", ".", "", None, b"a", 1,
                    ["a"], "a\u0000b", "a\ud800"):
            with self.subTest(rel=rel), self.assertRaises((ValueError, TypeError)):
                self.u(self.r + "/x", rel)

    def test_under_non_ascii_rel(self):   # U39
        for rel in ("décisions", "дец", "\U0001f4a9"):
            with self.subTest(rel=rel):
                self.assertTrue(self.u("/q/" + rel + "/x", rel))
                self.assertFalse(self.u("/q/other/x", rel))

    def test_under_case_fold(self):   # U40, U41, U43
        rows = [("/q/.Strict-Delivery/State/Decisions/x", D, True), ("/q/.STRICT-DELIVERY/STATE/DECISIONS/x", D, True),
                ("/q/.strict-delivery/State/decisions/x", D, True), ("/q/DECISIONS/x", "decisions", True),
                ("/q/decisions/x", "Decisions", True), ("/q/.STRICT-delivery/state/decisions/x", D, True)]
        for path, rel, want in rows:
            with self.subTest(path=path):
                self.assertEqual(self.u(path, rel), want)
        for rel, seg in (("décisions", "DÉCISIONS"), ("Straße", "STRASSE"), ("K", "k"),
                         ("İ", "i̇"), ("Ꭰ", "ꭰ")):
            with self.subTest(rel=rel, seg=seg):
                self.assertTrue(self.u("/q/" + seg + "/x", rel))
        self.assertFalse(self.u("/q/écisions/x", "écisions"))   # the ruling folds case, it does not normalise

    def test_under_unicode_versions(self):   # U42, V2
        for newer in ("ⱟ", "Ⱟ", "ꟁ", "Ꟁ", "\U00010597", "\U00010570"):
            with self.subTest(rel=newer), self.assertRaises(ValueError):
                self.u("/q/x", newer)
        for seg in ("Ⱟ", "ⱟ", "Ꟁ", "ꟁ", "\U00010570", "\U00010597"):
            with self.subTest(seg=seg):
                self.assertFalse(self.u("/q/" + seg + "/x.yml"))
                self.assertFalse(self.u("/q/" + seg + "/x", "decisions"))
                self.assertTrue(self.u("/q/" + seg + "/decisions/x", "decisions"))

    def test_under_path_refused(self):   # U44
        for p in ("a/b", "/a//b", "/a/../b", "/a/b/", None, 5, b"/a", "/a\u0000b", "/a\ud800", ""):
            with self.subTest(p=p), self.assertRaises((ValueError, TypeError)):
                self.u(p)
        for raw in ("a/b", "/a\u0000", 5):
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                self.u("/a/b", D, raw)

    def test_under_realpath_error(self):   # U45
        for exc in (OSError("x"), ValueError("x"), RecursionError("x")):
            with self.subTest(exc=type(exc)), mock.patch("os.path.realpath", side_effect=exc), self.assertRaises(type(exc)):
                self.u(self.r + "/src/a.py")

    def test_pre_edit_no_case_method(self):   # CD17, M24
        text = pathlib.Path(pre_edit.__file__).read_text(encoding="utf-8")
        tree = ast.parse(text)
        methods = ("lower", "casefold", "upper", "swapcase", "title", "capitalize")
        self.assertEqual([n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in methods], [])
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("unicodedata", names)
        self.assertNotIn("unicodedata", text)


# ====================================================================== the entry

class HandleTest(Base):
    def kinds(self):
        """``[(name, field path, cwd, shown path)]`` of the refused path kinds of rows HD1, U1-U5, U7, U8, U10, U11, U15-U17."""
        r = self.repo
        os.makedirs(r + "/" + D + "/sub")
        self.put(dec(DEC1))
        for d in ("src", "a", "uu"):
            os.makedirs(os.path.join(r, d), exist_ok=True)
        other = os.path.join(self.tmp, "other", D)
        os.makedirs(other)
        os.symlink(r + "/" + D, r + "/link")
        os.symlink(other, r + "/link2")
        os.symlink(r + "/" + D, r + "/a/b")
        os.symlink(r + "/" + D + "/DEC1.yml", r + "/src/rec.yml")
        os.symlink(r + "/" + D, r + "/uu/lnk")
        wt = os.path.join(self.tmp, "wt")
        git(r, "worktree", "add", "-q", "--detach", "--", wt)
        clone = os.path.join(self.tmp, "clone")
        os.makedirs(clone)
        make_repo(clone)
        ci = ".Strict-Delivery/State/Decisions"
        return [
            ("U1", r + "/" + D + "/DEC1.yml", None, r + "/" + D + "/DEC1.yml"),
            ("U2", r + "/" + D, None, r + "/" + D),
            ("U2 slash", r + "/" + D + "/", None, r + "/" + D),
            ("U3", r + "/" + D + "/sub/x.yml", None, r + "/" + D + "/sub/x.yml"),
            ("U4 up", "../" + D + "/x.yml", r + "/src", r + "/" + D + "/x.yml"),
            ("U4 down", D + "/x.yml", r + "/src", r + "/src/" + D + "/x.yml"),
            ("U5 in", r + "/src/../" + D + "/x.yml", None, r + "/" + D + "/x.yml"),
            ("U5 same", r + "/" + D + "/../decisions/x.yml", None, r + "/" + D + "/x.yml"),
            ("U7", r + "/link/x.yml", None, r + "/link/x.yml"),
            ("U8", r + "/link2/x.yml", None, r + "/link2/x.yml"),
            ("U10", r + "/a/b/c/x.yml", None, r + "/a/b/c/x.yml"),
            ("U11", r + "/src/rec.yml", None, r + "/src/rec.yml"),
            ("U15 worktree", wt + "/" + D + "/DEC1.yml", None, wt + "/" + D + "/DEC1.yml"),
            ("U15 clone", clone + "/" + D + "/DEC1.yml", None, clone + "/" + D + "/DEC1.yml"),
            ("U16 mixed", r + "/" + ci + "/x.yml", None, r + "/" + ci + "/x.yml"),
            ("U16 upper", r + "/.STRICT-DELIVERY/STATE/DECISIONS/x.yml", None, r + "/.STRICT-DELIVERY/STATE/DECISIONS/x.yml"),
            ("U16 state", r + "/.strict-delivery/State/decisions/x.yml", None, r + "/.strict-delivery/State/decisions/x.yml"),
            ("U17", r + "/uu/lnk/../decisions/x.yml", None, r + "/uu/decisions/x.yml"),
        ]

    def test_agent_edit_under_decisions_refused(self):   # HD1, HD26, HD4, HD5, U1-U5, U7-U11, U15-U17
        for name, field, cwd, shown in self.kinds():
            for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                with self.subTest(kind=name, tool=tool):
                    p = self.edit(field, tool=tool, cwd=cwd)
                    self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(shown)))
                    self.assertIn("hook.edit.decisions", p.stderr)

    def test_deny_line_text(self):   # HD2
        p = self.edit(self.repo + "/" + D + "/DEC1.yml")
        self.assertEqual(p.stderr, "FAIL hook.edit.decisions: " + self.repo + "/.strict-delivery/state/decisions/DEC1.yml: "
                         "decision records are written only by python3 -m gates decisions (owner answer Q-16 (a)); "
                         "answers and withdrawals come from the human\n")
        self.assertEqual(p.stderr.count("\n"), 1)
        self.assertIn("python3 -m gates decisions", p.stderr)

    def test_deny_line_escaped(self):   # HD3, V2
        names = {"a b": "a b", "a\nb": "a\\nb", "a\rb": "a\\rb", "a\\b": "a\\\\b", "\U0001fae0": "\\U0001fae0",
                 "Ⱟ": "\\u2c2f", "é": "é", "a\tb": "a\\tb"}
        for raw, shown in names.items():
            with self.subTest(name=raw):
                p = self.edit(self.repo + "/" + D + "/" + raw)
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                self.assertEqual(p.stderr, DENY(self.repo + "/" + D + "/" + shown))

    def test_deny_main_session(self):   # HD4
        p = self.edit(self.repo + "/" + D + "/x.yml", agent=False)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(self.repo + "/" + D + "/x.yml")))

    def test_deny_subagent(self):   # HD5
        for agent_type in ("general-purpose", ""):
            with self.subTest(agent_type=agent_type):
                pl = payload("PreToolUse", self.repo, tool_name="Write", tool_input={"file_path": self.repo + "/" + D + "/x.yml"},
                             agent_id="a-1", agent_type=agent_type)
                p = run_hook("PreToolUse", pl, self.env(), FW)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(self.repo + "/" + D + "/x.yml")))

    def test_case_variant_and_other_worktree_refused(self):   # HD6, HD17, U15, U16
        case_variant = self.repo + "/.Strict-Delivery/State/Decisions/x.yml"
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", "--detach", "--", wt)
        clone = os.path.join(self.tmp, "clone")
        os.makedirs(clone)
        make_repo(clone)
        for path in (case_variant, wt + "/" + D + "/DEC1.yml", clone + "/" + D + "/DEC1.yml",
                     "/tmp/other/.strict-delivery/state/decisions/x.yml"):
            with self.subTest(path=path):
                self.assertEqual(self.edit(path).returncode, 2)

    def test_sibling_directory_allowed(self):   # HD7, U18
        p = self.edit(".strict-delivery/state/decisions-old/x.yml")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_deny_configured_elsewhere(self):   # HD8
        cfg = minimal_config()
        cfg["paths"] = {"decisions": "records/decs"}
        repo = self.newrepo("custom", cfg)
        p = self.edit(repo + "/records/decs/x.yml", root=repo)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(repo + "/records/decs/x.yml")))
        p = self.edit(repo + "/" + D + "/x.yml", root=repo)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def broken(self, name, how):
        repo = self.newrepo(name)
        cfg = repo + "/.strict-delivery/config.yml"
        if how == "yaml":
            open(cfg, "w").write("schema: [\n")
        elif how == "schema":
            write_record(repo, ".strict-delivery/config.yml", dict(minimal_config(), schema="config/99"))
        elif how == "unknown":
            write_record(repo, ".strict-delivery/config.yml", dict(minimal_config(), bogus=1))
        elif how == "unknown+custom":
            write_record(repo, ".strict-delivery/config.yml", dict(minimal_config(), bogus=1, paths={"decisions": "records/decs"}))
        elif how == "dir":
            os.rename(cfg, cfg + ".bak")
            os.mkdir(cfg)
        elif how == "dangling":
            os.rename(cfg, cfg + ".bak")
            os.symlink("nowhere", cfg)
        return repo

    def test_deny_config_unloadable(self):   # HD9, HD10, HD11
        for how in ("yaml", "schema", "unknown", "dir", "dangling", "unknown+custom"):
            with self.subTest(how=how):
                repo = self.broken("c-" + how.replace("+", "-"), how)
                p = self.edit(repo + "/" + D + "/x.yml", root=repo)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(repo + "/" + D + "/x.yml")))
                p = self.edit(repo + "/src/a.py", root=repo)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
                if how == "unknown+custom":
                    p = self.edit(repo + "/records/decs/x.yml", root=repo)
                    self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_deny_bad_configured_path(self):   # HD12, HD13
        for n, value in enumerate(("/abs/dir", "a/../b", "a/b/", "", ".", "a//b", "Ⱟ", "\U0001fae0")):
            with self.subTest(value=value):
                cfg = dict(minimal_config(), paths={"decisions": value})
                repo = self.newrepo("bp%d" % n, cfg)
                p = self.edit(repo + "/" + D + "/x.yml", root=repo)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(repo + "/" + D + "/x.yml")))
                p = self.edit(repo + "/src/a.py", root=repo)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_deny_touches_nothing(self):   # HD14, M19
        self.put(dec(DEC1))
        p = self.edit(self.repo + "/" + D + "/x.yml")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(os.listdir(self.data), [])

    def test_deny_without_store(self):   # HD15
        p = self.edit(self.repo + "/" + D + "/x.yml", env=self.env(data=None))
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(self.repo + "/" + D + "/x.yml")))

    def test_deny_with_malformed_record(self):   # HD16
        os.makedirs(self.repo + "/" + D)
        open(self.repo + "/" + D + "/" + DEC2 + ".yml", "w").write("schema: decision/2\nid: x\nstatus: [\n")
        p = self.edit(self.repo + "/" + D + "/x.yml")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", DENY(self.repo + "/" + D + "/x.yml")))

    def test_silent_without_config(self):   # HD19
        repo = self.newrepo("noconfig")
        os.rename(repo + "/.strict-delivery/config.yml", repo + "/.strict-delivery/config.bak")
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        for root, path in ((repo, repo + "/" + D + "/x.yml"), (plain, plain + "/" + D + "/x.yml")):
            with self.subTest(root=root):
                p = self.edit(path, root=root)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_input_refusals(self):   # HD28, T5-T15, T18
        r = self.repo
        cases = [("Edit", {}, "tool_input.file_path is missing"), ("Edit", {"notebook_path": r + "/a.py"}, "tool_input.file_path is missing"),
                 ("NotebookEdit", {"file_path": r + "/n.ipynb"}, "tool_input.notebook_path is missing"),
                 ("Write", {"file_path": ""}, "tool_input.file_path is empty"),
                 ("MultiEdit", {"file_path": None}, "tool_input.file_path must be a string"),
                 ("Edit", {"file_path": 5}, "tool_input.file_path must be a string"),
                 ("Edit", {"file_path": ["a.py"]}, "tool_input.file_path must be a string"),
                 ("Edit", {"file_path": True}, "tool_input.file_path must be a string"),
                 ("NotebookEdit", {"notebook_path": {"p": "a"}}, "tool_input.notebook_path must be a string"),
                 ("Edit", {"file_path": "a\u0000b"}, "tool_input.file_path holds a NUL or a lone surrogate"),
                 ("Edit", {"file_path": "\ud800"}, "tool_input.file_path holds a NUL or a lone surrogate"),
                 ("Write", {"file_path": r + "/x\ud83d"}, "tool_input.file_path holds a NUL or a lone surrogate"),
                 ("Edit", {"file_path": "a" * 4097}, "tool_input.file_path is longer than 4096 bytes"),
                 ("Edit", {"file_path": "a" * (1 << 20)}, "tool_input.file_path is longer than 4096 bytes")]
        for tool, ti, reason in cases:
            with self.subTest(tool=tool, reason=reason, keys=sorted(ti)):
                p = self.edit(None, tool=tool, ti=ti)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", INP(reason)))

    def test_target_field_digit_limit(self):   # T13, V1, 3a.2 I16
        for digits, want in ((4300, "ok"), (4301, "parse")):
            with self.subTest(digits=digits):
                text = json.dumps(payload("PreToolUse", self.repo, tool_name="Edit", tool_input={"file_path": "__N__"}))
                data = text.replace('"__N__"', "1" * digits).encode("utf-8")
                p = run_hook("PreToolUse", data, self.env(), FW)
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                if want == "ok":
                    self.assertEqual(p.stderr, INP("tool_input.file_path must be a string"))
                else:
                    self.assertIn("hook.input: input is not valid JSON: integer longer than 4300 digits", p.stderr)
                    self.assertNotIn("hook.edit", p.stderr)

    def test_target_digit_limit_elsewhere(self):   # T21, V1
        text = json.dumps(payload("PreToolUse", self.repo, tool_name="Edit",
                                  tool_input={"file_path": self.repo + "/src/a.py", "n": "__N__"}))
        p = run_hook("PreToolUse", text.replace('"__N__"', "1" * 4300).encode("utf-8"), self.env(), FW)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    # ------------------------------------------------------------------ pass output

    def test_no_permission_decision(self):   # HD27
        self.put(dec(DEC1))
        for path in (self.src(), self.repo + "/docs/x.md"):
            p = self.edit(path)
            self.assertNotIn("permissionDecision", p.stdout)
            self.assertEqual(p.returncode, 0)

    def test_surfacing_blocks_nothing(self):   # HS17, HS18, HD27
        self.put(dec(DEC1))
        open(self.repo + "/" + D + "/" + DEC2 + ".yml", "w").write("schema: decision/2\nid: x\nstatus: [\n")
        p = self.edit(self.src())
        self.assertEqual(p.returncode, 0)
        lines = ctx_lines(p)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FAIL hook.edit.decisions-load: "), lines)
        self.assertIn(DEC2 + ".yml: unterminated flow sequence (line 3)", lines[0])
        self.assertNotIn("permissionDecision", p.stdout)

    # ------------------------------------------------------------------ surfacing

    def test_surfacing_none(self):   # HS1, HS2
        p = self.edit(self.src())   # D absent
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        os.makedirs(self.repo + "/" + D)
        self.assertEqual(ctx(self.edit(self.src())), "")
        open(self.repo + "/" + D + "/index.yml", "w").write("x\n")
        open(self.repo + "/" + D + "/in-force.md", "w").write("x\n")
        self.assertEqual(ctx(self.edit(self.src())), "")
        cases = [dec(DEC1, applies_to=["docs/*"]), dec(DEC1, applies_to=[]), dec(DEC1, applies_to=None),
                 dec(DEC1, status="open"), dec(DEC1, status="withdrawn"), dec(DEC1, effect="one-off"),
                 dec(DEC1, **{"class": "merge-grant"})]
        for n, row in enumerate(cases):
            with self.subTest(case=n):
                self.put(row)
                p = self.edit(self.src())
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_surfaces_once_per_session(self):   # HS3, HS4, HC11
        self.put(dec(DEC1))
        first = ctx(self.edit(self.src()))
        self.assertIn("in-force DEC-20261101-k3f9", first)
        self.assertEqual(first, IF(DEC1))
        p = self.edit(self.src())
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(ctx(p), "")
        self.assertEqual(ctx(self.edit(self.src("other.py"))), "")

    def test_new_session_surfaces_again(self):   # HS5
        self.put(dec(DEC1))
        self.edit(self.src())
        self.assertIn("in-force DEC-20261101-k3f9", ctx(self.edit(self.src(), session="sess-2")))
        self.assertEqual(ctx(self.edit(self.src(), session="sess-2")), "")

    def test_surfaced_state_written(self):   # HS6, HS29
        self.put(dec(DEC1))
        data = os.path.join(self.tmp, "does-not-exist-yet", "data")
        self.assertEqual(ctx(self.edit(self.src(), env=self.env(data=data))), IF(DEC1))
        state = yamlsub.load(os.path.join(data, "sessions", "sess-1.yml"), "state")
        self.assertEqual(state, {"schema": "hook-session/1", "session": "sess-1", "dispatches": [], "surfaced": [DEC1]})
        self.assertEqual(ctx(self.edit(self.src(), env=self.env(data=data))), "")
        self.assertEqual(yamlsub.load(os.path.join(data, "sessions", "sess-1.yml"), "state")["surfaced"], [DEC1])

    def test_surfaces_two_decisions(self):   # HS7, HS8, HS9, M12, M27
        self.put(dec(DEC2, applies_to=["src/**"]), dec(DEC1))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1), IF(DEC2)])
        self.assertEqual(ctx(self.edit(self.src())), "")
        repo = self.newrepo("two")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1))
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC1)])
        write_record(repo, D + "/" + DEC2 + ".yml", dec(DEC2, applies_to=["src/**"]))
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC2)])
        repo = self.newrepo("globs")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1))
        write_record(repo, D + "/" + DEC2 + ".yml", dec(DEC2, applies_to=["docs/*"]))
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC1)])
        self.assertEqual(ctx_lines(self.edit(repo + "/docs/b.md", root=repo)), [IF(DEC2)])
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [])
        self.assertEqual(ctx_lines(self.edit(repo + "/docs/b.md", root=repo)), [])

    def test_superseded_not_surfaced(self):   # HS10, HS11
        self.put(dec(DEC1), dec(DEC2, supersedes=DEC1, applies_to=["src/*"]))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC2)])
        for name, rows, want in (
                ("superseder open", [dec(DEC1), dec(DEC2, status="open", supersedes=DEC1)], [IF(DEC1)]),
                ("superseder withdrawn", [dec(DEC1), dec(DEC2, status="withdrawn", supersedes=DEC1)], [IF(DEC1)]),
                ("chain", [dec(DEC1), dec(DEC2, supersedes=DEC1), dec(DEC3, supersedes=DEC2)], [IF(DEC3)]),
                ("superseder no match", [dec(DEC1), dec(DEC2, supersedes=DEC1, applies_to=["docs/*"])], [])):
            with self.subTest(name=name):
                repo = self.newrepo("sup-" + name.replace(" ", "-"))
                for row in rows:
                    write_record(repo, D + "/" + row["id"] + ".yml", row)
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), want)

    def test_target_outside_root_not_surfaced(self):   # HS12, M14
        self.put(dec(DEC1, applies_to=["**"]))
        other = self.newrepo("other-repo")
        elsewhere = os.path.join(self.tmp, "elsewhere", "src")
        os.makedirs(elsewhere)
        for path in (elsewhere + "/a.py", self.repo + "/../src/a.py", other + "/src/a.py"):
            with self.subTest(path=path):
                p = self.edit(path)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(self.edit(self.src()).returncode, 0)
        self.assertEqual(ctx_lines(self.edit(self.src(), session="sess-9")), [IF(DEC1)])

    def test_no_store_surfaces_every_time(self):   # HS13
        self.put(dec(DEC1))
        regular = os.path.join(self.tmp, "afile")
        open(regular, "w").write("x")
        for name, data in (("unset", None), ("empty", ""), ("relative", "rel/dir"), ("regular file", regular)):
            with self.subTest(store=name):
                env = self.env(data=data) if data != "" else dict(self.env(data=None), CLAUDE_PLUGIN_DATA="")
                first, second = ctx(self.edit(self.src(), env=env)), ctx(self.edit(self.src(), env=env))
                self.assertTrue(first and second)
                self.assertEqual((first, second), (IF(DEC1), IF(DEC1)))

    def test_lock_held_surfaces_all(self):   # HS14, CD10
        self.put(dec(DEC1))
        sessions = os.path.join(self.data, "sessions")
        os.mkdir(sessions, 0o700)
        fd = os.open(os.path.join(sessions, "sess-1.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        started = time.monotonic()
        p = self.edit(self.src())
        self.assertGreaterEqual(time.monotonic() - started, 9)
        self.assertEqual(ctx_lines(p), [IF(DEC1)])
        self.assertFalse(os.path.exists(os.path.join(sessions, "sess-1.yml")))

    def test_corrupt_session_surfaces_all(self):   # HS15
        self.put(dec(DEC1))
        sessions = os.path.join(self.data, "sessions")
        os.mkdir(sessions, 0o700)
        path = os.path.join(sessions, "sess-1.yml")
        open(path, "w").write("x: [\n")
        for _ in range(2):
            self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])
        self.assertEqual(open(path).read(), "x: [\n")
        self.assertEqual(sorted(n for n in os.listdir(sessions) if n.endswith(".yml") or "corrupt" in n), ["sess-1.yml"])

    def test_write_failure_surfaces_all(self):   # HS16
        self.put(dec(DEC1))
        sessions = os.path.join(self.data, "sessions")
        os.mkdir(sessions, 0o700)
        os.mkdir(os.path.join(sessions, "sess-1.yml.tmp"))
        for _ in range(2):
            self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])
        self.assertFalse(os.path.exists(os.path.join(sessions, "sess-1.yml")))

    def test_load_errors_blocks_nothing(self):   # HS18, V1
        n = [0]

        def fresh(setup):
            n[0] += 1
            repo = self.newrepo("le%d" % n[0])
            setup(repo)
            return repo

        def nonmap(repo):
            write_record(repo, D + "/" + DEC2 + ".yml", dec(DEC2))
            open(repo + "/" + D + "/" + DEC2 + ".yml", "w").write("- a\n- b\n")

        def stray(repo):
            os.makedirs(repo + "/" + D)
            open(repo + "/" + D + "/notes.txt", "w").write("x")

        def subdir(repo):
            os.makedirs(repo + "/" + D + "/sub")

        def nonutf8(repo):
            os.makedirs(repo + "/" + D)
            open(repo + "/" + D + "/" + DEC2 + ".yml", "wb").write(b"id: \xff\xfe\n")

        def digits(k):
            def setup(repo):
                os.makedirs(repo + "/" + D)
                open(repo + "/" + D + "/" + DEC2 + ".yml", "w").write("id: x\nn: " + "1" * k + "\n")
            return setup

        def dlink(repo):
            os.makedirs(repo + "/.strict-delivery/state")
            os.makedirs(os.path.join(self.tmp, "real-d-%d" % n[0]))
            os.symlink(os.path.join(self.tmp, "real-d-%d" % n[0]), repo + "/" + D)

        def statelink(repo):
            os.makedirs(os.path.join(self.tmp, "real-s-%d" % n[0]))
            os.symlink(os.path.join(self.tmp, "real-s-%d" % n[0]), repo + "/.strict-delivery/state")

        def dfile(repo):
            os.makedirs(repo + "/.strict-delivery/state")
            open(repo + "/" + D, "w").write("x")

        for name, setup in (("non-mapping", nonmap), ("stray file", stray), ("subdirectory", subdir), ("not UTF-8", nonutf8),
                            ("1001 digits", digits(1001)), ("4300 digits", digits(4300)), ("4301 digits", digits(4301)),
                            ("D symlink", dlink), ("state symlink", statelink), ("D file", dfile)):
            with self.subTest(case=name):
                repo = fresh(setup)
                p = self.edit(repo + "/src/a.py", root=repo)
                self.assertEqual(p.returncode, 0)
                lines = ctx_lines(p)
                self.assertEqual(len(lines), 1, lines)
                self.assertTrue(lines[0].startswith("FAIL hook.edit.decisions-load: "), lines)
        with self.subTest(case="1000 digits loads"):
            repo = self.newrepo("le-1000")
            write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, n=int("1" * 1000)))
            self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC1)])

    def test_malformed_hides_good_record(self):   # HS19
        self.put(dec(DEC1))
        open(self.repo + "/" + D + "/" + DEC2 + ".yml", "w").write("id: [\n")
        lines = ctx_lines(self.edit(self.src()))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FAIL hook.edit.decisions-load: "))
        self.assertNotIn(DEC1, lines[0])
        os.rename(self.repo + "/" + D + "/" + DEC2 + ".yml", os.path.join(self.tmp, "gone.yml"))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])   # not marked while the load failed

    def test_load_error_every_time(self):   # HS20
        open_dir = self.repo + "/" + D
        os.makedirs(open_dir)
        open(open_dir + "/" + DEC2 + ".yml", "w").write("id: [\n")
        a, b = ctx_lines(self.edit(self.src())), ctx_lines(self.edit(self.src()))
        self.assertEqual(len(a), 1)
        self.assertEqual(a, b)

    def test_load_error_no_store(self):   # HS21
        os.makedirs(self.repo + "/" + D)
        open(self.repo + "/" + D + "/" + DEC2 + ".yml", "w").write("id: [\n")
        lines = ctx_lines(self.edit(self.src(), env=self.env(data=None)))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FAIL hook.edit.decisions-load: "))

    def test_cfg_error_no_surfacing(self):   # HS22, CD6
        repo = self.broken("cfgerr", "yaml")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1))
        p = self.edit(repo + "/src/a.py", root=repo)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_load_exception_kinds(self):   # HS23, V3
        self.put(dec(DEC1))
        eg = "ExceptionGroup: boom (1 sub-exception)" if HAS_EG else "ExceptionGroup: boom"
        for kind, want in (("Exception", "Exception: boom"), ("OSError", "OSError: boom"), ("ExceptionGroup", eg)):
            with self.subTest(kind=kind):
                env = self.env(patch=[["gates.lib.store", "Store.load", kind, "boom"]])
                p = self.edit(self.src(), env=env)
                self.assertEqual((p.returncode, p.stderr), (0, ""))
                self.assertEqual(ctx_lines(p), ["FAIL hook.edit.decisions-load: " + want])

    def test_base_exception_fails_closed(self):   # HS24, V3
        self.put(dec(DEC1))
        bg = "BaseExceptionGroup: boom (1 sub-exception)" if HAS_BG else "BaseExceptionGroup: boom"
        for target, kind, want in (("Store.load", "KeyboardInterrupt", "KeyboardInterrupt: boom"),
                                   ("Store.load", "SystemExit0", "SystemExit: 0"),
                                   ("Store.load", "BaseExceptionGroup", bg),
                                   ("locked", "KeyboardInterrupt", "KeyboardInterrupt: boom"),
                                   ("locked", "BaseExceptionGroup", bg)):
            with self.subTest(target=target, kind=kind):
                mod = "gates.lib.store" if target.startswith("Store") else "gates.lib.session"
                p = self.edit(self.src(), env=self.env(patch=[[mod, target, kind, "boom"]]))
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                self.assertEqual(p.stderr, "FAIL hook.PreToolUse: " + want + TAIL + "\n")

    def test_session_internal_error_fails_closed(self):   # HS25, M16
        self.put(dec(DEC1))
        eg = "ExceptionGroup: boom (1 sub-exception)" if HAS_EG else "ExceptionGroup: boom"
        for kind, want in (("ValueError", "ValueError: boom"), ("ExceptionGroup", eg), ("OSError", "OSError: boom")):
            with self.subTest(kind=kind):
                p = self.edit(self.src(), env=self.env(patch=[["gates.lib.session", "locked", kind, "boom"]]))
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                self.assertEqual(p.stderr, "FAIL hook.PreToolUse: " + want + TAIL + "\n")

    def test_mark_surfaced_not_new(self):   # HS26
        self.put(dec(DEC1))
        self.edit(self.src())
        self.assertEqual(ctx(self.edit(self.src())), "")
        sessions = os.path.join(self.data, "sessions")
        for other, want in (([DEC1], []), (["DEC-other"], [IF(DEC1)])):
            with self.subTest(surfaced=other):
                os.rename(os.path.join(sessions, "sess-1.yml"), os.path.join(self.tmp, "old-%s.yml" % len(other[0])))
                write_record(sessions, "sess-1.yml", {"schema": "hook-session/1", "session": "sess-1", "dispatches": [],
                                                      "surfaced": other})
                self.assertEqual(ctx_lines(self.edit(self.src())), want)

    def test_concurrent_surfaces_once(self):   # HS27
        self.put(dec(DEC1))
        out = []

        def run(name):
            out.append(self.edit(self.src(name)))
        threads = [threading.Thread(target=run, args=("a%d.py" % i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(ctx(p) for p in out), ["", IF(DEC1)])
        self.assertEqual(yamlsub.load(self.state_path(), "state")["surfaced"], [DEC1])

    def test_subagent_shares_session(self):   # HS28, CD11
        self.put(dec(DEC1))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])
        self.assertEqual(ctx(self.edit(self.src(), agent=True)), "")
        self.assertEqual(ctx_lines(self.edit(self.src(), session="sess-2", agent=True)), [IF(DEC1)])
        self.assertEqual(ctx(self.edit(self.src(), session="sess-2")), "")

    def test_surfaces_many(self):   # HS30
        ids = ["DEC-20261101-" + "".join(t) for t in itertools.islice(itertools.product("abcdefgh", "23456789"), 50)]
        self.assertEqual(len(set(ids)), 50)
        self.put(*[dec(i) for i in ids])
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(i) for i in sorted(ids)])

    def test_context_non_ascii(self):   # HS31
        self.put(dec(DEC1, rule="é\U0001fae0"))
        p = self.edit(self.src())
        self.assertTrue(all(ord(c) < 128 for c in p.stdout))
        self.assertIn("\\u00e9", p.stdout)
        self.assertEqual(ctx_lines(p), [IF(DEC1, "é\\U0001fae0")])

    # ------------------------------------------------------------------ the context line

    def test_context_line(self):   # HC1, HC2, HC3
        cases = [(dec(DEC1), IF(DEC1)), (dec(DEC1, rule=None), IF(DEC1, "Keep X?")), (dec(DEC1, rule=""), IF(DEC1, "Keep X?")),
                 (dec(DEC1, rule=5), IF(DEC1, "Keep X?")), (dec(DEC1, rule=["a"]), IF(DEC1, "Keep X?"))]
        for n, (row, want) in enumerate(cases):
            with self.subTest(case=n):
                repo = self.newrepo("cl%d" % n)
                write_record(repo, D + "/" + DEC1 + ".yml", row)
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [want])
        repo = self.newrepo("clnull")   # a literal YAML null
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, rule="placeholder"))
        text = open(repo + "/" + D + "/" + DEC1 + ".yml").read().replace("rule: placeholder", "rule: null")
        self.assertIn("rule: null", text)
        open(repo + "/" + D + "/" + DEC1 + ".yml", "w").write(text)
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC1, "Keep X?")])

    def test_context_first_line(self):   # HC4
        for n, (row, want) in enumerate([(dec(DEC1, rule="a\nb"), IF(DEC1, "a")), (dec(DEC1, rule=None, question="q1\nq2"), IF(DEC1, "q1")),
                                         (dec(DEC1, rule="\nb"), IF(DEC1, ""))]):
            with self.subTest(case=n):
                repo = self.newrepo("fl%d" % n)
                write_record(repo, D + "/" + DEC1 + ".yml", row)
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [want])

    def test_context_escaped(self):   # HC5, HC9
        for n, (row, want) in enumerate([
                (dec(DEC1, rule="a\tb\U0001fae0Ⱟ"), IF(DEC1, "a\\tb\\U0001fae0\\u2c2f")),
                (dec(DEC1, rule="a\rb"), IF(DEC1, "a\\rb")),
                (dec(DEC1, rule=None, question="q\\x"), IF(DEC1, "q\\\\x")),
                (dec(DEC1, rule="a\\b"), IF(DEC1, "a\\\\b"))]):
            with self.subTest(case=n):
                repo = self.newrepo("es%d" % n)
                write_record(repo, D + "/" + DEC1 + ".yml", row)
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [want])
        with self.subTest(case="id"):
            repo = self.newrepo("esid")
            write_record(repo, D + "/" + DEC1 + ".yml", dec("DEC-x\n\U0001fae0"))
            self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF("DEC-x\\n\\U0001fae0")])

    def test_context_landed_in(self):   # HC6, HC7, HC8
        cases = [(dec(DEC1, landed_in=None), "none"), (dec(DEC1, landed_in=[]), "none"),
                 (dec(DEC1, landed_in=["CLAUDE.md"]), "CLAUDE.md"),
                 (dec(DEC1, landed_in=["CLAUDE.md", ".strict-delivery/playbooks/p.md#x"]), "CLAUDE.md, .strict-delivery/playbooks/p.md#x"),
                 (dec(DEC1, landed_in="CLAUDE.md"), "none"), (dec(DEC1, landed_in=[1, None]), "none"),
                 (dec(DEC1, landed_in=[1, "a.md"]), "a.md")]
        for n, (row, want) in enumerate(cases):
            with self.subTest(case=n):
                repo = self.newrepo("li%d" % n)
                write_record(repo, D + "/" + DEC1 + ".yml", row)
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC1, cites=want)])

    def test_context_long(self):   # HC10
        self.put(dec(DEC1, rule="x" * 100000))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1, "x" * 100000)])

    # ------------------------------------------------------------------ applies_to and the repo-relative path

    def surfaces(self, globs, path, name):
        repo = self.newrepo(name)
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, applies_to=globs))
        return ctx_lines(self.edit(repo + "/" + path, root=repo))

    def test_applies_to_forms(self):   # HA1, HA2
        self.assertEqual(self.surfaces(None, "src/a.py", "af1"), [])
        self.assertEqual(self.surfaces([], "src/a.py", "af2"), [])
        self.assertEqual(self.surfaces(["docs/*", "src/*"], "src/a.py", "af3"), [IF(DEC1)])
        self.assertEqual(self.surfaces(["docs/*", "lib/*"], "src/a.py", "af4"), [])

    def test_applies_to_glob_forms(self):   # HA3, HA4, HA6, HA7
        rows = [(["src/*"], "src/a/b/c.py", True), (["src/**"], "src/a/b.py", True), (["**/x.py"], "x.py", False),
                (["**/x.py"], "a/x.py", True), (["src/**/x.py"], "src/x.py", False), (["src/**/x.py"], "src/a/x.py", True),
                (["**"], "any/where.py", True), (["*"], ".hidden", True), (["src/*"], "src/.hidden.py", True),
                (["src/[ab].py"], "src/a.py", True), (["src/[ab].py"], "src/c.py", False), (["src/[!a].py"], "src/a.py", False),
                (["src/[!a].py"], "src/b.py", True), (["src/[a-c].py"], "src/b.py", True), (["src/[a-c].py"], "src/d.py", False)]
        for n, (globs, path, want) in enumerate(rows):
            with self.subTest(globs=globs, path=path):
                self.assertEqual(self.surfaces(globs, path, "gf%d" % n), [IF(DEC1)] if want else [])

    def test_applies_to_case_sensitive(self):   # HA5, M21
        self.assertEqual(self.surfaces(["SRC/*"], "src/a.py", "cs1"), [])
        self.assertEqual(self.surfaces(["src/*.PY"], "src/a.py", "cs2"), [])
        self.assertEqual(self.surfaces(["src/*.py"], "src/a.py", "cs3"), [IF(DEC1)])

    def test_applies_to_invalid_glob(self):   # HA8, HA9, V5, M22
        repo = self.newrepo("ig0")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, applies_to=["src/*", "src/[z-a].py"]))
        write_record(repo, D + "/" + DEC2 + ".yml", dec(DEC2))
        for _ in range(2):   # the invalid record is skipped, never marked, so its line repeats; the others surface once
            p = self.edit(repo + "/src/a.py", root=repo)
            self.assertEqual(p.returncode, 0)
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo, session="ig-2")),
                         ["FAIL hook.edit.decisions-load: %s: applies_to.1: must be a supported glob: the bracket expression "
                          "[z-a] holds the reversed range z-a" % DEC1, IF(DEC2)])
        for n, glob in enumerate(("[", "[!", "[]", "src\\")):   # no bracket problem: fnmatchcase gives no match on both interpreters
            with self.subTest(glob=glob):
                repo = self.newrepo("ig%d" % (n + 1))
                write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, applies_to=[glob]))
                write_record(repo, D + "/" + DEC2 + ".yml", dec(DEC2))
                self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), [IF(DEC2)])

    def test_applies_to_wrong_types(self):   # HA10
        repo = self.newrepo("wt1")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, applies_to="src/*"))
        lines = ctx_lines(self.edit(repo + "/src/a.py", root=repo))
        self.assertEqual(lines, ["FAIL hook.edit.decisions-load: %s: applies_to: must be a list" % DEC1])
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)), lines)   # never marked: printed again
        repo = self.newrepo("wt2")
        write_record(repo, D + "/" + DEC1 + ".yml", dec(DEC1, applies_to=5))
        self.assertEqual(ctx_lines(self.edit(repo + "/src/a.py", root=repo)),
                         ["FAIL hook.edit.decisions-load: %s: applies_to: must be a list" % DEC1])
        for n, (globs, path, want) in enumerate([([5, "src/*"], "src/a.py", True), ([None], "src/a.py", False), ([""], "src/a.py", False),
                                                  (["/src/*"], "src/a.py", False)]):
            with self.subTest(globs=globs):
                self.assertEqual(self.surfaces(globs, path, "wt%d" % (n + 3)), [IF(DEC1)] if want else [])

    def test_rel_path(self):   # HA11, HA13, HA16, HA17
        self.put(dec(DEC1, applies_to=["src/a.py", "a.py", "src", ".git/config"]))
        os.makedirs(self.repo + "/src")
        for session, path, cwd, want in (
                ("s0", self.repo + "/src/a.py", None, [IF(DEC1)]),
                ("s1", self.repo + "/a.py", None, [IF(DEC1)]), ("s2", self.repo + "/src/", None, [IF(DEC1)]),
                ("s3", "//" + self.repo.lstrip("/") + "/src/a.py", None, [IF(DEC1)]), ("s4", "a.py", self.repo + "/src", [IF(DEC1)]),
                ("s5", self.repo + "/src/../src/a.py", None, [IF(DEC1)]), ("s6", self.repo + "/.git/config", None, [IF(DEC1)]),
                ("s7", self.repo, None, [])):
            with self.subTest(path=path, cwd=cwd):
                self.assertEqual(ctx_lines(self.edit(path, session=session, cwd=cwd)), want)
        self.put(dec(DEC1, applies_to=["*"]))
        self.assertEqual(ctx_lines(self.edit(self.repo, session="s8")), [])   # HA11: "." never surfaces
        os.makedirs(self.repo + "/" + D + "/x")
        p = self.edit(self.repo + "/" + D + "/x/y.yml", session="s9")   # HA16: refused first
        self.assertEqual(p.returncode, 2)

    def test_linked_worktree_root(self):   # HA12
        self.put(dec(DEC1, applies_to=["src/*"]))
        write_record(self.repo, "wt-marker.txt", {"a": 1})
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", "--detach", "--", wt)
        write_record(wt, D + "/" + DEC2 + ".yml", dec(DEC2, applies_to=["src/*"]))
        self.assertEqual(ctx_lines(self.edit(wt + "/src/a.py", cwd=wt)), [IF(DEC2)])
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])

    def test_symlinked_cwd_and_target(self):   # HA14, HA15 (Q3 (c): both forms)
        self.put(dec(DEC1, applies_to=["src/*"]), dec(DEC2, applies_to=["lib/*"]))
        os.makedirs(self.repo + "/src")
        os.makedirs(self.repo + "/lib")
        link = os.path.join(self.tmp, "link")
        os.symlink(self.repo, link)
        self.assertEqual(ctx_lines(self.edit("src/a.py", cwd=link, session="h14")), [IF(DEC1)])
        os.symlink(self.repo + "/lib/real.py", self.repo + "/src/link.py")
        os.symlink(os.path.join(self.tmp, "x.py"), self.repo + "/src/out.py")
        self.assertEqual(ctx_lines(self.edit(self.repo + "/src/link.py", session="h15")), [IF(DEC1), IF(DEC2)])
        self.assertEqual(ctx_lines(self.edit(self.repo + "/src/out.py", session="h15b")), [IF(DEC1)])

    # ------------------------------------------------------------------ hardening rows

    def test_hardening_symlink_targets(self):   # HR1
        r = self.repo
        os.makedirs(r + "/" + D)
        os.makedirs(r + "/src")
        open(r + "/" + D + "/DEC1.yml", "w").close()
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        open(elsewhere + "/x.yml", "w").close()
        os.symlink(r + "/" + D + "/DEC1.yml", r + "/src/in.yml")
        os.symlink(elsewhere + "/x.yml", r + "/" + D + "/out.yml")
        os.symlink(r + "/nowhere/missing.yml", r + "/" + D + "/dang.yml")
        for path in (r + "/src/in.yml", r + "/" + D + "/out.yml", r + "/" + D + "/dang.yml"):
            with self.subTest(path=path):
                self.assertEqual(self.edit(path).stderr, DENY(path))

    def test_hardening_directory_targets(self):   # HR2
        r = self.repo
        os.makedirs(r + "/" + D + "/sub")
        os.makedirs(r + "/src/dir")
        for path, shown in ((r + "/" + D, r + "/" + D), (r + "/" + D + "/sub/", r + "/" + D + "/sub")):
            with self.subTest(path=path):
                self.assertEqual(self.edit(path).stderr, DENY(shown))
        other = self.newrepo("dir-outside")   # a repository whose decisions directory is empty: nothing to load or surface
        os.makedirs(other + "/src/dir")
        p = self.edit(other + "/src/dir", root=other)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_hardening_fifo_targets(self):   # HR3
        r = self.repo
        os.makedirs(r + "/" + D)
        os.makedirs(r + "/src")
        os.mkfifo(r + "/" + D + "/x.yml")
        os.mkfifo(r + "/src/f")
        started = time.monotonic()
        kind, p = watched(lambda: self.edit(r + "/" + D + "/x.yml"), 5)
        self.assertEqual(kind, "ok")
        self.assertEqual((p.returncode, p.stderr), (2, DENY(r + "/" + D + "/x.yml")))
        other = self.newrepo("fifo-outside")
        os.makedirs(other + "/src")
        os.mkfifo(other + "/src/f")
        for path, root in ((other + "/src/f", other), ("/dev/null", None)):
            with self.subTest(path=path):
                kind, p = watched(lambda: self.edit(path, root=root), 5)
                self.assertEqual(kind, "ok")
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertLess(time.monotonic() - started, 15)

    def test_hardening_parent_symlink(self):   # HR4
        r = self.repo
        os.makedirs(r + "/" + D)
        os.symlink(r + "/" + D, r + "/par")
        self.assertEqual(self.edit(r + "/par/x.yml").stderr, DENY(r + "/par/x.yml"))

    def test_hardening_swap_after_check_is_stated_limit(self):   # HR4
        r = self.repo
        os.makedirs(r + "/" + D)
        os.makedirs(r + "/swap")
        first = self.edit(r + "/swap/x.yml")   # checked while swap is a real directory: passes
        self.assertEqual((first.returncode, first.stdout, first.stderr), (0, "", ""))
        os.rename(r + "/swap", r + "/swap-old")
        os.symlink(r + "/" + D, r + "/swap")   # replaced after the check: the earlier verdict cannot change
        self.assertEqual(first.returncode, 0)
        self.assertEqual(self.edit(r + "/swap/x.yml").returncode, 2)   # a new check follows the state at check time

    def test_hardening_nested_configured_paths(self):   # HR5
        for name, rel, refused, passed in (
                ("outer-cfg", ".strict-delivery/state", [".strict-delivery/state/x.yml", D + "/x.yml"], [".strict-delivery/other/x.yml"]),
                ("inner-cfg", D + "/inner", [D + "/inner/x.yml", D + "/inner"], [D + "/other.yml", D + "/x.yml"])):
            repo = self.newrepo("nest-" + name, dict(minimal_config(), paths={"decisions": rel}))
            for p in refused:
                with self.subTest(name=name, path=p):
                    self.assertEqual(self.edit(repo + "/" + p, root=repo).stderr, DENY(repo + "/" + p))
            for p in passed:
                with self.subTest(name=name, path=p):
                    q = self.edit(repo + "/" + p, root=repo)
                    self.assertEqual((q.returncode, q.stderr), (0, ""))

    def test_hardening_unusual_names(self):   # HR6
        p = self.edit(self.repo + "/x\ud800.yml")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", INP("tool_input.file_path holds a NUL or a lone surrogate")))
        for raw, shown in (("a\nb", "a\\nb"), ("a\tb", "a\\tb"), ("a b", "a b"), ("é", "é"), ("Ⱟ", "\\u2c2f")):
            with self.subTest(name=raw):
                self.assertEqual(self.edit(self.repo + "/" + D + "/" + raw).stderr, DENY(self.repo + "/" + D + "/" + shown))
                q = self.edit(self.repo + "/" + raw + "/x.yml")   # not under the decisions directory: the normal verdict
                self.assertEqual((q.returncode, q.stdout, q.stderr), (0, "", ""))
        os.makedirs(self.repo + "/" + D)
        open(self.repo + "/" + D + "/" + DEC2 + ".yml", "wb").write(b"id: \xff\xfe\n")
        q = self.edit(self.src())
        lines = ctx_lines(q)
        self.assertEqual(q.returncode, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FAIL hook.edit.decisions-load: "))

    def test_hardening_outside_root(self):   # HR7
        self.put(dec(DEC1, applies_to=["**"]))
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        for path in (outside + "/a.py", "/etc/hosts"):
            with self.subTest(path=path):
                p = self.edit(path)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        clone = os.path.join(self.tmp, "clone")
        os.makedirs(clone)
        make_repo(clone)
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", "--detach", "--", wt)
        for path in (clone + "/" + D + "/DEC1.yml", wt + "/" + D + "/DEC1.yml"):
            with self.subTest(path=path):
                self.assertEqual(self.edit(path).stderr, DENY(path))
        self.assertFalse(os.path.exists(os.path.join(self.data, "sessions")))


class ReviewOneTest(Base):
    """Fix round 1 (F-20261124-se42, jjq8, vyet, n5zc)."""

    def test_sibling_prefix_of_root_not_surfaced(self):   # se42 (a): a sibling sharing the root's name prefix is outside
        self.put(dec(DEC1, applies_to=["**"]), dec(DEC2, applies_to=["-x/*"]))
        for name in ("repo-x", "repo-", "repo2"):
            with self.subTest(sibling=name):
                os.makedirs(os.path.join(self.work, name, "src"))
                p = self.edit(os.path.join(self.work, name, "src", "a.py"))
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(ctx_lines(self.edit(self.src(), session="inside")), [IF(DEC1)])

    def test_outside_root_with_malformed_record(self):   # jjq8
        self.put(dec(DEC1, applies_to=["**"]))
        with open(self.repo + "/" + D + "/" + DEC2 + ".yml", "w") as fh:
            fh.write("id: [\n")
        outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(outside)
        for path in (outside + "/a.py", os.path.join(self.work, "repo-x", "a.py")):
            p = self.edit(path)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(os.listdir(self.data), [])

    def test_no_match_leaves_store_unchanged(self):   # vyet
        self.put(dec(DEC1, applies_to=["src/*"]))
        p = self.edit(self.repo + "/docs/x.md")   # no match, no state yet: nothing created
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(os.listdir(self.data), [])
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(DEC1)])
        path = self.state_path()
        def snap():
            with open(path, "rb") as fh:
                return (fh.read(), os.stat(path).st_mtime_ns, sorted(os.listdir(os.path.dirname(path))))
        before = snap()
        p = self.edit(self.repo + "/docs/x.md")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        after = snap()
        self.assertEqual(before, after)
        env = self.env(data=os.path.join(self.tmp, "fresh-data"))   # a store directory that does not exist yet stays absent
        self.assertEqual(self.edit(self.repo + "/docs/x.md", env=env).stdout, "")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "fresh-data")))

    def test_long_id_5000_characters(self):   # n5zc HC9
        long_id = "DEC-" + "a" * 4996
        self.assertEqual(len(long_id), 5000)
        write_record(self.repo, D + "/" + DEC1 + ".yml", dec(long_id))
        self.assertEqual(ctx_lines(self.edit(self.src())), [IF(long_id)])
        self.assertEqual(ctx(self.edit(self.src())), "")
        self.assertEqual(yamlsub.load(self.state_path(), "state")["surfaced"], [long_id])

    def test_read_tool_with_decisions_path_silent(self):   # n5zc HD18 (the row's Bash member is wrong: Bash routes to pre_bash)
        self.put(dec(DEC1))
        for path in (self.repo + "/" + D + "/DEC1.yml", self.repo + "/" + D, self.src()):
            with self.subTest(path=path):
                p = self.edit(path, tool="Read")
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(os.listdir(self.data), [])


if __name__ == "__main__":
    unittest.main()
