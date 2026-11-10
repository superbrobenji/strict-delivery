"""Gate ``claims``: the claims register (spec 7.2, 8; plan Task 2a.3).

Five categories, each one ``PASS claims.<cat>`` when clean, in this order: ``schema`` (``claims.validate``, one
line per file), ``store`` (``claims.file_errors``), ``document`` (``claims.document_errors``, one line per file),
``stale`` (``claims.stale_errors`` with the ids of one ``gitinfo.blob_ids`` call per run, owner Q-B2plan-4 (a),
Q-2a2r4-1 (a)) and ``base`` (``claims.base_errors`` against ``--base``,
default ``base_branch``, owner Q-B2plan-5 (a)). A line names a claim id only when it is valid and unique across the
run, else the claim file, with ``claims.<i>.`` in the reason (spec §13, Q-1c1-1 (a); stream d ruling 1). Lines of a
category are sorted by id. Every category is computed before any line is written, so a git or input problem
anywhere is the single ``claims.input`` line. The gate never runs a claim's ``direct`` or ``contradiction`` command
(Block 2 controller ruling).
"""
from __future__ import annotations

import sys

from gates.lib import claims, config, gitinfo, ids
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate

PRODUCES: tuple = ()  # Task 2c.1's claims tool declares ``claim`` (owner Q-B2plan-6 (a))

CATEGORIES = ("schema", "store", "document", "stale", "base")


def _args(args: list):
    p = gate_args("claims")
    p.add_argument("--base", default=None, action=_Once, help="the base branch (default: config base_branch)")
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root  # a root below the top level fails in config.load's _require_toplevel


def _suffix(s: str) -> str:
    """A line-id suffix with ``%`` written ``%25`` and ``:`` written ``%3A``, so the first ``": "`` of a FAIL line
    always ends its id, and the suffix decodes back (F-R1-1)."""
    return s.replace("%", "%25").replace(":", "%3A")


def _joined(pairs: list) -> list:
    """``(suffix, reason)`` pairs with one entry per encoded suffix, sorted by it (table G2, F-R1-2); the reasons
    of a repeated suffix are joined by ``"; "`` in order (line ids are unique per run)."""
    by: dict = {}
    for suffix, reason in pairs:
        by.setdefault(_suffix(suffix), []).append(reason)
    return [(s, "; ".join(by[s])) for s in sorted(by)]


def _items(cf) -> list:
    """``(index, claim)`` for the claim items of ``cf`` that are mappings, with their index in ``claims``."""
    items = cf.row.get("claims")
    return [(i, c) for i, c in enumerate(items) if type(c) is dict] if type(items) is list else []


def _where(files: list) -> dict:
    """Claim id -> ``[(file, index, item)]`` for every string id in the run."""
    out: dict = {}
    for cf in files:
        for i, c in _items(cf):
            if type(c.get("id")) is str:
                out.setdefault(c["id"], []).append((cf.file, i, c))
    return out


def check(args: list) -> Result:
    ns = _args(args)
    root = _root(ns)
    cfg = config.load(root)
    base = ns.base if ns.base is not None else cfg["base_branch"]
    files = claims.load(root, cfg)
    tracked = gitinfo.tracked_files(root)
    prefix = cfg["ids"]["claim"]
    where = _where(files)

    def valid(cid: str) -> bool:
        return not ids.id_problem(cid, prefix)

    def named(cid: str) -> bool:  # valid and unique across the run
        return valid(cid) and len(where.get(cid, ())) <= 1

    def by_file(kind: str, cid: str, reason: str) -> list:
        return [(kind + "." + f, "claims.%d.id: %s" % (i, reason)) for f, i, _c in where[cid]]

    # Owner Q-2a2r4-1 (a): one gitinfo.blob_ids call per run (at most one index copy), for every path any
    # stale_errors call below looks up; each call reads the map and copies no index.
    blobs = gitinfo.blob_ids(root, claims.stale_paths(files, root))
    stale = []
    for cf in files:
        for i, c in _items(cf):
            for cid, reason in claims.stale_errors(claims.ClaimFile(cf.file, {"claims": [c]}), root, base,
                                                   blob_ids=blobs):
                stale.append((cid, reason) if named(cid) else (cf.file, "claims.%d.%s" % (i, reason)))
    store = []
    for suffix, reason in claims.file_errors(files, prefix):
        kind, _, cid = suffix.partition(".")
        store += by_file(kind, cid, reason) if kind == "duplicate" else [(suffix, reason)]  # never unique
    base_lines = []
    for suffix, reason in claims.base_errors(root, cfg, files, base):
        kind, _, cid = suffix.partition(".")
        if kind == "collision" and not named(cid):
            lines = by_file(kind, cid, reason)
            # F-R2-1: blame only the occurrences that collide on their own, by the library's own comparison; if
            # none does, every occurrence stays named, so the collision is never dropped (fail closed).
            own = [ln for ln, (f, _i, c) in zip(lines, where[cid]) if suffix in dict(claims.base_errors(
                root, cfg, [claims.ClaimFile(f, {"claims": [c]})], base))]
            base_lines += own or lines
        elif kind == "removed" and not valid(cid):  # in no current file: named by its file at the merge base
            tail = reason.rindex(" on %s and is in no claim file now" % base)
            base_lines.append((kind + "." + reason[len("%s was in " % cid):tail], reason))
        else:
            base_lines.append((suffix, reason))
    found = {
        "schema": [(cf.file, "; ".join(errs)) for cf in files for errs in [claims.validate(cf.row, cfg)] if errs],
        "store": store,
        "document": [(cf.file, "; ".join(errs)) for cf in files
                     for errs in [claims.document_errors(cf, tracked)] if errs],
        "stale": stale,
        "base": base_lines,
    }
    res = Result("claims")
    for cat in CATEGORIES:
        pairs = _joined(found[cat])
        for suffix, reason in pairs:
            res.fail("claims.%s.%s" % (cat, suffix), reason)
        if not pairs:
            res.passed("claims." + cat)
    return res


def main(argv=None) -> int:
    return run_gate("claims", check, argv)


if __name__ == "__main__":
    sys.exit(main())
