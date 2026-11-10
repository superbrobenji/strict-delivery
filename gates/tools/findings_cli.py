"""Tool ``findings``: ``new`` and ``move`` write finding records (spec 7.2, 7.3, 13a; owner OQ-6, OQ-15).

Standard library only. ``python3 -m gates findings <sub>``. An argument error exits 2 with the usage on stderr; a
refusal exits 1 with one stderr line ``findings <sub>: <reason>`` and writes nothing. Every check runs before the
write; the indexes are regenerated after it (block 1d decisions D-1..D-10, D-19..D-21). Free text is restricted
to one line of U+0020-U+007E before any other check reads it (owner Q-B2FX2-1 (a)), so no Unicode-data predicate
and no ``int()`` runs on argv text first, and the record bytes are the same on every interpreter.
"""
from __future__ import annotations

import copy
import random
import re
import sys
from typing import Optional

from gates.lib import config, findings, gitinfo, ids, schema
from gates.lib.result import GateError, _GateParser, _Once, safe_text
from gates.lib.store import Record, Store
from gates.tools import index

PRODUCES = ("finding",)

_rng = random.SystemRandom()  # patched in tests to force an id collision (D-6)

_OWNER_KINDS = ("plan", "issue", "roadmap")
_NUMBER = re.compile(r"[1-9][0-9]{0,999}")  # D-19: at most yamlsub.MAX_INT_CHARS digits, ASCII only
_LINES = re.compile(r"([1-9][0-9]{0,8})(?:-([1-9][0-9]{0,8}))?")  # D-19
_PLAN = re.compile(r"[a-z0-9][a-z0-9._-]*")  # D-4


class _Refusal(Exception):
    """A content refusal: exit 1, nothing written."""


def _text(flag: str, v: str) -> None:
    """D-3: non-empty, one line of U+0020-U+007E, no leading or trailing space."""
    if v == "":
        raise _Refusal("%s: must not be empty" % flag)
    for c in v:
        if not 0x20 <= ord(c) <= 0x7E:
            raise _Refusal("%s: U+%04X is not allowed (only U+0020-U+007E)" % (flag, ord(c)))
    if v[0] == " " or v[-1] == " ":
        raise _Refusal("%s: must not start or end with a space" % flag)


def _token(flag: str, v: str) -> None:
    """Ids, cites and evidence: non-empty, U+0021-U+007E only (D-4's range)."""
    if v == "":
        raise _Refusal("%s: must not be empty" % flag)
    for c in v:
        if not 0x21 <= ord(c) <= 0x7E:
            raise _Refusal("%s: U+%04X is not allowed (only U+0021-U+007E)" % (flag, ord(c)))


def _no_dups(flag: str, values: list) -> None:
    seen: list = []
    for v in values:
        if v in seen:
            raise _Refusal("%s: %s given more than once" % (flag, v))
        seen.append(v)


def _no_dup_referents(flag: str, values: list, keys: list, first: int = 0) -> None:
    """D-32: ``values[i]`` for ``i >= first`` whose referent key equals an earlier one is a duplicate."""
    for i in range(first, len(values)):
        if keys[i] in keys[:i]:
            raise _Refusal("%s: %s given more than once" % (flag, values[i]))


def _commit(root: str, sha: str) -> str:
    """The full sha of the commit ``sha`` names; ``sha`` has passed ``gitinfo.commit_exists``."""
    return gitinfo.merge_base(root, sha, sha)


def _evidence_key(root: str, e: object) -> object:
    """D-32: a sha or ``<sha>:<path>`` entry naming a commit is keyed by its form, that commit's full sha and its
    path; any other entry (a non-commit, a non-string stored by hand) by itself. A plain path is its own ``path``
    (``findings._split``), so its key holds its whole text and two spellings never collide."""
    if type(e) is not str:
        return ("text", e)
    kind, path = findings._split(e)
    sha = e.partition(":")[0]
    if gitinfo.commit_exists(root, sha):
        return (kind, _commit(root, sha), path)
    return ("text", e)


def _cite(n: int, v: str, root: str) -> dict:
    where = "--cite %d" % n
    _token(where, v)
    at = v.rfind("@")
    colon = v.rfind(":", 0, at) if at >= 0 else -1
    if colon < 0:
        raise _Refusal("%s: expected FILE:LINES@SHA" % where)
    file, lines, sha = v[:colon], v[colon + 1:at], v[at + 1:]
    if not schema._path_ok(file):
        raise _Refusal("%s: FILE must be a normalised repo-relative path" % where)
    m = _LINES.fullmatch(lines)
    if m is None:
        raise _Refusal("%s: LINES must be N or N-M (1 to 9 digits each)" % where)
    if m.group(2) is not None and int(m.group(1)) > int(m.group(2)):
        raise _Refusal("%s: LINES start is after its end" % where)
    if not schema._SHA.fullmatch(sha) or not gitinfo.commit_exists(root, sha):
        raise _Refusal("%s: %s is not a commit (7-40 lowercase hex)" % (where, sha))
    return {"file": file, "lines": lines, "sha": sha}


def _new_epic(before: list, after: list) -> list:
    """The epic errors the change introduces (D-20, D-21): errors present only after it."""
    old = findings.epic_errors(before)
    return [reason for suffix, reason in findings.epic_errors(after) if (suffix, reason) not in old]


def _check(row: dict, root: str, cfg: dict, decs: list, before: list, after: list) -> None:
    errs = findings.validate(row, cfg)
    errs = errs or findings.transition_errors(row)
    errs = errs or findings.evidence_errors(row, root, cfg, decs, gitinfo.tracked_files(root), True)
    errs = errs or _new_epic(before, after)
    if errs:
        raise _Refusal(errs[0])


def _load(root: str, cfg: dict) -> tuple:
    fstore = Store(root, "finding", cfg)
    return fstore, fstore.load(), Store(root, "decision", cfg).load()


def _new(ns) -> tuple:
    root = index._root(ns.root)
    cfg = config.load(root)
    for flag, v in (("--source", ns.source), ("--class", ns.class_), ("--by", ns.by)):
        _text(flag, v)
    if ns.severity not in findings.SEVERITIES:
        raise _Refusal("--severity: must be one of %s" % ", ".join(findings.SEVERITIES))
    if ns.owner_kind not in _OWNER_KINDS:
        raise _Refusal("--owner-kind: must be one of %s" % ", ".join(_OWNER_KINDS))
    owner: dict = {"kind": ns.owner_kind}
    if ns.plan is not None:
        if not _PLAN.fullmatch(ns.plan):
            raise _Refusal("--plan: must match [a-z0-9][a-z0-9._-]*")
        owner["plan"] = ns.plan
    if ns.task is not None:
        _text("--task", ns.task)
        owner["task"] = ns.task
    if ns.number is not None:
        if not _NUMBER.fullmatch(ns.number):
            raise _Refusal("--number: must be a positive decimal integer of at most 1000 ASCII digits")
        owner["number"] = int(ns.number)
    if ns.parent is not None:
        _token("--parent", ns.parent)
    cite_args = ns.cite or []
    _no_dups("--cite", cite_args)
    cites = [_cite(n, v, root) for n, v in enumerate(cite_args, 1)]
    keys = [(c["file"], c["lines"].partition("-")[0], c["lines"].rpartition("-")[2], _commit(root, c["sha"]))
            for c in cites]  # D-32: N is N-N; LINES has no leading zero (D-19), so text equality is number equality
    _no_dup_referents("--cite", cite_args, keys)
    head = gitinfo.head_sha(root)
    fstore, frecs, decs = _load(root, cfg)
    index.render(root, cfg)  # D-7: a register the index refuses is refused before any write
    new_id = ids.mint(cfg["ids"]["finding"], {r.id for r in frecs + decs}, ids.utc_today(), _rng)
    row = {"schema": "finding/%d" % findings._schema().version, "id": new_id, "status": "open",
           "source": ns.source, "severity": ns.severity, "class": ns.class_, "siblings": [], "cites": cites,
           "repro": None, "owner": owner, "pin": None, "ruling": None, "evidence": [],
           "history": [{"status": "open", "sha": head, "by": ns.by}]}
    if ns.parent is not None:
        row["parent"] = ns.parent
    new = Record(new_id, row, fstore.path_for(new_id))
    _check(row, root, cfg, decs, frecs, frecs + [new])
    fstore.create(row)
    return root, cfg, new_id


def _move(ns) -> tuple:
    root = index._root(ns.root)
    cfg = config.load(root)
    _text("--by", ns.by)
    if ns.to not in findings.STATUSES:
        raise _Refusal("--to: must be one of %s" % ", ".join(findings.STATUSES))
    if ns.to == "merged":
        raise _Refusal("--to merged: merged is set only by the cleanup step")
    evidence = ns.evidence or []
    for n, e in enumerate(evidence, 1):
        _token("--evidence %d" % n, e)
    for flag, v in (("--ruling", ns.ruling), ("--pin-transcript", ns.pin_transcript)):
        if v is not None:
            _token(flag, v)
    for flag, v in (("--pin-test", ns.pin_test), ("--resolved-by", ns.resolved_by)):
        if v is not None:
            _text(flag, v)
    _token("ID", ns.id)
    fstore, frecs, decs = _load(root, cfg)
    fstore.path_for(ns.id)  # a malformed id is a GateError naming the form
    found = [r for r in frecs if r.id == ns.id]
    if not found:
        raise _Refusal("no finding %s" % ns.id)
    old = found[0].row
    status = old.get("status")
    if findings.is_resolved(old):
        raise _Refusal("%s is %s: a resolved finding is never changed" % (ns.id, safe_text(status)))
    if ns.to not in (findings.TRANSITIONS.get(status, []) if type(status) is str else []):
        raise _Refusal("%s -> %s is not a legal transition" % (safe_text(status), ns.to))
    if (ns.pin_test is None) != (ns.pin_transcript is None):
        raise _Refusal("--pin-test and --pin-transcript go together")
    if ns.pin_test is not None and ns.to != "pinned":
        raise _Refusal("--pin-test and --pin-transcript are given only with --to pinned")
    if ns.ruling is not None and ns.to != "deferred":
        raise _Refusal("--ruling is given only with --to deferred")
    if ns.to in findings.RESOLVED and ns.resolved_by is None:
        raise _Refusal("--resolved-by: required with --to %s" % ns.to)
    if ns.to not in findings.RESOLVED and ns.resolved_by is not None:
        raise _Refusal("--resolved-by is given only with --to closed")
    stored = old.get("evidence") if type(old.get("evidence")) is list else []
    _no_dups("--evidence", stored + evidence)
    _no_dup_referents("--evidence", stored + evidence, [_evidence_key(root, e) for e in stored + evidence],
                      len(stored))
    head = gitinfo.head_sha(root)
    index.render(root, cfg)  # D-7
    row = copy.deepcopy(old)
    row["status"] = ns.to
    row["history"] = list(row.get("history", [])) + [{"status": ns.to, "sha": head, "by": ns.by}]
    row["evidence"] = stored + evidence
    if ns.pin_test is not None:
        row["pin"] = {"test": ns.pin_test, "transcript": ns.pin_transcript}
    if ns.ruling is not None:
        row["ruling"] = ns.ruling
    if ns.resolved_by is not None:
        row["resolved_by"] = ns.resolved_by
    after = [Record(r.id, row, r.file) if r is found[0] else r for r in frecs]
    _check(row, root, cfg, decs, frecs, after)
    fstore.replace(row)
    return root, cfg, ns.id


def _parser() -> _GateParser:
    p = _GateParser(prog="findings", add_help=True)
    subs = p.add_subparsers(dest="sub", metavar="{new,move}")
    subs.required = True
    n = subs.add_parser("new", prog="findings new")
    for flag in ("--source", "--severity", "--owner-kind", "--by"):
        n.add_argument(flag, required=True, default=None, action=_Once)
    n.add_argument("--class", dest="class_", required=True, default=None, action=_Once)
    for flag in ("--plan", "--task", "--number", "--parent", "--root"):
        n.add_argument(flag, default=None, action=_Once)
    n.add_argument("--cite", action="append", default=None)
    m = subs.add_parser("move", prog="findings move")
    m.add_argument("id")
    for flag in ("--to", "--by"):
        m.add_argument(flag, required=True, default=None, action=_Once)
    for flag in ("--ruling", "--pin-test", "--pin-transcript", "--resolved-by", "--root"):
        m.add_argument(flag, default=None, action=_Once)
    m.add_argument("--evidence", action="append", default=None)
    return p


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates findings new|move ...``: print the record id; 2 on a usage error, 1 on a refusal."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        ns = _parser().parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    prog = "findings " + ns.sub
    try:
        root, cfg, rid = (_new if ns.sub == "new" else _move)(ns)
    except (_Refusal, GateError) as e:
        sys.stderr.write("%s: %s\n" % (prog, safe_text(e)))
        return 1
    sys.stdout.write(rid + "\n")
    try:
        index.regenerate(root, cfg)
    except GateError as e:  # D-7: the record stays; the caller has its id
        sys.stderr.write("%s: %s written; indexes not regenerated: %s; run python3 -m gates index\n"
                         % (prog, rid, safe_text(e)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
