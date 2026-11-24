"""Gate ``drift``: a live program's status page, stream branches and integration branch against git (plan Task 5c.2;
rulings R5c-1, R5c-2, R5c-4; decisions D-5c2-Q1 to D-5c2-Q21 of its table; owner answer Q-RC4-1 (a)).

Lines, in this order: ``drift.input`` (the whole run fails and nothing else prints) | ``drift.none`` (no live program and no
``--program``) | ``drift.base`` (once), then per program (sorted) ``drift.status.<p>`` (one ``FAIL`` per text of the status
page; an invalid page skips the row checks and ``host`` of that program), ``drift.integration.<p>``, and for each of the
checks ``branch``, ``behind``, ``merged``, ``handoff``, ``pending``, ``blockers``: one ``FAIL drift.<check>.<p>.<s>`` per
reason, streams in id order, or one ``PASS drift.<check>.<p>`` when nothing failed; with ``--host`` last ``drift.host.<p>``
(a ``gh`` failure) or ``drift.host.<p>.<s>``. A program is read at ``refs/heads/<p>/integration``, never from the work
tree. ``--program`` is repeatable (owner Q-RC4-1 (a)); ``--host`` given twice is accepted. The estimate is not a gate line
(R5c-2): ``gates.tools.drift_cli`` reports it."""
from __future__ import annotations

import sys

from gates.lib import config, drift, gitinfo, programs
from gates.lib.result import GateError, Result, gate_args, repo_root, run_gate, safe_text

PRODUCES: tuple = ()

CHECKS = ("branch", "behind", "merged", "handoff", "pending", "blockers")


def parser(prog: str, host: bool):
    """The argument parser of the gate (``host`` True) or of ``drift report`` (``host`` False)."""
    p = gate_args(prog)
    p.add_argument("--program", action="append", help="a live program to judge (repeatable; default: every live program)")
    if host:
        p.add_argument("--host", action="store_true", help="also compare the pull requests on the host through gh")
    return p


def root_of(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root


def selected(root: str, cfg: dict, named) -> list:
    """The programs to judge, sorted: every live program, or the ``--program`` names (each well formed, each live)."""
    live = programs.live_programs(root, cfg)
    if named is None:
        return live
    for name in named:
        why = programs.program_problem(name)
        if why:
            raise GateError("program name: %s" % why)
    out = sorted(set(named))
    for name in out:
        if name not in live:
            raise GateError("program %s is not live: no local branch %s/integration whose tip holds streams.yml"
                            % (safe_text(name), safe_text(name)))
    return out


def load(root: str, cfg: dict, p: str):
    """``(Program, status rows, status errors)`` of ``p`` at the tip of ``refs/heads/<p>/integration``."""
    prog = programs.load_program(root, cfg, p, "refs/heads/" + programs.branch_of(p))
    rows = programs.status_rows(prog.status_text)
    ids = [r.id for r in prog.requests if type(r.id) is str]
    return prog, rows, programs.status_errors(rows, prog.streams, cfg=cfg, request_ids=ids)


def _suffix(suffix: object, want: str) -> None:
    if suffix != want:
        raise GateError("a drift check gave suffix %s, not %s" % (safe_text(suffix), safe_text(want)))


def _program_level(res: Result, errs: list, id_: str, want: str) -> None:
    for suffix, reason in errs:
        _suffix(suffix, want)
        res.fail(id_, reason)
    if not errs:
        res.passed(id_)


def _streams(res: Result, root: str, cfg: dict, p: str, prog, rows: list) -> None:
    by = {r["stream"]: r for r in rows}
    found: dict = {c: [] for c in CHECKS}
    for st in sorted(prog.streams["streams"], key=lambda s: s["id"]):
        for suffix, reason in drift.stream_errors(root, cfg, prog, by[st["id"]], st):
            cat, dot, sid = suffix.partition(".")
            if cat not in found or dot != "." or sid != st["id"]:
                raise GateError("stream_errors gave suffix %s" % safe_text(suffix))
            found[cat].append((sid, reason))
    for c in CHECKS:
        for sid, reason in found[c]:
            res.fail("drift.%s.%s.%s" % (c, p, sid), reason)
        if not found[c]:
            res.passed("drift.%s.%s" % (c, p))


def _host(res: Result, root: str, cfg: dict, p: str, prog) -> None:
    ids = {s["id"] for s in prog.streams["streams"]}
    errs = drift.host_errors(root, cfg, prog)
    for suffix, reason in errs:
        cat, dot, sid = suffix.partition(".")
        if cat != "host" or (dot == "." and sid not in ids):
            raise GateError("host_errors gave suffix %s" % safe_text(suffix))
        res.fail("drift.host.%s%s" % (p, dot + sid), reason)
    if not errs:
        res.passed("drift.host." + p)


def check(args: list) -> Result:
    ns = parser("drift", True).parse_args(args)
    root = root_of(ns)
    cfg = config.load(root)
    res = Result("drift")
    names = selected(root, cfg, ns.program)
    if not names:
        res.passed("drift.none")
        return res
    if gitinfo.is_shallow(root):
        raise GateError("shallow clone; fetch the full history")
    _program_level(res, drift.base_errors(root, cfg), "drift.base", "base")
    for p in names:
        prog, rows, bad = load(root, cfg, p)
        for text in bad:
            res.fail("drift.status." + p, text)
        if not bad:
            res.passed("drift.status." + p)
        _program_level(res, drift.integration_errors(root, cfg, p), "drift.integration." + p, "integration." + p)
        if bad:
            continue
        _streams(res, root, cfg, p, prog, rows)
        if ns.host:
            _host(res, root, cfg, p, prog)
    return res


def main(argv=None) -> int:
    return run_gate("drift", check, argv)


if __name__ == "__main__":
    sys.exit(main())
