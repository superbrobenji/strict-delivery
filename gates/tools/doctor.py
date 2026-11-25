"""Tool ``doctor``: checks an initialised project and writes nothing (spec 4; plan Task 4d.3; rulings (4c), (4d)).

``python3 -m gates.tools.doctor --root R [--json]`` prints one line per check, in a fixed order, and exits 0 only
when every line passes, 1 for a FAIL, 2 for a usage error. ``doctor`` is a command, not a gate: it is in neither
``GATES`` nor ``run_all``. It makes no git write call, calls no ``gh`` write, and calls ``index.render`` (in memory),
never ``index.regenerate``. Standard library only.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import sys
from typing import Optional

from gates import gate_schema
from gates.lib import config, context, dispatch, gitinfo, host, managed, plugin, schema, templates
from gates.lib.result import GateError, Line, Result, gate_args, run_check, safe_text
from gates.tools import githooks, index

WORKFLOW = ".github/workflows/strict-delivery.yml"
SETTINGS = ".claude/settings.json"
CONFIG = ".strict-delivery/config.yml"
UNSET = "unset (Claude Code default)"
NEITHER = "neither extra installed: this repository is gated only inside Claude sessions"
NOT_FW = "%s is the framework's own directory; pass the target repository's top level"
FAILED_VERSION = "not checked: doctor.version failed"
FAILED_INDEXES = "not checked: doctor.indexes failed"
UPGRADE = "stale; run /strict-delivery:upgrade"
SHOWN_MAX = 64
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class _Unreadable(Exception):
    """A file doctor reads itself cannot be read; the message is the reason (without the path)."""


def _why(e: BaseException) -> str:
    return str(e) if isinstance(e, GateError) else "%s: %s" % (type(e).__name__, e)


def _read(root: str, rel: str) -> Optional[str]:
    """The text of the regular file ``rel`` under ``root`` (see ``_read_bytes``); non-UTF-8 is a reason."""
    data = _read_bytes(root, rel)
    if data is None:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _Unreadable("is not valid UTF-8") from None


def _read_bytes(root: str, rel: str) -> Optional[bytes]:
    """The bytes of the regular file ``rel`` under ``root``; ``None`` when it is absent. Every component is
    ``lstat``ed (a symlink or a non-directory parent and a non-regular file are refused) and then opened from the
    descriptor of the one before it with ``O_NOFOLLOW`` (a parent also ``O_DIRECTORY``, the file also ``O_NONBLOCK``)
    and the file ``fstat``ed, so an object swapped in after its check is refused and never read outside the root and a
    FIFO never blocks; any OSError is a reason."""
    parts = rel.split("/")
    try:
        fd = os.open(root, os.O_RDONLY | _DIRECTORY)
    except OSError as e:
        raise _Unreadable("cannot be read (%s)" % (e.strerror or type(e).__name__)) from None
    try:
        for i, part in enumerate(parts):
            shown = "/".join(parts[:i + 1])
            last = i == len(parts) - 1
            try:
                st = os.lstat(part, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError as e:
                raise _Unreadable("cannot be read (%s)" % (e.strerror or type(e).__name__)) from None
            if stat.S_ISLNK(st.st_mode):
                raise _Unreadable("is a symlink" if last else "parent %s is a symlink" % shown)
            if last and not stat.S_ISREG(st.st_mode):
                raise _Unreadable("is not a regular file")
            if not last and not stat.S_ISDIR(st.st_mode):
                raise _Unreadable("parent %s is not a directory" % shown)
            flags = os.O_RDONLY | _NOFOLLOW | (_NONBLOCK if last else _DIRECTORY)
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except OSError as e:
                raise _Unreadable(_open_reason(e, part, fd, shown, last)) from None
            os.close(fd)
            fd = nxt
        if not stat.S_ISREG(os.fstat(fd).st_mode):  # swapped to a FIFO or a directory after the lstat
            raise _Unreadable("is not a regular file")
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            data = fh.read()
    except OSError as e:
        raise _Unreadable("cannot be read (%s)" % (e.strerror or type(e).__name__)) from None
    finally:
        if fd >= 0:
            os.close(fd)
    return data


def _parents(root: str, rel: str) -> None:
    """Refuse a symlink or a non-directory among the parents of ``rel`` (``config.load`` follows a symlinked parent and
    would read outside the root); an absent parent is left to the reader's own reason."""
    parts = rel.split("/")
    for i in range(len(parts) - 1):
        shown = "/".join(parts[:i + 1])
        try:
            st = os.lstat(os.path.join(root, shown))
        except OSError:
            return
        if stat.S_ISLNK(st.st_mode):
            raise _Unreadable("parent %s is a symlink" % shown)
        if not stat.S_ISDIR(st.st_mode):
            raise _Unreadable("parent %s is not a directory" % shown)


def _open_reason(e: OSError, name: str, fd: int, shown: str, last: bool) -> str:
    """The reason an ``O_NOFOLLOW`` open failed: a symlink put in place after the ``lstat`` is named as one."""
    link = e.errno in (errno.ELOOP, errno.EMLINK)
    if not link and e.errno == errno.ENOTDIR:
        try:
            link = stat.S_ISLNK(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
        except OSError:
            link = False
    if link:
        return "is a symlink" if last else "parent %s is a symlink" % shown
    if e.errno == errno.ENOTDIR:
        return "parent %s is not a directory" % shown
    return "cannot be read (%s)" % (e.strerror or type(e).__name__)


def _fail(id_: str, reason: str) -> Line:
    return Line("FAIL", "doctor." + id_, reason)


def _pass(id_: str, reason: str = "") -> Line:
    return Line("PASS", "doctor." + id_, reason)


def _framework_sha() -> Optional[str]:
    """The framework checkout's commit (``None`` when it is not a git top level); the call of Task 4d.1."""
    try:
        return gitinfo.head_sha(plugin.framework_dir())
    except GateError:
        return None


# ---------------------------------------------------------------------------------------------------- the lines
def _python() -> Line:
    if sys.version_info >= (3, 9):
        return _pass("python")
    return _fail("python", "Python %d.%d is older than 3.9" % (sys.version_info[0], sys.version_info[1]))


def _context(root: str, cfg: dict) -> Line:
    """``doctor.context`` (plan :5102, Amendment C): the file at ``paths.context`` is opened the way every other file is
    (a symlink, a non-regular file and non-UTF-8 are refused with doctor's file-state texts) and then validated by the
    production loader ``context.load``, whose ``GateError`` text (also the missing-file text) is the reason."""
    rel = cfg["paths"]["context"]
    try:
        _read(root, rel)
    except _Unreadable as e:
        return _fail("context", "%s: %s" % (rel, e))
    context.load(root, cfg)  # an absent file raises its own "missing; run /strict-delivery:init"
    return _pass("context")


def _inside_framework(root: str) -> bool:
    real = os.path.realpath(root)
    fw = os.path.realpath(plugin.framework_dir())
    return real == fw or real.startswith(fw.rstrip(os.sep) + os.sep)


def _common_dir(root: str) -> str:
    """The absolute git common directory (git's own answer; the linked worktrees' hooks live in its ``hooks``)."""
    common = gitinfo._run(root, "rev-parse --git-common-dir", ["rev-parse", "--git-common-dir"])
    text = gitinfo._text(common.stdout, "rev-parse --git-common-dir")
    return os.path.abspath(os.path.join(root, text[:-1] if text.endswith("\n") else text))


def _locate(root: str, directory: str) -> Optional[tuple]:
    """``(base, parts)``: the hooks ``directory`` below the root or below the git common directory (the only two places a
    hooks directory may be; a linked worktree's lies outside the root), as the components under that base; ``None`` for
    any other place (H7), which no read may reach."""
    for base in (os.path.abspath(root), _common_dir(root)):
        rel = os.path.relpath(directory, base)
        if rel == ".":
            return base, []
        if rel != ".." and not rel.startswith(".." + os.sep):
            return base, rel.split(os.sep)
    return None


def _dir_safe(base: str, parts: list) -> bool:
    """True when every component of ``parts`` below ``base`` is a real directory or absent: each is opened from the
    descriptor of the one before it with ``O_NOFOLLOW`` and ``O_DIRECTORY`` (H4: a symlinked parent is never followed)."""
    try:
        fd = os.open(base, os.O_RDONLY | _DIRECTORY)
    except OSError:
        return False
    try:
        for part in parts:
            try:
                nxt = os.open(part, os.O_RDONLY | _NOFOLLOW | _DIRECTORY, dir_fd=fd)
            except FileNotFoundError:
                return True
            except OSError:
                return False
            os.close(fd)
            fd = nxt
        return True
    finally:
        os.close(fd)


def _hooks_dir_safe(root: str, directory: str) -> bool:
    found = _locate(root, directory)
    return found is not None and _dir_safe(found[0], found[1])


def _has_header(root: str, directory: str, name: str) -> bool:
    """True when ``name`` in the hooks ``directory`` is a regular file whose line 2 is the shim header. The file is read
    by ``_read_bytes`` (every component below its base opened from the one before with ``O_NOFOLLOW``, never outside
    the root or the common directory, a FIFO never opened blocking); any refusal means no."""
    found = _locate(root, directory)
    if found is None:
        return False
    try:
        data = _read_bytes(found[0], "/".join(found[1] + [name]))
    except _Unreadable:
        return False
    if data is None:
        return False
    lines = data.split(b"\n")  # line 2 must be complete: a third piece exists
    return len(lines) >= 3 and lines[1] == githooks.HEADER.encode("utf-8")


def _hooks_installed(root: str) -> bool:
    dirs = [gitinfo.hooks_dir(root), os.path.join(_common_dir(root), "hooks")]
    return any(_has_header(root, d, n) for d in dirs for n in githooks.NAMES)


class _Ci:
    """The state of the CI workflow: ``absent``, ``project``, ``managed`` or an unreadable reason."""

    def __init__(self, root: str) -> None:
        self.text = None
        self.error = None
        try:
            self.text = _read(root, WORKFLOW)
        except _Unreadable as e:
            self.error = "%s: %s" % (WORKFLOW, e)
        if self.error is not None or self.text is None:
            self.kind = "error" if self.error is not None else "absent"
        else:
            self.kind = "managed" if managed.is_generated(self.text) else "project"


def _extras(hooks: bool, ci: _Ci) -> Line:
    if ci.kind == "error":
        return _fail("extras", ci.error)
    project = "CI: %s is a project workflow, not the framework template" % WORKFLOW
    if not hooks and ci.kind != "managed":
        return _pass("extras", NEITHER + ("; " + project if ci.kind == "project" else ""))
    cipart = {"managed": "CI: installed", "absent": "CI: not installed", "project": project}[ci.kind]
    return _pass("extras", "git hooks: %s; %s" % ("installed" if hooks else "not installed", cipart))


def _githooks(root: str) -> list:
    out = []
    if not _hooks_dir_safe(root, gitinfo.hooks_dir(root)):
        # H4, H7 (EX9): the library's status reads by path and follows a symlinked parent; doctor refuses first
        for name in githooks.NAMES:
            out.append(_fail("githooks." + name, "foreign"))
    else:
        try:
            res = githooks.status(root, githooks.framework_dir())
        except githooks._FrameworkError as e:
            out.append(_fail("githooks.framework", str(e)))
        else:
            for ln in res.lines:  # "githooks.<name>" restated as "doctor.githooks.<name>"
                out.append(Line(ln.status, "doctor." + ln.id, ln.reason))
    value = githooks._hooks_path(root)
    if value is not None:
        out.append(_fail("githooks.hooks-path", "core.hooksPath is set (%s); unset it to install the hooks" % value))
    return out


def _ci_line(cfg: dict, pv: str, text: str) -> Line:
    expected = templates.ci_pin(pv, _framework_sha())
    found = templates.pin_of(text)
    if found != expected:
        return _fail("ci", "pin %s differs from %s" % ("not found" if found is None else found, expected))
    if templates.ci_workflow(cfg, expected, plugin.repository_slug(plugin.framework_dir())) != text:
        return _fail("ci", "stale")
    return _pass("ci")


def _block_line(root: str, cfg: dict, pv: str, rel: str, style: str, kind: str, render) -> Line:
    id_ = kind
    try:
        text = _read(root, rel)
    except _Unreadable as e:
        return _fail(id_, "%s: %s" % (rel, e))
    if text is None:
        return _fail(id_, "missing")
    try:
        block = managed.find_block(text, style)
    except managed.ManagedError as e:
        return _fail(id_, "malformed: %s" % e)
    if block is None:
        return _fail(id_, "missing")
    errs = schema.validate_managed_block(schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml")), text)
    if errs:
        return _fail(id_, "malformed: %s" % errs[0])
    if block.version != pv:
        return _fail(id_, "version %s differs from the plugin %s" % (block.version, pv))
    try:
        body = render(cfg)
    except GateError as e:
        return _fail(id_, "cannot render the block: %s" % e)
    if block.body != body:
        return _fail(id_, UPGRADE)
    return _pass(id_)


def _registers(root: str) -> Line:
    res = gate_schema.check(["--root", root])
    if res.ok():
        return _pass("registers")
    ids = []
    for ln in res.lines:
        if ln.status == "FAIL" and ln.id not in ids:
            ids.append(ln.id)
    return _fail("registers", ", ".join(ids))


class _IntText(str):
    """A JSON number kept as its text (no ``int()`` runs, so no interpreter's digit limit can fire)."""


class _Refused(Exception):
    pass


def _pairs(pairs: list) -> dict:
    out = {}
    for k, v in pairs:
        if k in out:
            raise _Refused("duplicate key")
        out[k] = v
    return out


def _constant(name: str):
    raise _Refused("constant")


def _float(text: str) -> float:
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise _Refused("not finite")
    return value


def _settings(root: str) -> dict:
    """The parsed ``.claude/settings.json`` (``{}`` when absent); a refusal is a ``GateError`` with the reason."""
    try:
        text = _read(root, SETTINGS)
    except _Unreadable as e:
        raise GateError("%s: %s" % (SETTINGS, e)) from None
    if text is None:
        return {}
    try:
        if text.startswith("\ufeff"):
            raise _Refused("BOM")
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_IntText,
                          parse_float=_float)
    except (ValueError, RecursionError, _Refused):
        raise GateError("%s: invalid JSON" % SETTINGS) from None
    if type(data) is not dict:
        raise GateError("%s: the top level must be an object" % SETTINGS)
    return data


def _shown(value: object) -> str:
    if type(value) is not str:
        return "a value that is not a string"
    return value if len(value) <= SHOWN_MAX else value[:SHOWN_MAX] + "..."


def _subagents(root: str) -> Line:
    data = _settings(root)
    env = data.get("env", {})
    if type(env) is not dict:
        raise GateError("%s: env must be an object" % SETTINGS)
    parts = []
    for name in (dispatch.ENV_DEPTH, dispatch.ENV_CONCURRENT):
        if name not in env:
            parts.append("%s=%s" % (name, UNSET))
            continue
        try:
            dispatch.limits_of({}, {name: env[name]})
        except ValueError:
            return _fail("subagents", "%s: %s=%s must be a decimal integer of at least 1" % (SETTINGS, name,
                                                                                            _shown(env[name])))
        parts.append("%s=%s" % (name, env[name]))
    return _pass("subagents", "; ".join(parts))


def _protection(root: str, cfg: dict) -> Line:
    try:
        slug = host.github_remote(root)
    except GateError as e:
        return _fail("protection", "cannot read the origin remote: %s" % e)
    if slug is None:
        return _pass("protection", "not checked: no GitHub remote")
    branch = cfg["base_branch"]
    try:
        state = host.read_state(root, slug, branch)
        missing = host.missing(state) if _shape_ok(state) else None
    except GateError as e:
        return _fail("protection", "cannot read %s: %s" % (slug, e))
    if missing is None:
        return _fail("protection", "cannot read %s: unexpected host answer" % slug)
    if not state["protected"] and not missing:
        missing = ["branch %s is not protected" % branch]
    if missing:
        return _fail("protection", "; ".join(missing))
    return _pass("protection", "%s %s is protected" % (slug, branch))


def _shape_ok(state: object) -> bool:
    keys = ("protected", "pr_required", "admins", "merge_commit", "squash", "rebase")
    return type(state) is dict and sorted(state) == sorted(keys) and all(type(state[k]) is bool for k in keys)


# ---------------------------------------------------------------------------------------------------- the run
def _guarded(lines: list, id_: str, fn) -> object:
    """Run ``fn``; append its Line (or Lines); an exception is ``FAIL doctor.<id>: cannot be checked: ...``."""
    try:
        out = fn()
    except GateError as e:  # the check refused with its own reason
        lines.append(_fail(id_, str(e)))
        return None
    except Exception as e:
        lines.append(_fail(id_, "cannot be checked: %s" % _why(e)))
        return None
    lines.extend(out if type(out) is list else [out])
    return out


def _lines(root: object) -> list:
    lines: list = []
    _guarded(lines, "python", _python)
    if type(root) is not str or root == "":
        lines.append(_fail("input", "--root must not be empty"))
        return lines
    if "\x00" in root:
        lines.append(_fail("input", "--root holds a NUL character"))
        return lines
    root = os.path.abspath(root)
    try:
        if _inside_framework(root):
            lines.append(_fail("input", NOT_FW % root))
            return lines
        try:
            _parents(root, CONFIG)
        except _Unreadable as e:
            lines.append(_fail("input", "%s: %s" % (CONFIG, e)))
            return lines
        cfg = config.load(root)
    except (GateError, ValueError, OSError) as e:
        lines.append(_fail("input", str(e) if isinstance(e, GateError) else "%s: %s" % (type(e).__name__, e)))
        return lines
    lines.append(_pass("input"))
    _guarded(lines, "context", lambda: _context(root, cfg))
    fw = plugin.framework_dir()
    pv = None
    try:
        pv = plugin.version(fw)
    except GateError as e:
        lines.append(_fail("version", str(e)))
    else:
        if cfg["framework_version"] == pv:
            lines.append(_pass("version"))
        else:
            lines.append(_fail("version", "framework_version %s differs from the plugin %s; run /strict-delivery:upgrade"
                               % (cfg["framework_version"], pv)))
    ci = _Ci(root)
    installed = False
    unsafe = False
    try:
        # owner Q-RC14-3, 2026-11-25 (Note H-2): "D-1: judge only the hooks dir git actually uses; with hooksPath
        # outside the root and no shim there, report 'not installed', no FAIL, even if old shims sit in .git/hooks. D-2:
        # an outside dir holding the shims also reports 'not installed', no FAIL": a hooks directory outside the root
        # and the git common dir (`_locate` None) is never read, and the default .git/hooks is then not looked at
        found = _locate(root, gitinfo.hooks_dir(root))
        installed = found is not None and _hooks_installed(root)
        # F-20261125-h7nn (CD17 "a symlink anywhere is a conflict"; Amendment H H4/H7 fail closed): an unsafe hooks
        # directory is reported `foreign` per hook whatever the installed gate says; owner Q-RC14-2 (b), 2026-11-25: only
        # one inside the repository (below the root or the git common dir): "A hooksPath outside the root with no shim
        # reports 'not installed', with no FAIL"
        unsafe = found is not None and not _dir_safe(found[0], found[1])
        lines.append(_extras(installed, ci))
    except Exception as e:
        lines.append(_fail("extras", "cannot be checked: %s" % _why(e)))
    if installed or unsafe:
        _guarded(lines, "githooks", lambda: _githooks(root))
    if ci.kind == "managed":
        if pv is None:
            lines.append(_fail("ci", FAILED_VERSION))
        else:
            _guarded(lines, "ci", lambda: _ci_line(cfg, pv, ci.text))
    for id_, rel, style, render in (("claude-block", "CLAUDE.md", managed.HTML, templates.claude_block_body),
                                    ("gitignore-block", ".gitignore", managed.HASH, templates.gitignore_block_body)):
        if pv is None:
            lines.append(_fail(id_, FAILED_VERSION))
        else:
            _guarded(lines, id_, lambda: _block_line(root, cfg, pv, rel, style, id_, render))
    _guarded(lines, "registers", lambda: _registers(root))
    rendered: dict = {}

    def _indexes() -> Line:
        rendered.update(index.render(root, cfg))
        return _pass("indexes")
    ok = _guarded(lines, "indexes", _indexes) is not None

    def _tracked() -> Line:
        idx = os.environ.get("GIT_INDEX_FILE")  # GT13: inherited by design, but it must name a regular file (a FIFO would block git)
        if idx is not None:
            try:
                regular = stat.S_ISREG(os.lstat(os.path.join(root, idx)).st_mode)
            except (OSError, ValueError):
                regular = False
            if not regular:
                raise GateError("cannot be checked: GIT_INDEX_FILE %s is not a regular file" % idx)
        tracked = gitinfo.tracked_files(root)
        hit = sorted(k for k in rendered if k in tracked)
        return _fail("generated-tracked", ", ".join(hit)) if hit else _pass("generated-tracked")
    if ok:
        _guarded(lines, "generated-tracked", _tracked)
    else:
        lines.append(_fail("generated-tracked", FAILED_INDEXES))
    _guarded(lines, "subagents", lambda: _subagents(root))
    lines.append(_pass("merge-mode", "merge.mode is %s" % cfg["merge"]["mode"]))
    _guarded(lines, "protection", lambda: _protection(root, cfg))
    return lines


def check(args: list) -> Result:
    """``check(["--root", R])``: the doctor lines as a ``Result`` (gate ``doctor``); prints nothing."""
    if type(args) is not list or any(type(a) is not str for a in args):
        raise GateError("args: must be a list of str")
    ns = gate_args("doctor").parse_args(args)
    if ns.root is None:
        raise GateError("--root is required")
    return Result("doctor", _lines(ns.root))


def format_lines(res: Result) -> str:
    """The text form: ``PASS <id>[: <reason>]`` and ``FAIL <id>: <reason>``, each reason through ``safe_text``."""
    out = []
    for ln in res.lines:
        if ln.status == "PASS":
            out.append("PASS %s%s\n" % (safe_text(ln.id), ": " + safe_text(ln.reason) if ln.reason else ""))
        else:
            out.append("FAIL %s: %s\n" % (safe_text(ln.id), safe_text(ln.reason)))
    return "".join(out)


def main(argv: list) -> int:
    """``--root R [--json]`` (``--json`` first or last): 0 when every line passes, 1 for a FAIL, 2 for usage."""
    if type(argv) is not list or any(type(a) is not str for a in argv):
        sys.stderr.write("usage: python3 -m gates.tools.doctor --root R [--json]\n")
        return 2
    args = list(argv)
    as_json = False
    if args[:1] == ["--json"]:
        as_json, args = True, args[1:]
    elif args[-1:] == ["--json"]:
        as_json, args = True, args[:-1]
    try:
        ns = gate_args("doctor").parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    if ns.root is None:
        sys.stderr.write("usage: python3 -m gates.tools.doctor --root R [--json]\n")
        return 2
    res = run_check("doctor", check, args)
    sys.stdout.write(res.render(True) if as_json else format_lines(res))
    return 0 if res.ok() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
