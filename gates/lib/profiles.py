"""Profiles: the three presets ``<framework>/profiles/<name>.yml`` (spec 6 and 12), standard library only.

A profile file holds ``defaults`` (keys a project may omit and later set itself) and ``policy`` (keys the project may
change only under ``overrides``). The profiles directory is read from the framework (the installed plugin), never from
the repository under check. This module is imported by ``gates.lib.config``, so it imports ``schema`` (which imports
``config``) only inside ``load`` (decision D4 of Task 2c.2).
"""
from __future__ import annotations

import copy
import os
import re
import stat
from typing import Optional

from gates.lib import plugin, result, yamlsub
from gates.lib.dispatch import MAX_DIGITS
from gates.lib.result import GateError

PROFILES: tuple = ("light", "standard", "strict")
_KEY = re.compile(r"[a-z][a-z0-9_]*")
# The installed profile.yml, fixed at import: a test or gate that points schema.SCHEMAS_DIR elsewhere must not move it.
PROFILE_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas", "profile.yml")
_MAX_TASKS = "policy.block.max_tasks"


def _refuse(name: str, reason: str) -> GateError:
    return GateError("profiles/%s.yml: %s" % (name, reason))


def _framework(framework: object) -> str:
    if framework is None:
        return plugin.framework_dir()
    if type(framework) is not str or framework == "" or "\x00" in framework:  # before any filesystem call
        raise GateError("framework %s is not a non-empty str without a NUL character" % result.safe_text(framework))
    return framework


def _regular(path: str, name: str, what: str, want_dir: bool) -> None:
    """Refuse ``path`` unless it is (by ``lstat``, never following a link) a regular file or a directory."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        raise _refuse(name, "%s is missing" % what) from None
    except OSError as e:
        raise _refuse(name, "%s cannot be read (%s)" % (what, result._type_name(e))) from None
    if stat.S_ISLNK(mode):
        raise _refuse(name, "%s is a symlink" % what)
    if not (stat.S_ISDIR(mode) if want_dir else stat.S_ISREG(mode)):
        raise _refuse(name, "%s is not a %s" % (what, "directory" if want_dir else "regular file"))


def load(name: str, framework: Optional[str] = None) -> dict:
    """``{"defaults": {...}, "policy": {...}}`` of the profile ``name``; a ``GateError`` naming the file otherwise."""
    from gates.lib import schema  # function-local: schema imports config, which imports this module (D4)
    if type(name) is not str or name not in PROFILES:
        raise GateError("profile %s must be one of %s" % (result.safe_text(name), ", ".join(PROFILES)))
    base = _framework(framework)
    shown = "profiles/%s.yml" % name
    _regular(os.path.join(base, "profiles"), name, "profiles directory", True)
    path = os.path.join(base, "profiles", name + ".yml")
    _regular(path, name, "file", False)
    try:
        data = yamlsub.load(path, shown)
    except yamlsub.YamlError as e:
        raise GateError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
    if type(data) is dict and "policy" in data and data["policy"] is None:
        data["policy"] = {}  # light: ``policy:`` with no value, the subset cannot write ``{}`` (decision D-Q1)
    sch = schema.load_schema(PROFILE_SCHEMA)
    errs = schema.validate(sch, data, {})
    if errs:
        raise _refuse(name, "; ".join(errs))
    if data["profile"] != name:
        raise _refuse(name, "profile: '%s' does not match the file name '%s'" % (result.safe_text(data["profile"]),
                                                                                   name))
    block = data["policy"].get("block")
    if block is not None and "max_tasks" in block and block["max_tasks"] >= 10 ** MAX_DIGITS:
        raise _refuse(name, "%s: must be an integer of at most %d digits" % (_MAX_TASKS, MAX_DIGITS))
    return {"defaults": copy.deepcopy(data["defaults"]), "policy": copy.deepcopy(data["policy"])}


def policy_keys(preset: dict) -> frozenset:
    """The dotted leaf keys of ``preset["policy"]`` (``preset`` is a ``load`` result), for example ``block.max_tasks``."""
    if type(preset) is not dict or "policy" not in preset or type(preset["policy"]) is not dict:
        raise ValueError("preset must be a dict holding a policy mapping")
    keys = set()
    stack = [((), preset["policy"])]
    while stack:  # iterative: a deep mapping must not hit the recursion limit
        parts, node = stack.pop()
        for k, v in node.items():
            if type(k) is not str or _KEY.fullmatch(k) is None:
                raise ValueError("a policy key must match [a-z][a-z0-9_]*")
            here = parts + (k,)
            if isinstance(v, dict):
                if type(v) is not dict:
                    raise ValueError("a policy mapping must be a dict")
                stack.append((here, v))
            else:
                keys.add(".".join(here))
    return frozenset(keys)
