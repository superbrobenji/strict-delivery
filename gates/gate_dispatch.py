"""Gate ``dispatch``: one agent dispatch checked against the dispatch contract (spec section 10; plan Task 2c.3).

``python3 -m gates check dispatch [--root R] [--prompts DIR] --input FILE``. The input file is a JSON object with
``prompt`` (str), ``subagent_type`` and ``model`` (str, optional), ``dispatcher`` (``id``, ``depth``, ``live_children``,
``live_total``) and ``program_live`` (bool). The caller supplies the counts; the gate cannot count for itself, so the
cap and concurrency lines are only as exact as the caller's count (F-B2p2-10).

An input failure (file, JSON, fields, config, environment, ``limits.max_children`` keys) prints the one line
``FAIL dispatch.input: <reason>`` and nothing else. After input passes every line is printed, in order; a line whose
input an earlier failure removed prints ``FAIL dispatch.<x>: not checked: dispatch.<y> failed`` (Decision D12).
Prompt blocks are read from ``--prompts``, default beside the installed ``gates`` package, never under ``--root``
(spec section 3). Not run by ``run_all`` (Q-B2plan-19 (a))."""
from __future__ import annotations

import json
import os
import re
import stat
import sys

import gates
from gates.lib import claims, config, decisions, dispatch, gitinfo, ids, store
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate

PRODUCES: tuple = ()

_TOP_KEYS = ("prompt", "subagent_type", "model", "dispatcher", "program_live")
_DISPATCHER_KEYS = ("id", "depth", "live_children", "live_total")
_STRIP = "`'\"()[],;:."
_WS = re.compile(r"[ \t\n\r\f\v]+")


def _args(args: list):
    p = gate_args("dispatch")
    p.add_argument("--prompts", default=None, action=_Once, help="the prompt block directory")
    p.add_argument("--input", default=None, action=_Once, help="the dispatch JSON file")
    return p.parse_args(args)


def _default_prompts() -> str:
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(gates.__file__)))
    return os.path.join(pkg, "skills", "strict-delivery", "prompts")


def _no_dup(pairs: list) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key '%s'" % k)
        out[k] = v
    return out


def _no_const(name: str):
    raise ValueError("%s is not allowed" % name)


def _parse_int(text: str) -> int:
    if len(text.lstrip("-")) > dispatch.MAX_DIGITS:
        raise ValueError("an integer of more than %d digits" % dispatch.MAX_DIGITS)
    return int(text)


def _bad(reason: str) -> GateError:
    return GateError("input: " + reason)


def _read_input(path: str) -> dict:
    try:
        mode = os.lstat(path).st_mode
    except OSError as e:
        raise _bad("%s: cannot read (%s)" % (path, e.strerror or type(e).__name__)) from None
    if not stat.S_ISREG(mode):
        raise _bad("%s: not a regular file (a directory or a symlink is never followed)" % path)
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
        data = json.loads(text, object_pairs_hook=_no_dup, parse_constant=_no_const, parse_int=_parse_int)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise _bad("%s: not valid UTF-8 JSON (%s)" % (path, type(e).__name__ if not isinstance(e, ValueError)
                                                      else e)) from None
    return data


def _count(v: object, what: str) -> int:
    if type(v) is not int or v < 0:
        raise _bad("%s must be an integer of at least 0" % what)
    return v


def _validate(data: object, cfg: dict) -> dict:
    if type(data) is not dict:
        raise _bad("the top level must be a JSON object")
    for k in data:
        if k not in _TOP_KEYS:
            raise _bad("unknown key '%s'" % k)
    if type(data.get("prompt")) is not str:
        raise _bad("prompt must be a string")
    for k in ("subagent_type", "model"):
        if k in data and type(data[k]) is not str:
            raise _bad("%s must be a string" % k)
    d = data.get("dispatcher")
    if type(d) is not dict:
        raise _bad("dispatcher must be an object")
    for k in d:
        if k not in _DISPATCHER_KEYS:
            raise _bad("dispatcher: unknown key '%s'" % k)
    for k in _DISPATCHER_KEYS:
        if k not in d:
            raise _bad("dispatcher.%s is required" % k)
    if type(d["id"]) is not str or (d["id"] != "session" and d["id"] not in dispatch.ROLES):
        raise _bad("dispatcher.id must be 'session' or a role id")
    for k in _DISPATCHER_KEYS[1:]:
        _count(d[k], "dispatcher." + k)
    if type(data.get("program_live")) is not bool:
        raise _bad("program_live must be true or false")
    known = dispatch.ROLES + ("session",)
    for k in (cfg.get("limits") or {}).get("max_children", {}):
        if k not in known:
            raise _bad("limits.max_children.%s names no role" % k)
    tr = cfg.get("top_tier_roles", dispatch.DEFAULT_TOP_TIER_ROLES)
    if type(tr) not in (list, tuple) or any(type(x) is not str or x == "" for x in tr):
        raise _bad("config top_tier_roles must be a list of non-empty strings")
    # top_tier_fallback is not checked here: a value that is not a str naming a set tier fails dispatch.tier, and only
    # for a top_tier_roles dispatch whose minimum tier is tier4 (dispatch.min_tier; plan P:2064).
    return data


def _ascii_lower(s: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def _token_ids(text: str, prefix: str) -> list:
    pat = re.compile(r"(?<![0-9A-Za-z_-])" + ids.id_pattern(prefix).pattern + r"(?![0-9A-Za-z_-])")
    out = []
    for m in pat.finditer(text):
        if not ids.id_problem(m.group(0), prefix) and m.group(0) not in out:
            out.append(m.group(0))
    return out


def _brief_paths(brief: str) -> list:
    out = []
    for tok in _WS.split(brief):
        tok = tok.strip(_STRIP)
        if tok and tok not in out:
            out.append(tok)
    return out


def _claim_lines(res: Result, text: str, root: str, cfg: dict) -> None:
    wanted = _token_ids(text, cfg["ids"]["claim"])
    problems = []
    if wanted:
        files = claims.load(root, cfg)
        blobs = gitinfo.blob_ids(root, claims.stale_paths(files, root))
        found: dict = {}
        stale: dict = {}
        for cf in files:
            for c in (cf.row.get("claims") if type(cf.row.get("claims")) is list else []):
                if type(c) is dict and type(c.get("id")) is str:
                    found.setdefault(c["id"], True)
                    for cid, reason in claims.stale_errors(claims.ClaimFile(cf.file, {"claims": [c]}), root,
                                                           cfg["base_branch"], blob_ids=blobs):
                        stale[cid] = reason
        for cid in wanted:
            if cid not in found:
                problems.append("%s names no claim" % cid)
            elif cid in stale:
                problems.append("%s is stale: %s" % (cid, stale[cid]))
    _line(res, "dispatch.claims", problems)


def _line(res: Result, name: str, problems: list) -> None:
    if problems:
        res.fail(name, "; ".join(problems))
    else:
        res.passed(name)


def _not_checked(res: Result, name: str, dep: str) -> None:
    res.fail(name, "not checked: %s failed" % dep)


def check(args: list) -> Result:
    ns = _args(args)
    if ns.input is None:
        raise _bad("--input FILE is required")
    root = ns.root if ns.root is not None else repo_root()
    cfg = config.load(root)
    prompts = ns.prompts if ns.prompts is not None else _default_prompts()
    data = _validate(_read_input(ns.input), cfg)
    try:
        max_depth, max_conc = dispatch.limits_of(cfg, os.environ)
    except ValueError as e:
        raise _bad(str(e)) from None
    disp = data["dispatcher"]
    live = data["program_live"]
    res = Result("dispatch")
    res.passed("dispatch.input")

    stype = data.get("subagent_type")
    _line(res, "dispatch.fork", ["subagent_type is fork"] if stype is not None and _ascii_lower(stype) == "fork" else [])

    sections, gerrors = dispatch.parse(data["prompt"])
    _line(res, "dispatch.grammar", gerrors)

    role = None
    if "Role" not in sections:
        _not_checked(res, "dispatch.role", "dispatch.grammar")
    else:
        try:
            role = dispatch.role_of(sections["Role"])
            res.passed("dispatch.role")
        except ValueError as e:
            res.fail("dispatch.role", str(e))

    if role is None:
        for name in ("dispatcher", "depth"):
            _not_checked(res, "dispatch." + name, "dispatch.role")
    else:
        did = disp["id"]
        if did in dispatch.ROLES and did not in dispatch.CONTROLLER_ROLES:
            res.fail("dispatch.dispatcher", "%s is a worker role, and a worker dispatches no agent" % did)
        elif did not in dispatch.DISPATCHERS[live][role]:
            res.fail("dispatch.dispatcher", "%s may not dispatch %s (program_live %s; allowed: %s)"
                     % (did, role, "true" if live else "false", ", ".join(dispatch.DISPATCHERS[live][role]) or "none"))
        else:
            res.passed("dispatch.dispatcher")
        _line(res, "dispatch.depth", [] if dispatch.depth_ok(role, disp["depth"], max_depth) else
              ["dispatcher depth %d + 1 + %d level(s) below %s exceeds max_depth %d"
               % (disp["depth"], dispatch.LEVELS_BELOW.get(role, 0), role, max_depth)])

    _line(res, "dispatch.concurrency", [] if disp["live_total"] + 1 <= max_conc else
          ["%d running + 1 exceeds max_concurrent %d" % (disp["live_total"], max_conc)])
    cap = ((cfg.get("limits") or {}).get("max_children") or {}).get(disp["id"])
    _line(res, "dispatch.children", [] if cap is None or disp["live_children"] + 1 <= cap else
          ["%d running children + 1 exceeds limits.max_children.%s %d" % (disp["live_children"], disp["id"], cap)])

    model = data.get("model")
    if "Model" not in sections:
        _not_checked(res, "dispatch.model", "dispatch.grammar")
    elif model is None:
        res.fail("dispatch.model", "the dispatch call passes no model")
    else:
        body = dispatch.model_line(sections["Model"])
        _line(res, "dispatch.model", [] if body == model else
              ["the dispatch's model '%s' is not the one line of ## Model" % model])

    tier = None
    small_ok = False
    brief = sections.get("Brief", "")
    line = None
    line_err = None
    if role in dispatch.SMALL_ROLES:
        try:
            line = dispatch.small_line(brief)
        except ValueError as e:
            line_err = str(e)
    if role is None or model is None:
        _not_checked(res, "dispatch.tier", "dispatch.role" if role is None else "dispatch.model")
    else:
        try:
            tier = dispatch.tier_of(model, cfg)
            need = dispatch.min_tier(role, cfg)
        except ValueError as e:
            res.fail("dispatch.tier", str(e))
            tier = None
            need = None
        else:
            if tier is None:
                res.fail("dispatch.tier", "model '%s' is named by no tier" % model)
            elif tier >= need:
                res.passed("dispatch.tier")
            elif (role in dispatch.SMALL_ROLES and line is not None and tier >= dispatch.small_tier(role, cfg)
                  and not dispatch.small_errors(line, dispatch_ids(sections, cfg), root, cfg)):
                res.passed("dispatch.tier")
            else:
                res.fail("dispatch.tier", "tier%d is below the minimum tier%d of %s" % (tier, need, role))
    if role in dispatch.SMALL_ROLES and (line is not None or line_err is not None):
        if line_err is not None:
            res.fail("dispatch.small", line_err)
        else:
            _line(res, "dispatch.small", dispatch.small_errors(line, dispatch_ids(sections, cfg), root, cfg))

    if role is None or model is None or tier is None:
        _not_checked(res, "dispatch.top-tier", "dispatch.tier")
    else:
        top = cfg.get("top_tier_roles", dispatch.DEFAULT_TOP_TIER_ROLES)
        _line(res, "dispatch.top-tier", ["tier4 is only for top_tier_roles, not %s" % role]
              if tier == 4 and role not in top else [])

    if role is None or "Strict block" not in sections:
        _not_checked(res, "dispatch.block", "dispatch.role" if role is None else "dispatch.grammar")
    else:
        _line(res, "dispatch.block", dispatch.block_errors(sections["Strict block"], role, prompts))

    _claim_lines(res, sections.get("Claims", ""), root, cfg)
    records = store.Store(root, "decision", cfg).load()
    by_id = {r.id: r for r in records}
    problems = []
    outside = "\n".join(v for k, v in sections.items() if k != "Strict block")
    for did in _token_ids(outside, cfg["ids"]["decision"]):
        if did not in by_id:
            problems.append("%s names no decision" % did)
        elif by_id[did].row.get("status") == "open":
            problems.append("%s is an open decision" % did)
    _line(res, "dispatch.decisions", problems)
    shown: list = []
    for path in _brief_paths(brief):
        for rec in decisions.find(records, [], path, None, False):
            if rec.id not in shown:
                shown.append(rec.id)
                res.passed("dispatch.in-force.%s" % rec.id)
    return res


def dispatch_ids(sections: dict, cfg: dict) -> list:
    return _token_ids(sections.get("Findings", ""), cfg["ids"]["finding"])


def main(argv=None) -> int:
    return run_gate("dispatch", check, argv)


if __name__ == "__main__":
    sys.exit(main())
