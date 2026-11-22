"""Gate ``decisions``: the decision register obeys its rules (spec 7.1, 7.2, 7.4, 11, 13)."""
from __future__ import annotations

import fnmatch
import os
import re
import stat
import sys

from gates.lib import config, decisions, gitinfo, ids, schema
from gates.lib.result import GateError, Result, _exact, _Once, gate_args, repo_root, run_gate
from gates.lib.store import Store, base_errors, store_errors

PRODUCES: tuple = ()

_BOUND = rb"(?<![0-9A-Za-z_-])(%s)(?![0-9A-Za-z_-])"


def _args(args: list):
    p = gate_args("decisions")
    p.add_argument("--base", default=None, action=_Once, help="the base ref (default: config base_branch)")
    return p.parse_args(args)


def _root(given) -> str:
    root = given if given is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    gitinfo._require_toplevel(root)
    return root


def _keys(records: list, prefix: str) -> dict:
    """Line key per record (owner Q-1c1-1): the id when valid and unique, else the repo-relative file."""
    count: dict = {}
    for r in records:
        if type(r.id) is str:
            count[r.id] = count.get(r.id, 0) + 1
    return {r.file: (r.id if type(r.id) is str and ids.id_problem(r.id, prefix) == "" and count[r.id] == 1
                     else r.file) for r in records}


def _read_bytes(root: str, rel: str) -> bytes:
    """The bytes of the regular file ``rel`` under ``root``; no parent and no file is a symlink."""
    cur = root
    parts = rel.split("/")
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        mode = os.lstat(cur).st_mode
        if i < len(parts) - 1:
            if not stat.S_ISDIR(mode):
                raise OSError("a parent is not a real directory")
        elif not stat.S_ISREG(mode):
            raise OSError("not a regular file")
    with open(cur, "rb") as fh:
        return fh.read()


def _bad_scan_globs(cfg: dict) -> list:
    """``(index, problem)`` for every ``decisions.scan`` glob outside the schema glob grammar (F-1, U-2 folded into
    F-1, decision D-31): fnmatch never compiles one."""
    return [(i, schema.bracket_problem(g)) for i, g in enumerate(cfg["decisions"]["scan"])
            if schema.bracket_problem(g)]


def _scanned(tracked: frozenset, cfg: dict) -> list:
    state = cfg["paths"]["state"]
    globs = cfg["decisions"]["scan"]
    return sorted(p for p in tracked
                  if not (p == state or p.startswith(state + "/"))
                  and any(fnmatch.fnmatchcase(p, g) for g in globs))


def _scan(res: Result, root: str, files: list, open_ids: list) -> None:
    pat = re.compile(_BOUND % b"|".join(re.escape(i.encode("ascii")) for i in open_ids)) if open_ids else None
    refs_failed = scan_failed = False
    for rel in files:
        try:
            data = _read_bytes(root, rel)
        except OSError as e:
            res.fail("decisions.scan." + rel, "cannot read the file (%s)" % (e.strerror or e))
            scan_failed = True
            continue
        if pat is None:
            continue
        line, pos = 1, 0
        for m in pat.finditer(data):
            line += data.count(b"\n", pos, m.start())
            pos = m.start()
            where = "%s:%d" % (rel, line)
            res.fail("decisions.open-ref." + where, "%s references unanswered %s; the human answers it first"
                     % (where, m.group(1).decode("ascii")))
            refs_failed = True
    if not refs_failed and not scan_failed:
        res.passed("decisions.open-ref")
    if not scan_failed:
        res.passed("decisions.scan")


def _category(res: Result, name: str, pairs: list) -> None:
    for suffix, reason in pairs:
        res.fail("decisions.%s.%s" % (name, suffix), reason)
    if not pairs:
        res.passed("decisions." + name)


_NEED_CLASS = "profile-override"


def _plain(x: object) -> str:
    """``x`` as an exact ``str`` the way ``safe_text`` makes one (a ``str`` subclass by its characters, any other value
    through ``str``), with no escaping: ``Result.render`` escapes each reason once (spec design.md:642)."""
    return _exact(x) if issubclass(type(x), str) else _exact(str(x))


def _override_entries(cfg: dict) -> list:
    """``(key, decision id)`` per ``cfg["overrides"]`` entry in file order, ``[]`` when the config has none.
    ``config.load`` refuses every malformed shape (Task 4a.2); a caller that bypasses it gets a ``GateError`` naming
    the entry (decision D3), never a ``TypeError``."""
    if "overrides" not in cfg:
        return []
    overrides = cfg["overrides"]
    if type(overrides) is not dict:
        raise GateError("overrides: must be a mapping")
    out: list = []
    for key, entry in overrides.items():
        name = "overrides." + _plain(key)
        if type(key) is not str:
            raise GateError(name + ": key must be a string")
        if type(entry) is not dict:
            raise GateError(name + ": must be a mapping")
        if "decision" not in entry:
            raise GateError(name + ".decision: required key is missing")
        if type(entry["decision"]) is not str:
            raise GateError(name + ".decision: must be a string")
        out.append((key, entry["decision"]))
    return out


def _override_problem(records: list, by_id: dict, in_force: set, gone: set, dec: str) -> str:
    """The one reason ``dec`` cannot authorise a profile override, the first that holds in the plan's order (decision
    D-Q2 (a)); ``""`` when it can. Ids and the class are compared by exact equality (D7)."""
    rec = by_id.get(dec)
    if rec is None:
        return "%s is missing" % dec
    row = decisions._row(rec)
    status = row.get("status")
    exact = type(status) is str  # a str subclass's methods never run (Q-1C0FIN2-R1 (a)): it matches no status
    if exact and status == "open":
        return "%s is open" % dec
    if exact and status == "withdrawn":
        return "%s is withdrawn" % dec
    if dec in gone:
        try:
            return "%s is superseded by %s" % (dec, decisions.current(records, dec))
        except GateError as e:  # a fork: the library's own text names the id and both superseders (D-Q3 (a))
            return str(e)
    cls = row.get("class")
    if type(cls) is not str or cls != _NEED_CLASS:
        return "%s has class %s; a profile override needs class %s" % (dec, _plain(cls), _NEED_CLASS)
    if not exact or id(rec) not in in_force:  # the library's in_force may have run a subclass's method: fail closed
        return "%s is not in force" % dec
    return ""


def _override_lines(res: Result, records: list, cfg: dict) -> None:
    entries = _override_entries(cfg)
    by_id = decisions._by_id(records)
    in_force = {id(r) for r in decisions.in_force(records)}
    gone = decisions.superseded_ids(records)
    for key, dec in entries:
        problem = _override_problem(records, by_id, in_force, gone, dec)
        if problem:
            res.fail("decisions.override." + key, problem)
        else:
            res.passed("decisions.override." + key)


def check(args: list) -> Result:
    ns = _args(args)
    root = _root(ns.root)
    cfg = config.load(root)
    base = ns.base if ns.base is not None else cfg["base_branch"]
    store = Store(root, "decision", cfg)
    records = store.load()
    tracked = gitinfo.tracked_files(root)
    key = _keys(records, store.prefix)
    res = Result("decisions")
    _category(res, "schema", [(key[r.file], e) for r in records for e in decisions.validate(r.row, cfg)])
    _category(res, "store", store_errors(records, store.prefix))
    _category(res, "base", base_errors(root, store, base, decisions.is_resolved, lambda row: False))
    _category(res, "landed", [(key[r.file], e) for r in records
                              for e in decisions.landed_errors(r.row, root, cfg, tracked)])
    _category(res, "refs", decisions.ref_errors(records))
    open_ids = sorted({r.id for r in records if type(r.id) is str and r.row.get("status") == "open"
                       and ids.id_problem(r.id, store.prefix) == ""})
    bad = _bad_scan_globs(cfg)
    for i, problem in bad:
        res.fail("decisions.scan-glob.%d" % i, "config decisions.scan.%d: %s" % (i, problem))
    if not bad:
        _scan(res, root, _scanned(tracked, cfg), open_ids)
    _override_lines(res, records, cfg)
    return res


def main(argv=None) -> int:
    return run_gate("decisions", check, argv)


if __name__ == "__main__":
    sys.exit(main())
