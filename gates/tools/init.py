"""Tool ``init``: ``python3 -m gates.tools.init <questions|plan|apply> --root R [--answers F] [--json]`` (Task 4d.1).

``questions`` prints what the owner is asked; ``plan`` shows every write as a diff and writes nothing; ``apply`` re-plans
and writes config, directories, blocks, CI, settings, hooks, in that order. Any conflict writes nothing. Nothing here
runs ``git add``, ``git commit`` or ``git push``. Standard library only; Python 3.9 or newer.

Exit codes: 0 success, 1 a conflict or a refusal (``FAIL <id>: <reason>`` on stdout), 2 a usage error (stderr).
"""
from __future__ import annotations

import copy
import difflib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from typing import Optional

from gates.lib import (config, detect, dispatch, gitinfo, managed, migrations, plugin, print_table,
                       profiles, schema, templates, yamlsub)
from gates.lib.result import GateError, GitNotFound, _GateParser, safe_text
from gates.tools import githooks

PRODUCES = ("claude-block", "gitignore-block")
USAGE = "usage: python3 -m gates init <questions|plan|apply> --root R [--answers F] [--json]\n"
SETTINGS = ".claude/settings.json"
CI_PATH = ".github/workflows/strict-delivery.yml"
CONTEXT_TEMPLATE = "context.yml"  # templates/context.yml (Amendment C, plan :5102, owner answer Q-RC13-1)
STATE_KEYS = ("decisions", "findings", "claims", "plan_state", "programs", "playbooks")
SLOTS = detect.SLOTS
TIERS = ("tier1", "tier2", "tier3", "tier4")
ENV_NAMES = (("depth", dispatch.ENV_DEPTH), ("concurrent", dispatch.ENV_CONCURRENT))
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*", re.ASCII)
_HEX_RUN = re.compile(r"[0-9a-fA-F]{41}", re.ASCII)
_ANSWERS_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas",
                               "init-answers.yml")
_STATUS_ARGS = ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=no", "--no-renames",
                "--ignore-submodules=none"]


class InitError(GateError):
    """A refusal with the id of the ``FAIL`` line it prints."""

    def __init__(self, ident: str, reason: str, parts: Optional[list] = None) -> None:
        super().__init__(reason)
        self.ident = ident
        self.reason = reason
        self.parts = list(parts) if parts is not None else [reason]  # one FAIL line each, escaped once when printed


def _input(reason: object) -> InitError:
    return InitError("init.input", str(reason))


@dataclass(frozen=True)
class InitPlan:
    writes: list
    conflicts: list
    settings: Optional[tuple]
    moves: list
    host_calls: list
    notes: list


@dataclass
class _Extra:
    """What ``plan_init`` keeps beside the six public fields."""
    config_path: Optional[str] = None
    dirs: list = field(default_factory=list)
    hooks: list = field(default_factory=list)
    hooks_dir: Optional[str] = None
    hook_names: list = field(default_factory=list)  # every hook init plans or keeps there: missing, stale, ok
    context_path: Optional[str] = None
    diffs: list = field(default_factory=list)  # (path, old, new)
    actions: list = field(default_factory=list)  # (path, new) from managed.plan


# ---------------------------------------------------------------------------------------------------- the root
def _check_root(root: object) -> str:
    """The real path of ``root`` when it is the top level of a repository outside the framework; else ``init.input``."""
    if type(root) is not str:
        raise _input("root: must be a str")
    try:
        real = os.path.realpath(root)
        fw = os.path.realpath(plugin.framework_dir())
    except ValueError:
        raise _input("%s: unusable path" % root) from None
    if real == fw or real.startswith(fw.rstrip(os.sep) + os.sep):
        raise _input("%s is the framework's own directory; pass the target repository's top level" % root)
    try:
        top = gitinfo.toplevel(root)
    except GateError as e:
        raise _input("%s: %s" % (root, e)) from None
    if top != real:
        raise _input("%s: not the repository top level (%s)" % (root, top))
    return real


def _load_config(root: str):
    """``(cfg, initialised)``: the loaded config, or a copy of the defaults when the config is absent."""
    if not os.path.lexists(os.path.join(root, config.CONFIG_PATH)):
        return copy.deepcopy(config.DEFAULTS), False
    try:
        return config.load(root), True
    except GateError as e:
        raise InitError("init.config", "%s; run /strict-delivery:doctor and /strict-delivery:upgrade" % e) from None


# ---------------------------------------------------------------------------------------------- settings reader
def _read_settings(root: str):
    """``("absent",)``, ``("ok", data)`` or ``("bad", reason)``; the one reader of ``.claude/settings.json``."""
    try:
        state = managed._inspect(root, SETTINGS)
    except GateError as e:
        raise _input(e) from None
    if state[0] == "absent":
        return ("absent",)
    if state[0] == "conflict":
        reason = state[1]
        if reason == managed._NOT_MANAGED:  # a directory, FIFO or socket, or a regular file that is not UTF-8
            try:
                regular = stat.S_ISREG(os.lstat(os.path.join(root, SETTINGS)).st_mode)
            except OSError:
                regular = False
            return ("bad", "is not valid UTF-8" if regular else "exists and is not a regular file")
        return ("bad", reason)
    try:
        data = json.loads(state[1], object_pairs_hook=plugin._pairs, parse_constant=plugin._constant,
                          parse_int=plugin._integer, parse_float=plugin._float)
    except plugin._Refused as e:
        return ("bad", e.args[0])
    except RecursionError:
        return ("bad", "nesting is too deep")
    except ValueError:
        return ("bad", "is not valid JSON")
    if type(data) is not dict:
        return ("bad", "top level is not an object")
    if "env" in data and type(data["env"]) is not dict:
        return ("bad", "env is not an object")
    return ("ok", data)


def _wanted_env(subagents: dict) -> dict:
    return {name: str(subagents[key]) for key, name in ENV_NAMES if key in subagents}


def _settings_change(root: str, subagents: dict):
    """``(settings, conflicts, write)``: ``settings`` is None, ``("create", text)`` or ``("conflict", reason)``."""
    wanted = _wanted_env(subagents)
    if not wanted:
        return None, [], None
    state = _read_settings(root)
    if state[0] == "absent":
        text = json.dumps({"env": wanted}, indent=2, sort_keys=True) + "\n"
        return ("create", text), [], managed.Write(SETTINGS, text, "file")
    if state[0] == "bad":
        reason = "%s: %s" % (SETTINGS, state[1])
        return ("conflict", reason), [reason], None
    env = state[1].get("env", {})
    notes = []
    for name in sorted(wanted):
        if name not in env:
            notes.append('%s: add "env"."%s": "%s"' % (SETTINGS, name, wanted[name]))
        elif env[name] != wanted[name] or type(env[name]) is not str:
            notes.append('%s: set "env"."%s" to "%s"' % (SETTINGS, name, wanted[name]))
    if notes:
        return ("conflict", "; ".join(notes)), notes, None
    return None, [], None


# ---------------------------------------------------------------------------------------------------- questions
def _problem_dicts(det) -> list:
    return [{"source": p.source, "reason": p.reason} for p in det.problems]


def questions(root: str) -> dict:
    """What the owner is asked; writes nothing."""
    real = _check_root(root)
    _cfg, initialised = _load_config(real)
    try:
        det = detect.detect(real)
        names = {}
        for slot_name in profiles.PROFILES:
            loaded = profiles.load(slot_name)
            names[slot_name] = {"name": slot_name, "defaults": loaded["defaults"], "policy": loaded["policy"]}
    except GateError as e:
        raise _input(e) from None
    problems = _problem_dicts(det)
    current = None
    try:
        state = _read_settings(real)
    except InitError as e:  # QS11: the problem's reason does not repeat the source it names
        state = ("bad", e.reason[len(SETTINGS) + 2:] if e.reason.startswith(SETTINGS + ": ") else e.reason)
    if state[0] == "bad":
        problems.append({"source": SETTINGS, "reason": state[1]})
    elif state[0] == "ok":
        env = state[1].get("env", {})
        found = {}
        for _key, name in ENV_NAMES:
            if name in env:
                if type(env[name]) is not str:
                    problems.append({"source": SETTINGS, "reason": "env.%s: is not a string" % name})
                    continue
                found[name] = env[name]
                if re.fullmatch(r"[0-9]+", env[name], re.ASCII) is None:
                    problems.append({"source": SETTINGS, "reason": "env.%s: is not a decimal string" % name})
        current = found or None
    return {
        "proposals": [{"slot": p.slot, "command": p.command, "source": p.source} for p in det.proposals],
        "problems": problems,
        "ask_test_one": True,
        "profiles": [names[n] for n in profiles.PROFILES],
        "default_profile": "standard",
        "models": copy.deepcopy(config.DEFAULTS["models"]["tiers"]),
        "defaults": {"git_hooks": True, "ci": False, "merge_mode": "host", "protect_base": True},
        "subagents": {"current": current},
        "superpowers_docs": [],
        "initialised": initialised,
    }


def _questions_text(q: dict) -> str:
    return "".join("%s: %s\n" % (k, safe_text(json.dumps(v))) for k, v in q.items())


# --------------------------------------------------------------------------------------------------- the answers
def _line_ok(value: object) -> bool:
    return (type(value) is str and value.replace(" ", "") != "" and print_table.is_printable(value))


def _branch_ok(value: str) -> bool:
    return (_BRANCH.fullmatch(value) is not None and ".." not in value and "//" not in value
            and not value.endswith("/") and not value.endswith(".lock") and _HEX_RUN.search(value) is None)


def _answer_errors(answers: dict, framework_schema) -> list:
    errs = schema.validate(framework_schema, answers, {})
    bad = {e.split(":", 1)[0].split(".")[0] for e in errs}
    for key in ("schema", "profile", "merge_mode", "base_branch"):
        if key not in bad and key in answers and type(answers[key]) is not str:
            errs.append("%s: must be a string" % key)
            bad.add(key)
    for key in ("git_hooks", "ci", "protect_base", "migrate"):
        if key not in bad and key in answers and type(answers[key]) is not bool:
            errs.append("%s: must be true or false" % key)
            bad.add(key)
    if "commands" not in bad and "commands" in answers:
        for slot in SLOTS:
            if slot in answers["commands"] and not _line_ok(answers["commands"][slot]) \
                    and ("commands." + slot) not in {e.split(":", 1)[0] for e in errs}:
                errs.append("commands.%s: must be one line of printable characters" % slot)
    if "models" not in bad and "models" in answers:
        errs.extend(_model_errors(answers["models"]))
    if "subagents" not in bad and "subagents" in answers:
        for key, _name in ENV_NAMES:
            if key in answers["subagents"]:
                v = answers["subagents"][key]
                if type(v) is not int:
                    errs.append("subagents.%s: must be an integer" % key)
                elif v < 1:
                    errs.append("subagents.%s: must be at least 1" % key)
                elif v >= 10 ** dispatch.MAX_DIGITS:
                    errs.append("subagents.%s: must be an integer of at most %d digits" % (key, dispatch.MAX_DIGITS))
    if "base_branch" not in bad and "base_branch" in answers and not _branch_ok(answers["base_branch"]):
        errs.append("base_branch: must be a branch name of letters, digits, '.', '_', '-' and '/'")
    if "migrate" in answers:
        errs.append("migrate: no superpowers documents are tracked")
    return errs


def _model_errors(models: object) -> list:
    errs = []
    if type(models) is not dict:
        return ["models: must be a mapping"]
    for key in models:
        if key != "tiers":
            errs.append("models.%s: unknown key" % key)
    if "tiers" not in models:
        return errs + ["models.tiers: required key is missing"]
    tiers = models["tiers"]
    if type(tiers) is not dict or not tiers:
        return errs + ["models.tiers: must be a non-empty mapping"]
    for key, value in tiers.items():
        if key not in TIERS:
            errs.append("models.tiers.%s: unknown key" % key)
        elif not _line_ok(value):
            errs.append("models.tiers.%s: must be one line of printable characters" % key)
    return errs


def _validated(answers: object, cfg: dict, initialised: bool) -> dict:
    if type(answers) is not dict:
        raise InitError("init.answers", "answers: must be a mapping")
    try:
        sch = schema.load_schema(_ANSWERS_SCHEMA)
    except (GateError, schema.SchemaError) as e:
        raise _input(e) from None
    errs = _answer_errors(answers, sch)
    if errs:
        raise InitError("init.answers", "; ".join(errs), errs)
    if initialised:
        errs = _config_differences(answers, cfg)
        if errs:
            raise InitError("init.answers", "; ".join(errs), errs)
    return answers


def _config_differences(answers: dict, cfg: dict) -> list:
    """D-Q4 (b): on an initialised repository an answer for a config key must equal the loaded config."""
    errs = []

    def differ(key: str, got: object, have: object) -> None:
        errs.append("%s: differs from the config (answer %s, config %s)" % (key, json.dumps(got), json.dumps(have)))
    if answers["profile"] != cfg["profile"]:
        differ("profile", answers["profile"], cfg["profile"])
    if answers["merge_mode"] != cfg["merge"]["mode"]:
        differ("merge_mode", answers["merge_mode"], cfg["merge"]["mode"])
    if answers["base_branch"] != cfg["base_branch"]:
        differ("base_branch", answers["base_branch"], cfg["base_branch"])
    for tier, value in answers["models"]["tiers"].items():
        if cfg["models"]["tiers"].get(tier) != value:
            differ("models.tiers." + tier, value, cfg["models"]["tiers"].get(tier))
    for slot, value in answers["commands"].items():
        if cfg.get("commands", {}).get(slot) != value:
            differ("commands." + slot, value, cfg.get("commands", {}).get(slot))
    return errs


def load_answers(path: str) -> dict:
    """The parsed and checked answers file; an error is ``init.answers: <dotted key>: <reason>``."""
    if type(path) is not str:
        raise InitError("init.answers", "path: must be a string")
    try:
        data = yamlsub.load(path, path)
    except yamlsub.YamlError as e:
        raise InitError("init.answers", "%s%s" % (e.reason, " (line %d)" % e.line if e.line else "")) from None
    if type(data) is not dict:
        raise InitError("init.answers", "top level: must be a mapping")
    for key in ("commands", "subagents"):  # D-Q1 (a): the subset cannot write an empty mapping
        if key in data and data[key] is None:
            data[key] = {}
    try:
        sch = schema.load_schema(_ANSWERS_SCHEMA)
    except (GateError, schema.SchemaError) as e:
        raise _input(e) from None
    errs = _answer_errors(data, sch)
    if errs:
        raise InitError("init.answers", "; ".join(errs), errs)
    return data


# ---------------------------------------------------------------------------------------------------- the plan
def _framework_sha() -> Optional[str]:
    """The framework checkout's commit (``None`` when it is not a git top level); 4d.3 imports this."""
    try:
        return gitinfo.head_sha(plugin.framework_dir())
    except (GateError, GitNotFound):
        return None


def _config_text(answers: dict, version: str) -> str:
    out: dict = {"schema": "config/%d" % migrations.current_version("config"), "framework_version": version,
                 "profile": answers["profile"]}
    commands = {s: answers["commands"][s] for s in SLOTS if s in answers["commands"]}
    if commands:
        out["commands"] = commands
    tiers = answers["models"]["tiers"]
    if tiers != config.DEFAULTS["models"]["tiers"]:
        out["models"] = {"tiers": {t: tiers[t] for t in TIERS if t in tiers}}
    if answers["base_branch"] != "main":
        out["base_branch"] = answers["base_branch"]
    out["merge"] = {"mode": answers["merge_mode"]}
    try:
        return yamlsub.emit(out)
    except yamlsub.EmitError as e:
        raise _input("config: %s" % e) from None


def _dir_plan(root: str, paths: list):
    """``(to_create, conflicts)`` for the state directories: every component is looked at with ``lstat``."""
    create: list = []
    conflicts: list = []
    for path in paths:
        cur = root
        parts = path.split("/")
        for i, part in enumerate(parts):
            cur = os.path.join(cur, part)
            rel = "/".join(parts[:i + 1])
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                if rel not in create:
                    create.append(rel)
                continue
            except OSError as e:
                raise _input("%s: cannot read (%s)" % (rel, e.strerror)) from None
            if stat.S_ISLNK(st.st_mode):
                conflicts.append("%s: is a symlink" % rel)
                break
            if not stat.S_ISDIR(st.st_mode):
                conflicts.append("%s: exists and is not a directory" % rel)
                break
    return create, conflicts


def _plan_block(root: str, kind: str, body: str, version: str, notes: list, writes: list) -> None:
    path = managed._KIND_FILE[kind]
    state = managed._inspect(root, path)
    if state[0] == "text":
        try:
            found = managed.find_block(state[1], managed._KIND_STYLE[kind])
        except GateError:
            found = None  # malformed: managed.plan reports it as a conflict
        if found is not None and found.kind == kind:  # another kind: managed.plan reports it as malformed
            if found.version == version and found.body == body:
                return
            notes.append("%s: present at version %s; run /strict-delivery:upgrade" % (path, found.version))
            return
    writes.append(managed.Write(path, body, kind))


_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")  # Note H-1: the one map


def _fold(path: str) -> str:
    """Note H-1 (VR4 amended for the H5 compare only): ``path`` with ``A``-``Z`` mapped to ``a``-``z`` by one explicit
    table, the same on every Unicode version; every other character is kept (a non-ASCII path never gets here:
    managed refuses it)."""
    return path.translate(_ASCII_FOLD)


def _context_overlap(ctx: str, dirs: list, files: list, state: str) -> list:
    """H5: conflicts for ``paths.context`` ``ctx`` equal to, or nested with, another path init plans: a state directory
    (``dirs``), an ancestor directory of a planned directory or file (so a state directory below ``ctx`` is this case),
    or a planned file (``files``). Texts are managed's own: ``<path>: two writes name the same path`` and
    ``<path>: parent <p> is not a directory`` (``ctx`` below a planned file). Every path is compared under the ASCII
    map (Note H-1, F-20261125-5x5w); a conflict names the configured spellings."""
    shown, ctx = ctx, _fold(ctx)
    dir_name, file_name = {}, {_fold(f): f for f in files}
    for p in [*dirs, state]:
        dir_name.setdefault(_fold(p), p)  # the first configured spelling of a folded directory
    dirs, files, state = [_fold(d) for d in dirs], [_fold(f) for f in files], _fold(state)
    for d in dirs + [state]:  # controller decision (owner delegation 2026-11-09): equal to or inside a state directory
        if ctx == d or ctx.startswith(d + "/"):
            return ["%s: inside the state directory %s" % (shown, dir_name[d])]
    taken = set(files)
    for p in dirs + files:
        parts = p.split("/")
        taken.update("/".join(parts[:i]) for i in range(1, len(parts)))
    if ctx in taken:
        return ["%s: two writes name the same path" % shown]
    return ["%s: parent %s is not a directory" % (shown, file_name[f]) for f in files if ctx.startswith(f + "/")]


def _hook_overlap(root: str, ctx: str, hooks: str, names: list) -> list:
    """H5 (F-20261125-ninr, controller decision): the hook files init plans (``names`` in ``hooks``) are planned files.
    ``ctx`` equal to one, or to the hooks directory when init creates it (absent), is ``two writes name the same
    path``; below one is ``parent <f> is not a directory``. A present hooks directory or git directory is managed's own
    conflict for the context write. Hooks outside ``root`` (a linked worktree's common git directory) get a ``..``
    path, which ``ctx`` never names (config: no ``..`` component). Compared under the ASCII map (Note H-1)."""
    rel = os.path.relpath(hooks, root)
    hook_files = [rel + "/" + n for n in names]
    hook_name = {_fold(h): h for h in hook_files}
    shown, ctx, rel = ctx, _fold(ctx), _fold(rel)
    hook_files = [_fold(h) for h in hook_files]
    if ctx in hook_files + ([] if os.path.lexists(hooks) else [rel]):
        return ["%s: two writes name the same path" % shown]
    return ["%s: parent %s is not a directory" % (shown, hook_name[h]) for h in hook_files if ctx.startswith(h + "/")]


def _state_overlap(dirs: list, files: list) -> list:
    """H5 (F-20261125-5bb3): a configured state directory (``dirs``) equal to a planned file (``files``) is
    ``<dir>: two writes name the same path``; below one is ``<dir>: parent <f> is not a directory`` (managed's texts).
    Compared under the ASCII map (Note H-1); the configured spellings are shown."""
    out = []
    for d in dirs:
        for f in files:
            if _fold(d) == _fold(f):
                out.append("%s: two writes name the same path" % d)
            elif _fold(d).startswith(_fold(f) + "/"):
                out.append("%s: parent %s is not a directory" % (d, f))
    return out


def _hooks_dir_blocked(hooks: str) -> bool:
    """CD17: the hooks directory exists as a link or as anything but a directory (``lstat``, never followed)."""
    return os.path.lexists(hooks) and (os.path.islink(hooks) or not os.path.isdir(hooks))


def _plan_hooks(root: str, answers: dict, conflicts: list, notes: list, extra: _Extra) -> None:
    fw = githooks.framework_dir()
    hooks = gitinfo.hooks_dir(root)
    extra.hooks_dir = hooks
    value = githooks._hooks_path(root)
    if value is not None:
        conflicts.append("core.hooksPath is set (%s); unset it to install the hooks" % value)
        return
    if _hooks_dir_blocked(hooks):
        conflicts.append("%s: exists and is not a directory" % hooks)
        return
    try:
        res = githooks.status(root, fw)
    except GateError as e:
        raise _input(e) from None
    foreign = []
    for line in res.lines:
        if line.status == "FAIL":
            state = line.reason
            name = line.id.split(".", 1)[1]
            if state == "foreign":
                conflicts.append("githooks.%s: foreign" % name)
                foreign.append(name)
            elif state == "missing":
                extra.hooks.append(name)
            else:
                notes.append("%s: present and stale; run /strict-delivery:upgrade" % os.path.join(hooks, name))
    extra.hook_names = [n for n in githooks.NAMES if n not in foreign]
    try:
        main = gitinfo.main_worktree(root)
    except GateError:
        main = None
    if main is not None and os.path.realpath(main) != os.path.realpath(root):
        notes.append("hooks go to %s, shared by every worktree of this repository" % hooks)


def _build(root: str, answers: dict) -> tuple:
    """``(InitPlan, _Extra)``; ``root`` is a checked real top level."""
    cfg, initialised = _load_config(root)
    answers = _validated(answers, cfg, initialised)
    try:
        version = plugin.version(plugin.framework_dir())
        writes: list = []
        notes: list = []
        conflicts: list = []
        extra = _Extra()
        if not initialised:
            text = _config_text(answers, version)
            writes.append(managed.Write(config.CONFIG_PATH, text, "file"))
            extra.config_path = config.CONFIG_PATH
        paths = []
        for key in STATE_KEYS:
            if cfg["paths"][key] not in paths:
                paths.append(cfg["paths"][key])
        extra.dirs, dir_conflicts = _dir_plan(root, paths)
        if extra.config_path:
            extra.dirs = [d for d in extra.dirs if d != ".strict-delivery"]
        _plan_block(root, "claude-block", templates.claude_block_body(cfg), version, notes, writes)
        _plan_block(root, "gitignore-block", templates.gitignore_block_body(cfg), version, notes, writes)
        if _fold(cfg["paths"]["decisions"]) == _fold(cfg["paths"]["findings"]):  # decision U-3 (a), F-20261125-38fh
            raise _input("two ignore lines are equal: %s/index.yml" % cfg["paths"]["findings"])
        if answers["ci"]:
            fw = plugin.framework_dir()
            try:
                pin = templates.ci_pin(version, _framework_sha())
            except GateError as e:
                raise InitError("init.answers", "ci: %s; answer ci: false until v0.1.0" % e) from None
            body = templates.ci_workflow(cfg, pin, plugin.repository_slug(fw))
            state = managed._inspect(root, CI_PATH)
            if state[0] == "text" and managed.is_generated(state[1]):
                if state[1] != body:
                    notes.append("%s: present at version %s; run /strict-delivery:upgrade"
                                 % (CI_PATH, templates.pin_of(state[1]) or "unknown"))
            else:
                writes.append(managed.Write(CI_PATH, body, "file"))
        settings, set_conflicts, set_write = _settings_change(root, answers["subagents"])
        if set_write is not None:
            writes.append(set_write)
        extra.context_path = cfg["paths"]["context"]
        planned_files = [config.CONFIG_PATH, "CLAUDE.md", ".gitignore", SETTINGS] + ([CI_PATH] if answers["ci"] else [])
        # H5 (F-20261125-5bb3): a state directory equal to or below a planned file; config.yml is _dir_plan's own
        # conflict (a present file when initialised; the defaults never overlap it otherwise)
        dir_conflicts = dir_conflicts + _state_overlap(paths, planned_files[1:])
        overlap = _context_overlap(extra.context_path, paths, planned_files, cfg["paths"]["state"])
        if overlap:  # H5: no write is planned for a path equal to or nested with another planned path
            dir_conflicts = dir_conflicts + overlap
        elif managed._inspect(root, extra.context_path)[0] != "text":  # CX1, CX2: a present file is never rewritten
            writes.append(managed.Write(extra.context_path, templates.render(CONTEXT_TEMPLATE, {}), "file"))
        actions, m_conflicts = managed.plan(root, writes, version)
        # write order: config, directories, blocks, CI, settings, hooks (PL3)
        config_c = [c for c in m_conflicts if c.startswith(config.CONFIG_PATH + ": ")]
        conflicts = config_c + dir_conflicts + [c for c in m_conflicts if c not in config_c] + set_conflicts
        conflicts = list(dict.fromkeys(conflicts))  # PO2: one line per conflict, first place kept
        if answers["git_hooks"]:
            _plan_hooks(root, answers, conflicts, notes, extra)
            if extra.hook_names:  # H5: every hook init plans or keeps is a planned file (ninr; jmqe: installed too)
                conflicts.extend(_hook_overlap(root, extra.context_path, extra.hooks_dir, extra.hook_names))
                hooks_rel = os.path.relpath(extra.hooks_dir, root)
                conflicts.extend(_state_overlap(paths, [hooks_rel + "/" + n for n in extra.hooks]))
                conflicts[:] = dict.fromkeys(conflicts)  # PO2 after the hook compares
    except InitError:
        raise
    except GateError as e:
        raise _input(e) from None
    except schema.SchemaError as e:
        raise _input(e) from None
    order = {w.path: i for i, w in enumerate(writes)}
    if conflicts:
        actions = []
        writes = []
        extra.dirs = []
        extra.hooks = []
    extra.actions = sorted(actions, key=lambda a: order[a[0]])
    for path, new in extra.actions:
        state = managed._inspect(root, path)
        extra.diffs.append((path, state[1] if state[0] == "text" else "", new))
    plan = InitPlan(writes=writes, conflicts=conflicts, settings=settings, moves=[], host_calls=[], notes=notes)
    return plan, extra


def plan_init(root: str, answers: dict) -> InitPlan:
    """The plan for ``root`` and ``answers``; writes nothing."""
    if type(answers) is not dict:
        raise InitError("init.answers", "answers: must be a mapping")
    return _build(_check_root(root), answers)[0]


# ----------------------------------------------------------------------------------------------------- output
def _lines_kept(text: str) -> list:
    """Lines split on ``"\\n"`` only, each keeping its newline, so a last line without one differs from the same line
    with one (PO5); difflib invents no ``\\ No newline`` marker."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1] != "":
        out.append(parts[-1])
    return out


def _diff_text(path: str, old: str, new: str) -> str:
    out = []
    for i, line in enumerate(difflib.unified_diff(_lines_kept(old), _lines_kept(new), "a/" + path, "b/" + path,
                                                  lineterm="")):
        if i >= 2 and line[:1] in (" ", "+", "-"):
            line = line[:-1] if line.endswith("\n") else line
        out.append(safe_text(line) + "\n")
    return "".join(out)


def _out(text: str) -> None:
    sys.stdout.write(text)


def _idle(extra: _Extra) -> bool:
    return not (extra.actions or extra.dirs or extra.hooks)


def _show_plan(plan: InitPlan, extra: _Extra) -> None:
    if _idle(extra):
        _out("no changes\n")
        for n in plan.notes:
            _out("note: %s\n" % safe_text(n))
        return
    for path, old, new in extra.diffs:
        if path == config.CONFIG_PATH:
            _out(_diff_text(path, old, new))
    for d in extra.dirs:
        _out("mkdir %s/\n" % safe_text(d))
    for path, old, new in extra.diffs:
        if path != config.CONFIG_PATH:
            _out(_diff_text(path, old, new))
    for name in extra.hooks:
        _out("hook %s\n" % safe_text(os.path.join(extra.hooks_dir, name)))
    for n in plan.notes:
        _out("note: %s\n" % safe_text(n))


def _fail(ident: str, parts: list) -> None:
    for part in parts:
        _out("FAIL %s: %s\n" % (ident, safe_text(part)))


# ------------------------------------------------------------------------------------------------------- apply
def _apply(root: str, plan: InitPlan, extra: _Extra, written: list) -> list:
    def group(paths: tuple) -> None:
        for act in [a for a in extra.actions if a[0] in paths]:  # one at a time: ``written`` keeps every file written
            written.extend(managed.apply(root, [act]))

    def failed(path: str, verb: str, e: OSError) -> GateError:
        return GateError("%s: %s (%s)" % (path, verb, e.strerror or type(e).__name__))
    problems = []  # AP3: every block action is re-checked before the first write, and again before its own write
    for path, new in [a for a in extra.actions if a[0] in ("CLAUDE.md", ".gitignore")]:
        reason = managed._recheck(root, path, new)
        if reason is not None:
            problems.append("%s: %s" % (path, reason))
    if problems:
        raise GateError("apply refused: " + "; ".join(problems))
    group((config.CONFIG_PATH,))
    for d in extra.dirs:
        path = os.path.join(root, d)
        _, conflicts = _dir_plan(root, [d])  # H4: a component may have turned into a link since the plan
        if conflicts:
            raise GateError(conflicts[0])
        if os.path.lexists(path):
            continue
        try:
            os.mkdir(path)
        except OSError as e:
            raise failed(d, "cannot create", e) from None
        written.append(d + "/")
    group(("CLAUDE.md", ".gitignore"))
    group((CI_PATH,))
    group((SETTINGS,))
    group((extra.context_path,))
    fw = githooks.framework_dir()
    for name in extra.hooks:
        hook = os.path.join(extra.hooks_dir, name)
        if _hooks_dir_blocked(extra.hooks_dir):  # H4: the hooks directory may have turned into a link
            raise GateError("%s: exists and is not a directory" % extra.hooks_dir)
        try:
            os.makedirs(extra.hooks_dir, exist_ok=True)
        except OSError as e:
            raise failed(extra.hooks_dir, "cannot create", e) from None
        try:
            githooks._write(hook, githooks.shim(name, fw))
        except OSError as e:
            raise failed(hook, "cannot write", e) from None
        written.append(hook)
    return written


def _status(root: str) -> str:
    p = gitinfo._run(root, "status --porcelain", _STATUS_ARGS, opts=gitinfo.FSMONITOR_OFF,
                     extra_env={"GIT_OPTIONAL_LOCKS": "0"})
    return gitinfo._text(p.stdout, "status --porcelain")


# -------------------------------------------------------------------------------------------------------- main
def _parser(sub: str) -> _GateParser:
    p = _GateParser(prog="init " + sub, add_help=True)
    for f in ("--root", "--answers"):
        p.add_argument(f, default=None, action="append")
    if sub == "questions":
        p.add_argument("--json", action="store_true")
    return p


def _run(sub: str, ns) -> int:
    root = ns.root[0]
    try:
        real = _check_root(root)
        if sub == "questions":
            q = questions(real)
            _out(json.dumps(q, indent=2) + "\n" if ns.json else _questions_text(q))
            return 0
        _cfg, _init = _load_config(real)
        answers = load_answers(ns.answers[0])
        plan, extra = _build(real, answers)
    except InitError as e:
        _fail(e.ident, e.parts)
        return 1
    except GateError as e:
        _fail("init.input", [str(e)])
        return 1
    if plan.conflicts:
        _fail("init.conflict", plan.conflicts)
        return 1
    if sub == "plan":
        _show_plan(plan, extra)
        return 0
    if _idle(extra):
        _out("no changes\n")  # PO6, IN3; a note of D-Q5 (a) follows it, as on ``plan`` (PO7)
    for n in plan.notes:
        _out("note: %s\n" % safe_text(n))
    written: list = []
    try:
        _apply(real, plan, extra, written)
    except (GateError, OSError) as e:
        _fail("init.write", [str(e) if isinstance(e, GateError) else "%s: %s" % (type(e).__name__, e.strerror)])
        _out("written: %s\n" % safe_text(", ".join(written)))
        return 1
    try:
        _out(_status(real))
    except GateError as e:
        _fail("init.status", [str(e)])
        return 1
    return 0


def main(argv: list) -> int:
    """``python3 -m gates.tools.init``: 2 on a usage error, 1 on a refusal or conflict, 0 otherwise."""
    if type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("init: argv must be a list of str\n")
        return 2
    sub = args[0] if args else ""
    if sub not in ("questions", "plan", "apply"):
        sys.stderr.write(USAGE)
        return 2
    try:
        ns = _parser(sub).parse_args(args[1:])
    except GateError:
        return 2
    if ns.root is None or len(ns.root) != 1 or (sub != "questions") != (ns.answers is not None) \
            or (ns.answers is not None and len(ns.answers) != 1):
        sys.stderr.write(USAGE)
        return 2
    return _run(sub, ns)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
