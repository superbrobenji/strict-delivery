"""Gate ``cleanup``: a finished plan's or program's per-effort files are gone and nothing is left unfinished (spec 9;
programs design 8.3 and 12; plan Task P3.3; decisions D-Q1 to D-Q8 of its table). Not in ``run_all`` (controller ruling).

``--plan SLUG`` or ``--program NAME --decision DEC`` (exactly one of the two; ``--decision`` is required with
``--program`` and refused with ``--plan``). Lines, in this order, each with one ``PASS`` when clean:

* ``cleanup.merge``: the plan has its final merge (``cleanup.final_merge``); for a program, ``--decision`` names an
  answered ``program-close`` decision of that program that nothing supersedes, and every stream plan has its final
  merge. A failure stops the gate here, since nothing else is defined without a merge.
* ``cleanup.gone.<path>``: a path of ``plan_effort`` (``program_effort``) is still tracked (the index decides).
* ``cleanup.owner.<id>``: a finding that is not resolved is still owned by the plan (by any plan of the program).
* ``cleanup.open.<id>``: a decision cited in the per-effort files is still open.
* ``cleanup.landed.<id>``: a cited lasting decision in force has no ``landed_in`` or fails ``landed_errors``.

Stated limits (D-Q8): the set is read at the plan's final merge commit, so a file added under the plan's folders after
that merge is not in it and is not judged (a follow-up row, not this gate). A path replaced by a symlink reads as
gone (``gitinfo.tracked_files`` lists regular files only). A shallow clone, an unreadable file and every library
``GateError`` are one ``cleanup.input`` line. The gate only reads: no network and no write.
"""
from __future__ import annotations

import sys

from gates.lib import checkpoints, cleanup, config, decisions, findings, gitinfo, ids, programs
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate
from gates.lib.store import Store

PRODUCES: tuple = ()


def _args(args: list):
    p = gate_args("cleanup")
    p.add_argument("--plan", default=None, action=_Once, help="the plan slug")
    p.add_argument("--program", default=None, action=_Once, help="the program name (with --decision)")
    p.add_argument("--decision", default=None, action=_Once, help="the answered program-close decision (with --program)")
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root


def _argv_rules(ns) -> None:
    """Every refusal that needs neither a git call nor a file (before the first I/O)."""
    if (ns.plan is None) == (ns.program is None):
        raise GateError("exactly one of --plan SLUG or --program NAME is required")
    if ns.plan is not None:
        if not cleanup.is_slug(ns.plan):
            raise GateError("--plan must match [a-z0-9][a-z0-9-]*")
        if ns.decision is not None:
            raise GateError("--decision is refused with --plan; it names the program-close decision of --program")
    else:
        why = programs.program_problem(ns.program)
        if why:
            raise GateError("--program: %s" % why)
        if ns.decision is None:
            raise GateError("--decision DEC is required with --program: the answered program-close decision")


def _close_problems(records: list, name: str, dec: str) -> list:
    """Why ``dec`` is not an answered ``program-close`` decision of program ``name`` (D-Q2); ``[]`` when it is."""
    rows = [r for r in records if type(r.id) is str and r.id == dec]
    if not rows:
        return ["decision %s has no record" % dec]
    row = rows[0].row
    why = []
    if row.get("status") != "answered":
        why.append("decision %s is not answered" % dec)
    if row.get("class") != programs.PROGRAM_CLOSE:
        why.append("decision %s is not of class %s" % (dec, programs.PROGRAM_CLOSE))
    if type(row.get("program")) is not str or row["program"] != name:
        why.append("decision %s does not name program %s" % (dec, name))
    if decisions.current(records, dec) != dec:
        why.append("decision %s is superseded" % dec)
    return why


def _stream_plans(root: str, cfg: dict, name: str) -> tuple:
    """``(program plan path, spec paths, stream plan slugs)`` of the program's ``streams.yml``."""
    prog = programs.load_program(root, cfg, name, "refs/heads/%s/integration" % name)
    streams = prog.streams
    slugs = []
    rows = streams.get("streams")
    for row in rows if type(rows) is list else []:
        path = row.get("plan") if type(row) is dict else None
        try:
            slugs.append(checkpoints.plan_slug(path))
        except ValueError:
            continue   # program_effort refuses the malformed row with its own text
    specs = streams.get("specs")
    return streams.get("plan"), (specs if type(specs) is list else []), sorted(set(slugs))


def _plan_mode(root: str, cfg: dict, res: Result, plan: str):
    fm = cleanup.final_merge(root, cfg, plan)
    if fm is None:
        res.fail("cleanup.merge", "plan %s has no final merge on the base branch" % plan)
        return None
    res.passed("cleanup.merge")
    effort = cleanup.plan_effort(root, cfg, plan, fm["merge"])
    return effort, [(effort, fm["merge"])], {plan}


def _program_mode(root: str, cfg: dict, res: Result, name: str, dec: str):
    why = _close_problems(Store(root, "decision", cfg).load(), name, dec)
    if why:
        res.fail("cleanup.merge", "; ".join(why))
        return None
    plan_path, specs, slugs = _stream_plans(root, cfg, name)
    scans = []
    missing = []
    for slug in slugs:
        fm = cleanup.final_merge(root, cfg, slug)
        if fm is None:
            missing.append("stream plan %s has no final merge; the program is not finished" % slug)
        else:
            scans.append((cleanup.plan_effort(root, cfg, slug, fm["merge"]), fm["merge"]))
    if missing:
        res.fail("cleanup.merge", "; ".join(missing))
        return None
    res.passed("cleanup.merge")
    effort = cleanup.program_effort(root, cfg, name, None)
    shared = [p for p in [plan_path] + specs if type(p) is str]
    scans.append((shared, "refs/heads/" + cfg["base_branch"]))
    owners = set(slugs)
    owners.add(checkpoints.plan_slug(plan_path))
    return effort, scans, owners


def _gone(res: Result, effort: list, tracked: frozenset) -> None:
    left = [p for p in effort if p in tracked]
    for p in left:
        res.fail("cleanup.gone." + p, "still tracked; remove it with git rm")
    if not left:
        res.passed("cleanup.gone")


def _owner(root: str, cfg: dict, res: Result, owners: set) -> None:
    bad = False
    for rec in Store(root, "finding", cfg).load():
        row = rec.row
        owner, status = row.get("owner"), row.get("status")
        if (type(owner) is not dict or type(owner.get("kind")) is not str or owner["kind"] != "plan"
                or type(owner.get("plan")) is not str or owner["plan"] not in owners
                or type(status) is not str or status in findings.RESOLVED):
            continue
        why = ids.id_problem(rec.id, cfg["ids"]["finding"])
        if why:
            raise GateError("%s: id: %s" % (rec.file, why))
        res.fail("cleanup.owner." + rec.id, "finding %s of plan %s is %s; pass it to an issue or roadmap item"
                 % (rec.id, owner["plan"], status))
        bad = True
    if not bad:
        res.passed("cleanup.owner")


def _decisions(root: str, cfg: dict, res: Result, scans: list, tracked: frozenset) -> None:
    cited: set = set()
    for paths, at in scans:
        cited.update(cleanup.cited_decisions(root, paths, at, cfg["ids"]["decision"]))
    records = Store(root, "decision", cfg).load()
    by_id: dict = {}
    for r in records:
        if type(r.id) is str:
            by_id.setdefault(r.id, r)
    force = {r.id for r in decisions.in_force(records) if type(r.id) is str}
    still_open: list = []
    judged: set = set()
    for dec in sorted(cited):
        rec = by_id.get(dec)
        if rec is None:
            continue
        if not decisions.is_resolved(rec.row):
            still_open.append(dec)
        elif rec.row.get("status") == "answered" and rec.row.get("effect") == "lasting":
            judged.add(decisions.current(records, dec))
    for dec in still_open:
        res.fail("cleanup.open." + dec, "decision %s is cited by the cleaned files and is still open" % dec)
    if not still_open:
        res.passed("cleanup.open")
    unlanded = False
    for dec in sorted(judged & force):
        row = by_id[dec].row
        why = decisions.landed_errors(row, root, cfg, tracked)
        if "landed_in" not in row or (type(row["landed_in"]) is list and row["landed_in"] == []):
            why = why + ["landed_in: absent or empty; a lasting decision lands its rule outside the cleaned files"]
        if why:
            res.fail("cleanup.landed." + dec, "; ".join(why))
            unlanded = True
    if not unlanded:
        res.passed("cleanup.landed")


def check(args: list) -> Result:
    ns = _args(args)
    _argv_rules(ns)
    root = _root(ns)
    cfg = config.load(root)
    if ns.decision is not None:
        why = ids.id_problem(ns.decision, cfg["ids"]["decision"])
        if why:
            raise GateError("--decision: %s" % why)
    if gitinfo.is_shallow(root):
        raise GateError("shallow clone; fetch the full history")
    res = Result("cleanup")
    got = _plan_mode(root, cfg, res, ns.plan) if ns.plan is not None else _program_mode(root, cfg, res, ns.program,
                                                                                        ns.decision)
    if got is None:
        return res
    effort, scans, owners = got
    tracked = gitinfo.tracked_files(root)
    _gone(res, effort, tracked)
    _owner(root, cfg, res, owners)
    _decisions(root, cfg, res, scans, tracked)
    return res


def main(argv=None) -> int:
    return run_gate("cleanup", check, argv)


if __name__ == "__main__":
    sys.exit(main())
