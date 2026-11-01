"""Finding rules (spec 5, 7.2, 13a): row validation, status transitions, evidence, epics, resolution and delete.

Standard library only. Reasons are returned unescaped: ``Result.render`` escapes them once. Records are
``store.Record`` values (owner Q-1b2-1); a record whose ``id`` or ``row`` is malformed takes part in nothing
(``validate`` reports the row), and no function here raises on one. A ``GateError`` from git (a root that is not
the top level of a repository) propagates: it is an input failure, not a bad row.
"""
from __future__ import annotations

import os
from typing import List

from gates.lib import decisions, gitinfo, schema

STATUSES = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed", "merged"]
RESOLVED = {"closed", "merged"}
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
TRANSITIONS = {
    "open": ["planned", "deferred", "closed"],
    "planned": ["in-progress", "open", "deferred"],
    "in-progress": ["fixed-unpinned", "pinned", "planned"],
    "fixed-unpinned": ["pinned"],
    "pinned": ["closed", "merged"],
    "deferred": ["open", "planned"],
    "closed": ["merged"],
    "merged": [],
}

_MERGED = "merged is set only by the cleanup step"
_SCHEMA_FILE = os.path.join(schema.SCHEMAS_DIR, "finding.yml")
_loaded: List[schema.Schema] = []


def _schema() -> "schema.Schema":
    if not _loaded:
        _loaded.append(schema.load_schema(_SCHEMA_FILE))
    return _loaded[0]


def _bad_name(v: object) -> bool:
    return type(v) is str and ("/" in v or any(c.isspace() for c in v))


# ---------------------------------------------------------------- one row

def validate(row: object, cfg: dict) -> list:
    """Schema errors of a finding row plus the plan-name and ``merged`` rules; ``[]`` when valid."""
    errs = schema.validate(_schema(), row, cfg)
    if type(row) is not dict or row.get("schema") != "finding/1":
        return errs  # a wrong or missing tag, or a non-mapping: that is the only error to report
    if row.get("status") == "merged":
        errs.append("status: " + _MERGED)
    history = row.get("history")
    if type(history) is list:
        for i, entry in enumerate(history):
            if type(entry) is dict and entry.get("status") == "merged":
                errs.append("history.%d.status: %s" % (i, _MERGED))
    owner = row.get("owner")
    if type(owner) is dict and _bad_name(owner.get("plan")):
        errs.append("owner.plan: must not contain '/' or whitespace")
    if _bad_name(row.get("resolved_by")):
        errs.append("resolved_by: must not contain '/' or whitespace")
    return errs


def is_resolved(row: object) -> bool:
    if type(row) is not dict:
        return False
    status = row.get("status")
    return type(status) is str and status in RESOLVED


# ---------------------------------------------------------------- transitions

def transition_errors(row: object) -> list:
    """History starts at ``open``, every step is in ``TRANSITIONS`` and the last entry equals ``status``."""
    history = row.get("history") if type(row) is dict else None
    if type(history) is not list or not history:
        return ["history: must be a non-empty list"]
    seq: list = []
    for i, entry in enumerate(history):
        s = entry.get("status") if type(entry) is dict else None
        if type(s) is not str:
            return ["history.%d.status: must be a status string" % i]
        seq.append(s)
    errs: list = []
    if seq[0] != "open":
        errs.append("history.0.status: the first entry must be open, got %s" % seq[0])
    for i in range(1, len(seq)):
        a, b = seq[i - 1], seq[i]
        if b not in TRANSITIONS.get(a, []):
            errs.append("history.%d.status: %s -> %s is not a legal transition" % (i, a, b))
    if row.get("status") != seq[-1]:
        errs.append("status: %s differs from the last history entry (%s)" % (row.get("status"), seq[-1]))
    return errs


# ---------------------------------------------------------------- evidence

def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory + "/")


def _split(entry: str) -> tuple:
    """``("sha", "")`` for a bare commit sha, ``("sha-path", path)`` for ``<sha>:<path>``, else ``("path", entry)``."""
    head, sep, tail = entry.partition(":")
    if sep and schema._SHA.fullmatch(head):
        return "sha-path", tail
    if not sep and schema._SHA.fullmatch(entry):
        return "sha", ""
    return "path", entry


def _path_shape_ok(p: str) -> bool:
    return "#" not in p and schema._path_ok(p)


def _answered(rec: object, cfg: dict) -> bool:
    """A decision record with ``status: answered`` that passes ``decisions.validate``; a superseded one counts
    (owner Q-1b3-1). ``decisions.is_resolved`` is true for withdrawn rows too, so it is not used."""
    row = decisions._row(rec)
    return row.get("status") == "answered" and decisions.validate(row, cfg) == []


def _transcript_errors(row: dict, root: str, cfg: dict) -> list:
    pin = row.get("pin")
    if type(pin) is not dict or "transcript" not in pin:
        return []
    t = pin["transcript"]
    kind, path = _split(t) if type(t) is str else ("path", "")
    if kind != "sha-path" or not _path_shape_ok(path):
        return ["pin.transcript: must be <sha>:<normalised repo-relative path>"]
    sha = t.partition(":")[0]
    if not gitinfo.commit_exists(root, sha):
        return ["pin.transcript: %s is not a commit" % sha]
    if not gitinfo.blob_exists(root, sha, path):
        return ["pin.transcript: %s is not a regular file at %s" % (path, sha)]
    base = cfg["paths"]["plan_state"]
    owner = row.get("owner")
    kind_ = owner.get("kind") if type(owner) is dict else None
    plan = owner.get("plan") if type(owner) is dict else None
    parts = path.split("/")
    if kind_ == "plan" and type(plan) is str and plan != "" and not _bad_name(plan):
        want = base + "/" + plan + "/mutations/"
        if not path.startswith(want):
            return ["pin.transcript: %s must be under %s" % (path, want)]
    elif kind_ in ("issue", "roadmap"):
        b = base.split("/")
        if not (len(parts) > len(b) + 2 and parts[:len(b)] == b and parts[len(b) + 1] == "mutations"):
            return ["pin.transcript: %s must be under %s/<plan>/mutations/" % (path, base)]
    else:
        return ["pin.transcript: cannot be located: owner has no usable kind or plan"]
    return []


def _entry_errors(i: int, entry: str, root: str, cfg: dict, tracked: frozenset, check_tracked: bool) -> list:
    where = "evidence.%d" % i
    kind, path = _split(entry)
    if kind == "sha":
        if not gitinfo.commit_exists(root, entry):
            return ["%s: %s is not a commit" % (where, entry)]
        return []
    if kind == "sha-path":
        sha = entry.partition(":")[0]
        if not _path_shape_ok(path):
            return ["%s: %s is not a normalised repo-relative path" % (where, path)]
        if not gitinfo.commit_exists(root, sha):
            return ["%s: %s is not a commit" % (where, sha)]
        if not gitinfo.blob_exists(root, sha, path):
            return ["%s: %s is not a regular file at %s" % (where, path, sha)]
        return []
    if not _path_shape_ok(path):
        return ["%s: %s is not a commit sha, <sha>:<path> or a normalised repo-relative path" % (where, entry)]
    paths = cfg["paths"]
    if _under(path, paths["findings"]):
        return ["%s: %s is a finding record; cite it as <sha>:<path>" % (where, path)]
    for key in ("specs", "plans", "plan_state", "reviews", "programs", "claims"):
        if _under(path, paths[key]):
            return ["%s: %s is under %s, which is cleaned; cite it as <sha>:<path>" % (where, path, paths[key])]
    if check_tracked and path not in tracked:
        return ["%s: %s is not a tracked regular file" % (where, path)]
    return []


def evidence_errors(row: object, root: str, cfg: dict, decision_records: list, tracked: frozenset,
                    changed: bool = True) -> list:
    """Status-dependent needs and the form of every evidence entry and of ``pin.transcript``.

    ``changed`` is true when the row differs from its merge-base version or is new (the caller knows; the default
    fails closed). A plain-path entry of a resolved row is checked for existence in ``tracked`` only when
    ``changed`` (owner Q-1b3-3): renaming a cited file must not turn an immutable row red. Sha-pinned entries and
    the shape and location rules are checked always."""
    if type(row) is not dict:
        return []
    errs: list = []
    status = row.get("status")
    evidence = row.get("evidence")
    entries = evidence if type(evidence) is list else []
    check_tracked = changed or not is_resolved(row)
    for i, entry in enumerate(entries):
        if type(entry) is str and entry != "":
            errs.extend(_entry_errors(i, entry, root, cfg, tracked, check_tracked))
    if status == "closed" and not [e for e in entries if type(e) is str and e != ""]:
        errs.append("evidence: a closed finding needs at least one entry")
    pin = row.get("pin")
    if status == "pinned":
        if pin is None:
            errs.append("pin: a pinned finding needs a pin")
        reviews = cfg["paths"]["reviews"]
        if not any(type(e) is str and _split(e)[0] == "sha-path" and _under(_split(e)[1], reviews) for e in entries):
            errs.append("evidence: a pinned finding needs a review report cited as <sha>:%s/<plan>/<file>"
                        % reviews)
    if pin is not None:
        errs.extend(_transcript_errors(row, root, cfg))
    ruling = row.get("ruling")
    by_id = decisions._by_id(decision_records)
    if status == "deferred" and ruling is None:
        errs.append("ruling: a deferred finding needs a ruling naming an answered decision")
    elif type(ruling) is str:
        rec = by_id.get(ruling)
        if rec is None:
            errs.append("ruling: no decision record for %s" % ruling)
        elif status == "deferred" and (not _answered(rec, cfg)
                                       or decisions._row(rec).get("class") == decisions.CLASS_GRANT):
            errs.append("ruling: %s is not an answered, valid decision of a class other than merge-grant" % ruling)
    return errs


# ---------------------------------------------------------------- epics

def _parent(rec: object) -> object:
    p = decisions._row(rec).get("parent")
    return p if type(p) is str and p != "" else None


def epic_errors(records: list) -> list:
    """``(suffix, reason)`` per failing row, named after the row carrying ``parent`` (owner Q-1b2-2 pattern):
    ``parent.<id>`` (the parent is the row itself, has no record, or leads back to the row) and ``epic.<id>`` (a
    resolved parent with an unresolved child). A resolved row is not checked for a missing parent (owner
    Q-1b3-2): it is immutable, so the error would have no legal fix."""
    by_id = decisions._by_id(records)
    out: list = []
    for r in records:
        i = decisions._rid(r)
        p = _parent(r)
        if i is None or p is None:
            continue
        row = decisions._row(r)
        resolved = is_resolved(row)
        if p == i:
            out.append(("parent." + i, "parent: a finding cannot be its own parent"))
            continue
        if p not in by_id:
            if not resolved:
                out.append(("parent." + i, "parent: %s has no record" % p))
            continue
        seen: set = set()
        node = p
        while node in by_id and node not in seen:
            seen.add(node)
            node = _parent(by_id[node])
            if node == i:
                out.append(("parent." + i, "parent: %s leads back to %s: a parent cycle" % (p, i)))
                break
            if node is None:
                break
        if is_resolved(decisions._row(by_id[p])) and not resolved:
            out.append(("epic." + i, "parent: %s is resolved but this finding is not" % p))
    return out


# ---------------------------------------------------------------- delete

def may_delete(row: object, root: str, cfg: dict, decision_records: list) -> bool:
    """True only when the row is resolved and an answered ``merge-grant`` decision names the plan in its
    ``resolved_by`` (OQ-5). ``root`` is for the merge-commit check that arrives with ``gate_cleanup``."""
    if not is_resolved(row):
        return False
    plan = row.get("resolved_by")
    if type(plan) is not str or plan == "":
        return False
    for rec in decision_records:
        d = decisions._row(rec)
        if d.get("class") == decisions.CLASS_GRANT and d.get("plan") == plan and _answered(rec, cfg):
            return True
    return False
