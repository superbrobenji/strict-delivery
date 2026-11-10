"""Decision rules (spec 7.1, 7.4, 11): row validation, ``landed_in`` checks, supersession, in-force and find.

Standard library only. Reasons are returned unescaped: ``Result.render`` escapes them once. Records are
``store.Record`` values (owner Q-1b2-1); a record whose ``id`` or ``row`` is malformed takes part in nothing
(``validate`` reports the row), and no function here raises on one.
"""
from __future__ import annotations

import fnmatch
import os
import re
import stat
from typing import List, Optional

from gates.lib import gitinfo, migrations, print_table, schema
from gates.lib.fold_table import FOLD
from gates.lib.result import GateError, _raw

CLASS_GRANT = "merge-grant"
CLASS_OVERRIDE = "rule-override"
CLASS_MODEL = "model-policy"
# The base playbook's fixed rules (owner F-2), which no `overrides` may name; kept equal to the `fixed: yes` rows
# of playbook/rules.md by tests/test_playbook.py (stream B or A, "Cross-stream order").
FIXED_RULES: tuple = ("SD-R3", "SD-R12", "SD-R18")
# Every base playbook rule id (DB-6; Q-B2plan-8 (a)); tests/test_playbook_drift.py keeps it equal to rules.md.
KNOWN_RULES: tuple = ("SD-R1", "SD-R2", "SD-R3", "SD-R4", "SD-R5", "SD-R6", "SD-R7", "SD-R8", "SD-R9", "SD-R10",
                      "SD-R11", "SD-R12", "SD-R13", "SD-R14", "SD-R15", "SD-R16", "SD-R17", "SD-R18", "SD-R19")
_RULE_ID = re.compile(r"SD-R[1-9][0-9]*")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_SCHEMA_FILE = os.path.join(schema.SCHEMAS_DIR, "decision.yml")
_loaded: List[schema.Schema] = []


def _schema() -> "schema.Schema":
    if not _loaded:
        _loaded.append(schema.load_schema(_SCHEMA_FILE))
    return _loaded[0]


# ---------------------------------------------------------------- one row

def _present_text(row: dict, key: str) -> bool:
    return key in row and type(row[key]) is str


def validate(row: object, cfg: dict) -> list:
    """Schema errors of a decision row plus the class, grant-field, ``overrides``, ``recommended`` and ``source``
    rules; ``[]`` when valid."""
    errs = schema.validate(_schema(), row, cfg)
    tag = row.get("schema") if type(row) is dict else None
    if type(tag) is not str or tag != "decision/%d" % migrations.current_version("decision"):
        return errs  # a wrong or missing tag, or a non-mapping: that is the only error to report
    cls = row.get("class")
    if type(cls) is not str or cls == "":
        return errs  # the schema error already names it
    if cls not in cfg["decision_classes"]["owner_only"]:
        errs.append("class: %s is not in decision_classes.owner_only" % cls)
    if cls == CLASS_GRANT:
        errs.extend(_grant_errors(row))
    else:
        for key in ("plan", "program", "stream"):
            if key in row:
                errs.append("%s: must be absent unless class is %s" % (key, CLASS_GRANT))
    errs.extend(_overrides_errors(row, cls))
    errs.extend(_recommended_errors(row, cls))
    src = row.get("source")
    if type(src) is str and (src == "" or "\n" in src or "\r" in src):
        errs.append("source: must be a non-empty single line")
    return errs


def _overrides_errors(row: dict, cls: str) -> list:
    """Spec 7.1: only class ``rule-override`` carries ``overrides``, of the form ``SD-R<n>``, naming a known rule
    that is not fixed. The value rules run on an exact non-empty ``str`` only; the schema names any other value."""
    if "overrides" not in row:
        return []
    errs: list = []
    if cls != CLASS_OVERRIDE:
        errs.append("overrides: only class %s carries it" % CLASS_OVERRIDE)
    v = row["overrides"]
    if type(v) is not str or v == "":
        return errs
    if not _RULE_ID.fullmatch(v):
        errs.append("overrides: %s does not match SD-R[1-9][0-9]*" % v)
    elif v in FIXED_RULES:
        errs.append("overrides: %s is a fixed rule and cannot be overridden" % v)
    elif v not in KNOWN_RULES:
        errs.append("overrides: %s is not a base playbook rule" % v)
    return errs


def _recommended_errors(row: dict, cls: str) -> list:
    """Session-resume design 3.6: ``recommended`` is the label of exactly one option (exact ``str`` equality), and
    class ``model-policy`` carries none (L:415)."""
    if "recommended" not in row:
        return []
    errs: list = []
    if cls == CLASS_MODEL:
        errs.append("recommended: class %s carries no recommended option" % CLASS_MODEL)
    v = row["recommended"]
    if type(v) is str:
        opts = row.get("options")
        hits = 0
        if type(opts) is list:
            hits = sum(1 for o in opts if type(o) is dict and type(o.get("label")) is str and o["label"] == v)
        if hits != 1:
            errs.append("recommended: %s is not the label of exactly one option" % v)
    return errs


def _grant_errors(row: dict) -> list:
    errs: list = []
    plan = row.get("plan")
    if type(plan) is str and ("/" in plan or any(c.isspace() for c in plan)):
        errs.append("plan: must not contain '/' or whitespace")
    for key, other in (("program", "stream"), ("stream", "program")):
        if key in row and other not in row:
            errs.append("%s: %s must be given too; program and stream come together or not at all" % (key, other))
        v = row.get(key)
        if type(v) is str and v != "" and not _NAME.fullmatch(v):
            errs.append("%s: must match [a-z0-9][a-z0-9-]*" % key)
    if row.get("stream") == "integration":
        errs.append("stream: 'integration' is reserved and cannot name a stream")
    return errs


def is_resolved(row: object) -> bool:
    return type(row) is not dict or row.get("status") != "open"


# ---------------------------------------------------------------- landed_in

def _token(id_: str) -> "re.Pattern":
    return re.compile(r"(?<![0-9A-Za-z_-])" + re.escape(id_) + r"(?![0-9A-Za-z_-])")


def _regular_file_text(root: str, rel: str) -> str:
    """The text of the regular file ``rel`` under ``root``; every parent is a real directory (no symlink).
    Raises OSError or UnicodeDecodeError, which the caller reports."""
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
        return fh.read().decode("utf-8")


def _cite_problem(cite: object) -> str:
    if type(cite) is not str:
        return "is not a string"
    path, sep, anchor = cite.partition("#")
    if not schema._path_ok(path) or (sep and (anchor == "" or "#" in anchor or not print_table.is_printable(anchor))):
        return "is not a normalised repo-relative path with an optional non-empty #anchor"
    return ""


def landed_errors(row: object, root: str, cfg: dict, tracked: frozenset) -> list:
    """One error per bad ``landed_in`` cite; ``[]`` when the row has none (presence is ``validate``'s).
    ``root`` must be the git top level (owner Q-1a-fin-1): ``tracked`` holds repo paths and the cites are read under it."""
    gitinfo._require_toplevel(root)
    if type(row) is not dict or "landed_in" not in row:
        return []
    cites = row["landed_in"]
    if type(cites) is not list:
        return ["landed_in: must be a list of cites"]
    paths = cfg["paths"]
    playbooks, architecture, specs = paths["playbooks"], paths["architecture"], paths["specs"]
    rid = row.get("id")
    pat = _token(rid) if type(rid) is str and rid != "" else None
    errs: list = []
    for cite in cites:
        problem = _cite_problem(cite)
        if problem:
            errs.append("landed_in: %s %s" % (_raw(cite), problem))
            continue
        path = cite.partition("#")[0]
        if path == specs or path.startswith(specs + "/"):
            errs.append("landed_in: %s is a spec; specs are cleaned, land the rule in a playbook, CLAUDE.md or "
                        "architecture.md" % path)
        elif not (path == "CLAUDE.md" or path == architecture or path.startswith(playbooks + "/")):
            errs.append("landed_in: %s is not a playbook, CLAUDE.md or architecture.md" % path)
        elif path not in tracked:
            errs.append("landed_in: %s is not a tracked regular file" % path)
        elif pat is None:
            errs.append("landed_in: %s cannot be checked: the row has no valid id to find in it" % path)
        else:
            try:
                text = _regular_file_text(root, path)
            except (OSError, UnicodeDecodeError) as e:
                why = "not valid UTF-8" if isinstance(e, UnicodeDecodeError) else (e.strerror or str(e))
                errs.append("landed_in: %s cannot be read as a UTF-8 regular file (%s)" % (path, why))
                continue
            if pat.search(text) is None:
                errs.append("landed_in: %s does not contain the decision id %s" % (path, rid))
    return errs


# ---------------------------------------------------------------- supersession

def _row(rec: object) -> dict:
    row = getattr(rec, "row", None)
    return row if type(row) is dict else {}


def _rid(rec: object) -> Optional[str]:
    i = getattr(rec, "id", None)
    return i if type(i) is str and i != "" else None


def _target(rec: object) -> Optional[str]:
    t = _row(rec).get("supersedes")
    return t if type(t) is str and t != "" else None


def _status(rec: object) -> object:
    return _row(rec).get("status")


def _by_id(records: list) -> dict:
    out: dict = {}
    for r in records:
        i = _rid(r)
        if i is not None and i not in out:
            out[i] = r
    return out


def _answered_superseders(records: list) -> dict:
    """target id -> ids of answered records that supersede it (a row never supersedes itself)."""
    out: dict = {}
    for r in records:
        i, t = _rid(r), _target(r)
        if i is not None and t is not None and t != i and _status(r) == "answered":
            if i not in out.setdefault(t, []):
                out[t].append(i)
    return out


def superseded_ids(records: list) -> set:
    return set(_answered_superseders(records))


def current(records: list, id: str) -> str:
    """The newest id reached from ``id`` through answered superseders; an unknown id comes back unchanged, a cycle
    stops at its first repeat, and two answered superseders of one id raise GateError."""
    sup = _answered_superseders(records)
    seen = [id]
    cur = id
    while True:
        nxt = sup.get(cur, [])
        if not nxt:
            return cur
        if len(nxt) > 1:
            raise GateError("%s is superseded by more than one answered decision (%s); fork.%s"
                            % (cur, ", ".join(nxt), cur))
        if nxt[0] in seen:
            return cur
        seen.append(nxt[0])
        cur = nxt[0]


def _cycles(by_id: dict, start: str, first: str) -> bool:
    """True when following ``supersedes`` from ``first`` leads back to ``start``."""
    seen = {start}
    node = first
    while node in by_id and node not in seen:
        seen.add(node)
        node = _target(by_id[node])
        if node == start:
            return True
        if node is None:
            return False
    return False


def ref_errors(records: list) -> list:
    """``(suffix, reason)`` per failing reference: ``supersedes.<row id>``, ``checked.<row id>`` (the row that
    carries the field, owner Q-1b2-2) and ``fork.<target id>``."""
    by_id = _by_id(records)
    out: list = []
    for r in records:
        i = _rid(r)
        if i is None:
            continue
        t = _target(r)
        if t is not None:
            probs: list = []
            if t == i:
                probs.append("a decision cannot supersede itself")
            elif t not in by_id:
                probs.append("%s has no record" % t)
            else:
                # a withdrawn superseder is exempt from the status of its target (owner Q-1b2-3)
                if _status(r) != "withdrawn" and _status(by_id[t]) != "answered":
                    probs.append("%s is not answered" % t)
                if _cycles(by_id, i, t):
                    probs.append("%s leads back to %s: a supersedes cycle" % (t, i))
            if probs:
                out.append(("supersedes." + i, "supersedes: " + "; ".join(probs)))
        checked = _row(r).get("checked_against")
        if type(checked) is list:
            unknown = [c for c in checked if type(c) is str and c not in by_id]
            if unknown:
                out.append(("checked." + i, "checked_against: no record for %s" % ", ".join(unknown)))
    live: dict = {}
    for r in records:
        i, t = _rid(r), _target(r)
        if i is not None and t is not None and t != i and _status(r) in ("open", "answered"):
            if i not in live.setdefault(t, []):
                live[t].append(i)
    for t, who in live.items():
        if len(who) > 1:
            out.append(("fork." + t, "%s is superseded by more than one open or answered decision (%s)"
                        % (t, ", ".join(who))))
    return out


# ---------------------------------------------------------------- in force and find

def in_force(records: list) -> list:
    gone = superseded_ids(records)
    out = []
    for r in records:
        row = _row(r)
        if row.get("status") == "answered" and row.get("effect") == "lasting" and row.get("class") != CLASS_GRANT \
                and _rid(r) not in gone:
            out.append(r)
    return out


def _fold(s: str) -> str:
    """``s`` case folded through the frozen Unicode 13.0.0 table, as ``str.casefold`` does on 3.9.6 (spec 14, owner
    decision U1 (a)). The characters decide, never a ``str`` subclass's own methods; anything else is a TypeError."""
    if not issubclass(type(s), str):
        raise TypeError("_fold() argument must be str, not %s" % type(s).__name__)
    return "".join(FOLD.get(ord(c), c) for c in str.__iter__(s))


def _texts(row: dict) -> list:
    topics = row.get("topics")
    parts = [row.get("question"), row.get("answer")] + (topics if type(topics) is list else [])
    return [_fold(p) for p in parts if type(p) is str]


def _matches(row: dict, terms: list, path: Optional[str], topic: Optional[str]) -> bool:
    texts = _texts(row)
    if not all(any(_fold(t) in x for x in texts) for t in terms):
        return False
    if path is not None:
        globs = row.get("applies_to")
        if type(globs) is not list:
            return False
        for i, g in enumerate(globs):  # F-1, U-2 folded into F-1 (D-31): no glob outside the grammar is compiled
            if type(g) is str and schema.bracket_problem(g):
                raise GateError("%s: applies_to.%d: %s" % (row.get("id"), i, schema.bracket_problem(g)))
        if not any(type(g) is str and fnmatch.fnmatchcase(path, g) for g in globs):
            return False
    if topic is not None:
        topics = row.get("topics")
        if type(topics) is not list or not any(type(x) is str and _fold(x) == _fold(topic) for x in topics):
            return False
    return True


def find(records: list, terms: list, path: Optional[str], topic: Optional[str], include_all: bool) -> list:
    """Records matching every term (case-insensitive over question, answer and topics), the ``path`` glob and the
    ``topic``. With ``include_all`` every match is returned as itself. Otherwise every match, whatever its status,
    effect or class, is replaced by its ``current`` (owner Q-1b2r-1), and only decisions in force are returned, once
    each, in order of first appearance."""
    if include_all:
        return [r for r in records if _matches(_row(r), terms, path, topic)]
    by_id = _by_id(records)
    force = {id(r) for r in in_force(records)}
    out: list = []
    for r in records:
        row = _row(r)
        if not _matches(row, terms, path, topic):
            continue
        i = _rid(r)
        hit = by_id[current(records, i)] if i is not None else r
        if id(hit) in force and all(hit is not o for o in out):
            out.append(hit)
    return out
