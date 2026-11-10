"""Gate ``register``: the finding register obeys its rules (spec 5, 7.2, 13, 13a; OQ-4, OQ-5, OQ-6, OQ-18)."""
from __future__ import annotations

import re
import sys

from gates.gate_decisions import _BOUND, _keys, _read_bytes, _root
from gates.lib import config, findings, gitinfo, ids
from gates.lib.result import Result, _Once, gate_args, run_gate
from gates.lib.store import Store, _merge_base_rows, _row_changed, base_errors, store_errors

PRODUCES: tuple = ()

_TAG = re.compile(rb"<!-- schema: review-report/[1-9][0-9]* -->")


def _args(args: list):
    p = gate_args("register")
    p.add_argument("--base", default=None, action=_Once, help="the base ref (default: config base_branch)")
    return p.parse_args(args)


def _category(res: Result, name: str, pairs: list) -> None:
    for suffix, reason in pairs:
        res.fail("register.%s.%s" % (name, suffix), reason)
    if not pairs:
        res.passed("register." + name)


def _is_report(data: bytes) -> bool:
    """The first line, with one trailing CR stripped (owner Q-1c2-1 (a)), is exactly a review-report tag."""
    first = data.split(b"\n", 1)[0]
    if first.endswith(b"\r"):
        first = first[:-1]
    return _TAG.fullmatch(first) is not None


def _reports(res: Result, root: str, cfg: dict, tracked: frozenset, known: set, prefix: str) -> None:
    reviews = cfg["paths"]["reviews"]
    files = sorted(p for p in tracked if p == reviews or p.startswith(reviews + "/"))
    shape = re.compile(_BOUND % (re.escape(prefix.encode("ascii")) + b"-[0-9]{8}-["
                                 + ids.ALPHABET.encode("ascii") + b"]{4}"))
    failed = False
    for rel in files:
        try:
            data = _read_bytes(root, rel)
        except OSError as e:
            res.fail("register.report." + rel, "cannot read the file (%s)" % (e.strerror or e))
            failed = True
            continue
        if not _is_report(data):
            continue
        seen: list = []
        for m in shape.finditer(data):
            token = m.group(1).decode("ascii")
            if token not in known and token not in seen:
                seen.append(token)
                res.fail("register.report." + rel, "%s is not in the register" % token)
                failed = True
    if not failed:
        res.passed("register.report")


def check(args: list) -> Result:
    ns = _args(args)
    root = _root(ns.root)
    cfg = config.load(root)
    base = ns.base if ns.base is not None else cfg["base_branch"]
    store = Store(root, "finding", cfg)
    records = store.load()
    decision_records = Store(root, "decision", cfg).load()
    tracked = gitinfo.tracked_files(root)
    key = _keys(records, store.prefix)
    res = Result("register")
    _category(res, "schema", [(key[r.file], e) for r in records for e in findings.validate(r.row, cfg)])
    _category(res, "store", store_errors(records, store.prefix))
    _category(res, "base", base_errors(root, store, base, findings.is_resolved,
                                       lambda row: findings.may_delete(row, root, cfg, decision_records)))
    _category(res, "transition", [(key[r.file], e) for r in records for e in findings.transition_errors(r.row)])
    at_mb = _merge_base_rows(root, store.directory, base)
    _category(res, "evidence", [(key[r.file], e) for r in records
                                for e in findings.evidence_errors(r.row, root, cfg, decision_records, tracked,
                                                                  _row_changed(r, at_mb, "finding"))])
    _category(res, "epic", findings.epic_errors(records))
    known = {r.id for r in records if ids.id_problem(r.id, store.prefix) == ""}
    _reports(res, root, cfg, tracked, known, store.prefix)
    return res


def main(argv=None) -> int:
    return run_gate("register", check, argv)


if __name__ == "__main__":
    sys.exit(main())
