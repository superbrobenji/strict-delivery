"""Config loader: ``.strict-delivery/config.yml`` merged over the defaults, with key checks (standard library only)."""
from __future__ import annotations

import copy
import os
import posixpath
import re

from gates.lib import yamlsub
from gates.lib.gitinfo import LONG_HEX, _require_toplevel
from gates.lib.result import GateError

CONFIG_PATH = ".strict-delivery/config.yml"

DEFAULTS: dict = {
    "paths": {
        "state": ".strict-delivery/state",
        "decisions": ".strict-delivery/state/decisions",
        "findings": ".strict-delivery/state/findings",
        "claims": ".strict-delivery/state/claims",
        "plan_state": ".strict-delivery/state/plans",
        "programs": ".strict-delivery/state/programs",
        "playbooks": ".strict-delivery/playbooks",
        "receipts": ".strict-delivery/receipts",
        "context": ".strict-delivery/context.yml",
        "architecture": "docs/strict-delivery/architecture.md",
        "index": "docs/strict-delivery/INDEX.md",
        "specs": "docs/strict-delivery/specs",
        "plans": "docs/strict-delivery/plans",
        "reviews": "docs/strict-delivery/reviews",
    },
    "ids": {"decision": "DEC", "finding": "F", "claim": "C", "request": "R"},
    "base_branch": "main",
    "decisions": {"scan": ["docs/**", "CLAUDE.md", ".strict-delivery/playbooks/**"]},
    "models": {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"}},
    "drift": {"estimate_factor_pct": 150},
    "decision_classes": {
        "owner_only": ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close",
                       "finding-class", "rule-override", "program-create", "stream-ownership",
                       "stream-merge", "request-dispute", "program-close"],
    },
}

CONFIG_KEYS = ("schema", "framework_version", "profile", "commands", "paths", "ids", "models", "roles",
               "top_tier_roles", "top_tier_fallback", "decision_classes", "block", "rulings", "dispatch",
               "budgets", "drift", "overrides", "base_branch", "decisions")
_REQUIRED = ("schema", "framework_version", "profile")
_PROFILES = ("light", "standard", "strict")
_OPEN_MAPS = ("models.tiers",)  # mappings that keep keys the defaults do not name


def _bad(key: str, reason: str) -> GateError:
    return GateError("%s: %s: %s" % (CONFIG_PATH, key, reason))


def _text_list(value: object, key: str, allow_empty: bool) -> list:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise _bad(key, "must be a non-empty list of non-empty strings" if not allow_empty
                   else "must be a list of non-empty strings")
    for item in value:
        if not isinstance(item, str) or item == "":
            raise _bad(key, "must hold only non-empty strings")
    return value


def _merge_map(default: dict, over: object, name: str) -> None:
    """Merge the file's mapping ``over`` into ``default`` in place."""
    if type(over) is not dict:
        raise _bad(name, "must be a mapping")
    for k, v in over.items():
        full = "%s.%s" % (name, k)
        if k not in default:
            if name not in _OPEN_MAPS:
                raise GateError("%s: unknown key '%s'" % (CONFIG_PATH, full))
            default[k] = copy.deepcopy(v)
        elif full == "decision_classes.owner_only":
            for slug in _text_list(v, full, allow_empty=False):
                if slug not in default[k]:
                    default[k].append(slug)
        elif type(default[k]) is dict:
            _merge_map(default[k], v, full)
        else:
            default[k] = copy.deepcopy(v)


def _check_path(key: str, v: object) -> None:
    if (not isinstance(v, str) or not v.isprintable() or v.startswith("/") or ".." in v.split("/")
            or v == "." or posixpath.normpath(v) != v):
        raise _bad(key, "must be a non-empty normalised repo-relative path of printable characters")


def _validate(cfg: dict) -> None:
    if cfg["schema"] != "config/1":
        raise _bad("schema", "must be 'config/1'")
    fv = cfg["framework_version"]
    if not isinstance(fv, str) or fv == "":
        raise _bad("framework_version", "must be a non-empty string")
    if cfg["profile"] not in _PROFILES:
        raise _bad("profile", "must be one of light, standard, strict")
    for k, v in cfg["paths"].items():
        _check_path("paths." + k, v)
    for k, v in cfg["ids"].items():
        if not isinstance(v, str) or not re.fullmatch(r"[A-Z]+", v):
            raise _bad("ids." + k, "must be a prefix of capital letters A-Z")
    if len(set(cfg["ids"].values())) != len(cfg["ids"]):
        raise _bad("ids", "the four prefixes must be distinct")
    bb = cfg["base_branch"]
    if not isinstance(bb, str) or bb == "":
        raise _bad("base_branch", "must be a non-empty string")
    if LONG_HEX.search(bb):
        raise _bad("base_branch", "must not hold more than 40 hex digits in a row "
                   "(gitinfo refuses such a revision)")
    _text_list(cfg["decisions"]["scan"], "decisions.scan", allow_empty=True)
    for k, v in cfg["models"]["tiers"].items():
        if not isinstance(v, str) or v == "":
            raise _bad("models.tiers." + k, "must be a non-empty string")
    pct = cfg["drift"]["estimate_factor_pct"]
    if type(pct) is not int or pct < 1:
        raise _bad("drift.estimate_factor_pct", "must be an integer of at least 1")


def load(root: str) -> dict:
    """The merged config of the tree at ``root``; a GateError names whatever is wrong."""
    _require_toplevel(root)
    path = os.path.join(root, CONFIG_PATH)
    if not os.path.lexists(path):
        raise GateError("%s: missing; run /strict-delivery:init" % CONFIG_PATH)
    try:
        data = yamlsub.load(path, CONFIG_PATH)
    except yamlsub.YamlError as e:
        raise GateError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
    if type(data) is not dict:
        raise GateError("%s: the top level must be a mapping" % CONFIG_PATH)
    for k in data:
        if k not in CONFIG_KEYS:
            raise GateError("%s: unknown key '%s'" % (CONFIG_PATH, k))
    for k in _REQUIRED:
        if k not in data:
            raise _bad(k, "required key is missing")
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in data.items():
        if k in cfg and type(cfg[k]) is dict:
            _merge_map(cfg[k], v, k)
        else:
            cfg[k] = v
    _validate(cfg)
    return cfg
