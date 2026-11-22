"""Tool ``continue``: render the continuation dispatch of a handed-off controller (plan Task P4.2; session-resume design
3.8; binding decisions D-Q1..D-Q10 of stream a14).

``python3 -m gates continue --plan SLUG [--ref REF] [--prompts DIR] [--root DIR] [--input-json FILE --dispatcher ID
--depth N --live-children N --live-total N]`` reads the handoff of plan ``SLUG`` and the ledger it names (the working
tree, or ``REF``), refuses while children are listed, a question has no answered decision, an input or a tier is
invalid, and otherwise prints one dispatch prompt in the spec section 10 grammar. The whole text is built first and
written once: a refusal prints nothing on stdout and writes nothing. Every reason of every failing stage goes to
stderr, one ``continue: <reason>`` line each, exit 1; exit 2 on a usage error. With ``--input-json`` the
``gate_dispatch`` input object is also written (exclusive create) after ``gate_dispatch.check`` accepted the prompt.

No ``str.lower``, ``isprintable``, ``isalnum``, ``isdigit`` or ``strip`` decides a verdict (ordinal ranges and ASCII
patterns only), and no ``int()`` reads text longer than ``dispatch.MAX_DIGITS``, so the verdicts are the same on every
interpreter. Standard library only; every git read goes through ``gitinfo``."""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import sys
import tempfile
from typing import Optional

from gates import gate_dispatch
from gates.lib import batch, checkpoints, config, decisions, dispatch, gitinfo, ids, programs
from gates.lib.result import GateError, _GateParser, safe_text
from gates.tools import index, questions_cli
from gates.tools.claims_cli import _once, _root_arg

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_COUNT = re.compile(r"0|[1-9][0-9]{0,%d}" % (dispatch.MAX_DIGITS - 1))
_MISSING = (errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG)
_FLAGS = ("--plan", "--ref", "--prompts", "--root", "--input-json", "--dispatcher", "--depth", "--live-children",
          "--live-total")
_COUNT_FLAGS = ("--depth", "--live-children", "--live-total")
_USAGE = ("usage: python3 -m gates continue --plan SLUG [--ref REF] [--prompts DIR] [--root DIR] "
          "[--input-json FILE --dispatcher ID --depth N --live-children N --live-total N]\n")
_REPORT = "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED"


class _Usage(Exception):
    """A usage error (exit 2): the message goes to stderr after the usage line."""


def _ascii(s: str) -> bool:
    return all(" " <= c <= "~" for c in s)


def _path_flag(flag: str, v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if v == "":
        raise GateError("%s: must not be empty" % flag)
    if not _ascii(v):
        raise GateError("%s: must be printable ASCII on one line" % flag)
    return v


# ---------------------------------------------------------------- reading the sources

def _read_bytes(root: str, rel: str) -> tuple:
    """``(data, problem)`` of ``rel`` (``/``-joined) below ``root``; the rule of ``gate_checkpoint._read_bytes``, copied
    (decision D-Q3): every component is looked at with ``lstat`` and none is followed, the last is a regular file."""
    parts = rel.split("/")
    path = root
    for i, part in enumerate(parts):
        path = os.path.join(path, part)
        shown = "/".join(parts[:i + 1])
        try:
            mode = os.lstat(path).st_mode
        except OSError as e:
            if e.errno in _MISSING:
                return None, "%s: missing" % rel
            return None, "%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)
        if i < len(parts) - 1:
            if stat.S_ISLNK(mode):
                return None, "%s: is a symlink; directories must be real directories" % shown
            if not stat.S_ISDIR(mode):
                return None, "%s: not a directory" % shown
        elif not stat.S_ISREG(mode):
            return None, "%s: is not a regular file (a directory, symlink or other entry is never followed)" % rel
    try:
        with open(path, "rb") as fh:
            return fh.read(), ""
    except OSError as e:
        return None, "%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)


def _read_text(root: str, ref: Optional[str], rel: str) -> tuple:
    """``(text, problem)``: from the working tree of ``root`` (``ref`` None) or from ``ref``."""
    if ref is not None:
        try:
            text = gitinfo.show(root, ref, rel)
        except GateError as e:
            return None, "%s: %s" % (rel, e)
        return (text, "") if text is not None else (None, "%s: missing at %s" % (rel, ref))
    data, problem = _read_bytes(root, rel)
    if data is None:
        return None, problem
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "%s: not valid UTF-8" % rel


def _ledger(root: str, cfg: dict, ref: Optional[str], row: dict) -> tuple:
    """``(tail lines or None, reasons)`` of the ledger the handoff names: the lines after the last conforming
    ``CHECKPOINT``."""
    led = row["ledger"]
    text, problem = _read_text(root, ref, led)
    if text is None:
        return None, [problem]
    reasons = ["%s: %s" % (led, r) for r in checkpoints.ledger_errors(text, cfg)]
    marks = checkpoints.checkpoint_lines(text)
    if not marks:
        reasons.append("%s: no conforming CHECKPOINT line" % led)
    if reasons:
        return None, reasons
    tail = text.split("\n")[marks[-1]["line"]:]
    if tail and tail[-1] == "":
        tail.pop()
    for n, line in enumerate(tail, marks[-1]["line"] + 1):
        if line.startswith("## "):
            reasons.append("%s: line %d begins with '## ' and would be a heading of the prompt" % (led, n))
        elif line.startswith(dispatch.PROGRAM_PREFIX) or line.startswith(dispatch.STREAM_PREFIX):
            reasons.append("%s: line %d begins with '%s' and would be read as the Brief's program or stream line"
                           % (led, n, line.split(" ", 1)[0] + " "))
    return (None if reasons else tail), reasons


# ---------------------------------------------------------------- the stages

def _questions(root: str, cfg: dict, slug: str, row: dict, handoff: str, errors: list) -> str:
    """The answer blocks (one per distinct source, in order of first appearance) of ``row``'s questions; each question
    without an answered decision is an error naming its qid."""
    qs = row["questions"]
    if not qs:
        return ""
    try:
        records = index._records(root, "decision", cfg, decisions.validate)
    except GateError as e:
        errors.append("register: %s" % e)
        return ""
    tags, sources, states, bad = {}, [], [], False
    for q in qs:
        src = q.get("source", handoff)
        if src not in sources:
            sources.append(src)
        try:
            t = questions_cli.tag(slug, q["qid"])
            state = questions_cli.question_state(records, t)
        except (GateError, ValueError) as e:
            errors.append("question %s: %s" % (q["qid"], e))
            bad = True
            continue
        tags[t] = q
        states.append((q, src, state))
        if state[0] == "pending":
            errors.append("question %s: unanswered (no decision carries %s)" % (q["qid"], t))
            bad = True
        elif state[0] == "asked":
            errors.append("question %s: asked, not answered (%s)" % (q["qid"], state[1]))
            bad = True
    if bad:
        return ""
    mine = [(r.id, r.row) for r in records
            if type(r.row.get("topics")) is list and any(t in tags for t in r.row["topics"])]
    date = ids.utc_today().isoformat()
    blocks = {}
    for src in sources:
        try:
            blocks[src] = batch.render_answers(mine, src, date)
        except GateError as e:
            errors.append("answers for %s: %s" % (src, e))
            return ""
    for q, src, (_, rid) in states:
        if not any(ln.startswith(rid + ": ") for ln in blocks[src].split("\n")):
            errors.append("question %s: the answered decision %s is not printed for source %s (its source differs)"
                          % (q["qid"], rid, src))
    return "".join(blocks[s] for s in sources)


def _model(cfg: dict, role: str, errors: list) -> Optional[str]:
    """The model of ``role``'s resolved tier, or None with the reasons in ``errors`` (plan :3144, Q-B2plan-21)."""
    top = cfg.get("top_tier_roles", dispatch.DEFAULT_TOP_TIER_ROLES)
    if type(top) not in (list, tuple) or any(type(x) is not str or x == "" for x in top):
        errors.append("config top_tier_roles must be a list of non-empty strings")
        return None
    try:
        need = dispatch.min_tier(role, cfg)
    except ValueError as e:
        errors.append(str(e))
        return None
    tier = "tier%d" % need
    tiers = cfg["models"]["tiers"]
    model = tiers.get(tier)
    if model is None:
        errors.append("%s of role %s has no model in models.tiers" % (tier, role))
        return None
    if type(model) is not str or model == "" or not _ascii(model) or model[0] == " " or model[-1] == " " \
            or model.startswith("## "):
        errors.append("models.tiers.%s: must be one line of printable ASCII, without a leading or trailing space and "
                      "not beginning with '## '" % tier)
        return None
    try:
        dispatch.tier_of(model, cfg)
    except ValueError as e:
        errors.append(str(e))
        return None
    return model


def _status_row(root: str, cfg: dict, program: str, stream: str, errors: list) -> Optional[str]:
    """The raw status line of ``stream`` on the integration tip of ``program`` (decisions D-Q8)."""
    try:
        prog = programs.load_program(root, cfg, program, "refs/heads/" + programs.branch_of(program))
    except GateError as e:
        errors.append("program %s: %s" % (program, e))
        return None
    rows = programs.status_rows(prog.status_text)
    lines = prog.status_text.split("\n")
    start = None
    for n, line in enumerate(lines):
        if line.startswith("|") and programs._cells(line) == list(programs.STATUS_HEADERS):
            start = n + 2
            break
    if start is None or len(rows) > len(lines) - start:
        errors.append("program %s: the status page has no status table" % program)
        return None
    hits, own = [], []
    for i, r in enumerate(rows):
        if "__error__" in r:
            own.append("program %s: status page line %d: %s" % (program, r["__line__"], r["__error__"]))
        elif r[programs.STATUS_HEADERS[0]] == stream:
            hits.append(lines[start + i])
    if not own and not hits:
        own.append("program %s: the status page has no row for stream %s" % (program, stream))
    if not own and len(hits) > 1:
        own.append("program %s: the status page has %d rows for stream %s" % (program, len(hits), stream))
    errors.extend(own)
    return None if own else hits[0]


def _block(prompts: str, role: str, errors: list) -> Optional[str]:
    """The bytes of ``<prompts>/<role>.md``, as ``dispatch.block_errors`` reads them (a symlink is followed); a
    non-regular file is refused before it is opened."""
    path = os.path.join(prompts, role + ".md")
    try:
        mode = os.stat(path).st_mode
        if not stat.S_ISREG(mode):
            errors.append("strict block file %s is not a regular file" % path)
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        errors.append("strict block file %s cannot be read (%s)" % (path, e.strerror or type(e).__name__))
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("strict block file %s is not valid UTF-8" % path)
        return None


def _budget(row: dict, errors: list) -> Optional[tuple]:
    b = row.get("budget")
    out = []
    for k in ("tokens", "minutes"):
        v = b.get(k) if type(b) is dict else None
        if type(v) is not int or v < 1 or v >= 10 ** dispatch.MAX_DIGITS:
            errors.append("budget.%s: must be an integer from 1 to %d digits" % (k, dispatch.MAX_DIGITS))
            return None
        out.append(v)
    return tuple(out)


# ---------------------------------------------------------------- the run

def _flags(ns) -> dict:
    """Every flag checked before the first git or file call."""
    v = {f: _once(f, getattr(ns, f[2:].replace("-", "_"))) for f in _FLAGS}
    if v["--plan"] is None:
        raise _Usage("--plan is required")
    if _NAME.fullmatch(v["--plan"]) is None:
        raise GateError("--plan: must match [a-z0-9][a-z0-9-]*")
    for f in ("--ref", "--prompts", "--input-json"):
        v[f] = _path_flag(f, v[f])
    v["--root"] = _root_arg([v["--root"]] if v["--root"] is not None else None)
    given = [f for f in ("--dispatcher",) + _COUNT_FLAGS if v[f] is not None]
    if v["--input-json"] is None and given:
        raise GateError("%s: only valid with --input-json" % ", ".join(given))
    if v["--input-json"] is not None:
        for f in ("--dispatcher",) + _COUNT_FLAGS:
            if v[f] is None:
                raise GateError("%s is required with --input-json" % f)
        d = v["--dispatcher"]
        if not (_ascii(d) and (d == "session" or d in dispatch.ROLES)):
            raise GateError("--dispatcher: must be 'session' or a role id")
        for f in _COUNT_FLAGS:
            if _COUNT.fullmatch(v[f]) is None:
                raise GateError("%s: must be a decimal integer from 0 to %d digits (digits 0-9 only)"
                                % (f, dispatch.MAX_DIGITS))
    return v


def _run(ns) -> int:
    v = _flags(ns)
    slug, ref, prompts = v["--plan"], v["--ref"], v["--prompts"]
    root = index._root(v["--root"])
    cfg = config.load(root)
    if ref is not None and not gitinfo.commit_exists(root, ref):
        raise GateError("--ref: %s is not a commit" % ref)
    if prompts is None:
        prompts = gate_dispatch._default_prompts()
    rel = "%s/%s/handoff.md" % (cfg["paths"]["plan_state"], slug)
    text, problem = _read_text(root, ref, rel)
    if text is None:
        raise GateError(problem)
    row, reasons = questions_cli._validate(cfg, text, slug, None, None)
    reasons = ["%s: %s" % (rel, r) for r in reasons]
    if not reasons:
        tail, reasons = _ledger(root, cfg, ref, row)
    if reasons:
        raise GateError("\n".join(reasons))
    errors: list = []
    if row["live_subagents"]:
        errors.append("live_subagents is not empty: continuing would orphan %s"
                      % ", ".join(s["agent"] for s in row["live_subagents"]))
    answers = _questions(root, cfg, slug, row, rel, errors)
    role = row["role"]
    model = _model(cfg, role, errors)
    budget = _budget(row, errors)
    status = None
    if "program" in row:
        status = _status_row(root, cfg, row["program"], row["stream"], errors)
    block = _block(prompts, role, errors)
    live = None
    if v["--input-json"] is not None:
        try:
            live = bool(programs.live_programs(root, cfg))
        except GateError as e:
            errors.append("program_live: %s" % e)
    if errors:
        raise GateError("\n".join(errors))
    brief = ["Continue %s at %s; branch %s; head %s" % (row["plan"], row["next_task"], row["branch"], row["head"]),
             "Handoff: " + rel]
    if tail:
        brief += ["Ledger since the last checkpoint:"] + tail
    if status is not None:
        brief += ["Status row:", status]
    if answers:
        brief += answers.split("\n")[:-1]
    if "program" in row:
        brief += ["program: " + row["program"], "stream: " + row["stream"]]
    findings = row["findings_in_flight"]
    parts = ["## Role", role, "## Brief"] + brief + ["## Findings"] + (findings if findings else ["None."])
    parts += ["## Claims", "None.", "## Budget: tokens=%d minutes=%d" % budget, "## Model", model,
              "## Report", _REPORT, "## Strict block"]
    out = "\n".join(parts) + "\n\n" + block + "\n## Task\nResume at %s from the handoff; nothing continues from " \
        "inherited memory.\n" % row["next_task"]
    try:
        out.encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        raise GateError("the prompt cannot be encoded for stdout (%s)" % (sys.stdout.encoding or "utf-8")) from None
    path = v["--input-json"]
    if path is not None:
        data = {"prompt": out, "model": model, "program_live": live,
                "dispatcher": {"id": v["--dispatcher"], "depth": int(v["--depth"]),
                               "live_children": int(v["--live-children"]), "live_total": int(v["--live-total"])}}
        body = json.dumps(data, sort_keys=True) + "\n"
        _self_check(root, prompts, body)
        _create(path, body)
    sys.stdout.write(out)
    return 0


def _self_check(root: str, prompts: str, body: str) -> None:
    """Run ``gate_dispatch.check`` on the input object in a private temporary directory (decision D-Q5)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "input.json")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
        res = gate_dispatch.check(["--root", root, "--prompts", prompts, "--input", tmp])
    bad = ["%s: %s" % (ln.id, ln.reason) for ln in res.lines if ln.status != "PASS"]
    if bad or not res.ok():
        raise GateError("the prompt fails gate_dispatch:\n" + "\n".join("FAIL " + b for b in bad))


def _create(path: str, body: str) -> None:
    created = False
    try:
        with open(path, "x", encoding="utf-8", newline="") as fh:
            created = True
            fh.write(body)
    except OSError as e:
        left = ""
        if created:  # the file is ours (exclusive create): a partial one is removed, as store.create does
            try:
                os.unlink(path)
            except OSError:
                left = "; the partial file could not be removed: %s" % path
        raise GateError("--input-json: %s cannot be created (%s)%s"
                        % (path, e.strerror or type(e).__name__, left)) from None


def _parser() -> _GateParser:
    p = _GateParser(prog="continue", add_help=True)
    for f in _FLAGS:
        p.add_argument(f, default=None, action="append")
    return p


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates continue ...``: 2 on a usage error, 1 on a refusal, 0 otherwise."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("continue: argv must be a list of str\n")
        return 2
    if not args:
        sys.stderr.write(_USAGE)
        return 2
    try:
        ns = _parser().parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _run(ns)
    except _Usage as e:
        sys.stderr.write(_USAGE + "continue: %s\n" % e)
        return 2
    except (GateError, ValueError) as e:
        for part in str(e).split("\n"):                 # one line per reason, each escaped on its own
            sys.stderr.write("continue: %s\n" % safe_text(part))
        return 1


if __name__ == "__main__":
    sys.exit(main())
