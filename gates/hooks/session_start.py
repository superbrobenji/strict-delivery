"""SessionStart handler (Task 3a.2, plan P:3474-3484): the session's context lines and the reset of the live subagent
counts. It refuses nothing: every problem is a ``FAIL hook.session-start.<what>: <reason>`` line, and the hook exits 0.

The ``text`` lines, in order: the reset FAIL line (when there is one); the header; ``regenerate: PASS`` or its FAIL line;
the handoff lines (sorted by path); the resume lines (handoff order, then each live program); the open decisions; the
active overrides; the load line; the skill line. With a config error the lines are the reset FAIL line (when there is
one), the config FAIL line and the skill line. Standard library only."""
from __future__ import annotations

import os
import re
import stat

from gates import gate_checkpoint
from gates.lib import checkpoints, decisions, gitinfo, programs, schema, session
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import GateError, safe_text
from gates.lib.store import Store
from gates.tools import index

SKILL_REL = "skills/strict-delivery/SKILL.md"
DOCTOR = "; run /strict-delivery:doctor"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_KEEP_SOURCES = ("clear", "compact")   # every other source, absent and unknown included, resets (plan P:3484)


class _Checked(Exception):
    """Raised inside ``session.locked`` so that the state is read and checked but never written back."""


def why(e: BaseException) -> str:
    """The escaped one-line reason of ``e``."""
    if isinstance(e, GateError):
        return safe_text(e)
    return safe_text("%s: %s" % (type(e).__name__, e))


def skill_name(framework_dir: str) -> tuple:
    """``(name, reason)``: line 2 of ``<framework_dir>/skills/strict-delivery/SKILL.md`` after ``name: ``, or ``None``
    and the (already escaped) reason when the file is missing or malformed."""
    path = os.path.join(framework_dir, *SKILL_REL.split("/"))
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return None, "%s is missing" % SKILL_REL
    except OSError as e:
        return None, "%s cannot be read (%s)" % (SKILL_REL, safe_text(e.strerror or type(e).__name__))
    if not stat.S_ISREG(mode):
        return None, "%s is not a regular file" % SKILL_REL
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        return None, "%s cannot be read (%s)" % (SKILL_REL, safe_text(e.strerror or type(e).__name__))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "%s is not valid UTF-8" % SKILL_REL
    lines = text.split("\n")
    if len(lines) < 2:
        return None, "%s has no line 2" % SKILL_REL
    if not lines[1].startswith("name: "):
        return None, "line 2 of %s does not start with 'name: '" % SKILL_REL
    name = lines[1][len("name: "):]
    if name == "":
        return None, "the skill name in %s is empty" % SKILL_REL
    if _NAME.match(name) is None:
        return None, "the skill name '%s' in %s does not match [a-z0-9][a-z0-9-]*" % (safe_text(name), SKILL_REL)
    return name, ""


def _reset_lines(ctx: HookContext) -> list:
    source = ctx.raw.get("source")
    try:
        if type(source) is str and source in _KEEP_SOURCES:
            try:
                with session.locked(ctx.env, ctx.session_id):
                    raise _Checked()
            except _Checked:
                pass
            return []
        moved = session.reset(ctx.env, ctx.session_id)
    except session.SessionUnavailable as e:
        return ["FAIL hook.session-start.session: " + safe_text(e)]
    if moved is None:
        return []
    path = os.path.join(session.session_dir(ctx.env), ctx.session_id + ".yml")
    return ["FAIL hook.session-start.session: %s was unreadable and was moved to %s; live subagent counts restart at "
            "zero" % (safe_text(path), safe_text(moved))]


def _handoffs(root: str, cfg: dict) -> tuple:
    """``(lines, parsed)``: the handoff or FAIL line of each ``<plan_state>/*/handoff.md`` in path order, and
    ``[(rel, row)]`` of the valid ones."""
    plan_state = cfg["paths"]["plan_state"]
    try:
        names = os.listdir(os.path.join(root, *plan_state.split("/")))
    except (FileNotFoundError, NotADirectoryError):
        return [], []
    except OSError as e:
        return ["FAIL hook.session-start.handoff.%s: cannot list the directory (%s)"
                % (safe_text(plan_state), safe_text(e.strerror or type(e).__name__))], []
    lines, parsed, sch = [], [], None
    for rel in sorted("%s/%s/handoff.md" % (plan_state, n) for n in names):
        try:
            mode = os.lstat(os.path.join(root, *rel.split("/")[:-1])).st_mode
        except OSError:
            continue
        if not (stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
            continue
        text, problem = gate_checkpoint._read_text(root, rel)
        if text is None:
            if problem != "%s: missing" % rel:
                lines.append("FAIL hook.session-start.handoff.%s: %s" % (safe_text(rel), safe_text(problem)))
            continue
        if sch is None:
            sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "handoff.yml"))
        reasons = list(schema.validate_front_matter(sch, text, cfg))
        row = None
        try:
            row = checkpoints.parse_handoff(text)
        except ValueError as e:
            reasons = reasons or [str(e)]
        if row is not None:
            reasons += checkpoints.handoff_errors(row, cfg)
        if reasons:
            lines.append("FAIL hook.session-start.handoff.%s: %s" % (safe_text(rel), safe_text("; ".join(reasons))))
            continue
        lines.append("handoff %s: %s" % (safe_text(rel), safe_text(row["resume"])))
        parsed.append((rel, row))
    return lines, parsed


def _resume_line(rel: str, row: dict) -> str:
    reads = row.get("required_reads")
    return ("resume %s: before any edit or dispatch, invoke the skills %s; read the default load and the context list, "
            "the %d required reads and the ledger from line %d; dispatch the read-only investigator check; ledger the "
            "Resume check line; report, and stop on any difference (session-resume design §3.1)"
            % (safe_text(rel), safe_text(", ".join(row["skills"])), len(reads) if reads is not None else 0,
               row["ledger_from"]))


def _first_line(value: object) -> str:
    return safe_text(value.split("\n")[0]) if type(value) is str else ""


def _decision_lines(root: str, cfg: dict) -> list:
    try:
        records = Store(root, "decision", cfg).load()
    except Exception as e:
        return ["FAIL hook.session-start.decisions: " + why(e)]
    gone = decisions.superseded_ids(records)
    rows = sorted(((r.id, r.row) for r in records if type(r.id) is str and type(r.row) is dict), key=lambda t: t[0])
    lines = ["open decision %s: %s" % (safe_text(i), _first_line(row.get("question")))
             for i, row in rows if row.get("status") == "open"]
    for i, row in rows:
        target = row.get("overrides")
        if (row.get("class") == decisions.CLASS_OVERRIDE and row.get("status") == "answered"
                and type(target) is str and target != "" and i not in gone):
            rule = row.get("rule")
            lines.append("override %s by %s: %s" % (safe_text(target), safe_text(i),
                                                    _first_line(rule if type(rule) is str and rule != "" else row.get("question"))))
    return lines


def handle(ctx: HookContext) -> Outcome:
    lines = _reset_lines(ctx)
    name, reason = skill_name(ctx.framework_dir)
    skill = "Invoke the %s skill before any change." % name if name is not None else "FAIL hook.session-start.skill: " + reason
    if ctx.cfg is None:
        lines.append("FAIL hook.session-start.config: %s%s" % (ctx.cfg_error or "the config is unavailable", DOCTOR))
        lines.append(skill)
        return Outcome(text=lines)
    cfg, fails = ctx.cfg, []
    try:
        current = gitinfo.current_branch(ctx.root)
        branch = "detached" if current is None else safe_text(current)
    except Exception as e:
        branch = "unknown"
        fails.append("FAIL hook.session-start.branch: " + why(e))
    live = []
    try:
        live = programs.live_programs(ctx.root, cfg)
        names = ", ".join(safe_text(p) for p in live) if live else "none"
    except Exception as e:
        names = "unknown"
        fails.append("FAIL hook.session-start.programs: " + why(e))
    lines.append("strict-delivery: profile %s; branch %s; base %s; live programs: %s"
                 % (safe_text(cfg["profile"]), branch, safe_text(cfg["base_branch"]), names))
    lines.extend(fails)
    try:
        index.regenerate(ctx.root, cfg)
        lines.append("regenerate: PASS")
    except Exception as e:
        lines.append("FAIL hook.session-start.index: " + why(e))
    handoff_lines, parsed = _handoffs(ctx.root, cfg)
    lines.extend(handoff_lines)
    lines.extend(_resume_line(rel, row) for rel, row in parsed)
    lines.extend("resume program %s: before any edit or dispatch, re-read the overview and the status page on %s/integration "
                 "and dispatch the read-only investigator check of the program facts" % (safe_text(p), safe_text(p))
                 for p in live)
    lines.extend(_decision_lines(ctx.root, cfg))
    lines.append("load: %s/in-force.md and the open decisions above" % safe_text(cfg["paths"]["decisions"]))
    lines.append(skill)
    return Outcome(text=lines)
