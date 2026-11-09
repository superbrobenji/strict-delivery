"""Tool ``decisions``: ``ask``, ``decide``, ``withdraw`` and ``find`` over the decision register (spec 7.1, 7.3, 7.4;
plan Task 1d.1; owner OQ-7, OQ-8, OQ-11, OQ-12, Q-decisions-1 (b), I3; controller ruling R-rev3-2).

Standard library only. Every argv text is checked against a whitelist before any other code reads it (owner
Q-B2FX2-1 (a); block 1d decisions D-3, D-4, D-5): free text is printable ASCII, so the record bytes and every printed
line are the same on every interpreter. Exit 2 on a usage error, 1 on a refusal (nothing written), 0 otherwise.
"""
from __future__ import annotations

import datetime
import fnmatch
import random
import re
import sys
from typing import List, Optional

from gates.lib import config, decisions, gitinfo, ids
from gates.lib import batch
from gates.lib.result import GateError, _Once, gate_args, safe_text
from gates.lib.store import Store
from gates.tools import index

PRODUCES = ("decision",)

_rng = random.SystemRandom()  # the mint's generator (decision D-6); tests patch it to force a collision
_SUBS = ("ask", "batch", "decide", "find", "withdraw")
_TOPIC = re.compile(r"[a-z0-9][a-z0-9-]*")
_PLAN = re.compile(r"[a-z0-9][a-z0-9._-]*")
_WORD = re.compile(r"[0-9A-Za-z]+")
_EFFECTS = ("lasting", "one-off")


# ---------------------------------------------------------------- argv whitelists (decisions D-3, D-4, D-13)

def _text(flag: str, value: str, multiline: bool = False) -> str:
    """``value`` when it is non-empty printable ASCII (and U+000A when ``multiline``) with no leading or trailing
    space or line break; the refusal names the first offending code point, never the text."""
    if value == "":
        raise GateError("%s: must not be empty" % flag)
    for c in value:
        o = ord(c)
        if not (0x20 <= o <= 0x7E or (multiline and o == 0x0A)):
            raise GateError("%s: U+%04X is not allowed; the text must be printable ASCII (U+0020-U+007E)%s"
                            % (flag, o, ", with line breaks (U+000A)" if multiline else ""))
    if value[0] in " \n" or value[-1] in " \n":
        raise GateError("%s: must not start or end with a space or a line break" % flag)
    return value


def _slug(flag: str, value: str, pattern: "re.Pattern") -> str:
    if not pattern.fullmatch(value):
        raise GateError("%s: must match %s" % (flag, pattern.pattern))
    return value


def _glob(flag: str, value: str) -> str:
    if value == "":
        raise GateError("%s: must not be empty" % flag)
    for c in value:
        if not 0x21 <= ord(c) <= 0x7E:
            raise GateError("%s: U+%04X is not allowed; a path or glob is printable ASCII without spaces "
                            "(U+0021-U+007E)" % (flag, ord(c)))
    if value.startswith("/"):
        raise GateError("%s: must be repo-relative (it starts with /)" % flag)
    if ".." in value.split("/"):
        raise GateError("%s: must not hold a .. segment" % flag)
    return value


def _unique(flag: str, values: list) -> list:
    seen: list = []
    for v in values:
        if v in seen:
            raise GateError("%s: %s given twice" % (flag, v))
        seen.append(v)
    return values


def _option(value: str) -> dict:
    if sum(1 for i in range(len(value) - 1) if value[i:i + 2] == "::") != 1:
        raise GateError("--option: expected LABEL::COST with exactly one ::")
    label, _, cost = value.partition("::")
    return {"label": _text("--option label", label), "cost": _text("--option cost", cost)}


def _id(flag: str, value: str, prefix: str) -> str:
    problem = ids.id_problem(value, prefix)
    if problem:
        raise GateError("%s: %s" % (flag, problem))
    return value


# ---------------------------------------------------------------- shared steps

def _setup(given_root: Optional[str]) -> tuple:
    root = index._root(given_root)
    return root, config.load(root)


def _load(root: str, cfg: dict) -> tuple:
    return Store(root, "decision", cfg).load(), Store(root, "finding", cfg).load()


def _email(root: str) -> str:
    email = gitinfo.user_email(root)
    if email is None:
        raise GateError("set git config user.email; the answer records it")
    for c in email:
        if not 0x20 <= ord(c) <= 0x7E:
            raise GateError("user.email: U+%04X is outside U+0020-U+007E" % ord(c))
    return email


def _valid(row: dict, cfg: dict) -> None:
    errs = decisions.validate(row, cfg)
    if errs:
        raise GateError("; ".join(errs))


def _regenerate(root: str, cfg: dict, sub: str, rid: str) -> int:
    """Regenerate the indexes after a write; on failure the record stays and the caller learns its id (D-7)."""
    try:
        index.regenerate(root, cfg)
    except GateError as e:
        sys.stdout.write(rid + "\n")
        sys.stderr.write("decisions %s: %s written; indexes not regenerated: %s; run python3 -m gates index\n"
                         % (sub, rid, safe_text(e)))
        return 1
    sys.stdout.write(rid + "\n")
    return 0


def _open_record(decs: list, rid: str) -> object:
    for r in decs:
        if r.id == rid:
            if r.row.get("status") != "open":
                raise GateError("%s is not open; only an open decision can be answered or withdrawn" % rid)
            return r
    raise GateError("%s: no such decision" % rid)


# ---------------------------------------------------------------- ask

def _words(question: str) -> list:
    """Maximal runs of ASCII letters and digits of 4 or more characters (decision D-12). ``find`` compares a term
    case-insensitively, which on ASCII is the ASCII lowering D-12 names, and the union drops repeats."""
    return [w for w in _WORD.findall(question) if len(w) >= 4]


def _candidates(decs: list, topics: list, globs: list, question: str) -> list:
    """The union of plan L864 (decision D-11): topic and word hits as themselves, glob hits by ``current``."""
    hits: set = set()
    for t in topics:
        hits.update(r.id for r in decisions.find(decs, [], None, t, True))
    for r in decs:  # every row passed index.render's validation: applies_to is a list of str
        if any(rg == g or fnmatch.fnmatchcase(g, rg) or fnmatch.fnmatchcase(rg, g)
               for rg in r.row["applies_to"] for g in globs):
            hits.add(decisions.current(decs, r.id))
    for w in _words(question):
        hits.update(r.id for r in decisions.find(decs, [w], None, None, True))
    return sorted(hits)


def _supersedes(decs: list, target: str) -> None:
    by_id = {r.id: r for r in decs}
    if target not in by_id:
        raise GateError("supersedes: %s has no record" % target)
    if by_id[target].row.get("status") != "answered":
        raise GateError("supersedes: %s is not answered" % target)
    live = [r.id for r in decs if r.row.get("supersedes") == target and r.row.get("status") in ("open", "answered")]
    if live:
        raise GateError("supersedes: %s is already superseded by %s; ask refuses a second (owner Q-decisions-1 (b))"
                        % (target, ", ".join(live)))


def _ask(ns) -> int:
    question = _text("--question", ns.question, multiline=True)
    options = [_option(v) for v in ns.option]
    _unique("--option label", [o["label"] for o in options])
    cls = _text("--class", ns.cls)
    by = _text("--by", ns.by)
    topics = _unique("--topic", [_slug("--topic", t, _TOPIC) for t in ns.topic or []])
    globs = _unique("--applies-to", [_glob("--applies-to", g) for g in ns.applies_to or []])
    if ns.effect not in _EFFECTS:
        raise GateError("--effect: must be lasting or one-off")
    if ns.plan is not None:
        _slug("--plan", ns.plan, _PLAN)
    for flag, value in (("--program", ns.program), ("--stream", ns.stream)):
        if value is not None:
            _slug(flag, value, _TOPIC)  # the grant-field name rule of decisions.py (decision D-4)
    root, cfg = _setup(ns.root)
    prefix = cfg["ids"]["decision"]
    if ns.supersedes is not None:
        _id("--supersedes", ns.supersedes, prefix)
    head = gitinfo.head_sha(root)
    decs, fins = _load(root, cfg)
    index.render(root, cfg)  # a record the index refuses blocks the ask before any write (D-7, D-15)
    if ns.supersedes is not None:
        _supersedes(decs, ns.supersedes)
    cands = _candidates(decs, topics, globs, question)
    rid = ids.mint(prefix, {r.id for r in decs + fins}, ids.utc_today(), _rng)
    row = {"schema": "decision/%d" % decisions._schema().version, "id": rid, "status": "open", "class": cls,
           "question": question, "options": options, "asked_at": head, "asked_by": by, "topics": topics,
           "applies_to": globs, "checked_against": cands, "effect": ns.effect}
    for key in ("supersedes", "plan", "program", "stream"):
        if getattr(ns, key) is not None:
            row[key] = getattr(ns, key)
    _valid(row, cfg)
    Store(root, "decision", cfg).create(row)
    qs = {r.id: r.row.get("question") for r in decs}
    sys.stdout.write("".join("candidate %s: %s\n" % (c, safe_text(qs[c])) for c in cands))
    return _regenerate(root, cfg, "ask", rid)


# ---------------------------------------------------------------- decide and withdraw

def _decide(ns) -> int:
    root, cfg = _setup(ns.root)
    rid = _id("ID", ns.id, cfg["ids"]["decision"])
    decs, _ = _load(root, cfg)
    rec = _open_record(decs, rid)
    email = _email(root)
    answer = _text("--answer", ns.answer, multiline=True)
    rule = _text("--rule", ns.rule) if ns.rule is not None else None
    landed = _unique("--landed-in", [_text("--landed-in", c) for c in ns.landed_in or []])
    head = gitinfo.head_sha(root)
    row = dict(rec.row)
    row.update(status="answered", answer=answer, answered_at={"at": head, "by": email})
    if rule is not None:
        row["rule"] = rule
    if ns.landed_in is not None:
        row["landed_in"] = landed
    _valid(row, cfg)
    errs = decisions.landed_errors(row, root, cfg, gitinfo.tracked_files(root))
    if errs:
        raise GateError("; ".join(errs))
    index.render(root, cfg)
    Store(root, "decision", cfg).replace(row)
    return _regenerate(root, cfg, "decide", rid)


def _withdraw(ns) -> int:
    root, cfg = _setup(ns.root)
    rid = _id("ID", ns.id, cfg["ids"]["decision"])
    decs, _ = _load(root, cfg)
    rec = _open_record(decs, rid)
    email = _email(root)
    reason = _text("--reason", ns.reason, multiline=True)
    head = gitinfo.head_sha(root)
    row = dict(rec.row)
    row.update(status="withdrawn", withdrawn={"at": head, "by": email, "reason": reason})
    _valid(row, cfg)
    index.render(root, cfg)
    Store(root, "decision", cfg).replace(row)
    return _regenerate(root, cfg, "withdraw", rid)


# ---------------------------------------------------------------- find

def _find(ns) -> int:
    terms = [_text("TERM", t) for t in ns.terms]
    topic = _slug("--topic", ns.topic, _TOPIC) if ns.topic is not None else None
    path = _glob("--path", ns.path) if ns.path is not None else None
    root, cfg = _setup(ns.root)
    decs = index._records(root, "decision", cfg, decisions.validate)
    lines = []
    for r in decisions.find(decs, terms, path, topic, ns.all):
        row = r.row
        answer = row["answer"] if row.get("status") == "answered" else "(%s)" % row.get("status")
        lines.append("%s [%s] %s -> %s\n" % (r.id, ", ".join(safe_text(t) for t in row["topics"]),
                                             safe_text(row["question"]), safe_text(answer)))
    sys.stdout.write("".join(lines))
    return 0


# ---------------------------------------------------------------- batch (plan Task 1d.3; decisions D-22..D-29)

_SINCE = re.compile(r"[0-9a-f]{7,40}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NOT_ANCESTOR = "; not an ancestor of HEAD: every open record is new"
_NO_CUT = "; no cut-off: every open record is new"


def _batch_date(value: Optional[str]) -> str:
    if value is None:
        return ids.utc_today().isoformat()
    if _DATE.fullmatch(value):  # an ASCII class first: strptime alone takes 2026-1-2 and fullwidth digits (N6, U2)
        try:
            datetime.datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            pass
    raise GateError("--date must be a calendar date YYYY-MM-DD")


def _is_ancestor(root: str, sha: str) -> bool:
    """``sha`` names a commit that is an ancestor of HEAD (plan P:976); no common history counts as not."""
    if not gitinfo.commit_exists(root, sha):
        return False
    try:
        return gitinfo.merge_base(root, sha, "HEAD") == gitinfo.merge_base(root, sha, sha)
    except GateError:
        return False


def _printable(records: list, check) -> list:
    """``(id, row)`` of ``records``; a row ``check`` refuses names its file (rows C9, Q13)."""
    out = []
    for r in records:
        try:
            check(r)
        except GateError as e:
            raise GateError("%s: %s" % (r.file, e)) from None
        out.append((r.id, r.row))
    return out


def _batch(ns) -> int:
    if ns.answered:
        if ns.since is not None:
            raise GateError("--since has no meaning with --answered")
        if ns.source is None:
            raise GateError("--answered needs --source")
        source = ns.source
        if source == "":
            raise GateError("--source: must not be empty")
        for c in source:
            if c in "\n\r" or ord(c) in batch._REFUSED:
                raise GateError("--source: U+%04X is not allowed" % ord(c))
        date = _batch_date(ns.date)
    else:
        if ns.source is not None or ns.date is not None:
            raise GateError("--source and --date need --answered")
        if ns.since is not None and not _SINCE.fullmatch(ns.since):
            raise GateError("--since must be 7 to 40 lowercase hex digits")
    root, cfg = _setup(ns.root)
    decs = index._records(root, "decision", cfg, decisions.validate)
    if ns.answered:
        # render_answers prints, and so checks, only the answered records of this source
        rows = _printable(decs, lambda r: batch.render_answers([(r.id, r.row)], source, date))
        sys.stdout.write(batch.render_answers(rows, source, date))
        return 0
    open_ = _printable([r for r in decs if not decisions.is_resolved(r.row)],
                       lambda r: batch.render_question(r.id, r.row))
    if ns.since is None:
        new, also, note = open_, [], _NO_CUT
    elif _is_ancestor(root, ns.since):
        at_cut = set(gitinfo.ls_tree(root, ns.since, cfg["paths"]["decisions"]))
        files = {r.id: r.file for r in decs}
        new = [(i, row) for i, row in open_ if files[i] not in at_cut]
        also = [(i, row) for i, row in open_ if files[i] in at_cut]
        note = ""
    else:
        new, also, note = open_, [], _NOT_ANCESTOR
    sys.stdout.write(batch.render(new, also, ns.since, note))
    return 0


# ---------------------------------------------------------------- argv

def _parser(sub: str):
    p = gate_args("decisions " + sub)
    if sub == "ask":
        p.add_argument("--class", dest="cls", required=True, action=_Once)
        p.add_argument("--question", required=True, action=_Once)
        p.add_argument("--option", required=True, action="append")
        p.add_argument("--topic", action="append")
        p.add_argument("--applies-to", action="append")
        p.add_argument("--effect", required=True, action=_Once)
        p.add_argument("--supersedes", action=_Once)
        p.add_argument("--by", required=True, action=_Once)
        p.add_argument("--plan", action=_Once)
        p.add_argument("--program", action=_Once)
        p.add_argument("--stream", action=_Once)
    elif sub == "decide":
        p.add_argument("id", metavar="ID")
        p.add_argument("--answer", required=True, action=_Once)
        p.add_argument("--rule", action=_Once)
        p.add_argument("--landed-in", action="append")
    elif sub == "withdraw":
        p.add_argument("id", metavar="ID")
        p.add_argument("--reason", required=True, action=_Once)
    elif sub == "batch":
        p.add_argument("--since", action=_Once)
        p.add_argument("--answered", action="store_true")
        p.add_argument("--source", action=_Once)
        p.add_argument("--date", action=_Once)
    else:
        p.add_argument("terms", metavar="TERM", nargs="*")
        p.add_argument("--path", action=_Once)
        p.add_argument("--topic", action=_Once)
        p.add_argument("--all", action="store_true")
    return p


_RUN = {"ask": _ask, "batch": _batch, "decide": _decide, "find": _find, "withdraw": _withdraw}


def main(argv: Optional[List[str]] = None) -> int:
    """``python3 -m gates decisions <sub> [args]``: 2 on a usage error, 1 on a refusal, 0 otherwise."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in _SUBS:
        sys.stderr.write("usage: python3 -m gates decisions <sub> [args]\nsubcommands: %s\n" % ", ".join(_SUBS))
        return 2
    sub = args[0]
    try:
        ns = _parser(sub).parse_args(args[1:])
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _RUN[sub](ns)
    except GateError as e:
        sys.stderr.write("decisions %s: %s\n" % (sub, safe_text(e)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
