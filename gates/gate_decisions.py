"""Gate ``decisions``: the decision register obeys its rules (spec 7.1, 7.2, 7.4, 11, 13)."""
from __future__ import annotations

import fnmatch
import os
import re
import stat
import sys

from gates.lib import config, decisions, gitinfo, ids
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate
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
    _scan(res, root, _scanned(tracked, cfg), open_ids)
    return res


def main(argv=None) -> int:
    return run_gate("decisions", check, argv)


if __name__ == "__main__":
    sys.exit(main())
