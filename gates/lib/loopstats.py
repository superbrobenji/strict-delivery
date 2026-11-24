"""Rules N and T and the escape-cost verdict (spec section 10, "Rules N and T"; plan Task 6E.3), standard library only.

Advisory statistics over the findings of one task. All arithmetic is in ``fractions.Fraction`` and integers
except ``u``. ``report`` is the one entry that reads finding rows; ``trend``, ``geo_fit``, ``rule_n``,
``verdict`` and ``ev`` are pure functions of the series.

``escape_cost`` (optional, ``config/2``) is read by ``report`` (the ``ev`` and ``escape_cost_set`` fields, through
``ev``) and by ``small_signals`` (``ev_below_one``). A ``cfg`` holding a malformed ``escape_cost`` is refused (the
controller ruling of plan Task 6E): ``config.load`` refuses it first on the CLI path; the local check is the library's
own line of defence.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Optional

from gates.lib import findings
from gates.lib.result import GateError, safe_text

ALPHA = Fraction(1, 10)
NOVELTY = Fraction(1, 2)
FIX_ROUND_CAP = 5
COUNTED = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
WEIGHTS = {"CRITICAL": 8, "HIGH": 4, "MEDIUM": 2, "LOW": 1}
LOW_PLATEAU_RUN = 2
MAX_COST_DIGITS = 600  # config/2's cap on an escape_cost value
MAX_ROUNDS = 99  # bounds the exact convolution (table D1)
_BISECTION_STEPS = 64


def trend(counts: list) -> dict:
    """``{N, S, p, u}`` of the weighted tally ``counts`` (``counts[i]`` is review ``i + 1``'s weight)."""
    k = len(counts)
    n = sum(counts)
    s = sum(i * c for i, c in enumerate(counts))
    # ways[t] = number of draw sequences with sum t, kept only for t <= s (sums never decrease).
    ways = [0] * (s + 1)
    ways[0] = 1
    for _ in range(n):
        prefix = [0] * (s + 2)
        for t in range(s + 1):
            prefix[t + 1] = prefix[t] + ways[t]
        ways = [prefix[t + 1] - prefix[max(0, t - k + 1)] for t in range(s + 1)]
    p = Fraction(sum(ways), k ** n)
    u = None
    if n > 0 and k >= 2:
        num = Fraction(2 * s - n * (k - 1), 2)
        var = Fraction(n * (k * k - 1), 12)
        u = float(num) / math.sqrt(float(var))
    return {"N": n, "S": s, "p": p, "u": u}


def _mean(q: Fraction, k: int) -> Fraction:
    """The truncated-geometric mean ``sum j q^j / sum q^j`` over ``j = 0..k-1``."""
    top = Fraction(0)
    bottom = Fraction(0)
    power = Fraction(1)
    for j in range(k):
        top += j * power
        bottom += power
        power *= q
    return top / bottom


def geo_fit(counts: list) -> Optional[dict]:
    """``{q, boundary, a, R, E_next}``; ``None`` when ``k < 2`` or ``N == 0``."""
    k = len(counts)
    t = trend(counts)
    n, s = t["N"], t["S"]
    if k < 2 or n == 0:
        return None
    if s == 0:
        return {"q": Fraction(0), "boundary": False, "a": Fraction(n), "R": Fraction(0), "E_next": Fraction(0)}
    if 2 * s >= n * (k - 1):
        return {"q": Fraction(1), "boundary": True, "a": None, "R": None, "E_next": Fraction(n, k)}
    target = Fraction(s, n)
    lo, hi = Fraction(0), Fraction(1)
    q = lo
    for _ in range(_BISECTION_STEPS):
        q = (lo + hi) / 2
        m = _mean(q, k)
        if m == target:
            break
        if m < target:
            lo = q
        else:
            hi = q
    qk = q ** k
    a = n / (1 - qk)
    return {"q": q, "boundary": False, "a": a, "R": a * qk, "E_next": a * (1 - q) * qk}


def rule_n(counts: list, novelty: Optional[Fraction]) -> bool:
    """Rule N: ``k >= 2``, ``X_k > 0``, ``novelty >= 1/2`` and ``X_k >= X_(k-1)``; ``counts`` is ``X``."""
    k = len(counts)
    return k >= 2 and counts[-1] > 0 and novelty is not None and novelty >= NOVELTY and counts[-1] >= counts[-2]


def verdict(counts: list, novelty: Optional[Fraction], narrowed: int, weighted: list, low_run: int) -> tuple:
    """``(word, reason)``, the ladder of spec section 10, first match wins."""
    k = len(counts)
    if counts[-1] == 0:
        return "CLEAN", "no counted finding in the last review"
    if low_run >= LOW_PLATEAU_RUN:
        return "LOW_PLATEAU", "only LOW findings in the last 2 reviews"
    if k > FIX_ROUND_CAP:
        return "ESCALATE", "fix rounds exhausted"
    if rule_n(counts, novelty):
        if narrowed >= 1:
            return "ESCALATE", "Rule N fired after a narrowing"
        return "STOP_NARROW", "Rule N fired: new dimensions keep arriving"
    if k < 3:
        return "CONTINUE", "insufficient data"
    fit = geo_fit(weighted)
    if trend(weighted)["p"] <= ALPHA and fit is not None and not fit["boundary"]:
        return "CONTINUE", "converging"
    if narrowed >= 1:
        return "ESCALATE", "not converging after a narrowing"
    if novelty is not None and novelty >= NOVELTY:
        return "STOP_NARROW", "not converging; new dimensions"
    return "ESCALATE", "same dimensions recur"


def ev(counts: list, severities: dict, escape_cost: Optional[dict]) -> Optional[dict]:
    """``{value, verdict}``: ``E_next * sum_s (n_s / N) * escape_cost[s]``; ``None`` without cost or fit.

    ``counts`` is the weighted tally ``W``; ``severities[s]`` is the number of counted findings of severity ``s``.
    """
    if escape_cost is None:
        return None
    fit = geo_fit(counts)
    if fit is None:
        return None
    n = sum(counts)
    value = fit["E_next"] * sum(Fraction(c, n) * escape_cost[s] for s, c in severities.items())
    return {"value": value, "verdict": "continue" if value > 1 else "stop"}


def _int(x: object) -> bool:
    return type(x) is int


def _check_escape_cost(ec: object) -> None:
    """Refuse an ``escape_cost`` that is not a mapping of exactly the four counted severities to ints in 0..10**600-1
    (the rule of ``config/2``, written locally; compared as numbers, never through ``str()``)."""
    if type(ec) is not dict:
        raise GateError("escape_cost: must be a mapping")
    for k in ec:
        if k not in COUNTED:
            raise GateError("escape_cost.%s: unknown key" % safe_text(k))
    for k in COUNTED:
        if k not in ec:
            raise GateError("escape_cost.%s: required key is missing" % k)
        v = ec[k]
        if not _int(v) or v < 0:
            raise GateError("escape_cost.%s: must be an integer of at least 0" % k)
        if v >= 10 ** MAX_COST_DIGITS:
            raise GateError("escape_cost.%s: must be an integer of at most %d digits" % (k, MAX_COST_DIGITS))


def _check_args(rounds: object, narrowed: object, cfg: object) -> list:
    """The refusals that depend on no row; returns the distinct narrowings, ascending."""
    if not _int(rounds) or not 1 <= rounds <= MAX_ROUNDS:
        raise GateError("rounds must be an integer from 1 to %d" % MAX_ROUNDS)
    if type(narrowed) is not list:
        raise GateError("narrowed must be a list")
    for r in narrowed:
        if not _int(r) or not 1 <= r <= rounds - 1:
            raise GateError("narrowing %s is outside 1..%d (the contract is narrowed after a review, not the last)"
                            % (safe_text(r), rounds - 1))
    if type(cfg) is dict and "escape_cost" in cfg:
        _check_escape_cost(cfg["escape_cost"])
    return sorted(set(narrowed))


def _parts(item: object) -> tuple:
    """``(id, row)`` of a store ``Record`` or of a bare row."""
    if hasattr(item, "row"):
        return item.id, item.row
    return (item.get("id") if type(item) is dict else None), item


def report(rows: list, plan: str, task: str, rounds: int, narrowed: list, cfg: dict) -> dict:
    """The statistics of one task. ``rows`` are the finding store's records (``Store.load()``) or bare rows.

    Every row must pass ``findings.validate``; every finding of the task needs ``review_round`` (at most
    ``rounds``) and ``caused_by_change``, and a counted one ``dimension``. A GateError names the record id.
    """
    distinct = _check_args(rounds, narrowed, cfg)
    by_round = [[] for _ in range(rounds)]  # counted findings of review i + 1: (severity, dimension)
    for item in rows:
        rid, row = _parts(item)
        errs = findings.validate(row, cfg)
        if errs:
            raise GateError("finding %s: %s" % (safe_text(rid), safe_text(errs[0])))
        owner = row["owner"]
        if owner["kind"] != "plan" or owner["plan"] != plan or owner["task"] != task:
            continue
        for field in ("review_round", "caused_by_change"):
            if field not in row:
                raise GateError("finding %s: %s is missing; loopstats needs it on every finding of the task"
                                % (safe_text(rid), field))
        rnd = row["review_round"]
        if rnd > rounds:
            raise GateError("finding %s: review_round %d is above --rounds %d" % (safe_text(rid), rnd, rounds))
        counted = row["caused_by_change"] is True and row["severity"] in COUNTED
        if counted and "dimension" not in row:
            raise GateError("finding %s: dimension is missing; loopstats needs it on a counted finding"
                            % safe_text(rid))
        if counted:
            by_round[rnd - 1].append((row["severity"], row.get("dimension")))
    x = [len(r) for r in by_round]
    w = [sum(WEIGHTS[s] for s, _ in r) for r in by_round]
    severities = {}
    for r in by_round:
        for s, _ in r:
            severities[s] = severities.get(s, 0) + 1
    # Novelty: round k's counted dimensions against the counted dimensions of earlier rounds only.
    earlier = set(d for r in by_round[:-1] for _, d in r)
    nu = None
    if x[-1] > 0:
        nu = Fraction(sum(1 for _, d in by_round[-1] if d not in earlier), x[-1])
    low_run = 0
    for r in reversed(by_round):
        if any(s != "LOW" for s, _ in r):
            break
        low_run += 1
    t = trend(w)
    fit = geo_fit(w)
    word, reason = verdict(x, nu, len(distinct), w, low_run)
    cost_set = type(cfg) is dict and "escape_cost" in cfg
    return {"plan": plan, "task": task, "rounds": rounds, "X": x, "W": w, "N": t["N"], "S": t["S"],
            "narrowed": distinct, "p": t["p"], "u": t["u"], "fit": fit, "nu": nu, "rule_n": rule_n(x, nu),
            "ev": ev(w, severities, cfg["escape_cost"] if cost_set else None),
            "escape_cost_set": cost_set, "verdict": word, "reason": reason, "low_run": low_run, "severities": severities,
            "note": any(s in ("CRITICAL", "HIGH") for s, _ in by_round[-1])}


def small_signals(rows: list, plan: str, task: str, rounds: int, narrowed: list, cfg: dict) -> dict:
    """``{rule_n, converging, ev_below_one}`` for the small re-review's conditions 6-8 (same refusals as report).

    ``ev_below_one`` is ``ev(...)["value"] < 1``; ``None`` when ``escape_cost`` is unset, ``rounds < 3`` or there is
    no fit (plan Task 6E.3, ``ev_below_one``)."""
    r = report(rows, plan, task, rounds, narrowed, cfg)
    converging = None
    if rounds >= 3:
        converging = r["p"] <= ALPHA and r["fit"] is not None and not r["fit"]["boundary"]
    below = None
    if rounds >= 3 and r["ev"] is not None:
        below = r["ev"]["value"] < 1
    return {"rule_n": r["rule_n"], "converging": converging, "ev_below_one": below}
