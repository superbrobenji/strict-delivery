"""Command ``loopstats``: the advisory Rules N and T after a review (spec section 10; plan Task 6E.3).

Standard library only. ``python3 -m gates.loopstats [--plan SLUG] --task TASK --rounds K [--narrowed R]...
[--root R] [--json]``. Once the numbers are computed it exits 0 whatever the verdict; every refusal, argument
errors included, exits 1 with one stderr line ``loopstats: <reason>`` and writes nothing to stdout (table D2).
"""
from __future__ import annotations

import json
import re
import sys
from fractions import Fraction
from types import SimpleNamespace
from typing import Optional

from gates.lib import config, loopstats
from gates.lib.result import GateError, repo_root, safe_text
from gates.lib.store import Store

_PLAN = re.compile(r"[a-z0-9][a-z0-9-]*")
_INT = re.compile(r"[1-9][0-9]?")  # D1: 1..99, ASCII only, matched before int() runs


_ONCE = ("--plan", "--task", "--rounds", "--root")


def _parse(args: list) -> SimpleNamespace:
    """argv by hand (no argparse): ``--opt value`` and ``--opt=value``; ``--plan``, ``--task``, ``--rounds``,
    ``--root`` and ``--json`` once, ``--narrowed`` repeatable. An unknown token (a positional, an abbreviation,
    ``--help``, ``-h``, ``--``), a missing value and a value starting with ``-`` are refused with the token named."""
    ns = SimpleNamespace(plan=None, task=None, rounds=None, root=None, narrowed=[], json=False)
    i = 0
    while i < len(args):
        tok = args[i]
        i += 1
        name, eq, value = tok.partition("=")
        if name == "--json":
            if eq:
                raise GateError("--json: takes no value")
            if ns.json:
                raise GateError("--json given more than once")
            ns.json = True
            continue
        if name not in _ONCE and name != "--narrowed":
            raise GateError("unknown argument %s" % safe_text(tok))
        if not eq:
            if i >= len(args):
                raise GateError("%s: value missing" % name)
            value = args[i]
            i += 1
        if value.startswith("-"):
            raise GateError("%s: value must not start with '-'" % name)
        if name == "--narrowed":
            ns.narrowed.append(value)
            continue
        key = name[2:]
        if getattr(ns, key) is not None:
            raise GateError("%s given more than once" % name)
        setattr(ns, key, value)
    return ns


def _number(flag: str, text: str) -> int:
    if _INT.fullmatch(text) is None:
        raise GateError("%s: must be an integer from 1 to 99" % flag)
    return int(text)


def _fmt(f: Fraction) -> str:
    """A rational ``f >= 0`` to 3 places, half to even (every printed figure is non-negative: escape_cost is >= 0)."""
    n = round(f * 1000)
    return "%d.%03d" % (n // 1000, n % 1000)


def _ev_text(r: dict) -> str:
    """The text after ``EV `` (also the JSON ``ev``): unset wins over no fit."""
    if not r["escape_cost_set"]:
        return "unset: escape_cost not configured"
    if r["ev"] is None:
        return "n/a: no fit"
    return "value=%s -> %s" % (_fmt(r["ev"]["value"]), r["ev"]["verdict"])


def _csv(values: list) -> str:
    return ",".join(str(v) for v in values)


def _words(r: dict) -> dict:
    """The printed form of every figure of ``r`` (``None`` for an absent one)."""
    fit = r["fit"]
    q = R = e = None
    if fit is not None:
        q = "1(boundary)" if fit["boundary"] else _fmt(fit["q"])
        R = "unbounded" if fit["R"] is None else _fmt(fit["R"])
        e = _fmt(fit["E_next"])
    return {"p": _fmt(r["p"]), "u": None if r["u"] is None else "%+.2f" % r["u"], "q": q, "R": R, "E_next": e,
            "nu": None if r["nu"] is None else _fmt(r["nu"])}


def _lines(r: dict) -> list:
    wd = _words(r)
    na = lambda v: "n/a" if v is None else v  # noqa: E731
    task = safe_text(r["task"])
    narrowed = _csv(r["narrowed"]) if r["narrowed"] else "none"
    x, w = _csv(r["X"]), _csv(r["W"])
    ev_line = "EV " + _ev_text(r)
    out = [
        "LOOPSTATS plan=%s task=%s rounds=%d X=%s W=%s N=%d S=%d narrowed=%s"
        % (r["plan"], task, r["rounds"], x, w, r["N"], r["S"], narrowed),
        "RULE-T p=%s u=%s q=%s R=%s E_next=%s" % (wd["p"], na(wd["u"]), na(wd["q"]), na(wd["R"]), na(wd["E_next"])),
        "RULE-N nu=%s fired=%s" % (na(wd["nu"]), "yes" if r["rule_n"] else "no"),
        ev_line,
        "VERDICT %s (%s)" % (r["verdict"], r["reason"]),
    ]
    if r["note"]:
        out.append("NOTE CRITICAL or HIGH findings caused by the change are fixed whatever the verdict")
    out.append("Loopstats: %s r%d: X=%s W=%s p=%s q=%s nu=%s -> %s"
               % (task, r["rounds"], x, w, wd["p"], na(wd["q"]), na(wd["nu"]), r["verdict"]))
    return out


def _json(r: dict, lines: list) -> str:
    wd = _words(r)
    note = None
    ev_text = _ev_text(r)
    for ln in lines:
        if ln.startswith("NOTE "):
            note = ln[len("NOTE "):]
    obj = {"plan": r["plan"], "task": safe_text(r["task"]), "rounds": r["rounds"], "X": r["X"], "W": r["W"],
           "N": r["N"], "S": r["S"], "narrowed": r["narrowed"], "p": wd["p"], "u": wd["u"], "q": wd["q"],
           "R": wd["R"], "E_next": wd["E_next"], "nu": wd["nu"], "rule_n": r["rule_n"], "ev": ev_text,
           "verdict": r["verdict"], "reason": r["reason"], "note": note, "ledger": lines[-1]}
    return json.dumps(obj, sort_keys=True) + "\n"


def _run(args: list) -> str:
    ns = _parse(args)
    if ns.plan is None:
        raise GateError("--plan: required")
    if _PLAN.fullmatch(ns.plan) is None:
        raise GateError("--plan: must match [a-z0-9][a-z0-9-]*")
    if ns.task is None or ns.task == "":
        raise GateError("--task: required and not empty")
    if ns.rounds is None:
        raise GateError("--rounds: required")
    rounds = _number("--rounds", ns.rounds)
    narrowed = [_number("--narrowed", t) for t in ns.narrowed]
    for i, r in enumerate(narrowed):
        if r in narrowed[:i]:
            raise GateError("--narrowed %d given twice" % r)
        if r > rounds - 1:
            raise GateError("--narrowed: %d must be below --rounds %d" % (r, rounds))
    root = ns.root if ns.root is not None else repo_root()
    cfg = config.load(root)
    rows = Store(root, "finding", cfg).load()
    r = loopstats.report(rows, ns.plan, ns.task, rounds, narrowed, cfg)
    lines = _lines(r)
    return _json(r, lines) if ns.json else "".join(ln + "\n" for ln in lines)


def main(argv: Optional[list] = None) -> int:
    """0 with the report on stdout; 1 with one ``loopstats: <reason>`` stderr line and nothing on stdout."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        text = _run(args)
    except GateError as e:
        sys.stderr.write("loopstats: %s\n" % safe_text(e))
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
