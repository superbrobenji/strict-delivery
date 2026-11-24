"""Tool ``drift``: ``python3 -m gates drift report [--program P]... [--root R]`` prints one ``over`` line per status row
whose ``used`` is past ``drift.estimate_factor_pct`` percent of its ``estimate``, or ``none`` (plan Task 5c.2, ruling R5c-2;
decisions D-5c2-Q10, Q14 to Q20). It reads each program at the tip of ``refs/heads/<p>/integration``, writes nothing, and
is not a gate: no ``PASS`` or ``FAIL`` line. Exit 0 when every selected program loaded, 1 when one did not (the others are
still reported; ``none`` is then not printed) or the selection is refused, 2 on a usage error."""
from __future__ import annotations

import sys

from gates import gate_drift
from gates.lib import config, drift
from gates.lib.result import GateError, safe_text

_USAGE = "drift: usage: python3 -m gates drift report [--program P]... [--root R]\n"
_MAX_DIGITS = 600


def _why(e: BaseException) -> str:
    return safe_text(e) if isinstance(e, GateError) else "%s: %s" % (type(e).__name__, safe_text(e))


def _over(root: str, cfg: dict, p: str, pct: int) -> list:
    prog, rows, bad = gate_drift.load(root, cfg, p)
    if bad:
        raise GateError("%s: %s" % (p, safe_text(bad[0])))
    return [line for line in (drift.over_estimate(row, pct) for row in rows) if line is not None]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "report":
        sys.stderr.write(_USAGE)
        return 2
    try:
        ns = gate_drift.parser("drift report", False).parse_args(args[1:])
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        root = gate_drift.root_of(ns)
        cfg = config.load(root)
        pct = cfg["drift"]["estimate_factor_pct"]
        if pct >= 10 ** _MAX_DIGITS:
            raise GateError("drift.estimate_factor_pct: more than %d digits" % _MAX_DIGITS)
        names = gate_drift.selected(root, cfg, ns.program)
    except Exception as e:
        sys.stderr.write("drift: %s\n" % _why(e))
        return 1
    lines, failed = [], False
    for p in names:
        try:
            lines += _over(root, cfg, p, pct)
        except Exception as e:
            sys.stderr.write("drift: %s\n" % _why(e))
            failed = True
    sys.stdout.write("".join(l + "\n" for l in lines) if lines or failed else "none\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
