"""Tool ``program``: ``create``, ``status``, ``request new``, ``request set``, ``sync-log`` and ``merged`` write the
files of a program on its integration branch (plan Task P2.2; owner answers Q-Pplan-4, Q-Pplan-11, Q-PL-1 (a),
Q-F80W-6 (b); task domain table P2.2, binding controller decisions D-Q1..D-Q20 and D-A26).

Standard library only. ``python3 -m gates program <sub>``. An argument error exits 2 with the usage on stderr; a
refusal exits 1 with one stderr line ``program <sub>: <reason>`` per reason and writes nothing. Every flag is read
and checked before the first git or file call; free text is printable ASCII on one line (D-Q1), so the bytes written
are the same on every interpreter; no ``int()`` runs on argv text. Every subcommand refuses unless the current
branch is ``<program>/integration``, validates every file it writes before writing it, and prints
``push <program>/integration`` after a write (the controller pushes; the tool runs no push and commits nothing).
"""
from __future__ import annotations

import dataclasses
import os
import random
import re
import stat
import sys
import tempfile
from typing import List, Optional

from gates.lib import (breakdown, checkpoints, claims, config, decisions, dispatch, gitinfo, ids, migrations, programs,
                       schema, store, yamlsub)
from gates.lib.result import GateError, _GateParser, safe_text
from gates.lib.store import Store
from gates.tools import index
from gates.tools.claims_cli import _once, _root_arg, _text

PRODUCES = ("streams", "status", "sync-log", "request", "breakdown", "merged-log")

_rng = random.SystemRandom()  # the mint's generator; tests patch it to force a collision
_NUM = re.compile(r"0|[1-9][0-9]{0,599}")
_SLUG = re.compile(programs.NAME_RE)
_HEX40 = re.compile(r"[0-9a-f]{40}")
_LEDGER_FIRST = "<!-- schema: ledger/1 -->"


# ---------------------------------------------------------------- argv

def _req(flag: str, values: Optional[list]) -> str:
    v = _once(flag, values)
    if v is None:
        raise GateError("%s is required" % flag)
    return _text(flag, v)


def _opt(flag: str, values: Optional[list]) -> Optional[str]:
    v = _once(flag, values)
    return None if v is None else _text(flag, v)


def _cell(flag: str, v: str) -> str:
    _text(flag, v)
    if "|" in v or "\\" in v:
        raise GateError("%s: must not hold '|' or a backslash (a status cell)" % flag)
    return v


def _many(flag: str, values: Optional[list]) -> list:
    out = [_text(flag, v) for v in values or []]
    if len(set(out)) != len(out):
        raise GateError("%s: a value is given twice" % flag)
    return out


def _fail(errs: list, what: str = "") -> None:
    if errs:
        raise GateError("\n".join(("%s: %s" % (what, e)) if what else e for e in errs))


def _pairs(errs: list) -> list:
    return ["%s: %s" % (s, r) for s, r in errs]


# ---------------------------------------------------------------- context

def _context(program: str, given_root: Optional[str]) -> tuple:
    why = programs.program_problem(program)
    if why:
        raise GateError("program name: %s" % why)
    root = index._root(given_root)
    cfg = config.load(root)
    want = "%s/integration" % program
    got = gitinfo.current_branch(root)
    if got != want:
        raise GateError("the current branch is %s; program runs only on %s"
                        % ("detached HEAD" if got is None else "'%s'" % got, want))
    return root, cfg


def _why(e: OSError) -> str:
    return e.strerror or type(e).__name__


def _replace(root: str, rel: str, text: str) -> None:
    """Rewrite the existing regular file ``rel``: a temp file beside it and ``os.replace``; the temp file is removed
    on every failure path."""
    path = os.path.join(root, *rel.split("/"))
    try:
        st = os.lstat(path)
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("%s: not a regular file" % rel)
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".program.", suffix=".tmp")
    except OSError as e:
        raise GateError("%s: cannot write (%s)" % (rel, _why(e))) from None
    done = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.replace(tmp, path)
        done = True
    except OSError as e:
        raise GateError("%s: cannot write (%s)" % (rel, _why(e))) from None
    finally:
        if not done:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _new_file(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, *rel.split("/"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "x", encoding="utf-8", newline="")
    except FileExistsError:
        raise GateError("%s: already exists" % rel) from None
    except OSError as e:
        raise GateError("%s: cannot create (%s)" % (rel, _why(e))) from None
    done = False
    try:
        with fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        done = True
    except OSError as e:
        raise GateError("%s: cannot write (%s)" % (rel, _why(e))) from None
    finally:
        if not done:
            try:
                os.unlink(path)
            except OSError:
                pass


def _pushed(program: str) -> None:
    sys.stdout.write("push %s/integration\n" % program)


def _load(root: str, cfg: dict, program: str) -> "programs.Program":
    return programs.load_program(root, cfg, program, None)


def _rel(cfg: dict, program: str, name: str) -> str:
    return "%s/%s/%s" % (cfg["paths"]["programs"], program, name)


def _breakdown_of(root: str, cfg: dict, streams: dict, required: bool) -> Optional[dict]:
    try:
        slug = checkpoints.plan_slug(streams.get("plan"))
    except ValueError as e:
        raise GateError(str(e)) from None
    rel = "%s/%s/breakdown.yml" % (cfg["paths"]["plan_state"], slug)
    if not required and programs._fs_text(root, rel) is None:
        return None
    return programs._mapping(programs._file_text(root, rel, None), rel)


# ---------------------------------------------------------------- create

def _read_yaml_file(path: str, what: str) -> dict:
    try:
        mode = os.stat(path).st_mode
    except OSError as e:
        raise GateError("%s %s: cannot read (%s)" % (what, path, _why(e))) from None
    if not stat.S_ISREG(mode):
        raise GateError("%s %s: not a regular file" % (what, path))
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
        data = yamlsub.parse(text)
    except (OSError, UnicodeDecodeError) as e:
        raise GateError("%s %s: cannot read (%s)" % (what, path, getattr(e, "strerror", None) or type(e).__name__)) \
            from None
    except yamlsub.YamlError as e:
        raise GateError("%s %s: %s%s" % (what, path, e.reason, " (line %d)" % e.line if e.line else "")) from None
    if type(data) is not dict:
        raise GateError("%s %s: the top level must be a mapping" % (what, path))
    return data


def _status_line(cells: list) -> str:
    return "| " + " | ".join(cells) + " |"


def _status_page(row: dict, program: str) -> str:
    out = ["<!-- schema: status/1 -->", _status_line(list(programs.STATUS_HEADERS)),
           "|" + "---|" * len(programs.STATUS_HEADERS)]
    for st in row["streams"]:
        sid = st["id"]
        cells = [sid, "none", programs.branch_of(program, sid), programs.worktree_of(row["worktrees"], program, sid),
                 "none", "%d" % st["estimate"], "0", "ready", "none", "none", st["purpose"]]
        out.append(_status_line(cells))
    return "\n".join(out) + "\n"


def _purpose_ok(row: dict) -> list:
    errs = []
    for st in row["streams"]:
        p = st["purpose"]
        why = ""
        if p == "" or p[0] == " " or p[-1] == " ":
            why = "must not be empty or start or end with a space"
        elif any(not 0x20 <= ord(c) <= 0x7E for c in p) or "|" in p or "\\" in p:
            why = "must be printable ASCII without '|' and a backslash (it is a status cell)"
        if why:
            errs.append("streams: stream %s purpose %s" % (st["id"], why))
    return errs


def _create(ns) -> int:
    program = ns.program
    streams_path = _once("--streams", ns.streams)
    if streams_path is None or streams_path == "":
        raise GateError("--streams is required and must not be empty")
    decision = _req("--decision", ns.decision)
    plan = _req("--plan", ns.plan)
    if _SLUG.fullmatch(plan) is None:
        raise GateError("--plan: '%s' is not a plan slug ([a-z0-9][a-z0-9-]*)" % plan)
    given_root = _root_arg(ns.root)
    root, cfg = _context(program, given_root)
    row = _read_yaml_file(streams_path, "streams file")
    sch = schema.schemas()
    _fail(["streams/1: " + e for e in schema.validate(sch["streams"], row, cfg)])
    _fail(programs.streams_errors(row, program, cfg))
    _fail(_purpose_ok(row))
    want = os.path.join(programs.worktrees_dir(root, row), program, "integration")
    top = gitinfo.toplevel(root)
    if os.path.realpath(top) != os.path.realpath(want):
        raise GateError("the top level of --root is %s; create runs in the integration worktree %s" % (top, want))
    p = cfg["paths"]
    plan_rel, bd_rel = "%s/%s.md" % (p["plans"], plan), "%s/%s/breakdown.yml" % (p["plan_state"], plan)
    plan_text = programs._fs_text(root, plan_rel)
    if plan_text is None:
        raise GateError("the plan %s is missing" % plan_rel)
    bd = programs._mapping(programs._file_text(root, bd_rel, None), bd_rel)
    bad = schema.validate(sch["breakdown"], bd, cfg)
    _fail(["breakdown/1: " + e for e in bad])
    try:
        plans = {s["id"]: checkpoints.plan_slug(s["plan"]) for s in row["streams"]}
    except ValueError as e:
        raise GateError(str(e)) from None
    errs = _pairs(breakdown.breakdown_errors(bd, plans, p["plan_state"])) + _pairs(breakdown.plan_errors(plan_text, bd))
    _fail(["breakdown: " + e for e in errs])
    try:
        depth, conc = dispatch.limits_of(cfg, os.environ)
    except ValueError as e:
        raise GateError("limits: %s" % e) from None
    errs = []
    if bd["max_concurrent"] > conc:
        errs.append("max_concurrent %d is above the effective limit %d" % (bd["max_concurrent"], conc))
    if bd["max_depth"] > depth:
        errs.append("max_depth %d is above the effective limit %d" % (bd["max_depth"], depth))
    _fail(["breakdown: " + e for e in errs])
    try:
        errs = programs.agreement_errors(row, bd, plan)
    except ValueError as e:
        errs = ["streams: %s" % e]
    _fail(errs)
    base = "%s/%s" % (p["programs"], program)
    if os.path.lexists(os.path.join(root, *base.split("/"))):
        raise GateError("%s already exists in the working tree" % base)
    for ref in ("HEAD", "refs/heads/" + cfg["base_branch"]):
        for name in ("streams.yml", "status.md", "sync-log.md", "merged.md"):
            if gitinfo.show(root, ref, "%s/%s" % (base, name)) is not None:
                raise GateError("%s already exists at %s" % (base, ref))
    recs = Store(root, "decision", cfg).load()
    ok = [r for r in recs if r.id == decision and type(r.row) is dict and r.row.get("status") == "answered"
          and r.row.get("class") == "program-create" and r.id not in decisions.superseded_ids(recs)]
    if not ok:
        raise GateError("%s is not an answered program-create decision" % decision)
    files = {"streams.yml": yamlsub.emit(row), "status.md": _status_page(row, program),
             "sync-log.md": "<!-- schema: sync-log/1 -->\n", "merged.md": "<!-- schema: merged-log/1 -->\n"}
    page = programs.status_rows(files["status.md"])
    _fail(schema.validate_markdown(sch["status"], files["status.md"]), "status.md")
    _fail(programs.status_errors(page, row, cfg=cfg, request_ids=set()), "status.md")
    for kind, name in (("sync-log", "sync-log.md"), ("merged-log", "merged.md")):
        _fail(schema.validate_markdown(sch[kind], files[name]), name)
    programs_dir = os.path.join(root, *p["programs"].split("/"))
    tmp = None
    try:
        os.makedirs(programs_dir, exist_ok=True)
        tmp = tempfile.mkdtemp(dir=programs_dir, prefix=".%s." % program, suffix=".tmp")
        for name, text in files.items():
            with open(os.path.join(tmp, name), "x", encoding="utf-8", newline="") as fh:
                fh.write(text)
        os.chmod(tmp, 0o755)
        os.rename(tmp, os.path.join(programs_dir, program))
        tmp = None
    except OSError as e:
        raise GateError("%s: cannot write (%s)" % (base, _why(e))) from None
    finally:
        if tmp is not None:
            for name in files:
                try:
                    os.unlink(os.path.join(tmp, name))
                except OSError:
                    pass
            try:
                os.rmdir(tmp)
            except OSError:
                pass
    _pushed(program)
    return 0


# ---------------------------------------------------------------- status

def _table_rows(text: str) -> tuple:
    """``(lines, first data line index)`` of the first status table."""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if line.startswith("|") and programs._cells(line) == list(programs.STATUS_HEADERS):
            return lines, n + 2
    raise GateError("status.md: has no status table")


def _page_errors(sch: dict, text: str, prog: "programs.Program", cfg: dict) -> list:
    errs = schema.validate_markdown(sch["status"], text)
    rows = programs.status_rows(text)
    rids = {r.id for r in prog.requests if type(r.id) is str}
    errs += programs.status_errors(rows, prog.streams, cfg=cfg, request_ids=rids)
    errs += programs.status_fact_errors(text, prog.streams)
    return errs


def _status(ns) -> int:
    stream = _text("STREAM", ns.stream)
    fields = {}
    for key, flag, vals in (("block", "--block", ns.block), ("next task", "--next-task", ns.next_task),
                            ("status", "--status", ns.status), ("blockers", "--blockers", ns.blockers),
                            ("pending decisions", "--pending", ns.pending), ("delivers", "--delivers", ns.delivers)):
        v = _once(flag, vals)
        if v is not None:
            fields[key] = _cell(flag, v)
    used = _once("--used", ns.used)
    if used is not None:
        if _NUM.fullmatch(used) is None:
            raise GateError("--used: must be 0 or a decimal integer without leading zeros (at most 600 digits)")
        fields["used"] = used
    if not fields:
        raise GateError("nothing to change: give at least one of --block, --next-task, --used, --status, --blockers, "
                        "--pending, --delivers")
    given_root = _root_arg(ns.root)
    root, cfg = _context(ns.program, given_root)
    prog = _load(root, cfg, ns.program)
    sch = schema.schemas()
    _fail(_page_errors(sch, prog.status_text, prog, cfg), "status.md")
    lines, start = _table_rows(prog.status_text)
    hit = None
    for n in range(start, len(lines)):
        if not lines[n].startswith("|"):
            break
        cells = programs._cells(lines[n])
        if cells and cells[0] == stream:
            hit = (n, cells)
    if hit is None:
        raise GateError("%s: is not a stream of the program" % stream)
    n, cells = hit
    for key, v in fields.items():
        cells[programs.STATUS_HEADERS.index(key)] = v
    lines[n] = _status_line(cells)
    text = "\n".join(lines)
    _fail(_page_errors(sch, text, prog, cfg), "status.md")
    _replace(root, _rel(cfg, ns.program, "status.md"), text)
    _pushed(ns.program)
    return 0


# ---------------------------------------------------------------- request

def _all_ids(root: str, cfg: dict, program: str, prog: "programs.Program") -> set:
    existing = {r.id for r in prog.requests if type(r.id) is str}
    for kind in ("decision", "finding"):
        existing.update(r.id for r in Store(root, kind, cfg).load() if type(r.id) is str)
    for cf in claims.load(root, cfg):
        existing.update(c["id"] for c in claims._claims(cf.row) if type(c.get("id")) is str)
    for other in programs.live_programs(root, cfg):
        if other != program:
            o = programs.load_program(root, cfg, other, "refs/heads/%s/integration" % other)
            existing.update(r.id for r in o.requests if type(r.id) is str)
    return existing


def _judge(prog: "programs.Program", rid: str, root: str, cfg: dict) -> list:
    bd = _breakdown_of(root, cfg, prog.streams, False)
    return ["%s: %s" % (s, r) for s, r in programs.request_errors(prog, root, cfg, bd) if s.endswith("." + rid)]


def _check_by(by: str, prog: "programs.Program") -> None:
    sids = {s["id"] for s in prog.streams.get("streams", []) if type(s) is dict and type(s.get("id")) is str}
    if by != "program" and by not in sids:
        raise GateError("--by: '%s' is neither a stream of the program nor 'program'" % by)


def _request_new(ns) -> int:
    frm, to = _req("--from", ns.frm), _req("--to", ns.to)
    if ns.file is None:
        raise GateError("--file is required (at least once)")
    files = _many("--file", ns.file)
    for f in files:
        if f.endswith("/") or "\\" in f or not schema._path_ok(f):
            raise GateError("--file: '%s' is not a normalised repository path" % f)
    interface, need, by = _req("--interface", ns.interface), _req("--need", ns.need), _req("--by", ns.by)
    given_root = _root_arg(ns.root)
    root, cfg = _context(ns.program, given_root)
    prog = _load(root, cfg, ns.program)
    _check_by(by, prog)
    rid = ids.mint(cfg["ids"]["request"], _all_ids(root, cfg, ns.program, prog), ids.utc_today(), _rng)
    row = {"schema": "request/%d" % migrations.current_version("request"), "id": rid, "from_stream": frm,
           "to_stream": to, "files": files, "interface": interface, "need": need, "status": "open",
           "raised_at": {"sha": gitinfo.head_sha(root), "by": by}}
    _fail(schema.validate(schema.schemas()["request"], row, cfg), "request")
    rel = "%s/requests/%s.yml" % ("%s/%s" % (cfg["paths"]["programs"], ns.program), rid)
    now = dataclasses.replace(prog, requests=list(prog.requests) + [store.Record(rid, row, rel)])
    _fail(_judge(now, rid, root, cfg))
    _new_file(root, rel, yamlsub.emit(row))
    _pushed(ns.program)
    sys.stdout.write(rid + "\n")
    return 0


def _request_set(ns) -> int:
    rid = _text("ID", ns.id)
    status = _req("--status", ns.status)
    commits = _many("--commit", ns.commit)
    decision = _opt("--decision", ns.decision)
    by = _req("--by", ns.by)
    given_root = _root_arg(ns.root)
    root, cfg = _context(ns.program, given_root)
    prog = _load(root, cfg, ns.program)
    _check_by(by, prog)
    found = [r for r in prog.requests if r.id == rid]
    if not found:
        raise GateError("%s: no such request in program %s" % (rid, ns.program))
    old = found[0]
    cur = old.row.get("status")
    if cur not in programs.REQUEST_TRANSITIONS or status not in programs.REQUEST_TRANSITIONS[cur]:
        raise GateError("%s: status %s to %s is not allowed (from %s: %s)" % (
            rid, cur, status, cur, ", ".join(programs.REQUEST_TRANSITIONS.get(cur, ())) or "none"))
    if status == "done" and not commits:
        raise GateError("--commit is required for status done")
    if commits and status != "done":
        raise GateError("--commit is allowed only with --status done")
    if cur == "disputed" and decision is None:
        raise GateError("--decision is required to leave disputed")
    if decision is not None and cur != "disputed":
        raise GateError("--decision is allowed only when leaving disputed")
    row = dict(old.row)
    row["status"] = status
    if status == "done":
        row["resolution"] = {"commits": commits, "at": gitinfo.head_sha(root), "by": by}
    if decision is not None:
        row["decision"] = decision
    _fail(schema.validate(schema.schemas()["request"], row, cfg), "request")
    new = store.Record(rid, row, old.file)
    now = dataclasses.replace(prog, requests=[new if r.id == rid else r for r in prog.requests])
    _fail(_judge(now, rid, root, cfg))
    _fail(["%s: %s" % (s, r) for s, r in programs.request_base_errors(now, prog) if s.endswith("." + rid)])
    _replace(root, old.file, yamlsub.emit(row))
    _pushed(ns.program)
    return 0


# ---------------------------------------------------------------- sync-log and merged

def _append(text: str, line: str, name: str) -> str:
    if not text.endswith("\n"):
        raise GateError("%s: does not end with a newline" % name)
    return text + line + "\n"


def _sync_log(ns) -> int:
    main_sha = _req("--main", ns.main)
    if _HEX40.fullmatch(main_sha) is None:
        raise GateError("--main: must be a full 40-hex commit id")
    merged_main = _req("--merged-main", ns.merged_main)
    if merged_main not in ("yes", "no"):
        raise GateError("--merged-main: must be yes or no")
    tests = _req("--tests", ns.tests)
    if tests not in ("PASS", "FAIL"):
        raise GateError("--tests: must be PASS or FAIL")
    updated, combined, questions = (_many("--updated", ns.updated), _many("--combined", ns.combined),
                                    _many("--question", ns.question))
    given_root = _root_arg(ns.root)
    root, cfg = _context(ns.program, given_root)
    prog = _load(root, cfg, ns.program)
    if not gitinfo.commit_exists(root, main_sha):
        raise GateError("--main: %s is not a commit" % main_sha)
    sids = {s["id"] for s in prog.streams["streams"]}
    for flag, vals in (("--updated", updated), ("--combined", combined)):
        for v in vals:
            if v not in sids:
                raise GateError("%s: '%s' is not a stream of the program" % (flag, v))
    known = {r.id for r in Store(root, "decision", cfg).load()}
    for q in questions:
        if q not in known:
            raise GateError("--question: %s is not a decision of the register" % q)
    line = "SYNC integration=%s main=%s merged-main=%s updated=%s combined=%s tests=%s questions=%s" % (
        gitinfo.head_sha(root), main_sha, merged_main, ",".join(sorted(updated)) or "none",
        ",".join(sorted(combined)) or "none", tests, ",".join(sorted(questions)) or "none")
    text = _append(prog.sync_log, line, "sync-log.md")
    _fail(schema.validate_markdown(schema.schemas()["sync-log"], text), "sync-log.md")
    _replace(root, _rel(cfg, ns.program, "sync-log.md"), text)
    _pushed(ns.program)
    return 0


def _merged(ns) -> int:
    line = _req("--line", ns.line)
    given_root = _root_arg(ns.root)
    parsed = checkpoints.merged_lines(_LEDGER_FIRST + "\n" + line)   # merged_lines skips the first line of a file
    if len(parsed) != 1 or parsed[0]["stream"] is None or parsed[0]["block"] is None:
        raise GateError("--line: not one MERGED line with stream and block")
    ln = parsed[0]
    root, cfg = _context(ns.program, given_root)
    prog = _load(root, cfg, ns.program)
    text = _append(prog.merged_log, line, "merged.md")
    _fail(schema.validate_markdown(schema.schemas()["merged-log"], text), "merged.md")
    sids = {s["id"] for s in prog.streams["streams"]}
    if ln["stream"] not in sids:
        raise GateError("stream %s is not a stream of streams.yml" % ln["stream"])
    body = "\n".join(text.split("\n")[1:])
    last = len(text.split("\n")) - 1
    errs = [e for e in checkpoints.ledger_errors(_LEDGER_FIRST + "\n" + body, cfg, None, sids, True)
            if e.startswith("line %d:" % last)]
    _fail(errs, "merged.md")
    bd = _breakdown_of(root, cfg, prog.streams, True)
    now = dataclasses.replace(prog, merged_log=text)
    try:
        _, _, errs = programs.counted_lines(now, root, cfg, bd)
    except ValueError as e:
        raise GateError("breakdown: %s" % e) from None
    _fail([e for e in errs if e.startswith("merged.md pr %d:" % ln["pr"])])
    _replace(root, _rel(cfg, ns.program, "merged.md"), text)
    _pushed(ns.program)
    return 0


# ---------------------------------------------------------------- argv

def _flags(p: _GateParser, once: tuple = (), many: tuple = ()) -> None:
    for f in once + many + ("--root",):
        p.add_argument(f, default=None, action="append")


def _parser(sub: str) -> _GateParser:
    p = _GateParser(prog="program " + sub, add_help=True)
    p.add_argument("items", metavar="PROGRAM", nargs="*")
    if sub == "create":
        _flags(p, ("--streams", "--decision", "--plan"))
    elif sub == "status":
        _flags(p, ("--block", "--next-task", "--used", "--status", "--blockers", "--pending", "--delivers"))
    elif sub == "request new":
        p.add_argument("--from", dest="frm", default=None, action="append")
        _flags(p, ("--to", "--interface", "--need", "--by"), ("--file",))
    elif sub == "request set":
        _flags(p, ("--status", "--decision", "--by"), ("--commit",))
    elif sub == "sync-log":
        _flags(p, ("--main", "--merged-main", "--tests"), ("--updated", "--combined", "--question"))
    else:
        _flags(p, ("--line",))
    return p


_RUN = {"create": _create, "status": _status, "request new": _request_new, "request set": _request_set,
        "sync-log": _sync_log, "merged": _merged}


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates program <sub> ...``: 2 on a usage error, 1 on a refusal, 0 after a write."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("program: argv must be a list of str\n")
        return 2
    sub = args[0] if args else ""
    if sub == "request" and len(args) > 1:
        sub, rest = "request " + args[1], args[2:]
    else:
        rest = args[1:]
    if sub not in _RUN:
        sys.stderr.write("usage: python3 -m gates program {create,status,request new,request set,sync-log,merged} "
                         "PROGRAM [options]\n")
        return 2
    try:
        p = _parser(sub)
        ns = p.parse_args(rest)
        want = 2 if sub in ("status", "request set") else 1
        if len(ns.items) != want:
            p.error("expected %s" % ("PROGRAM and %s" % ("STREAM" if sub == "status" else "ID") if want == 2 else "PROGRAM"))
        ns.program = ns.items[0]
        ns.stream = ns.id = ns.items[1] if want == 2 else None
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _RUN[sub](ns)
    except GateError as e:
        for part in str(e).split("\n"):                 # one line per reason, each escaped on its own (PG11)
            sys.stderr.write("program %s: %s\n" % (sub, safe_text(part)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
