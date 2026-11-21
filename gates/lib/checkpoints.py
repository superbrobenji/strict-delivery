"""Checkpoint rules: the ``handoff/1`` rules beyond the schema and the ``ledger/1`` readers and rules (plan Task P1.2,
standard library only).

``handoff.yml`` (``gates/schemas``) says what a handoff's front matter holds; ``handoff_errors`` adds the rules a schema
vocabulary cannot say. ``ledger.yml`` holds the line forms (``CHECKPOINT``, ``Ruling``, ``Request``, ``UPDATE``,
``MERGED``); ``ledger_errors`` adds the rules across lines. Controller decisions D-Q1 to D-Q30 of the Task P1.2
input-domain table settle every edge: a rule whose input has the wrong type is skipped (the schema names it), every
text is ``<field>: <reason>``, and no verdict depends on ``str.lower``, ``isprintable``, ``isdigit`` or ``\\w``/``\\d``/
``\\s``, so every verdict is the same on every supported interpreter (table rows V1, V2). Numerals of ledger lines have
at most 600 digits (``dispatch.MAX_DIGITS``; the pattern refuses longer ones), so ``int()`` never meets text above the 3.11 limit.
No ``except`` here catches ``BaseException`` or an exception group: a failing library call propagates."""
from __future__ import annotations

import datetime
import os
import re
from typing import Optional

from gates.lib import dispatch, findings as findings_lib, gitinfo, ids, schema, store, yamlsub
from gates.lib.result import GateError

CLASS_MODEL = "model-policy"  # the one decision class that carries no recommended option (spec 7.1, design 3.6)
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_GRANT = re.compile(r"pr=[1-9][0-9]{0,599} head=[0-9a-f]{40}")
_LINES = re.compile(r"[1-9][0-9]{0,599}-(?:[1-9][0-9]{0,599}|end)")
_BLOCK = re.compile(r"##(#?) Block ([0-9A-Za-z]+)(?::| \()")
_STREAM = re.compile(r"## Stream [^,]+, sub-block ([0-9A-Za-z]+)(?: \(|\Z)")


# ---------------------------------------------------------------- small helpers

def _ascii_line(v: object) -> bool:
    """A ``str`` of printable ASCII (U+0020-U+007E) only, so one line (decision D-Q18)."""
    return type(v) is str and all(" " <= c <= "~" for c in v)


def _line_check(errs: list, path: str, v: object) -> bool:
    """Append the single-line rule's error for a ``str`` that breaks it; True when ``v`` is a ``str`` that passes."""
    if type(v) is not str:
        return False
    if not _ascii_line(v):
        errs.append("%s: must be a single line of printable ASCII" % path)
        return False
    return True


def _dups(errs: list, path: str, values: object) -> None:
    """``<path>.<i>: <v> given twice`` for each later copy of a ``str`` item of the list ``values``."""
    if type(values) is not list:
        return
    seen: set = set()
    for i, v in enumerate(values):
        if type(v) is not str:
            continue
        if v in seen:
            errs.append("%s.%d: %s given twice" % (path, i, v))
        seen.add(v)


def plan_slug(plan_path: str) -> str:
    """The basename of ``plan_path`` without its final ``.md``. ``ValueError`` for a non-``str``, a path not ending
    ``.md`` and an empty slug (``.md``, ``dir/.md``)."""
    if type(plan_path) is not str:
        raise ValueError("plan_slug: the plan path must be a string")
    if not plan_path.endswith(".md"):
        raise ValueError("plan_slug: '%s' does not end with .md" % plan_path)
    slug = plan_path.rsplit("/", 1)[-1][:-3]
    if slug == "":
        raise ValueError("plan_slug: '%s' has an empty name before .md" % plan_path)
    return slug


def resume_line(row: dict) -> str:
    """``Resume strict-delivery plan <plan> at <next_task>; branch <branch>; head <head>; open questions: <ids or
    none>.``; the ids are ``open_decisions`` then each question's ``qid``, joined by ``, `` (Process for this plan).
    ``ValueError`` naming the field when a field it reads is missing, not a non-empty string of printable ASCII, or
    (``open_decisions``, ``questions``) not a list of them (decisions D-Q3, D-Q17, D-Q18)."""
    if type(row) is not dict:
        raise ValueError("resume_line: the row must be a mapping")

    def need(name: str, v: object) -> str:
        if type(v) is not str or v == "" or not _ascii_line(v):
            raise ValueError("resume_line: %s must be a non-empty single line of printable ASCII" % name)
        return v

    plan, nxt = need("plan", row.get("plan")), need("next_task", row.get("next_task"))
    branch, head = need("branch", row.get("branch")), need("head", row.get("head"))
    decisions, questions = row.get("open_decisions"), row.get("questions")
    if type(decisions) is not list:
        raise ValueError("resume_line: open_decisions must be a list")
    if type(questions) is not list:
        raise ValueError("resume_line: questions must be a list")
    open_ids = [need("open_decisions.%d" % i, d) for i, d in enumerate(decisions)]
    for i, q in enumerate(questions):
        if type(q) is not dict:
            raise ValueError("resume_line: questions.%d must be a mapping" % i)
        open_ids.append(need("questions.%d.qid" % i, q.get("qid")))
    return "Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: %s." % (
        plan, nxt, branch, head, ", ".join(open_ids) if open_ids else "none")


# ---------------------------------------------------------------- the handoff

def parse_handoff(text: str) -> dict:
    """The front matter of the handoff ``text`` as a mapping. The structural part only (decision D-Q4): line 1 is
    exactly ``---``, the front matter runs to the next line that is exactly ``---``, it is a YAML mapping. ``ValueError``
    whose message is the one error, in Task P1.1's texts; the schema is not run (callers run ``validate_front_matter``)."""
    if type(text) is not str:
        raise ValueError("front matter: text must be a string")
    lines = text.split("\n")
    if lines[0] != "---":
        raise ValueError("front matter: first line must be '---'")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("front matter: no closing '---' line") from None
    try:
        value = yamlsub.parse("\n".join(lines[1:end]))
    except yamlsub.YamlError as e:
        raise ValueError("front matter: line %d: %s" % (e.line + 1, e.reason)) from None
    if type(value) is not dict:
        raise ValueError("front matter: must be a mapping")
    return value


def _plan_ok(plan: str, cfg: dict) -> bool:
    prefix = cfg["paths"]["plans"] + "/"
    if not (plan.startswith(prefix) and plan.endswith(".md") and len(plan) > len(prefix) + 3):
        return False
    return "/" not in plan[len(prefix):-3] and schema._path_ok(plan)


def _worktree_path_ok(p: str) -> bool:
    """``.``, or a leading run of ``../`` then a normalised path, or a normalised path (decision D-Q11); printable ASCII
    without a backslash."""
    if not _ascii_line(p) or "\\" in p:
        return False
    if p == ".":
        return True
    rest = p
    while rest.startswith("../"):
        rest = rest[3:]
    return schema._path_ok(rest)


def question_errors(questions: object, cfg: dict) -> list:
    """The rules of the handoff's ``questions`` beyond the schema (plan P:2451, design 3.6, 3.7; decisions D-Q7 to D-Q9).
    ``qid`` problems are keyed by the index, ``recommended`` and ``source`` by the ``qid`` (only for a valid, unique one)."""
    if type(questions) is not list:
        return []
    errs: list = []
    counts: dict = {}
    for q in questions:
        if type(q) is dict and type(q.get("qid")) is str:
            counts[q["qid"]] = counts.get(q["qid"], 0) + 1
    owner_only = cfg["decision_classes"]["owner_only"]
    seen: set = set()
    for i, q in enumerate(questions):
        if type(q) is not dict:
            continue
        where = "questions.%d" % i
        qid = q.get("qid") if "qid" in q else None
        usable = False
        if "qid" in q:
            if type(qid) is not str or _NAME.fullmatch(qid) is None:
                errs.append("%s.qid: must be a string matching [a-z0-9][a-z0-9-]*" % where)
            elif qid in seen:
                errs.append("%s.qid: %s given twice" % (where, qid))
            else:
                usable = counts[qid] == 1
            if type(qid) is str:
                seen.add(qid)
        cls = q.get("class")
        if type(cls) is str:
            if _line_check(errs, where + ".class", cls) and cls not in owner_only:
                errs.append("%s.class: %s is not an owner-only class (%s)" % (where, cls, ", ".join(owner_only)))
        _line_check(errs, where + ".question", q.get("question"))
        options = q.get("options")
        if type(options) is list:
            for j, o in enumerate(options):
                if type(o) is dict:
                    _line_check(errs, "%s.options.%d.label" % (where, j), o.get("label"))
                    _line_check(errs, "%s.options.%d.cost" % (where, j), o.get("cost"))
        if not usable:
            continue
        key = "questions.%s" % qid
        if type(cls) is str and cls == CLASS_MODEL:
            if "recommended" in q:
                errs.append("%s.recommended: class %s carries no recommended option" % (key, cls))
        elif type(cls) is str and "recommended" not in q:
            errs.append("%s.recommended: missing" % key)
        rec = q.get("recommended")
        if type(rec) is str:
            hits = 0
            if type(options) is list:
                hits = sum(1 for o in options if type(o) is dict and type(o.get("label")) is str and o["label"] == rec)
            if hits != 1:
                errs.append("%s.recommended: %s is not the label of exactly one option" % (key, rec))
        if "source" in q:
            src = q["source"]
            if type(src) is str and (src == "" or not _ascii_line(src)):
                errs.append("%s.source: must be a non-empty single line of printable ASCII" % key)
    return errs


def handoff_errors(row: object, cfg: dict) -> list:
    """The rules of a ``handoff/1`` row beyond the schema (plan P:2451 and the decisions D-Q1 to D-Q18), each
    ``<field>: <reason>``, in the field order of the plan's list. Never raises on a mapping: a rule whose input has the
    wrong type is skipped, the schema names it."""
    if type(row) is not dict:
        return ["handoff: must be a mapping"]
    errs: list = []
    plan = row.get("plan")
    if _line_check(errs, "plan", plan) and not _plan_ok(plan, cfg):
        errs.append("plan: must be %s/<name>.md" % cfg["paths"]["plans"])
    for i, s in enumerate(row.get("spec") if type(row.get("spec")) is list else []):
        _line_check(errs, "spec.%d" % i, s)
    _dups(errs, "spec", row.get("spec"))
    _line_check(errs, "branch", row.get("branch"))
    ledger = row.get("ledger")
    if _line_check(errs, "ledger", ledger) and type(plan) is str:
        try:
            expected = "%s/%s/ledger.md" % (cfg["paths"]["plan_state"], plan_slug(plan))
        except ValueError:
            expected = None
        if expected is not None and ledger != expected:
            errs.append("ledger: expected '%s'" % expected)
    resume = row.get("resume")
    if _line_check(errs, "resume", resume):
        try:
            want = resume_line(row)
        except ValueError:
            want = None
        if want is not None and resume != want:
            errs.append("resume: expected '%s'" % want)
    _line_check(errs, "block", row.get("block"))
    _line_check(errs, "next_task", row.get("next_task"))
    _dups(errs, "findings_in_flight", row.get("findings_in_flight"))
    _dups(errs, "open_decisions", row.get("open_decisions"))
    grant = row.get("grant")
    if type(grant) is str and _GRANT.fullmatch(grant) is None:
        errs.append("grant: must be null or 'pr=<n> head=<40 hex>'")
    _subagent_errors(errs, row)
    role = row.get("role")
    if _line_check(errs, "role", role) and role not in dispatch.ROLES:
        errs.append("role: must be one of %s" % ", ".join(dispatch.ROLES))
    has_program, has_stream = "program" in row, "stream" in row
    for name in ("program", "stream"):
        v = row.get(name)
        if type(v) is str and _NAME.fullmatch(v) is None:
            errs.append("%s: must match [a-z0-9][a-z0-9-]*" % name)
    if has_program and not has_stream:
        errs.append("stream: required when program is present")
    if has_stream and not has_program:
        errs.append("program: required when stream is present")
    _worktree_errors(errs, row.get("worktrees"))
    _read_errors(errs, row.get("required_reads"))
    for i, s in enumerate(row.get("skills") if type(row.get("skills")) is list else []):
        _line_check(errs, "skills.%d" % i, s)
    _dups(errs, "skills", row.get("skills"))
    errs.extend(question_errors(row.get("questions"), cfg))
    return errs


def _subagent_errors(errs: list, row: dict) -> None:
    subs = row.get("live_subagents")
    if type(subs) is not list:
        return
    wts = row.get("worktrees")
    paths = None
    if type(wts) is list:
        paths = {w["path"] for w in wts if type(w) is dict and type(w.get("path")) is str}
    agents: set = set()
    for i, s in enumerate(subs):
        if type(s) is not dict:
            continue
        where = "live_subagents.%d" % i
        a = s.get("agent")
        if _line_check(errs, where + ".agent", a):
            if a in agents:
                errs.append("%s.agent: %s given twice" % (where, a))
            agents.add(a)
        for k in ("task", "transcript", "last_record"):
            _line_check(errs, "%s.%s" % (where, k), s.get(k))
        if _line_check(errs, where + ".worktree", s.get("worktree")) and paths is not None and s["worktree"] not in paths:
            errs.append("%s.worktree: not in worktrees" % where)
        jobs = s.get("jobs")
        if type(jobs) is list:
            seen: set = set()
            for j, job in enumerate(jobs):
                if type(job) is not dict:
                    continue
                if _line_check(errs, "%s.jobs.%d.id" % (where, j), job.get("id")):
                    if job["id"] in seen:
                        errs.append("%s.jobs.%d.id: %s given twice" % (where, j, job["id"]))
                    seen.add(job["id"])


def _worktree_errors(errs: list, wts: object) -> None:
    if type(wts) is not list:
        return
    seen: set = set()
    roots = 0
    for i, w in enumerate(wts):
        if type(w) is not dict:
            continue
        where = "worktrees.%d" % i
        p = w.get("path")
        if type(p) is str:
            if not _worktree_path_ok(p):
                errs.append("%s.path: must be '.' or a normalised relative path with '..' only as a leading run "
                            "(printable ASCII, no backslash)" % where)
            elif p in seen:
                errs.append("%s.path: %s given twice" % (where, p))
            seen.add(p)
            roots += p == "."
        _line_check(errs, where + ".branch", w.get("branch"))
    if roots != 1:
        errs.append("worktrees: exactly one entry must have path '.' (found %d)" % roots)


def _read_errors(errs: list, reads: object) -> None:
    if type(reads) is not list:
        return
    seen: set = set()
    for i, r in enumerate(reads):
        if type(r) is not dict:
            continue
        where = "required_reads.%d" % i
        p = r.get("path")
        if _line_check(errs, where + ".path", p) and (not schema._path_ok(p) or "\\" in p):  # _path_ok refuses '.', '..', '/x'; a backslash too (D-Q11)
            errs.append("%s.path: must be a normalised repo-relative path (no leading '/', no '..' segment, not '.')"
                        % where)
        lines = r.get("lines")
        if type(lines) is str and _LINES.fullmatch(lines) is None:
            errs.append("%s.lines: must be <first>-<last> or <first>-end" % where)
        _line_check(errs, where + ".why", r.get("why"))
        if type(p) is str and (lines is None or type(lines) is str):
            key = (p, lines)
            if key in seen:
                errs.append("required_reads.%d: %s listed twice" % (i, p))
            seen.add(key)


# ---------------------------------------------------------------- the ledger

def _ledger_schema() -> "schema.Schema":
    return schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "ledger.yml"))


def _keyword(line: str) -> str:
    """The word a line leads with, as ``validate_markdown`` reads it (first space-delimited token, one ``:`` off)."""
    token = line.split(" ", 1)[0]
    return token[:-1] if token.endswith(":") else token


def _conforming(text: str, word: str) -> list:
    """``[(n, line)]`` of the lines after the first led by ``word`` that match its pattern in ``ledger.yml``."""
    rule = _ledger_schema().rules[word]
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        if n > 1 and _keyword(line) == word and rule[1].fullmatch(line):
            out.append((n, line))
    return out


def _need_text(text: object) -> None:
    if type(text) is not str:
        raise ValueError("the ledger text must be a string")


def _tests(token: str) -> tuple:
    a, b = token[len("tests="):].split("/")
    return int(a), int(b)


def checkpoint_lines(text: str) -> list:
    """The conforming ``CHECKPOINT`` lines after the first line, in file order, as dicts ``line`` (1-based), ``block``,
    ``task``, ``head``, ``passed`` and ``total`` (``int``), ``gates``, ``next``. A keyword line that fails its pattern is
    skipped (``ledger_errors`` reports it); a non-``str`` text is a ``ValueError`` (decision D-Q25)."""
    _need_text(text)
    out = []
    for n, line in _conforming(text, "CHECKPOINT"):
        p = line.split(" ")
        passed, total = _tests(p[4])
        out.append({"line": n, "block": p[1], "task": p[2], "head": p[3][len("head="):], "passed": passed,
                    "total": total, "gates": p[5][len("gates="):], "next": p[6][len("next="):]})
    return out


def _merged_dict(line: str) -> dict:
    head, _, words = line.partition(" words=")
    d = {"pr": None, "head": None, "merge": None, "merged_by": None, "at": None, "final": None,
         "stream": None, "block": None, "approval": None, "approval_pr": None, "approval_head": None, "words": None}
    chat = False
    for part in head.split(" ")[1:]:
        k, _, v = part.partition("=")
        if k == "approval":
            d["approval"] = v
            chat = v == "chat"
        elif chat and k == "pr":
            d["approval_pr"] = int(v)
        elif chat and k == "head":
            d["approval_head"] = v
        elif k == "pr":
            d["pr"] = int(v)
        else:
            d[k] = v
    if chat:
        d["words"] = words
    return d


def merged_lines(text: str) -> list:
    """The conforming ``MERGED`` lines after the first line, in file order, as dicts ``pr`` (``int``),
    ``head``, ``merge``, ``merged_by``, ``at``, ``final`` (``"yes"`` or ``"no"``), ``stream``, ``block`` (``None`` when
    absent), ``approval`` (``host`` or ``chat``) and, for ``chat``, ``approval_pr`` (``int``), ``approval_head``, ``words``
    (verbatim to the end of the line); those keys are ``None`` for ``host``. A keyword line that fails its pattern is
    skipped; a non-``str`` text is a ``ValueError`` (decision D-Q25)."""
    _need_text(text)
    return [_merged_dict(line) for n, line in _conforming(text, "MERGED")]


def block_ids(plan_text: str) -> set:
    """The block ids with a heading in ``plan_text``, read exactly as the plan's P:2739: ``## Block <id>`` or
    ``### Block <id>`` followed by ``:`` or `` (``, or ``## Stream <name>, sub-block <id>`` followed by `` (`` or the end of
    the line; ``<id>`` is ``[0-9A-Za-z]+``; ``### Block <id>`` counts only inside a ``## Stream`` section (from a
    ``## Stream`` heading to the next ``## `` heading). Code fences are not special (decision D-Q30)."""
    found: set = set()
    in_stream = False
    for line in plan_text.split("\n"):
        if line.startswith("## "):
            in_stream = line.startswith("## Stream ")
        m = _BLOCK.match(line)
        if m is not None and (m.group(1) == "" or in_stream):
            found.add(m.group(2))
            continue
        m = _STREAM.match(line)
        if m is not None:
            found.add(m.group(1))
    return found


def _check_args(plan_text: object, stream_ids: object, per_stream: object) -> None:
    if plan_text is not None and type(plan_text) is not str:
        raise ValueError("ledger_errors: plan_text must be None or a string")
    if stream_ids is not None and (type(stream_ids) not in (set, frozenset)
                                   or any(type(s) is not str for s in stream_ids)):
        raise ValueError("ledger_errors: stream_ids must be None or a set of strings")
    if type(per_stream) is not bool:
        raise ValueError("ledger_errors: per_stream must be a bool")


def _valid_utc(at: str) -> bool:
    """``at`` has the shape ``YYYY-MM-DDTHH:MM:SSZ`` (the pattern); True when it is a real UTC date and time."""
    try:
        datetime.datetime(int(at[0:4]), int(at[5:7]), int(at[8:10]), int(at[11:13]), int(at[14:16]), int(at[17:19]))
    except ValueError:
        return False
    return True


def ledger_errors(text: str, cfg: dict, plan_text: Optional[str] = None, stream_ids: Optional[set] = None,
                  per_stream: bool = False) -> list:
    """The errors of a ledger: the schema's (``validate_markdown`` with ``ledger.yml``), plus ``line <n>: tests passed >
    total``, ``line <n>: <id>: <reason>`` for a ``Request`` id failing ``ids.id_problem(id, cfg["ids"]["request"])``,
    ``line <n>: pr <n> recorded twice``, ``line <n>: at <v> is not a valid UTC time``, ``line <n>: final=yes after a final
    line`` (``... of stream <s>`` with ``per_stream``, which counts only the earlier lines of the same ``stream``; the lines
    without a ``stream`` form one group), ``line <n>: unknown stream <s>`` (only when ``stream_ids`` is given),
    ``line <n>: block <b> has no block heading`` (only when ``plan_text`` is given). The extra rules run only on lines
    that match their pattern; errors come in line order, a line's schema error first; a wrong first line is the only error
    returned (decisions D-Q21 to D-Q28)."""
    _check_args(plan_text, stream_ids, per_stream)
    sch = _ledger_schema()
    problems = schema.validate_markdown(sch, text)
    if problems and problems[0].startswith("first line:"):
        return problems
    by_line: dict = {}
    for p in problems:
        by_line.setdefault(int(p.split(":", 1)[0][len("line "):]), []).append(p)
    headings = block_ids(plan_text) if plan_text is not None else None
    prefix = cfg["ids"]["request"]
    errs: list = []
    prs: set = set()
    finals: set = set()
    for n, line in enumerate(text.split("\n")[1:], 2):  # line 1 is the checked first line
        errs.extend(by_line.get(n, ()))
        word = _keyword(line)
        rule = sch.rules.get(word)
        if rule is None or not rule[1].fullmatch(line):
            continue
        p = line.split(" ")
        if word in ("CHECKPOINT", "UPDATE"):
            passed, total = _tests(p[4])
            if passed > total:
                errs.append("line %d: tests passed > total" % n)
        elif word == "Request":
            problem = ids.id_problem(p[1], prefix)
            if problem:
                errs.append("line %d: %s: %s" % (n, p[1], problem))
        elif word == "MERGED":
            m = _merged_dict(line)
            if m["pr"] in prs:
                errs.append("line %d: pr %d recorded twice" % (n, m["pr"]))
            prs.add(m["pr"])
            if not _valid_utc(m["at"]):
                errs.append("line %d: at %s is not a valid UTC time" % (n, m["at"]))
            if m["final"] == "yes":
                group = m["stream"] if per_stream else None
                if group in finals:
                    errs.append("line %d: final=yes after a final line%s" % (
                        n, " of stream %s" % (group if group is not None else "(none)") if per_stream else ""))
                finals.add(group)
            if stream_ids is not None and m["stream"] is not None and m["stream"] not in stream_ids:
                errs.append("line %d: unknown stream %s" % (n, m["stream"]))
            if headings is not None and m["block"] is not None and m["block"] not in headings:
                errs.append("line %d: block %s has no block heading" % (n, m["block"]))
    return errs


# ---------------------------------------------------------------- block size, rulings and record agreement (Task 6K.1)
# Decisions D-K-Q1 to D-K-Q17 of the Task 6K.1 input-domain table: a wrong argument is a ``ValueError`` (``records_at``,
# which reaches git, and a bad cap value in ``cfg`` raise ``GateError``); a block is ``[0-9A-Za-z]+``; a count or a
# number that is put into a message has at most 600 digits (``dispatch.MAX_DIGITS``), so one verdict holds on every
# interpreter and int conversion limit.

_BLOCK_ARG = re.compile(r"[0-9A-Za-z]+")
_HEADING = re.compile(r"#{3,4} Task ([0-9A-Za-z]+)\.([0-9A-Za-z]+):")
_REGISTER_KEY = {"decision": "decisions", "finding": "findings"}
_LINES_MSG = "%s: lines must be a list of checkpoint line dicts"


def _need_block(fn: str, block: object) -> None:
    if type(block) is not str or _BLOCK_ARG.fullmatch(block) is None:
        raise ValueError("%s: block must be a string of ASCII letters and digits" % fn)


def _need_lines(fn: str, lines: object) -> None:
    """``lines`` is a ``list`` of ``dict`` that each hold a ``str`` ``block`` and a ``str`` ``task``."""
    if type(lines) is not list:
        raise ValueError(_LINES_MSG % fn)
    for ln in lines:
        if type(ln) is not dict or type(ln.get("block")) is not str or type(ln.get("task")) is not str:
            raise ValueError(_LINES_MSG % fn)


def _digits_ok(v: object) -> bool:
    """``v`` is an ``int`` (not a ``bool``, not a subclass) of 0 to 600 digits; compared as a number, never as text."""
    return type(v) is int and 0 <= v < 10 ** dispatch.MAX_DIGITS


def ledger_tasks(lines: list, block: str) -> list:
    """The distinct ``task`` tokens of the ``CHECKPOINT`` lines of ``block`` (``lines`` come from ``checkpoint_lines``)
    that start with ``<block>.`` and have at least one more character, in first-seen order. ``block`` is
    ``[0-9A-Za-z]+``; a wrong argument is a ``ValueError``."""
    _need_block("ledger_tasks", block)
    _need_lines("ledger_tasks", lines)
    prefix = block + "."
    seen: set = set()
    out = []
    for ln in lines:
        task = ln["task"]
        if ln["block"] == block and task.startswith(prefix) and len(task) > len(prefix) and task not in seen:
            seen.add(task)
            out.append(task)
    return out


def plan_tasks(plan_text: str, block: str) -> list:
    """The ``<block>.<rest>`` ids of the plan's lines ``### Task <id>:`` or ``#### Task <id>:`` (column 0, one space, the
    colon right after the id; ``<rest>`` is ``[0-9A-Za-z]+``), in order. Lines are split on the line feed only and code
    fences are not special. A repeated id of ``block`` is a ``ValueError``."""
    _need_block("plan_tasks", block)
    if type(plan_text) is not str:
        raise ValueError("plan_tasks: plan_text must be a string")
    seen: set = set()
    out = []
    for line in plan_text.split("\n"):
        m = _HEADING.match(line)
        if m is None or m.group(1) != block:
            continue
        tid = "%s.%s" % (block, m.group(2))
        if tid in seen:
            raise ValueError("plan_tasks: task %s is listed twice" % tid)
        seen.add(tid)
        out.append(tid)
    return out


def ledger_rulings(ledger_text: str, block: str) -> int:
    """The number of ``Ruling`` lines in the block's segment of the ledger (decisions D-K-Q1, D-K-Q2). The segment starts
    after the last ``CHECKPOINT`` line of another block that comes before the block's last ``CHECKPOINT`` line (only the
    latest run counts), or at the file start when there is none; a block with no ``CHECKPOINT`` line yet starts after the
    last ``CHECKPOINT`` line of any block. It runs to the end of the file. Boundaries are the conforming lines of
    ``checkpoint_lines``; a ``Ruling`` line is read by ``_keyword``; line 1 is never read."""
    _need_block("ledger_rulings", block)
    cps = checkpoint_lines(ledger_text)
    mine = [i for i, c in enumerate(cps) if c["block"] == block]
    before = cps[:mine[-1]] if mine else cps
    start = 0
    for c in reversed(before):
        if c["block"] != block:
            start = c["line"]
            break
    return sum(1 for n, line in enumerate(ledger_text.split("\n"), 1) if n > 1 and n > start and _keyword(line) == "Ruling")


def _cap_value(cfg: dict, section: str, key: str) -> Optional[int]:
    """``cfg[section][key]``: ``None`` when the section or the key is absent; a ``GateError`` naming the key when the
    section is not a mapping or the value is not an ``int`` of at least 1 (a ``bool`` is refused)."""
    if section not in cfg:
        return None
    sec = cfg[section]
    if type(sec) is not dict:
        raise GateError("%s: must be a mapping" % section)
    if key not in sec:
        return None
    v = sec[key]
    if type(v) is not int or v < 1:
        raise GateError("%s.%s: must be an integer of at least 1" % (section, key))
    return v


def cap_errors(handoff: dict, lines: list, plan_text: str, cfg: dict, rulings: int) -> list:
    """The size errors of the handoff's block, ``rulings`` being ``ledger_rulings`` for it. In this order:
    ``block: <n> tasks in ledger exceed block.max_tasks <m>`` and the same for ``plan`` (when ``block.max_tasks`` is set;
    Q-B6plan-2 (d)); ``rulings: <n> Ruling lines in the ledger exceed rulings.max_per_block <m>`` (when it is set; judged on
    the ledger count); ``rulings: handoff says <h>, ledger has <n>`` (always, when they differ). A set cap that is not an
    ``int`` of at least 1, or a section that is not a mapping, is a ``GateError`` naming the key, raised before any
    counting. A wrong argument, or a count of more than 600 digits, is a ``ValueError``."""
    if type(handoff) is not dict:
        raise ValueError("cap_errors: handoff must be a dict")
    block = handoff.get("block")
    if type(block) is not str or _BLOCK_ARG.fullmatch(block) is None:
        raise ValueError("cap_errors: handoff block must be a string of ASCII letters and digits")
    if not _digits_ok(handoff.get("rulings")):
        raise ValueError("cap_errors: handoff rulings must be an integer of 0 to 600 digits")
    if not _digits_ok(rulings):
        raise ValueError("cap_errors: rulings must be an integer of 0 to 600 digits")
    if type(cfg) is not dict:
        raise ValueError("cap_errors: cfg must be a dict")
    max_tasks = _cap_value(cfg, "block", "max_tasks")
    max_rulings = _cap_value(cfg, "rulings", "max_per_block")
    in_ledger = len(ledger_tasks(lines, block))
    in_plan = len(plan_tasks(plan_text, block))
    errs = []
    if max_tasks is not None:
        for source, n in (("ledger", in_ledger), ("plan", in_plan)):
            if n > max_tasks:
                errs.append("block: %d tasks in %s exceed block.max_tasks %d" % (n, source, max_tasks))
    if max_rulings is not None and rulings > max_rulings:
        errs.append("rulings: %d Ruling lines in the ledger exceed rulings.max_per_block %d" % (rulings, max_rulings))
    if handoff["rulings"] != rulings:
        errs.append("rulings: handoff says %d, ledger has %d" % (handoff["rulings"], rulings))
    return errs


def records_at(root: str, cfg: dict, ref: str, kind: str) -> list:
    """The ``store.Record`` list of the ``kind`` (``decision`` or ``finding``) records directly in its configured
    directory (``cfg["paths"]``) at ``ref``, sorted by file name, read through git (``ls_tree_entries``, ``show``,
    ``yamlsub.parse``). A symlink, subfolder, gitlink or non-record name under the directory (other than the generated
    ``index.yml`` and ``in-force.md``) is a ``GateError`` ``<ref>:<path>: not a regular file named <id>.yml``; a file or
    symlink on the directory's path at ``ref`` is a ``GateError``; a configured directory with a leading or trailing ``/``,
    an empty, ``.`` or ``..`` segment is a ``GateError`` (as in ``gitinfo.ls_tree_entries``); an absent directory gives ``[]``; a file that does not
    parse is a ``GateError`` naming ``<ref>:<path>`` (decision D-K-Q12)."""
    if type(kind) is not str or kind not in _REGISTER_KEY:
        raise GateError("store kind must be 'decision' or 'finding'")
    key = _REGISTER_KEY[kind]
    paths = cfg.get("paths") if type(cfg) is dict else None
    directory = paths.get(key) if type(paths) is dict else None
    if type(directory) is not str or directory == "":
        raise GateError("config lacks paths.%s" % key)
    gitinfo._check_norm(directory, "ls-tree: directory")
    parts = directory.split("/")
    for i in range(len(parts)):
        rel = "/".join(parts[:i + 1])
        modes = [mode for mode, _, name in gitinfo.ls_tree_entries(root, ref, "/".join(parts[:i])) if name == rel]
        if not modes:
            return []
        if modes[0] != "040000":
            raise GateError("%s: not a directory" % rel)
    for mode, _, name in gitinfo.ls_tree_entries(root, ref, directory):
        base = name.rpartition("/")[2]
        if base in store._GENERATED:
            continue
        if mode not in gitinfo._REGULAR or not store._is_record_name(base):
            raise GateError("%s:%s: not a regular file named <id>.yml" % (ref, name))
    return [store.Record(row.get("id"), row, name) for name, row in store._records_at(root, ref, directory, ref, "")]


def _index_records(records: object, what: str) -> dict:
    """``{id: Record}`` of a ``list`` of ``store.Record``; the first record of an id wins and a record whose id is not a
    ``str`` is ignored (decision D-K-Q13). Anything else is a ``ValueError``."""
    if type(records) is not list or any(type(r) is not store.Record for r in records):
        raise ValueError("record_errors: %s must be a list of store.Record" % what)
    out: dict = {}
    for r in records:
        if type(r.row) is not dict:
            raise ValueError("record_errors: the row of record %s in %s must be a dict" % (r.id if type(r.id) is str else "(id not a string)", what))
        if type(r.id) is str and r.id not in out:
            out[r.id] = r
    return out


def _status_text(v: object) -> str:
    """The status as it reads in a message (``%s`` of the value, decision D-K-Q15): a ``str``, ``None``, ``bool``,
    ``float`` or an ``int`` of at most 600 digits; any other value is a ``ValueError``."""
    if v is None or type(v) in (str, bool, float) or (type(v) is int and -10 ** dispatch.MAX_DIGITS < v < 10 ** dispatch.MAX_DIGITS):
        return str(v)
    raise ValueError("record_errors: a decision's status must be a scalar of at most 600 digits")


def record_errors(handoff: dict, findings: list, decisions: list) -> list:
    """The disagreements between a handoff and the registers: for each id of ``findings_in_flight``, in the handoff's
    order (a ``Record`` whose ``row`` is not an exact ``dict`` is a ``ValueError`` naming its id), ``findings_in_flight.<id>: no finding record`` or ``findings_in_flight.<id>: resolved (status <s>)``; then for
    each id of ``open_decisions``, ``open_decisions.<id>: no decision record`` or ``open_decisions.<id>: status <s>, not
    open``. ``findings`` and ``decisions`` are lists of ``store.Record``; an absent handoff list is empty."""
    if type(handoff) is not dict:
        raise ValueError("record_errors: handoff must be a dict")
    lists = {}
    for key in ("findings_in_flight", "open_decisions"):
        v = handoff.get(key, [])
        if type(v) is not list or any(type(i) is not str for i in v):
            raise ValueError("record_errors: handoff %s must be a list of strings" % key)
        lists[key] = v
    found = _index_records(findings, "findings")
    decided = _index_records(decisions, "decisions")
    errs = []
    for id_ in lists["findings_in_flight"]:
        rec = found.get(id_)
        if rec is None:
            errs.append("findings_in_flight.%s: no finding record" % id_)
        elif findings_lib.is_resolved(rec.row):
            errs.append("findings_in_flight.%s: resolved (status %s)" % (id_, rec.row["status"]))
    for id_ in lists["open_decisions"]:
        rec = decided.get(id_)
        if rec is None:
            errs.append("open_decisions.%s: no decision record" % id_)
            continue
        status = rec.row.get("status")
        if not (type(status) is str and status == "open"):
            errs.append("open_decisions.%s: status %s, not open" % (id_, _status_text(status)))
    return errs


def last_line_errors(lines: list) -> list:
    """The errors of the last element of ``lines`` (Q-B6plan-5 (a)): ``last CHECKPOINT: gates=<g>`` unless ``gates`` is
    ``PASS``, then ``last CHECKPOINT: tests <p>/<t>`` unless ``p == t``; ``["no CHECKPOINT line"]`` for an empty list.
    The last element must hold a ``gates`` ``str`` (or ``None`` or a ``bool``) and ``passed`` and ``total`` ``int`` of 0 to
    600 digits; otherwise a ``ValueError``."""
    if type(lines) is not list or any(type(x) is not dict for x in lines):
        raise ValueError(_LINES_MSG % "last_line_errors")
    if not lines:
        return ["no CHECKPOINT line"]
    last = lines[-1]
    gates, passed, total = last.get("gates"), last.get("passed"), last.get("total")
    if not (type(gates) in (str, bool) or gates is None) or not _digits_ok(passed) or not _digits_ok(total):
        raise ValueError("last_line_errors: the last line must have a gates string, and passed and total integers of 0 to 600 digits")
    errs = []
    if gates != "PASS":
        errs.append("last CHECKPOINT: gates=%s" % gates)
    if passed != total:
        errs.append("last CHECKPOINT: tests %d/%d" % (passed, total))
    return errs
