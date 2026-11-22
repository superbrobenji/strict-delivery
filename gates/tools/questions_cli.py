"""Tool ``questions``: ``list`` and ``ask``, the upward-question path (plan Task P4.1; Q-Pplan-8 (a); session-resume
design 3.6, 3.7, 5; binding decisions D-Q1..D-Q9 of stream a14).

The questions of a stream sit in its committed ``handoff.md`` at the tip of its branch; a question ``qid`` of plan ``x`` is
tied to its decision record by the topic ``q:<x>:<qid>`` (``tag``). ``list`` prints one line per question, ``ask`` asks every
pending one through ``decisions ask``. Every source is read and validated before anything is printed or asked; any error
goes to stderr (one ``questions <sub>: <reason>`` line per reason), nothing to stdout, nothing asked, exit 1. Exit 2 on a
usage error. Standard library only; every git read goes through ``gitinfo``.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from typing import Optional

from gates.lib import checkpoints, config, decisions, gitinfo, ids, programs, schema
from gates.lib.result import GateError, _GateParser, safe_text
from gates.tools import decisions_cli, index
from gates.tools.claims_cli import _once, _root_arg

MAX_TAG_CHARS = 128  # the whole tag q:<x>:<qid> (decision D-Q2)
_NAME_RE = "[a-z0-9][a-z0-9-]*"
_NAME = re.compile(_NAME_RE)
_USAGE = "usage: python3 -m gates questions {list,ask} (--program PROGRAM | --plan SLUG --ref REF) [--by WHO] [--root DIR]\n"


def tag(plan_slug: str, qid: str) -> str:
    """The topic ``q:<plan_slug>:<qid>`` that ties a question to its decision (plan :3089). ``ValueError`` for a name that
    does not match ``[a-z0-9][a-z0-9-]*`` or a tag longer than ``MAX_TAG_CHARS``."""
    for what, v in (("plan slug", plan_slug), ("qid", qid)):
        if type(v) is not str or _NAME.fullmatch(v) is None:
            raise ValueError("tag: the %s must be a string matching %s" % (what, _NAME_RE))
    t = "q:%s:%s" % (plan_slug, qid)
    if len(t) > MAX_TAG_CHARS:
        raise ValueError("tag: the tag %s... is longer than %d characters" % (t[:40], MAX_TAG_CHARS))
    return t


# ---------------------------------------------------------------- reading the sources

def _validate(cfg: dict, text: str, slug: str, program: Optional[str], stream: Optional[str]) -> tuple:
    """``(row, reasons)`` of the handoff ``text`` found in the directory ``slug`` (decision D-Q3)."""
    sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "handoff.yml"))
    reasons = list(schema.validate_front_matter(sch, text, cfg))
    try:
        row = checkpoints.parse_handoff(text)
    except ValueError as e:
        return None, reasons or [str(e)]
    reasons += checkpoints.handoff_errors(row, cfg)
    try:
        named = checkpoints.plan_slug(row.get("plan"))
    except ValueError:
        named = slug  # handoff_errors has named the plan problem
    if named != slug:
        reasons.append("plan: names %s, not %s" % (named, slug))
    if program is not None:
        for key, want in (("program", program), ("stream", stream)):
            if key in row and row[key] != want:
                reasons.append("%s: names %s, not %s" % (key, row[key], want))
    qs = row.get("questions")
    for i, q in enumerate(qs if type(qs) is list else []):
        qid = q.get("qid") if type(q) is dict else None
        if type(qid) is str and _NAME.fullmatch(qid) and len("q:%s:%s" % (slug, qid)) > MAX_TAG_CHARS:
            reasons.append("questions.%d.qid: the tag q:%s:%s... is longer than %d characters"
                           % (i, slug, qid[:20], MAX_TAG_CHARS))
    return row, reasons


def _read(root: str, cfg: dict, ref: str, slug: str, label: str, shown: str, program: Optional[str],
          stream: Optional[str], errors: list) -> list:
    """The questions of the handoff of plan ``slug`` at ``ref`` as ``(shown, slug, question)``; the reasons, each led by
    ``label``, go to ``errors``."""
    rel = "%s/%s/handoff.md" % (cfg["paths"]["plan_state"], slug)
    try:
        text = gitinfo.show(root, ref, rel)
    except GateError as e:
        errors.append("%s: %s: %s" % (label, rel, e))
        return []
    if text is None:
        errors.append("%s: %s: missing at %s" % (label, rel, ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref))
        return []
    row, reasons = _validate(cfg, text, slug, program, stream)
    if reasons:
        errors += ["%s: %s: %s" % (label, rel, r) for r in reasons]
        return []
    return [(shown, slug, q) for q in row["questions"]]


def _streams(cfg: dict, prog: programs.Program, errors: list) -> list:
    """``(stream id, plan slug)`` for each stream of ``streams.yml`` whose fields read here are valid (decision D-Q4)."""
    rows = prog.streams.get("streams")
    if type(rows) is not list:
        errors.append("streams.yml: streams: must be a list")
        return []
    plans = cfg["paths"]["plans"]
    out, seen_plans, seen_ids = [], {}, set()
    for st in rows:
        sid = st.get("id") if type(st) is dict else None
        why = programs.stream_problem(sid)
        if why:
            errors.append("stream %s: id: %s" % (sid, why))
            continue
        if sid in seen_ids:
            errors.append("stream %s: id: duplicate stream id" % sid)
            continue
        seen_ids.add(sid)
        plan = st.get("plan")
        rest = plan[len(plans) + 1:] if type(plan) is str and plan.startswith(plans + "/") else None
        if rest is None or "/" in rest or not rest.endswith(".md") or rest == ".md":
            errors.append("stream %s: plan: must be %s/<name>.md" % (sid, plans))
            continue
        slug = checkpoints.plan_slug(plan)
        if _NAME.fullmatch(slug) is None:
            errors.append("stream %s: plan slug %s must match %s" % (sid, slug, _NAME_RE))
        elif slug in seen_plans:
            errors.append("stream %s: plan: the same plan as stream %s" % (sid, seen_plans[slug]))
        else:
            seen_plans[slug] = sid
            out.append((sid, slug))
    return out


def question_state(records: list, tag: str) -> tuple:
    """``("pending", None)``, ``("asked", <id>)`` or ``("answered", <id>)`` for the question whose tag is ``tag``, from the
    decision ``records`` (``store.Record``): a withdrawn record is ignored; the tag is compared as the exact string. Two
    non-withdrawn records carrying the tag are a ``GateError`` naming both (all, sorted, when more)."""
    found = []
    for r in records:
        if r.row.get("status") in ("open", "answered") and tag in (r.row["topics"] if type(r.row.get("topics")) is list else []):
            found.append((r.id, r.row["status"]))
    if len(found) > 1:
        raise GateError("%s: carried by decisions %s" % (tag, ", ".join(sorted(i for i, _ in found))))
    if not found:
        return "pending", None
    return ("answered" if found[0][1] == "answered" else "asked"), found[0][0]


# ---------------------------------------------------------------- the run

def _run(sub: str, ns) -> int:
    program, plan, ref = _once("--program", ns.program), _once("--plan", ns.plan), _once("--ref", ns.ref)
    by = None
    if sub == "ask":
        by = _once("--by", ns.by)
        if by is None:
            raise GateError("--by is required")
        decisions_cli._text("--by", by)
    root_arg = _root_arg(ns.root)
    if program is not None and plan is not None:
        raise GateError("--program and --plan are exclusive")
    if ref is not None and plan is None:
        raise GateError("--ref is only valid with --plan")
    if program is None and plan is None:
        raise GateError("one of --program or --plan is required")
    if program is not None:
        why = programs.program_problem(program)
        if why:
            raise GateError("--program: %s" % why)
    else:
        if ref is None:
            raise GateError("--ref is required with --plan")
        if _NAME.fullmatch(plan) is None:
            raise GateError("--plan: must match %s" % _NAME_RE)
        if ref == "":
            raise GateError("--ref: must not be empty")
    root = index._root(root_arg)
    cfg = config.load(root)
    errors: list = []
    sources: list = []
    if program is not None:
        integ = programs.branch_of(program)
        if program not in programs.live_programs(root, cfg):
            raise GateError("--program: %s is not a live program (no branch %s with a streams.yml)" % (program, integ))
        if sub == "ask":
            here = gitinfo.current_branch(root)
            if here != integ:
                raise GateError("--program: ask must run on %s (HEAD is %s)" % (integ, here or "detached"))
        prog = programs.load_program(root, cfg, program, "refs/heads/" + integ)
        branches = set(gitinfo.local_branches(root))
        for sid, slug in _streams(cfg, prog, errors):
            branch = programs.branch_of(program, sid)
            if branch not in branches:
                errors.append("stream %s: branch %s does not exist" % (sid, branch))
                continue
            sources += _read(root, cfg, "refs/heads/" + branch, slug, "stream " + sid, sid, program, sid, errors)
    else:
        if not gitinfo.commit_exists(root, ref):
            raise GateError("--ref: %s is not a commit" % ref)
        sources += _read(root, cfg, ref, plan, "plan " + plan, plan, None, None, errors)
    records = index._records(root, "decision", cfg, decisions.validate)
    states = []
    for _, slug, q in sources:
        try:
            states.append(question_state(records, tag(slug, q["qid"])))
        except GateError as e:
            errors.append(str(e))
    if errors:
        raise GateError("\n".join(errors))
    if sub == "list":
        for (label, slug, q), (state, rid) in zip(sources, states):
            if state == "pending":
                sys.stdout.write("pending %s:%s %s: %s\n" % (slug, q["qid"], label, q["question"]))
            else:
                sys.stdout.write("%s %s:%s -> %s\n" % (state, slug, q["qid"], rid))
        return 0
    prefix = cfg["ids"]["decision"]
    for (_, slug, q), (state, _rid) in zip(sources, states):
        t = tag(slug, q["qid"])
        if state != "pending":
            continue
        # re-read: a record may have appeared since the read phase (decision D-Q7)
        if question_state(index._records(root, "decision", cfg, decisions.validate), t)[0] != "pending":
            continue
        handoff = "%s/%s/handoff.md" % (cfg["paths"]["plan_state"], slug)
        argv = ["ask", "--class=" + q["class"], "--question=" + q["question"]]
        argv += ["--option=%s::%s" % (o["label"], o["cost"]) for o in q["options"]]
        argv += ["--effect=" + q["effect"], "--topic=" + t, "--source=" + q.get("source", handoff)]
        if q["class"] != decisions.CLASS_MODEL:
            argv.append("--recommend=" + q["recommended"])
        argv += ["--by=" + by, "--root=" + root]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = decisions_cli.main(argv)
        lines = [l for l in out.getvalue().split("\n") if l]
        rid = lines[-1] if lines else ""
        written = ids.id_problem(rid, prefix) == ""
        if written:
            sys.stdout.write("asked %s:%s -> %s\n" % (slug, q["qid"], rid))
        if rc != 0 or not written:
            reasons = [l for l in err.getvalue().split("\n") if l]
            if not reasons:
                reasons = ["decisions ask returned %d and printed no valid id" % rc]
            raise GateError("\n".join("%s:%s: %s" % (slug, q["qid"], r) for r in reasons))
    return 0


# ---------------------------------------------------------------- argv

def _parser(sub: str) -> _GateParser:
    p = _GateParser(prog="questions " + sub, add_help=True)
    for f in ("--program", "--plan", "--ref", "--root") + (("--by",) if sub == "ask" else ()):
        p.add_argument(f, default=None, action="append")
    return p


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates questions <sub> ...``: 2 on a usage error, 1 on a refusal, 0 otherwise."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("questions: argv must be a list of str\n")
        return 2
    sub = args[0] if args else ""
    if sub not in ("list", "ask"):
        sys.stderr.write(_USAGE)
        return 2
    try:
        ns = _parser(sub).parse_args(args[1:])
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _run(sub, ns)
    except GateError as e:
        for part in str(e).split("\n"):                 # one line per reason, each escaped on its own
            sys.stderr.write("questions %s: %s\n" % (sub, safe_text(part)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
