"""Gate ``cites``: every cite in a tracked ``*.md`` and every ``landed_in`` anchor resolves (spec 9, 7.4, 13)."""
from __future__ import annotations

import os
import stat
from typing import Optional

from gates.lib import cites, config, gitinfo
from gates.lib.result import GateError, Result, _raw, gate_args, repo_root, run_gate
from gates.lib.store import Store

PRODUCES: tuple = ()

_CATEGORIES = ("doc", "line", "anchor", "landed")


def _root(args: list) -> str:
    ns = gate_args("cites").parse_args(args)
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    gitinfo._require_toplevel(root)
    return root


class _Reader:
    """Reads tracked files from the working tree, once each; a symlink, a directory, a missing entry or a
    symlinked parent is None (never followed); any other read error is a GateError (owner Q-C22-1 (a))."""

    def __init__(self, root: str) -> None:
        self.root = root
        self._cache: dict = {}

    def __call__(self, rel: str) -> Optional[str]:
        if rel not in self._cache:
            self._cache[rel] = self._read(rel)
        return self._cache[rel]

    def _read(self, rel: str) -> Optional[str]:
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            try:
                mode = os.lstat(os.path.join(self.root, *parts[:i])).st_mode
            except (FileNotFoundError, NotADirectoryError):
                return None
            except OSError as e:
                raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None
            if i < len(parts):
                if not stat.S_ISDIR(mode):
                    return None
            elif not stat.S_ISREG(mode):
                return None
        try:
            with open(os.path.join(self.root, *parts), "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None
        return data.decode("utf-8", "surrogateescape")


def _landed(res_fail, record, tracked: frozenset, read) -> None:
    row = record.row
    if "landed_in" not in row:
        return
    rid = record.id if isinstance(record.id, str) else record.file
    entries = row["landed_in"]
    if type(entries) is not list:
        res_fail(rid, "landed_in: must be a list of cites")
        return
    for entry in entries:
        if not isinstance(entry, str):
            res_fail(rid, "%s: is not a string" % _raw(entry))
            continue
        if "#" not in entry:
            continue
        path, anchor = entry.split("#", 1)
        why = cites.problem(cites.Cite(record.file, 0, entry, path, None, None, anchor), tracked, read)
        if why:
            res_fail(rid, "%s: %s" % (entry, why))


def check(args: list) -> Result:
    root = _root(args)
    cfg = config.load(root)
    tracked = gitinfo.tracked_files(root)
    records = Store(root, "decision", cfg).load()
    read = _Reader(root)
    failures: dict = {c: [] for c in _CATEGORIES}
    for doc in sorted(p for p in tracked if p.endswith(".md")):
        text = read(doc)
        if text is None:
            failures["doc"].append(("cites.doc.%s" % doc, "tracked but missing from the working tree"))
            continue
        if any("\udc80" <= ch <= "\udcff" for ch in text):
            failures["doc"].append(("cites.doc.%s" % doc, "not UTF-8"))
            continue
        for cite in cites.extract(doc, text):
            why = cites.problem(cite, tracked, read)
            if why:
                cat = "line" if cite.anchor is None else "anchor"
                failures[cat].append(("cites.%s.%s:%d" % (cat, doc, cite.line), "%s: %s" % (cite.token, why)))
    for record in records:
        _landed(lambda rid, reason: failures["landed"].append(("cites.landed.%s" % rid, reason)),
                record, tracked, read)
    res = Result("cites")
    for cat in _CATEGORIES:
        if failures[cat]:
            for line_id, reason in failures[cat]:
                res.fail(line_id, reason)
        else:
            res.passed("cites." + cat)
    return res


def main(argv: Optional[list] = None) -> int:
    return run_gate("cites", check, argv)


if __name__ == "__main__":
    raise SystemExit(main())
