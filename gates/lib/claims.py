"""Claim rules (spec 7.2, 8; plan Task 2a.2): one claim file per document, row validation, file names and ids,
tracked documents and cites, freshness by blob id (owner Q-B2plan-4 (a)) and the base-branch checks (no-delete
extended to claim files, owner Q-B2plan-5 (a)).

Standard library only. Reasons are returned unescaped: ``Result.render`` escapes them once. Fields are read from
the claim schema (``gates/schemas/claim.yml``). Claims are never executed and carry no expected outcomes (Block 2
controller ruling). A malformed row takes part in nothing (``validate`` reports it), and no function here but
``load``, ``base_errors``, ``stale_errors`` (git and root problems) raises on one.
"""
from __future__ import annotations

import os
import posixpath
import re
import stat
from dataclasses import dataclass
from typing import List, Optional

from gates.lib import gitinfo, ids, migrations, schema, store, yamlsub
from gates.lib.result import GateError, _raw

KIND = "claim"
_SCHEMA_FILE = os.path.join(schema.SCHEMAS_DIR, "claim.yml")
_loaded: List[schema.Schema] = []
_BLOB = re.compile(r"[0-9a-f]{40}")
_LINES = re.compile(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?")
DOC_ERR = "document: must be a .md path with no '--'"
DASH_ERR = "document: no path component may start or end with '-'"
PATH_ERR = "must be a normalised repo-relative path with no '#'"
BLOB_ERR = "must be 40 lowercase hex characters"
LINES_ERR = "must be <n> or <first>-<last>: positive decimals without a leading zero, first <= last"


@dataclass(frozen=True)
class ClaimFile:
    file: str  # repo-relative, "/"-separated
    row: dict


def _schema() -> "schema.Schema":
    if not _loaded:
        _loaded.append(schema.load_schema(_SCHEMA_FILE))
    return _loaded[0]


def slug(document: str) -> str:
    """The path without its last ``.md`` suffix, each ``/`` replaced by ``--`` (owner Q-B2plan-2 (a))."""
    stem = document[:-len(".md")] if document.endswith(".md") else document
    return stem.replace("/", "--")


def _path_ok(p: str) -> bool:
    return schema._path_ok(p) and "#" not in p


def _claims(row: object) -> list:
    """The claim items of ``row`` that are mappings; ``[]`` for a malformed row."""
    items = row.get("claims") if type(row) is dict else None
    return [c for c in items if type(c) is dict] if type(items) is list else []


def _cites(claim: dict) -> list:
    """``(index, cite)`` for the cites of ``claim`` that are mappings."""
    cites = claim.get("cites")
    return [(j, c) for j, c in enumerate(cites) if type(c) is dict] if type(cites) is list else []


def _not_above(a: str, b: str) -> bool:
    """``a <= b`` for decimal digit strings without a leading zero, compared by length then as text, so no
    ``int()`` runs into Python 3.11+'s 4300-digit limit (FD1)."""
    return (len(a), a) <= (len(b), b)


def _text(d: dict, key: str) -> Optional[str]:
    """``d[key]`` when it is an exact non-empty ``str``, else None."""
    v = d.get(key)
    return v if type(v) is str and v != "" else None


# ---------------------------------------------------------------- one row

def validate(row: object, cfg: dict) -> list:
    """Schema errors of a claim row plus the document-path rules (owner Q-2a2-1 (a), Q-2a2r1-1 (a)) and the cite
    ``path``, ``lines`` and ``blob`` forms; ``[]`` when valid."""
    errs = schema.validate(_schema(), row, cfg)
    tag = row.get("schema") if type(row) is dict else None
    if type(tag) is not str or tag != "%s/%d" % (KIND, migrations.current_version(KIND)):
        return errs  # a wrong or missing tag, or a non-mapping: that is the only error to report
    doc = _text(row, "document")
    if doc is not None:
        if not _path_ok(doc):
            errs.append("document: " + PATH_ERR)
        if not doc.endswith(".md") or "--" in doc or posixpath.basename(doc) == ".md":
            errs.append(DOC_ERR)
        if any(c.startswith("-") or c.endswith("-") for c in doc.split("/")):
            errs.append(DASH_ERR)  # owner Q-2a2r1-1 (a): a '-' next to a '/' would make the slug ambiguous
    items = row.get("claims")
    for i, claim in enumerate(items if type(items) is list else []):
        if type(claim) is not dict:
            continue
        for j, cite in _cites(claim):
            where = "claims.%d.cites.%d." % (i, j)
            p = _text(cite, "path")
            if p is not None and not _path_ok(p):
                errs.append(where + "path: " + PATH_ERR)
            lines = _text(cite, "lines")
            if lines is not None:
                m = _LINES.fullmatch(lines)
                if m is None or (m.group(2) is not None and not _not_above(m.group(1), m.group(2))):
                    errs.append(where + "lines: " + LINES_ERR)
            blob = cite.get("blob")
            if type(blob) is str and not _BLOB.fullmatch(blob):
                errs.append(where + "blob: " + BLOB_ERR)
    return errs


# ---------------------------------------------------------------- the claims directory

def _dir_exists(root: str, directory: str) -> bool:
    """True when ``directory`` exists; False when it or a parent is missing. A symlinked or non-directory
    component is a GateError naming it (as ``Store._dir_exists``, owner Q-1a3r-1)."""
    parts = directory.split("/")
    for i in range(1, len(parts) + 1):
        rel = "/".join(parts[:i])
        try:
            mode = os.lstat(os.path.join(root, *parts[:i])).st_mode
        except FileNotFoundError:
            return False
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None
        if stat.S_ISLNK(mode):
            raise GateError("%s: is a symlink; the claims directory must be a real directory" % rel)
        if not stat.S_ISDIR(mode):
            raise GateError("%s: is not a directory" % rel)
    return True


def _is_claim_name(name: str) -> bool:
    return name.endswith(".yml") and not name.startswith(".")


def load(root: str, cfg: dict) -> list:
    """``ClaimFile`` for every ``*.yml`` directly under ``cfg["paths"]["claims"]``, sorted by name. A missing
    directory is empty. Any other entry, a file that does not load, or one whose top level is not a mapping is a
    GateError naming it; a non-regular entry is never opened."""
    gitinfo._require_toplevel(root)
    directory = cfg["paths"]["claims"]
    if not _dir_exists(root, directory):
        return []
    d = os.path.join(root, *directory.split("/"))
    try:
        names = sorted(os.listdir(d))
    except OSError as e:
        raise GateError("%s: cannot read the claims directory (%s)" % (directory, e.strerror or type(e).__name__)) \
            from None
    out = []
    for name in names:
        rel = "%s/%s" % (directory, name)
        path = os.path.join(d, name)
        try:
            mode = os.lstat(path).st_mode
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None
        if not _is_claim_name(name) or not stat.S_ISREG(mode):
            raise GateError("%s: not a regular file named <document slug>.yml" % rel)
        try:
            data = yamlsub.load(path, rel)
        except yamlsub.YamlError as e:
            raise GateError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
        if type(data) is not dict:
            raise GateError("%s: the top level must be a mapping" % rel)
        out.append(ClaimFile(rel, data))
    return out


# ---------------------------------------------------------------- across files

def file_errors(files: list, prefix: str) -> list:
    """``(suffix, reason)`` pairs: ``name.<file>``, ``id.<file>`` and ``duplicate.<id>``."""
    out = []
    files_by_id: dict = {}
    for cf in files:
        row = cf.row if type(cf.row) is dict else {}
        doc = row.get("document")
        stem = posixpath.basename(cf.file)
        stem = stem[:-len(".yml")] if stem.endswith(".yml") else stem
        if type(doc) is str and stem != slug(doc):
            out.append(("name." + cf.file, "file name %s.yml differs from %s.yml, the slug of the document %s"
                        % (stem, slug(doc), doc)))
        bad = []
        for claim in _claims(row):
            if "id" not in claim:
                continue
            problem = ids.id_problem(claim["id"], prefix)
            if problem:
                bad.append("%s: %s" % (_raw(claim["id"]), problem))
            if type(claim["id"]) is str:
                files_by_id.setdefault(claim["id"], []).append(cf.file)
        if bad:
            out.append(("id." + cf.file, "; ".join(bad)))
    for id_ in sorted(files_by_id):
        where = files_by_id[id_]
        if len(where) > 1:
            out.append(("duplicate." + id_, "id %s appears %d times: %s" % (id_, len(where), ", ".join(where))))
    return out


def document_errors(cf: ClaimFile, tracked: frozenset) -> list:
    """Reasons, one per problem: the ``document`` or a cited path that is not a tracked file."""
    out = []
    row = cf.row if type(cf.row) is dict else {}
    doc = row.get("document")
    if type(doc) is str and doc not in tracked:
        out.append("document %s is not a tracked file" % doc)
    for claim in _claims(row):
        for _, cite in _cites(claim):
            p = cite.get("path")
            if type(p) is str and p not in tracked:
                out.append("claim %s: cited path %s is not a tracked file" % (_raw(claim.get("id")), p))
    return out


def _plain_file(root: str, rel: str) -> bool:
    """True when every ancestor of ``rel`` is a real directory and ``rel`` a regular file (``lstat``, no link
    followed): the condition under which ``gitinfo.blob_ids`` stages it."""
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        try:
            mode = os.lstat(os.path.join(root, *parts[:i])).st_mode
        except OSError:
            return False
        if not (stat.S_ISREG(mode) if i == len(parts) else stat.S_ISDIR(mode)):
            return False
    return True


def stale_paths(files: list, root: str) -> list:
    """Every path ``stale_errors`` would look up for ``files``: cited, tracked and a regular file in the working
    tree, in first-seen order, each once. ``gate_claims`` gives it to ``gitinfo.blob_ids`` once per run and passes
    the map to every ``stale_errors`` call (owner Q-2a2r4-1 (a)). The root check is ``tracked_files``'s."""
    tracked = gitinfo.tracked_files(root)
    out: list = []
    for cf in files:
        out += _stale_rows(cf, root, tracked)[1]
    return list(dict.fromkeys(out))


def stale_errors(cf: ClaimFile, root: str, base: Optional[str], *, blob_ids: Optional[dict] = None) -> list:
    """``(id, reason)``, one per claim with a stale cite (owner Q-B2plan-4 (a)): a cite is fresh when its path is
    tracked, is a regular file in the working tree and its ``blob`` equals the id ``git add`` would store for it
    (``gitinfo.blob_ids``, owner Q-2a2r1-2 (a)). With ``blob_ids`` None the ids come from one ``gitinfo.blob_ids``
    call for every such path, so the index is copied once per call. With a map (owner Q-2a2r4-1 (a)) the ids are
    read from it and git is not asked; a path it lacks is a GateError (fail closed, Decision under the owner
    delegation 2026-11-09) and extra keys are ignored. A line cite compares the whole file. ``base`` is not read
    (the plan's signature, kept for Task 2a.3). The root check is ``tracked_files``'s."""
    if blob_ids is not None and type(blob_ids) is not dict:
        raise GateError("stale: blob_ids must be a dict or None")
    tracked = gitinfo.tracked_files(root)
    checks, staged = _stale_rows(cf, root, tracked)
    if blob_ids is None:
        ids = gitinfo.blob_ids(root, staged) if staged else {}
    else:
        for p in staged:
            if p not in blob_ids:
                raise GateError("stale: no blob id for %s in the given map" % p)
        ids = blob_ids
    out = []
    for cid, rows in checks:
        problems = []
        for j, p, blob, problem in rows:
            if problem is None and ids[p] != blob:
                problem = "cites.%d: %s has blob %s; the claim records %s" % (j, p, ids[p], blob)
            if problem is not None:
                problems.append(problem)
        if problems:
            out.append((cid, "; ".join(problems)))
    return out


def _stale_rows(cf: ClaimFile, root: str, tracked: frozenset) -> tuple:
    """``(checks, staged)``: per claim with a ``str`` id, ``(id, [(j, path, blob, problem or None)])``; and the
    paths a ``None`` problem needs an id for, in order (repeats kept; ``blob_ids`` drops them)."""
    checks = []  # (id, [(j, path, blob, problem or None)])
    staged: list = []
    for claim in _claims(cf.row):
        cid = claim.get("id")
        if type(cid) is not str:
            continue
        rows = []
        for j, cite in _cites(claim):
            p, blob = cite.get("path"), cite.get("blob")
            if type(p) is not str or type(blob) is not str:
                continue
            if p not in tracked:
                rows.append((j, p, blob, "cites.%d: %s is absent or untracked" % (j, p)))
            elif not _plain_file(root, p):
                rows.append((j, p, blob, "cites.%d: %s is absent or not a regular file" % (j, p)))
            else:
                rows.append((j, p, blob, None))
                staged.append(p)  # blob_ids drops repeats
        checks.append((cid, rows))
    return checks, staged


# ---------------------------------------------------------------- the base branch

def _rows_at(root: str, ref: str, directory: str, base: str, where: str) -> list:
    """``(file, migrated row)`` for every non-hidden ``*.yml`` directly in ``directory`` at ``ref``; one that does
    not parse or is not a mapping is a GateError naming ``<base>:<file>``."""
    out = []
    for name in sorted(gitinfo.ls_tree(root, ref, directory)):
        if not _is_claim_name(posixpath.basename(name)):
            continue
        shown = "%s:%s%s" % (base, name, where)
        try:
            text = gitinfo.show(root, ref, name)
            if text is None:
                raise GateError("missing")
            data = store._parse(text)
        except GateError as e:
            raise GateError("%s: %s" % (shown, e)) from None
        except yamlsub.YamlError as e:
            raise GateError("%s: %s (line %d)" % (shown, e.reason, e.line)) from None
        if type(data) is not dict:
            raise GateError("%s: the top level must be a mapping" % shown)
        out.append((name, migrations.migrate(KIND, data)))
    return out


def _ids(row: object) -> list:
    return [c["id"] for c in _claims(row) if type(c.get("id")) is str]


def base_errors(root: str, cfg: dict, files: list, base: str) -> list:
    """``(suffix, reason)`` pairs against the base branch: ``deleted.<file>`` and ``removed.<id>`` against the
    merge base with HEAD, ``collision.<id>`` against the tip of ``base``. Rows are migrated first; claim items are
    compared as parsed values. There is no immutability check. The root check is ``merge_base``'s."""
    if type(base) is not str:
        raise GateError("the base ref must be a string")
    directory = cfg["paths"]["claims"]
    mb = gitinfo.merge_base(root, base, "HEAD")
    tracked = gitinfo.tracked_files(root)
    now_files = {cf.file for cf in files}
    now_ids = set()
    for cf in files:
        now_ids.update(_ids(cf.row))
    out = []
    removed = {}
    mb_ids = set()
    for file, row in _rows_at(root, mb, directory, base, " (at the merge base)"):
        mb_ids.update(_ids(row))
        if file in now_files:
            for cid in _ids(row):
                if cid not in now_ids:
                    removed.setdefault(cid, file)
            continue
        doc = row.get("document")
        existed = type(doc) is str and _path_ok(doc) and gitinfo.blob_exists(root, mb, doc)
        if not (existed and doc not in tracked):
            kept = " and its document %s is kept" % doc if type(doc) is str and doc in tracked else ""
            out.append(("deleted." + file, "%s exists on %s%s; claim files are never deleted" % (file, base, kept)))
    for cid in sorted(removed):
        out.append(("removed." + cid, "%s was in %s on %s and is in no claim file now; claim ids are never removed"
                    % (cid, removed[cid], base)))
    tip: dict = {}
    for _, row in _rows_at(root, base, directory, base, ""):
        for claim in _claims(row):
            if type(claim.get("id")) is str:
                tip.setdefault(claim["id"], []).append(claim)
    seen = set()
    for cf in files:
        for claim in _claims(cf.row):
            cid = claim.get("id")
            if type(cid) is not str or cid in mb_ids or cid in seen or cid not in tip:
                continue
            if any(not store._same(claim, other) for other in tip[cid]):
                seen.add(cid)
                out.append(("collision." + cid, "id %s already exists on %s with other content; mint a new id"
                            % (cid, base)))
    return out
