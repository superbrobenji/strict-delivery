"""Config loader: ``.strict-delivery/config.yml`` merged over the defaults, with key checks (standard library only)."""
from __future__ import annotations

import copy
import os
import posixpath
import re

from gates.lib import ids, print_table, profiles, result, yamlsub
from gates.lib.dispatch import MAX_DIGITS
from gates.lib.gitinfo import LONG_HEX, _require_toplevel
from gates.lib.result import GateError

CONFIG_PATH = ".strict-delivery/config.yml"
# The current config tag. It cannot be read from the schema file here: gates.lib.schema imports this module, so a
# module-level import of schema would be circular. tests/test_config.py pins it to migrations.current_version("config").
CONFIG_TAG = "config/2"
_OLD_TAG = re.compile(r"config/[1-9][0-9]*")  # the tag form gate_schema gives the upgrade hint for (schema._TAG)

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
                       "rule-override", "profile-override", "program-create", "stream-ownership",
                       "stream-merge", "request-dispute", "program-close"],
    },
    # No DEFAULTS entry for ``limits`` or ``escape_cost``: both are absent by default (Q-H2, Q-B6plan-3 (a)).
    "merge": {"mode": "host"},
    "reviews": {"small": {"max_lines": 150, "max_files": 4,
                          "exclude": [".strict-delivery/**", ".github/workflows/**", ".claude/**", "CLAUDE.md"],
                          "tier": "tier2"}},
    "context": {"max_lines": 2000, "max_bytes": 100000},
}

CONFIG_KEYS = ("schema", "framework_version", "profile", "commands", "paths", "ids", "models", "roles",
               "top_tier_roles", "top_tier_fallback", "decision_classes", "block", "rulings", "dispatch",
               "budgets", "drift", "overrides", "base_branch", "decisions", "limits", "merge", "escape_cost",
               "reviews", "context")
_REQUIRED = ("schema", "framework_version", "profile")
_PROFILES = profiles.PROFILES
# An override of a limit: the two caps, or one role's child cap (the role grammar of the ``roles`` ids, decision D13).
_LIMITS_KEY = re.compile(r"limits\.(max_depth|max_concurrent|max_children\.[a-z][a-z0-9_]*)")
_ROLE_ID = re.compile(r"[a-z][a-z0-9_]*")  # explicit ASCII classes and fullmatch: no str.isidentifier, no "$" newline
_OPEN_MAPS =("models.tiers",)  # mappings that keep keys the defaults do not name


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
    if (not isinstance(v, str) or not print_table.is_printable(v) or v.startswith("/") or ".." in v.split("/")
            or v == "." or posixpath.normpath(v) != v):
        raise _bad(key, "must be a non-empty normalised repo-relative path of printable characters")


def _unknown(full: str) -> GateError:
    return GateError("%s: unknown key '%s'" % (CONFIG_PATH, full))


def _int_min(v: object, key: str, least: int) -> None:
    if type(v) is not int or v < least:
        raise _bad(key, "must be an integer of at least %d" % least)
    if v >= 10 ** MAX_DIGITS:  # compared as numbers: no str() or int() of text, so no int string-conversion limit applies
        raise _bad(key, "must be an integer of at most %d digits" % MAX_DIGITS)


def _check_glob(key: str, item: object) -> None:
    """``item`` is a glob of the framework's one grammar: a non-empty normalised repo-relative pattern of printable
    characters (no leading ``/``, no empty, ``.`` or ``..`` segment) whose bracket expressions are supported."""
    from gates.lib import schema  # function-local: schema imports this module (D4)
    # An empty item and a leading '/' both give an empty first segment, so the segment test covers them.
    if (not isinstance(item, str) or not print_table.is_printable(item)
            or any(seg in ("", ".", "..") for seg in item.split("/")) or schema.bracket_problem(item)):
        raise _bad(key, "must hold only globs: non-empty printable repo-relative patterns with no leading '/', "
                   "no empty, '.' or '..' segment and supported bracket expressions")


def _validate_limits(limits: object) -> None:
    if type(limits) is not dict:
        raise _bad("limits", "must be a mapping")
    for k in limits:
        if k not in ("max_children", "max_depth", "max_concurrent"):
            raise _unknown("limits." + k)
    if "max_children" in limits:
        mc = limits["max_children"]
        if type(mc) is not dict:
            raise _bad("limits.max_children", "must be a mapping")
        for role, n in mc.items():
            if role == "":  # yamlsub gives only str keys, so a non-str key is unreachable (table L14)
                raise _bad("limits.max_children", "keys must be non-empty strings")
            _int_min(n, "limits.max_children." + role, 1)
    for k in ("max_depth", "max_concurrent"):
        if k in limits:
            _int_min(limits[k], "limits." + k, 1)


def _role_keys(m: dict, key: str) -> None:
    """The keys of ``m`` are role ids of the grammar ``[a-z][a-z0-9_]*`` (exact ``str``; shape only, no role list)."""
    for k in m:
        if type(k) is not str or not _ROLE_ID.fullmatch(k):
            raise _bad(key, "keys must be role ids of [a-z][a-z0-9_]*")


def _entry_keys(entry: dict, full: str, allowed: tuple) -> None:
    for f in entry:
        if type(f) is not str or f not in allowed:
            raise _unknown("%s.%s" % (full, result.safe_text(f)))


def _validate_prompt(v: object, key: str) -> None:
    if type(v) is not str:
        _check_path(key, None)
    _check_path(key, v)
    if not v.endswith(".md") or "\\" in v or " " in v or v.rsplit("/", 1)[-1] == ".md":
        raise _bad(key, "must be a normalised repo-relative path ending in .md")


def _validate_roles(roles: object) -> None:
    if type(roles) is not dict:
        raise _bad("roles", "must be a mapping")
    _role_keys(roles, "roles")
    for rid, entry in roles.items():
        full = "roles." + rid
        if type(entry) is not dict:
            raise _bad(full, "must be a mapping")
        _entry_keys(entry, full, ("prompt", "min_tier"))
        for f in ("prompt", "min_tier"):
            if f not in entry:
                raise _bad(full + "." + f, "required key is missing")
            if f == "prompt":
                _validate_prompt(entry[f], full + ".prompt")
            elif type(entry[f]) is not str or entry[f] not in ("tier1", "tier2", "tier3", "tier4"):
                raise _bad(full + ".min_tier", "must be one of tier1, tier2, tier3, tier4")


def _validate_budgets(budgets: object) -> None:
    if type(budgets) is not dict:
        raise _bad("budgets", "must be a mapping")
    _role_keys(budgets, "budgets")
    for rid, entry in budgets.items():
        full = "budgets." + rid
        if type(entry) is not dict:
            raise _bad(full, "must be a mapping")
        _entry_keys(entry, full, ("tokens", "minutes"))
        for f in ("tokens", "minutes"):
            if f in entry:
                _int_min(entry[f], full + "." + f, 1)


def _validate_int_map(m: object, key: str, leaf: str) -> None:
    if type(m) is not dict:
        raise _bad(key, "must be a mapping")
    _entry_keys(m, key, (leaf,))
    if leaf in m:
        _int_min(m[leaf], "%s.%s" % (key, leaf), 1)


def _validate_escape_cost(ec: object) -> None:
    sev = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    if type(ec) is not dict:
        raise _bad("escape_cost", "must be a mapping")
    for k in ec:
        if k not in sev:
            raise _unknown("escape_cost." + k)
    for k in sev:
        if k not in ec:
            raise _bad("escape_cost." + k, "required key is missing")
        _int_min(ec[k], "escape_cost." + k, 0)


def _validate_ids(cfg: dict) -> None:
    for k, v in cfg["ids"].items():
        if not isinstance(v, str) or not re.fullmatch(r"[A-Z]+", v):
            raise _bad("ids." + k, "must be a prefix of capital letters A-Z")
    if len(set(cfg["ids"].values())) != len(cfg["ids"]):
        raise _bad("ids", "the four prefixes must be distinct")


def _validate(cfg: dict) -> None:
    tag = cfg["schema"]
    if tag != CONFIG_TAG:
        hint = "; run /strict-delivery:upgrade" if type(tag) is str and _OLD_TAG.fullmatch(tag) else ""
        raise _bad("schema", "must be '%s'%s" % (CONFIG_TAG, hint))
    fv = cfg["framework_version"]
    if not isinstance(fv, str) or fv == "":
        raise _bad("framework_version", "must be a non-empty string")
    if cfg["profile"] not in _PROFILES:
        raise _bad("profile", "must be one of light, standard, strict")
    for k, v in cfg["paths"].items():
        _check_path("paths." + k, v)
    _validate_ids(cfg)
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
    if "limits" in cfg:
        _validate_limits(cfg["limits"])
    if cfg["merge"]["mode"] not in ("host", "controller"):
        raise _bad("merge.mode", "must be one of host, controller")
    if "escape_cost" in cfg:
        _validate_escape_cost(cfg["escape_cost"])
    small = cfg["reviews"]["small"]
    _int_min(small["max_lines"], "reviews.small.max_lines", 1)
    _int_min(small["max_files"], "reviews.small.max_files", 1)
    if type(small["exclude"]) is not list:
        raise _bad("reviews.small.exclude", "must be a list of globs")
    for item in small["exclude"]:
        _check_glob("reviews.small.exclude", item)
    if small["tier"] not in ("tier1", "tier2", "tier3", "tier4"):
        raise _bad("reviews.small.tier", "must be one of tier1, tier2, tier3, tier4")
    for k in ("max_lines", "max_bytes"):
        _int_min(cfg["context"][k], "context." + k, 1)
    # Task 4a.3, after the merge (so a preset or an applied override is what is checked); order: D5.
    if "roles" in cfg:
        _validate_roles(cfg["roles"])
    if "budgets" in cfg:
        _validate_budgets(cfg["budgets"])
    for k, leaf in (("block", "max_tasks"), ("rulings", "max_per_block"), ("dispatch", "max_prompt_chars")):
        if k in cfg:
            _validate_int_map(cfg[k], k, leaf)


def _refuse_file_policy_keys(data: dict, keys: frozenset, profile: str) -> None:
    """Step 3: a file key the profile presets is refused; a ``block`` that is not a mapping cannot be merged (D9)."""
    for key in sorted(keys):
        parts = key.split(".")
        node = data
        for i, seg in enumerate(parts):
            if seg not in node:
                break
            if i == len(parts) - 1:
                raise _bad(key, "preset by profile %s; change it under overrides with the authorising decision"
                           % profile)
            node = node[seg]
            if type(node) is not dict:
                raise _bad(".".join(parts[:i + 1]), "must be a mapping")


def _set_path(cfg: dict, key: str, value: object) -> None:
    parts = key.split(".")
    node = cfg
    for seg in parts[:-1]:
        node = node.setdefault(seg, {})
    node[parts[-1]] = copy.deepcopy(value)


def _apply_overrides(cfg: dict, overrides: object, keys: frozenset, profile: str) -> None:
    """Step 5: check each override entry in file order and apply its value (authorisation is gate_decisions')."""
    from gates.lib import schema  # function-local: schema imports this module (D4)
    if type(overrides) is not dict:
        raise _bad("overrides", "must be a mapping")
    if "limits" in cfg:  # an override never repairs an invalid direct value (D14)
        _validate_limits(cfg["limits"])
    sch = None
    for key, entry in overrides.items():
        name = "overrides." + result.safe_text(key)
        if type(key) is not str or not (key in keys or _LIMITS_KEY.fullmatch(key)):
            raise _bad(name, "not a policy key of profile %s and not a limits key" % profile)
        if type(entry) is not dict:
            raise _bad(name, "must be a mapping")
        for f in entry:
            if f not in ("value", "decision"):
                raise _bad(name + "." + result.safe_text(f), "unknown key")
        for f in ("value", "decision"):
            if f not in entry:
                raise _bad(name + "." + f, "required key is missing")
        value = entry["value"]
        if type(value) not in (int, float, str, bool, list):
            raise _bad(name + ".value", "must be a scalar or a list")
        if key in keys:
            if sch is None:
                sch = schema.load_schema(profiles.PROFILE_SCHEMA)
            doc = {"schema": "profile/1", "profile": profile, "defaults": {}, "policy": {}}
            _set_path(doc["policy"], key, value)
            errs = schema.validate(sch, doc, {})
            if errs:
                raise _bad(name + ".value", errs[0].partition(": ")[2])
            if type(value) is int and value >= 10 ** MAX_DIGITS:
                raise _bad(name + ".value", "must be an integer of at most %d digits" % MAX_DIGITS)
        else:
            _int_min(value, name + ".value", 1)
        problem = ids.id_problem(entry["decision"], cfg["ids"]["decision"])
        if problem:
            raise _bad(name + ".decision", problem)
        _set_path(cfg, key, value)


def load(root: str) -> dict:
    """The merged config of the tree at ``root``; a GateError names whatever is wrong.

    Order: the file's keys are checked; ``DEFAULTS``, then the profile's ``defaults`` for keys the file omits, then the
    file's keys; a file key the profile presets is refused; the profile's ``policy``; each ``overrides`` value;
    ``_validate``."""
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
    profile = data["profile"]
    if type(profile) is not str or profile not in _PROFILES:  # before the profile file is read (decision D3)
        raise _bad("profile", "must be one of light, standard, strict")
    preset = profiles.load(profile)
    keys = profiles.policy_keys(preset)
    cfg = copy.deepcopy(DEFAULTS)
    for k, v in preset["defaults"].items():
        if k not in data:
            cfg[k] = copy.deepcopy(v)
    _refuse_file_policy_keys(data, keys, profile)
    for k, v in data.items():
        if k in cfg and type(cfg[k]) is dict:
            _merge_map(cfg[k], v, k)
        else:
            cfg[k] = copy.deepcopy(v)
    for key in sorted(keys):
        node = preset["policy"]
        for seg in key.split("."):
            node = node[seg]
        _set_path(cfg, key, node)
    if "overrides" in data:
        _validate_ids(cfg)  # the decision prefix is checked against a validated prefix (decision D10)
        _apply_overrides(cfg, data["overrides"], keys, profile)
    _validate(cfg)
    return cfg
