"""Program records: names and branches, the window and period contract, path ownership, the status page and the
request rules (plan Task P2.1, part ii).

Every function here is pure over hand-built rows except the ones that name git (``worktrees_dir``, and in phase 2
``load_program``, ``live_programs``, ``request_errors``, ``counted_lines``). Path keys use ``fold_table`` only: this
module imports no Unicode database module and calls no ``str`` case method, so a key is the same on every Python 3.9+ (owner
answers Q-X35 (a), Q-FT-1 (a); decisions D-B6, D-B12). Text is compared by character class written out here
(``[0-9A-Za-z]``), never by ``isalnum`` or ``\\w``. Known limit: a code point that Unicode 13.0.0 does not assign is
compared as itself."""
import datetime
import posixpath
import re
from typing import Optional

from gates.lib import checkpoints, config, ids, migrations, schema, store
from gates.lib.fold_table import CCC, COMPOSE, DECOMP, FOLD

PROGRAM_START = "program-start"
PROGRAM_CLOSE = "program-close"
NAME_RE = "[a-z0-9][a-z0-9-]*"
_NAME = re.compile(NAME_RE)
_DIGITS = "0123456789"
_ALNUM = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
STATUS_HEADERS = ("stream", "block", "branch", "worktree", "next task", "estimate", "used", "status", "blockers",
                  "pending decisions", "delivers")
STATUS_VALUES = ("ready", "running", "blocked", "checkpoint", "merged", "closed")
REQUEST_TRANSITIONS = {"open": ("accepted", "disputed", "withdrawn"), "accepted": ("done", "withdrawn"),
                       "disputed": ("accepted", "withdrawn"), "done": (), "withdrawn": ()}
_NUMBER = re.compile(r"(0|[1-9][0-9]{0,599})")


def _is_str(x: object) -> bool:
    return type(x) is str


def _need_str(x: object, what: str) -> str:
    if type(x) is not str:
        raise ValueError("%s: must be a string" % what)
    return x


# ---------------------------------------------------------------- names and branches

def _id_problem(x: object, special: str) -> str:
    if type(x) is not str:
        return "not a string (%s)" % type(x).__name__
    if _NAME.fullmatch(x) is None:
        return "'%s' does not match %s" % (x, NAME_RE)
    if x == special:
        return "'%s' is reserved" % special
    return ""


def program_problem(name: object) -> str:
    """``""`` for ``<YYYYMMDD>-<slug>`` (a valid calendar date, the slug matching ``NAME_RE``), else the reason."""
    if type(name) is not str:
        return "program name is not a string (%s)" % type(name).__name__
    if len(name) < 10 or any(c not in _DIGITS for c in name[:8]) or name[8] != "-":
        return "program name '%s' is not <YYYYMMDD>-<slug>" % name
    if _NAME.fullmatch(name[9:]) is None or _NAME.fullmatch(name) is None:
        return "program name '%s': the slug must match %s" % (name, NAME_RE)
    try:
        datetime.date(int(name[:4]), int(name[4:6]), int(name[6:8]))
    except ValueError:
        return "program name '%s': %s is not a valid calendar date" % (name, name[:8])
    return ""


def stream_problem(id: object) -> str:
    """``""`` for a stream id (``NAME_RE``, not ``integration``, not ``records``), else the reason."""
    p = _id_problem(id, "integration")
    return p or _id_problem(id, "records")


def group_problem(id: object) -> str:
    """``""`` for a group id (``NAME_RE``, not ``main``), else the reason."""
    return _id_problem(id, "main")


def parse_branch(name: str) -> Optional[tuple]:
    """``("integration"|"records", p, None, None)``, ``("stream", p, s, None)``, ``("group", p, s, g)``; ``None``
    for a name whose first component is no program name; ``ValueError`` naming the rule for a wrong shape or id."""
    _need_str(name, "name")
    parts = name.split("/")
    if program_problem(parts[0]):
        return None
    p = parts[0]
    if len(parts) == 1:
        raise ValueError("branch '%s': a bare program name is not a program branch" % name)
    if len(parts) == 2:
        if parts[1] in ("integration", "records"):
            return (parts[1], p, None, None)
        raise ValueError("branch '%s': expected %s/integration, %s/records, %s/<stream>/main or %s/<stream>/<group>"
                         % (name, p, p, p, p))
    if len(parts) > 3:
        raise ValueError("branch '%s': too many components" % name)
    why = stream_problem(parts[1])
    if why:
        raise ValueError("branch '%s': stream id: %s" % (name, why))
    if parts[2] == "main":
        return ("stream", p, parts[1], None)
    why = group_problem(parts[2])
    if why:
        raise ValueError("branch '%s': group id: %s" % (name, why))
    return ("group", p, parts[1], parts[2])


def _check_ids(p: object, s: object, g: object) -> None:
    why = program_problem(p)
    if why:
        raise ValueError(why)
    if s is None:
        if g is not None:
            raise ValueError("a group needs its stream")
        return
    why = stream_problem(s)
    if why:
        raise ValueError("stream id: " + why)
    if g is not None:
        why = group_problem(g)
        if why:
            raise ValueError("group id: " + why)


def branch_of(p: str, s: Optional[str] = None, g: Optional[str] = None) -> str:
    """``<p>/integration`` (no stream), ``<p>/<s>/main`` or ``<p>/<s>/<g>``; ``ValueError`` for a wrong id."""
    _check_ids(p, s, g)
    if s is None:
        return "%s/integration" % p
    return "%s/%s/%s" % (p, s, g or "main")


def worktree_of(worktrees: str, p: str, s: str, g: Optional[str] = None) -> str:
    """``<worktrees>/<p>/<s>/main`` or ``<worktrees>/<p>/<s>/<g>`` (joined with ``/`` on every platform)."""
    if type(worktrees) is not str or worktrees == "":
        raise ValueError("worktrees: must be a non-empty string")
    if s is None:
        raise ValueError("stream id: required")
    _check_ids(p, s, g)
    return "%s/%s/%s/%s" % (worktrees.rstrip("/"), p, s, g or "main")


# ---------------------------------------------------------------- path keys (fold_table only)

def _decompose(ch: str, out: list) -> None:
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3:
        s = o - 0xAC00
        out.append(chr(0x1100 + s // 588))
        out.append(chr(0x1161 + (s % 588) // 28))
        if s % 28:
            out.append(chr(0x11A7 + s % 28))
        return
    d = DECOMP.get(o)
    if d is None:
        out.append(ch)
        return
    for c in d:
        _decompose(chr(c), out)


def _order(chars: list) -> list:
    out = []
    run = []
    for ch in chars:
        c = CCC.get(ord(ch), 0)
        if c:
            run.append((c, ch))
            continue
        if run:
            out.extend(x[1] for x in sorted(run, key=lambda x: x[0]))
            run = []
        out.append(ch)
    if run:
        out.extend(x[1] for x in sorted(run, key=lambda x: x[0]))
    return out


def _text_arg(s: object, fn: str) -> str:
    if type(s) is not str:
        raise TypeError("%s() argument must be str, not %s" % (fn, type(s).__name__))
    return s


def nfd(s: str) -> str:
    """Canonical decomposition (``DECOMP`` recursively, Hangul by arithmetic) in canonical order (``CCC``)."""
    _text_arg(s, "nfd")
    chars: list = []
    for ch in s:
        _decompose(ch, chars)
    return "".join(_order(chars))


def fold(s: str) -> str:
    """Each character through ``FOLD`` (full case folding, Unicode 13.0.0)."""
    _text_arg(s, "fold")
    return "".join(FOLD.get(ord(c), c) for c in s)


def _compose_pair(a: str, b: str) -> Optional[str]:
    x, y = ord(a), ord(b)
    if 0x1100 <= x <= 0x1112 and 0x1161 <= y <= 0x1175:
        return chr(0xAC00 + ((x - 0x1100) * 21 + (y - 0x1161)) * 28)
    if 0xAC00 <= x <= 0xD7A3 and (x - 0xAC00) % 28 == 0 and 0x11A8 <= y <= 0x11C2:
        return chr(x + (y - 0x11A7))
    c = COMPOSE.get((x, y))
    return None if c is None else chr(c)


def nfc(s: str) -> str:
    """Canonical composition of the NFC algorithm over ``COMPOSE`` and ``CCC`` (after ``nfd``)."""
    _text_arg(s, "nfc")
    out: list = []
    starter = -1
    last = 0
    for ch in nfd(s):
        cc = CCC.get(ord(ch), 0)
        if starter >= 0:
            blocked = len(out) - 1 != starter and last >= cc
            if not blocked:
                comp = _compose_pair(out[starter], ch)
                if comp is not None:
                    out[starter] = comp
                    continue
        out.append(ch)
        if cc == 0:
            starter = len(out) - 1
        last = cc
    return "".join(out)


def path_key(p: str) -> str:
    """``nfc(fold(nfd(p)))``: the comparison key of a path (decision D-B6: a non-``str`` is a ``TypeError``)."""
    return nfc(fold(nfd(_text_arg(p, "path_key"))))


# ---------------------------------------------------------------- events, windows

def event_problem(event: object, stream_ids: object) -> str:
    """``""`` for ``program-start``, ``program-close``, ``merged:<s>`` and ``merged:<s>/<b>`` (``<s>`` in
    ``stream_ids``, ``<b>`` in ``[0-9A-Za-z]+``), else what is wrong with it."""
    if type(stream_ids) not in (set, frozenset, dict) or any(type(x) is not str for x in stream_ids):
        raise ValueError("stream_ids: must be a set, frozenset or dict of strings")
    if type(event) is not str:
        return "event is not a str (%s)" % type(event).__name__
    if event in (PROGRAM_START, PROGRAM_CLOSE):
        return ""
    if not event.startswith("merged:"):
        return "'%s' is not an event" % event
    rest = event[7:]
    s, slash, b = rest.partition("/")
    if s not in stream_ids:
        return "'%s' is not an event (unknown stream '%s')" % (event, s)
    if slash and (b == "" or any(c not in _ALNUM for c in b)):
        return "'%s': sub-block id must be [0-9A-Za-z]+" % event
    return ""


def window_of(stream: dict, item: object) -> tuple:
    """``(from, until)`` of an owned item: a window's own bounds, a plain item's and a missing bound's from the
    stream's ``period``, whole program (``program-start`` to ``program-close``) when it has none."""
    if type(stream) is not dict:
        raise ValueError("stream: must be a mapping")
    per = stream.get("period")
    if per is None:
        lo, hi = PROGRAM_START, PROGRAM_CLOSE
    elif type(per) is dict and type(per.get("from")) is str and type(per.get("until")) is str:
        lo, hi = per["from"], per["until"]
    else:
        raise ValueError("period: needs a string from and until")
    if type(item) is str:
        return (lo, hi)
    if type(item) is not dict or type(item.get("path")) is not str or not set(item) <= {"path", "from", "until"} \
            or any(k in item and type(item[k]) is not str for k in ("from", "until")):
        raise ValueError("owns item: a string or a map of path, from and until")
    return (item.get("from", lo), item.get("until", hi))


def sub_block(task: str) -> Optional[str]:
    """The task id up to its last ``.`` (``4e.3`` is in ``4e``); ``None`` for an id without ``.``."""
    _need_str(task, "task")
    return task.rpartition(".")[0] if "." in task else None


def _check_held(held: object) -> None:
    if type(held) is not frozenset or any(type(x) is not str for x in held):
        raise ValueError("held: must be a frozenset of strings")
    if PROGRAM_START not in held or PROGRAM_CLOSE in held:
        raise ValueError("held: must hold %s and not %s" % (PROGRAM_START, PROGRAM_CLOSE))


def held_events(merged: dict, sub_blocks: dict) -> frozenset:
    """The events that hold: ``program-start``; ``merged:<s>/<b>`` for each merged sub-block; ``merged:<s>`` once
    ``<s>`` has sub-blocks and all are merged; never ``program-close``."""
    for name, d in (("merged", merged), ("sub_blocks", sub_blocks)):
        if type(d) is not dict:
            raise ValueError("%s: must be a dict" % name)
        for k, v in d.items():
            if type(k) is not str or type(v) not in (set, frozenset) or any(type(x) is not str for x in v):
                raise ValueError("%s: each stream id maps to a set of strings" % name)
            for x in v:
                if x == "" or any(c not in _ALNUM for c in x):
                    raise ValueError("%s: sub-block id '%s' must be [0-9A-Za-z]+" % (name, x))
    out = {PROGRAM_START}
    for s, bs in merged.items():
        out.update("merged:%s/%s" % (s, b) for b in bs)
        have = sub_blocks.get(s)
        if have and all(b in bs for b in have):
            out.add("merged:" + s)
    return frozenset(out)


# ---------------------------------------------------------------- entries, ownership

def _paths(cfg: Optional[dict]) -> dict:
    out = dict(config.DEFAULTS["paths"])
    if cfg is not None:
        out.update((cfg.get("paths") or {}))
    return out


def _slug_of(plan: object, plans: str) -> Optional[str]:
    """The slug of ``<plans>/<name>.md`` directly under ``plans``; ``None`` for any other form."""
    if type(plan) is not str or not plan.startswith(plans + "/"):
        return None
    rest = plan[len(plans) + 1:]
    if "/" in rest or not rest.endswith(".md") or rest == ".md":
        return None
    return rest[:-3]


def _ends(path: str) -> tuple:
    """(key without one trailing ``/``, is-directory) of an owned entry or a path."""
    k = path_key(path)
    return (k[:-1], True) if k.endswith("/") else (k, False)


def _entries_overlap(a: tuple, b: tuple) -> bool:
    (ka, da), (kb, db) = a, b
    return ka == kb or (da and kb.startswith(ka + "/")) or (db and ka.startswith(kb + "/"))


def _covers(entry: tuple, path: tuple) -> bool:
    """Does the owned entry cover the path (decision D-B4: ``a`` covers only ``a``, ``a/`` all under it)."""
    (ke, de), (kp, _) = entry, path
    return ke == kp or (de and kp.startswith(ke + "/"))


def _is_residual(st: object) -> bool:
    return type(st) is dict and st.get("residual") is True


def _stream_list(row: object) -> list:
    sts = row.get("streams") if type(row) is dict else None
    return [s for s in sts if type(s) is dict and type(s.get("id")) is str] if type(sts) is list else []


def _all_entries(row: dict, p: dict) -> list:
    """Every entry in file order: ``(stream id, path as written, key tuple, window or None, implicit)``; the
    window is ``None`` for an implicit plan workspace (always open, a whole-program entry)."""
    out = []
    for st in _stream_list(row):
        items = st.get("owns")
        for it in items if type(items) is list else []:
            try:
                win = window_of(st, it)
                path = it if type(it) is str else it["path"]
                out.append((st["id"], path, _ends(path), win, False))
            except (ValueError, TypeError):
                continue
        slug = _slug_of(st.get("plan"), p["plans"])
        if slug is not None:
            ws = "%s/%s/" % (p["plan_state"], slug)
            out.append((st["id"], ws, _ends(ws), None, True))
    return out


def _open(win: Optional[tuple], held: frozenset) -> bool:
    return win is None or (win[0] in held and win[1] not in held)


def _records(row: dict, cfg: Optional[dict], p: Optional[dict] = None) -> list:
    """Key tuples of the program records: program folder, decisions, findings, the program plan's file and its
    workspace (those owned by no stream; owner answer Q-F80W-14 (a))."""
    p = p or _paths(cfg)
    out = [_ends(p["programs"] + "/" + str(row.get("program")) + "/"), _ends(p["decisions"] + "/"),
           _ends(p["findings"] + "/")]
    plan = row.get("plan")
    if type(plan) is str:
        out.append(_ends(plan))
        slug = _slug_of(plan, p["plans"])
        if slug is not None:
            out.append(_ends("%s/%s/" % (p["plan_state"], slug)))
    return out


def _check_path(path: object) -> None:
    _need_str(path, "path")
    segs = path[:-1].split("/") if path.endswith("/") else path.split("/")
    if path == "" or "\x00" in path or path.startswith("/") or any(s in ("", ".", "..") for s in segs):
        raise ValueError("path '%s': not a repository path" % path)


def _entry_paths(cfg: Optional[dict], plan_state: str) -> dict:
    p = _paths(cfg)
    if cfg is None or "plan_state" not in (cfg.get("paths") or {}):
        p["plan_state"] = plan_state
    return p


def owner_of(streams: dict, plan_state: str, path: str, held: frozenset, *, cfg: Optional[dict] = None) -> Optional[str]:
    """The stream with an entry covering ``path`` whose window is open at ``held`` (its implicit plan workspace
    is open at every state); else the ``residual`` stream when its ``period`` is open and ``path`` is no program
    record; else ``None``. ``ValueError`` naming both streams when two open entries cover ``path``."""
    _check_held(held)
    _check_path(path)
    if type(streams) is not dict:
        raise ValueError("streams: must be a mapping")
    p = _entry_paths(cfg, plan_state)
    kp = _ends(path)
    found = []
    for sid, _, key, win, _ in _all_entries(streams, p):
        if _covers(key, kp) and _open(win, held) and sid not in found:
            found.append(sid)
    if len(found) > 1:
        raise ValueError("paths owned by streams %s and %s are both open for %s" % (found[0], found[1], path))
    if found:
        return found[0]
    for st in _stream_list(streams):
        if _is_residual(st):
            try:
                win = window_of(st, "")
            except ValueError:
                return None
            if _open(win, held) and not any(_entries_overlap(r, kp) for r in _records(streams, cfg, p)):
                return st["id"]
    return None


def shared_rule(streams: dict, path: str) -> Optional[str]:
    """The ``rule`` of the ``shared`` entry that covers ``path``, else ``None``."""
    if type(streams) is not dict:
        raise ValueError("streams: must be a mapping")
    _need_str(path, "path")
    kp = _ends(path)
    for it in streams.get("shared") or []:
        if type(it) is dict and type(it.get("path")) is str and _covers(_ends(it["path"]), kp):
            return it.get("rule")
    return None


# ---------------------------------------------------------------- streams_errors

def _worktrees_problem(w: object) -> str:
    if type(w) is not str:
        return ""
    if w == "" or w.startswith("/") or w.startswith("\\") or w[1:2] == ":":
        return "worktrees: '%s' must be a relative path (an absolute path carries a home directory)" % w
    if any(not 0x20 <= ord(c) <= 0x7E for c in w) or "\\" in w or posixpath.normpath(w) != w:
        return "worktrees: '%s' is not a normalised relative path" % w
    segs = w.split("/")
    if segs[0] != "..":
        return "worktrees: '%s' lies inside the main worktree; use a path that leaves it (../w)" % w
    if all(s == ".." for s in segs):
        return "worktrees: '%s' is the main worktree or an ancestor of it" % w
    return ""


def _find_cycle(edges: dict) -> Optional[list]:
    for start in edges:
        seen = [start]
        cur = edges.get(start)
        while cur is not None and cur in edges:
            if cur == start:
                return seen + [start]
            if cur in seen:
                break
            seen.append(cur)
            cur = edges.get(cur)
    return None


def _dfs_cycle(graph: dict) -> Optional[list]:
    state: dict = {}

    def visit(n: str, path: list) -> Optional[list]:
        state[n] = 1
        for m in graph.get(n, []):
            if state.get(m) == 1:
                return path[path.index(m):] + [m] if m in path else [m, n, m]
            if m in graph and state.get(m) is None:
                r = visit(m, path + [m])
                if r:
                    return r
        state[n] = 2
        return None

    for n in graph:
        if state.get(n) is None:
            r = visit(n, [n])
            if r:
                return r
    return None


def streams_errors(row: dict, name: str, cfg: dict, held: Optional[frozenset] = None) -> list:
    """The reasons ``row`` (a ``streams/1`` row) breaks the structural and ownership rules; ``[]`` when it keeps
    them. ``held`` ``None``: only the rules that need no event state. A field of the wrong type is skipped (the
    schema names it)."""
    _need_str(name, "name")
    if held is not None:
        _check_held(held)
    if type(row) is not dict:
        return ["streams: must be a mapping"]
    errs: list = []
    p = _paths(cfg)
    why = program_problem(name)
    if why:
        errs.append("program: folder name: " + why)
    if type(row.get("program")) is str:
        if row["program"] != name:
            errs.append("program: '%s' differs from the folder name '%s'" % (row["program"], name))
        why = program_problem(row["program"])
        if why and row["program"] != name:
            errs.append("program: " + why)
    sts = row.get("streams") if type(row.get("streams")) is list else []
    ids_seen: dict = {}
    for i, st in enumerate(sts):
        if type(st) is dict and type(st.get("id")) is str:
            why = stream_problem(st["id"])
            if why:
                errs.append("streams.%d.id: %s" % (i, why))
            if st["id"] in ids_seen:
                errs.append("streams.%d.id: duplicate stream id '%s'" % (i, st["id"]))
            ids_seen.setdefault(st["id"], i)
    known = set(ids_seen)
    deps: dict = {}
    stacks: dict = {}
    orders: dict = {}
    plans_seen: dict = {}
    prog_plan = row.get("plan")
    residuals = []
    for i, st in enumerate(sts):
        if type(st) is not dict or type(st.get("id")) is not str:
            continue
        sid = st["id"]
        d = st.get("depends_on")
        if type(d) is list:
            deps[sid] = [x for x in d if type(x) is str and x != sid]
            for x in [y for y in d if type(y) is str]:
                if x == sid or x not in known:
                    errs.append("streams.%d.depends_on: '%s' is %s" % (
                        i, x, "the stream itself" if x == sid else "not a stream of this program"))
        s_on = st.get("stacked_on")
        if type(s_on) is str:
            stacks[sid] = s_on
            if s_on == sid or s_on not in known:
                errs.append("streams.%d.stacked_on: '%s' is %s" % (
                    i, s_on, "the stream itself" if s_on == sid else "not a stream of this program"))
        mo = st.get("merge_order")
        if type(mo) is int:
            if mo in orders:
                errs.append("streams.%d.merge_order: %d repeats stream %s" % (i, mo, orders[mo]))
            orders.setdefault(mo, sid)
        pl = st.get("plan")
        if type(pl) is str:
            if _slug_of(pl, p["plans"]) is None:
                errs.append("streams.%d.plan: '%s' must be %s/<name>.md" % (i, pl, p["plans"]))
            k = path_key(pl)
            if k in plans_seen:
                errs.append("streams.%d.plan: the same plan as stream %s" % (i, plans_seen[k]))
            plans_seen.setdefault(k, sid)
            if type(prog_plan) is str and k == path_key(prog_plan):
                errs.append("streams.%d.plan: equals the program plan" % i)
        if st.get("residual") is True:
            residuals.append(sid)
            if "owns" in st:
                errs.append("streams.%d.owns: a residual stream has no owns" % i)
        elif type(st.get("owns")) is list and not st["owns"] or "owns" not in st:
            errs.append("streams.%d.owns: needs at least one entry unless the stream is residual" % i)
    if len(residuals) > 1:
        errs.append("streams: at most one residual stream (%s)" % ", ".join(residuals))
    cyc = _dfs_cycle(deps)
    if cyc:
        errs.append("streams: depends_on cycle %s" % " -> ".join(cyc))
    cyc = _find_cycle({k: v for k, v in stacks.items() if k != v})
    if cyc:
        errs.append("streams: stacked_on cycle %s" % " -> ".join(cyc))
    why = _worktrees_problem(row.get("worktrees"))
    if why:
        errs.append(why)
    errs.extend(_ownership_errors(row, cfg, held, known))
    return errs


def _bad_event(ev: object, known: set) -> str:
    return event_problem(ev, known)


def _never_opens(win: tuple) -> bool:
    return win[0] == win[1] or win[0] == PROGRAM_CLOSE or win[1] == PROGRAM_START


def _ownership_errors(row: dict, cfg: dict, held: Optional[frozenset], known: set) -> list:
    errs: list = []
    p = _paths(cfg)
    flat = []          # (sid, path, key, window or None, implicit)
    shared_keys = []
    sh = row.get("shared")
    seen_shared: dict = {}
    for it in sh if type(sh) is list else []:
        if type(it) is dict and type(it.get("path")) is str:
            k = _ends(it["path"])
            for sk, sp in shared_keys:
                if _entries_overlap(k, sk) and k == sk:
                    errs.append("shared: '%s' duplicates '%s'" % (it["path"], sp))
            shared_keys.append((k, it["path"]))
    recs = _records(row, cfg)
    for st in _stream_list(row):
        sid = st["id"]
        per = st.get("period")
        per_ok = per is None
        if type(per) is dict and type(per.get("from")) is str and type(per.get("until")) is str:
            per_ok = True
            bad = False
            for b in ("from", "until"):
                why = _bad_event(per[b], known)
                if why:
                    errs.append("period: %s: %s" % (sid, why))
                    bad = True
            if not bad and _never_opens((per["from"], per["until"])):
                errs.append("period: %s: window can never open" % sid)
            per_bad = bad
        else:
            per_bad = False
        items = st.get("owns")
        for it in items if type(items) is list else []:
            if type(it) is str:
                path, own = it, {}
            elif type(it) is dict and type(it.get("path")) is str:
                path, own = it["path"], it
            else:
                continue
            body = path[:-1] if path.endswith("/") else path
            if not schema._path_ok(body):
                errs.append("owns: %s (stream %s): not a normalised repository path" % (path, sid))
                continue
            win_bad = False
            for b in ("from", "until"):
                if type(own.get(b)) is str:
                    why = _bad_event(own[b], known)
                    if why:
                        errs.append("owns: %s (stream %s): %s" % (path, sid, why))
                        win_bad = True
            try:
                win = window_of(st, it) if per_ok else None
            except ValueError:
                win = None
            if win is not None and not win_bad and not per_bad:
                if own and _never_opens(win):
                    errs.append("owns: %s (stream %s): window can never open" % (path, sid))
            elif win is not None and (win_bad or per_bad):
                win = None
            key = _ends(path)
            if win is None:
                continue
            for r in recs:
                if _entries_overlap(key, r):
                    errs.append("owns: %s (stream %s): overlaps the program records (program folder, "
                                "decisions, findings, the program plan)" % (path, sid))
                    break
            for sk, sp in shared_keys:
                if _entries_overlap(key, sk):
                    errs.append("owns: %s (stream %s): overlaps the shared path %s" % (path, sid, sp))
                    break
            flat.append((sid, path, key, win, False))
        slug = _slug_of(st.get("plan"), p["plans"])
        if slug is not None:
            ws = "%s/%s/" % (p["plan_state"], slug)
            flat.append((sid, ws, _ends(ws), None, True))
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            a, b = flat[i], flat[j]
            if a[0] == b[0] or not _entries_overlap(a[2], b[2]):
                continue
            wa = a[3] or (PROGRAM_START, PROGRAM_CLOSE)
            wb = b[3] or (PROGRAM_START, PROGRAM_CLOSE)
            whole = (PROGRAM_START, PROGRAM_CLOSE)
            chained = wa[1] == wb[0] or wb[1] == wa[0]
            hit = (not chained) and (wa == whole or wb == whole)
            if not hit and held is not None:
                hit = _open(wa, held) and _open(wb, held)
            if hit:
                errs.append("owns: %s (stream %s) overlaps %s (stream %s)" % (a[1], a[0], b[1], b[0]))
    return errs


def worktrees_dir(root: str, row: dict) -> str:
    """The absolute directory ``worktrees`` names, resolved against the main worktree (never against ``root``).
    Needs git 2.31 (``--path-format=absolute``, in ``gitinfo.main_worktree``)."""
    from gates.lib.result import GateError
    if type(row) is not dict:
        raise GateError("worktrees_dir: the streams row must be a mapping")
    w = row.get("worktrees")
    why = _worktrees_problem(w) if type(w) is str else "worktrees: must be a string"
    if why:
        raise GateError(why)
    main = _main_worktree(root)
    out = posixpath.normpath(posixpath.join(main, w))
    if out == main or out.startswith(main.rstrip("/") + "/") or main.startswith(out.rstrip("/") + "/"):
        raise GateError("worktrees: '%s' resolves inside or above the main worktree %s" % (w, main))
    return out


def _main_worktree(root: str) -> str:
    """The one seam to git: ``gitinfo.main_worktree`` (delivery (i)); tests replace this name."""
    from gates.lib import gitinfo
    return gitinfo.main_worktree(root)


# ---------------------------------------------------------------- status page

def _error_row(reason: str, n: int) -> dict:
    return {"__error__": reason, "__line__": n}


def _cells(line: str) -> list:
    cells, cur, i = [], [], 1
    while i < len(line):
        c = line[i]
        if c == "\\" and line[i + 1:i + 2] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(cur).strip(" \t"))
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip(" \t")
    if tail:
        cells.append(tail)
    return cells


def status_rows(text: str) -> list:
    """One dict per data row of the first table whose header is the eleven headers; a row of another cell count
    is ``{"__error__": reason, "__line__": n}`` in place; ``[]`` when the header is wrong."""
    _need_str(text, "text")
    lines = text.split("\n")
    start = None
    for n, line in enumerate(lines):
        if line.startswith("|") and _cells(line) == list(STATUS_HEADERS):
            nxt = lines[n + 1] if n + 1 < len(lines) else ""
            if nxt.startswith("|") and set(nxt) <= set("|-: "):
                start = n + 2
            break
    if start is None:
        return []
    rows = []
    for n in range(start, len(lines)):
        if not lines[n].startswith("|"):
            break
        cells = _cells(lines[n])
        if len(cells) != len(STATUS_HEADERS):
            rows.append(_error_row("row has %d cells, expected %d" % (len(cells), len(STATUS_HEADERS)), n + 1))
        else:
            rows.append(dict(zip(STATUS_HEADERS, cells)))
    return rows


def _keyword_lines(text: str, word: str) -> list:
    return [(n + 1, line) for n, line in enumerate(text.split("\n")) if line.split(" ", 1)[0] == word]


def status_fact_errors(text: str, streams: dict) -> list:
    """At most one ``Batch-cut:`` and one ``Integration:`` line; ``Agent:`` ids unique; each ``stream=`` a stream
    id of ``streams`` or ``program``. Values are the investigator's, not checked here."""
    _need_str(text, "text")
    if type(streams) is not dict or type(streams.get("streams")) is not list \
            or any(type(s) is not dict for s in streams["streams"]):
        raise ValueError("streams: must be a streams row")
    errs = []
    for word in ("Batch-cut:", "Integration:"):
        ls = _keyword_lines(text, word)
        if len(ls) > 1:
            errs.append("%s more than one line (lines %s)" % (word, ", ".join(str(n) for n, _ in ls)))
    known = {s.get("id") for s in streams["streams"]} | {"program"}
    seen: dict = {}
    for n, line in _keyword_lines(text, "Agent:"):
        toks = line.split(" ")
        if len(toks) < 3 or toks[1] == "" or not all(0x21 <= ord(c) <= 0x7E for c in toks[1]):
            continue
        if toks[1] in seen:
            errs.append("Agent: id %s repeats line %d (line %d)" % (toks[1], seen[toks[1]], n))
        seen.setdefault(toks[1], n)
        for t in toks[2:]:
            if t.startswith("stream=") and t[7:] not in known:
                errs.append("Agent: line %d: stream '%s' is not a stream of the program or 'program'" % (n, t[7:]))
    return errs


def status_errors(rows: list, streams: dict, *, cfg: dict, request_ids: object) -> list:
    """The reasons the status ``rows`` break the page rules: one row per stream and no other; ``status``,
    ``branch``, ``worktree``, ``estimate``, ``used``, ``blockers`` (request ids of this program) and
    ``pending decisions`` (decision ids). ``worktree`` is ``worktree_of`` of ``worktrees`` as written."""
    if type(rows) is not list:
        raise ValueError("rows: must be a list")
    if type(streams) is not dict or type(streams.get("streams")) is not list or type(streams.get("program")) is not str \
            or any(type(s) is not dict or type(s.get("id")) is not str for s in streams["streams"]):
        raise ValueError("streams: must be a streams row")
    if type(request_ids) not in (set, frozenset, list, tuple):
        raise ValueError("request_ids: must be a collection of ids")
    prog = streams["program"]
    ids_ = {s["id"] for s in streams["streams"]}
    errs, seen = [], set()
    for r in rows:
        if type(r) is not dict or "__error__" in r or set(r) != set(STATUS_HEADERS):
            line = r.get("__line__", "?") if type(r) is dict else "?"
            why = r.get("__error__", "row keys are not the status headers") if type(r) is dict else "row is not a mapping"
            errs.append("status row at line %s: %s" % (line, why))
            continue
        s = r["stream"]
        if s not in ids_:
            errs.append("extra row: stream '%s' is not a stream of the program" % s)
            continue
        if s in seen:
            errs.append("duplicate row for stream %s" % s)
            continue
        seen.add(s)
        if r["status"] not in STATUS_VALUES:
            errs.append("stream %s: status '%s' is not one of %s" % (s, r["status"], ", ".join(STATUS_VALUES)))
        try:
            want_b = branch_of(prog, s)
            want_w = worktree_of(streams.get("worktrees"), prog, s)
        except ValueError as e:
            errs.append("stream %s: %s" % (s, e))
            continue
        if r["branch"] != want_b:
            errs.append("stream %s: branch '%s' must be %s" % (s, r["branch"], want_b))
        if r["worktree"] != want_w:
            errs.append("stream %s: worktree '%s' must be %s" % (s, r["worktree"], want_w))
        for col in ("estimate", "used"):
            if _NUMBER.fullmatch(r[col]) is None:
                errs.append("stream %s: %s '%s' is not a non-negative decimal integer" % (s, col, r[col]))
        if r["blockers"] != "none":
            for b in r["blockers"].split(","):
                if b not in request_ids or ids.id_problem(b, cfg["ids"]["request"]):
                    errs.append("stream %s: blockers '%s' is not a request of this program" % (s, b))
        if r["pending decisions"] != "none":
            for d in r["pending decisions"].split(","):
                if ids.id_problem(d, cfg["ids"]["decision"]):
                    errs.append("stream %s: pending decisions '%s' is not a decision id" % (s, d))
    for s in sorted(ids_ - seen):
        errs.append("missing row for stream %s" % s)
    return errs


# ---------------------------------------------------------------- requests

def _migrated(kind: str, row: object) -> object:
    """``migrations.migrate`` through one seam (rows pass through it before use)."""
    return migrations.migrate(kind, row)


def _known_status(st: object) -> bool:
    return type(st) is str and st in REQUEST_TRANSITIONS


def request_base_errors(now: object, base: object) -> list:
    """``(suffix, reason)`` for what a program changed in its requests against the base: ``deleted.<id>``,
    ``transition.<id>``, ``dispute.<id>``, ``immutable.<id>`` (decision D-A22: a new request must be ``open``)."""
    for x in (now, base):
        if not hasattr(x, "requests") or not hasattr(x, "name"):
            raise ValueError("now and base must be programs")
    if now.name != base.name:
        raise ValueError("now and base are different programs (%s, %s)" % (now.name, base.name))
    new = {r.id: r for r in now.requests if type(r.id) is str}
    old = {r.id: r for r in base.requests if type(r.id) is str}
    out = []
    for rid, o in old.items():
        n = new.get(rid)
        if n is None:
            out.append(("deleted." + rid, "request %s existed at the base and is gone" % rid))
            continue
        a = _migrated("request", o.row)
        b = _migrated("request", n.row)
        sa, sb = a.get("status") if type(a) is dict else None, b.get("status") if type(b) is dict else None
        if sa != sb:
            if not _known_status(sa) or not _known_status(sb):
                out.append(("transition." + rid, "status %r to %r: not a known status" % (sa, sb)))
            elif sb not in REQUEST_TRANSITIONS[sa]:
                out.append(("transition." + rid, "status %s to %s is not allowed" % (sa, sb)))
            elif sa == "disputed" and type(b) is dict and b.get("decision") is None:
                out.append(("dispute." + rid, "leaving disputed needs a decision"))
        if sa in ("done", "withdrawn") and not store._same(a, b):
            out.append(("immutable." + rid, "a %s request does not change" % sa))
    for rid, n in new.items():
        if rid not in old:
            b = _migrated("request", n.row)
            st = b.get("status") if type(b) is dict else None
            if st != "open":
                out.append(("transition." + rid, "a new request must be open, not %r" % (st,)))
    return out


# ---------------------------------------------------------------- the breakdown's event order

def _breakdown_streams(bd: object) -> list:
    if type(bd) is not dict or type(bd.get("streams")) is not list:
        raise ValueError("breakdown: needs a streams list")
    for s in bd["streams"]:
        if type(s) is not dict or type(s.get("id")) is not str:
            raise ValueError("breakdown: each stream needs a string id")
        if type(s.get("tasks")) is not list or any(type(t) is not str for t in s["tasks"]):
            raise ValueError("breakdown: stream %s needs a list of task ids" % s["id"])
    return bd["streams"]


def breakdown_sub_blocks(breakdown: dict) -> dict:
    """Each stream id of a ``breakdown/1`` row to the set of the ``sub_block``s of its ``tasks`` (an id without
    ``.`` is left out)."""
    out = {}
    for s in _breakdown_streams(breakdown):
        out[s["id"]] = {b for b in (sub_block(t) for t in s["tasks"]) if b is not None}
    return out


class _Order:
    """The sub-block order of a breakdown: ``reach[(s, b)]`` is the set of sub-blocks a path of edges reaches
    from a task of ``(s, b)`` where each edge joining two sub-blocks joins two different streams."""

    def __init__(self, bd: dict):
        self.subs = breakdown_sub_blocks(bd)
        self.task = {}
        for s in _breakdown_streams(bd):
            for t in s["tasks"]:
                b = sub_block(t)
                if b is not None:
                    self.task[t] = (s["id"], b)
        edges = bd.get("edges", [])
        if type(edges) is not list or any(type(e) is not dict or type(e.get("from")) is not str
                                          or type(e.get("to")) is not str for e in edges):
            raise ValueError("breakdown: edges must be a list of from/to maps")
        self.adj: dict = {}
        for e in edges:
            a, b = self.task.get(e["from"]), self.task.get(e["to"])
            if a is None or b is None or (a[0] == b[0] and a[1] != b[1]):
                continue
            self.adj.setdefault(e["from"], set()).add(e["to"])
        self.by_sub: dict = {}
        for t, sb in self.task.items():
            self.by_sub.setdefault(sb, []).append(t)
        self._reach: dict = {}

    def reach(self, sb: tuple) -> set:
        if sb not in self._reach:
            seen = set(self.by_sub.get(sb, []))
            todo = list(seen)
            while todo:
                for n in self.adj.get(todo.pop(), ()):
                    if n not in seen:
                        seen.add(n)
                        todo.append(n)
            self._reach[sb] = {self.task[t] for t in seen} - {sb}
        return self._reach[sb]

    def blocks_of(self, ev: str) -> list:
        """Sub-block pairs an event is made of: ``[]`` for an event that never holds."""
        s, _, b = ev[7:].partition("/")
        if b:
            return [(s, b)] if b in self.subs.get(s, ()) else []
        return [(s, x) for x in sorted(self.subs.get(s, ()))]


def _event_blocks(order: _Order, ev: object, ids_: set) -> list:
    why = event_problem(ev, ids_)
    if why:
        raise ValueError("event: " + why)
    if ev in (PROGRAM_START, PROGRAM_CLOSE):
        return []
    if "/" in ev and not order.blocks_of(ev):
        raise ValueError("event '%s': the breakdown has no such sub-block" % ev)
    return order.blocks_of(ev)


def comes_before(breakdown: dict, a: str, b: str) -> bool:
    """Whether event ``a`` comes before event ``b`` by the breakdown's edges (``ValueError`` for an event the
    row cannot name). Equal events: false."""
    order = _Order(breakdown)
    ids_ = set(order.subs)
    ba, bb = _event_blocks(order, a, ids_), _event_blocks(order, b, ids_)
    if a == b or a == PROGRAM_CLOSE or b == PROGRAM_START:
        return False
    if a == PROGRAM_START or b == PROGRAM_CLOSE:
        return True
    if not ba or not bb:
        return False
    return all(any(y in order.reach(x) for y in bb) for x in ba)


def _needs(order: _Order, ev: object, ids_: set) -> Optional[frozenset]:
    """The sub-blocks that must be in ``H`` for ``ev`` to hold; ``None`` when it can never hold."""
    if type(ev) is not str or event_problem(ev, ids_) or ev == PROGRAM_CLOSE:
        return None
    if ev == PROGRAM_START:
        return frozenset()
    blocks = order.blocks_of(ev)
    return frozenset(blocks) if blocks else None


def residual_reachable(streams: dict, breakdown: dict, plan_state: str, path: str, *, cfg: Optional[dict] = None) -> bool:
    """True when ``owner_of`` gives the residual stream ``path`` at the held events of some state the breakdown's
    order allows. Computed as the least set ``H`` of merged sub-blocks that opens the residual period and closes
    each window it has opened (polynomial; see the plan's Task P2.1)."""
    _check_path(path)
    if type(streams) is not dict:
        raise ValueError("streams: must be a mapping")
    p = _entry_paths(cfg, plan_state)
    res = next((s for s in _stream_list(streams) if _is_residual(s)), None)
    if res is None:
        return False
    order = _Order(breakdown)
    ids_ = set(order.subs)
    kp = _ends(path)
    entries = [e for e in _all_entries(streams, p) if e[0] != res["id"] and _covers(e[2], kp)]
    own = any(e[0] == res["id"] and e[4] and _covers(e[2], kp) for e in _all_entries(streams, p))
    per = window_of(res, "")
    pf = _needs(order, per[0], ids_)
    if not own and pf is None:
        return False
    allb = [(s, b) for s in order.subs for b in order.subs[s]]
    H: set = set(pf or ())

    def close() -> None:
        changed = True
        while changed:
            changed = False
            for x in allb:
                if x not in H and order.reach(x) & H:
                    H.add(x)
                    changed = True

    close()
    grown = True
    while grown:
        grown = False
        for e in entries:
            win = e[3] or (PROGRAM_START, PROGRAM_CLOSE)
            f, u = _needs(order, win[0], ids_), _needs(order, win[1], ids_)
            if f is not None and f <= H and u is not None and not u <= H:
                H |= u
                close()
                grown = True

    def holds(ev: str) -> bool:
        n = _needs(order, ev, ids_)
        return n is not None and n <= H

    for e in entries:
        win = e[3] or (PROGRAM_START, PROGRAM_CLOSE)
        if holds(win[0]) and not holds(win[1]):
            return False
    if own:
        return True
    if not (holds(per[0]) and not holds(per[1])):
        return False
    return not any(_entries_overlap(r, kp) for r in _records(streams, cfg, p))


# ---------------------------------------------------------------- create's agreement (decision D-A26)

def _item_set(stream: dict, key: str) -> set:
    out = set()
    items = stream.get(key)
    for it in items if type(items) is list else []:
        try:
            path = it if type(it) is str else it["path"]
            out.add((path,) + window_of(stream, it))
        except (ValueError, KeyError, TypeError):
            out.add(("?", repr(it)))
    return out


def _period_of(stream: dict) -> tuple:
    per = stream.get("period")
    if type(per) is dict:
        return (per.get("from"), per.get("until"))
    return (PROGRAM_START, PROGRAM_CLOSE)


def agreement_errors(streams_row: dict, breakdown_row: dict, plan_slug: str) -> list:
    """``create``'s agreement of ``streams.yml`` with the program plan's ``breakdown.yml`` and the stacked-order
    check (plan Task P2.2, owner answers Q-F80W-9 (a), Q-F80a-1 (a), Q-RD8-1 (a)): same stream ids, each stream's
    ``paths`` equal to its ``owns`` as (path, window) sets, ``residual`` and ``period`` equal (absent is
    ``program-start`` to ``program-close``), the breakdown's ``plan`` and the streams file's ``plan`` slug equal to
    ``plan_slug``, and for ``stacked_on`` streams every ``merged:<s>/<b>`` ordered after ``merged:<t>`` by
    ``comes_before``. ``done`` is not compared. Each reason names ``streams`` (or ``stacked_on``)."""
    _need_str(plan_slug, "plan_slug")
    errs = []
    sts = {s["id"]: s for s in _stream_list(streams_row)}
    bds = {s["id"]: s for s in _stream_list(breakdown_row)}
    for sid in sorted(set(sts) - set(bds)):
        errs.append("streams: stream %s is not in the breakdown" % sid)
    for sid in sorted(set(bds) - set(sts)):
        errs.append("streams: stream %s is in the breakdown but not in streams.yml" % sid)
    for sid in sts:
        if sid not in bds:
            continue
        a, b = sts[sid], bds[sid]
        if _item_set(a, "owns") != _item_set(b, "paths"):
            errs.append("streams: stream %s: owns differs from the breakdown's paths" % sid)
        if (a.get("residual") is True) != (b.get("residual") is True):
            errs.append("streams: stream %s: residual differs from the breakdown" % sid)
        if _period_of(a) != _period_of(b):
            errs.append("streams: stream %s: period differs from the breakdown" % sid)
    if breakdown_row.get("plan") != plan_slug:
        errs.append("streams: the breakdown's plan '%s' differs from the program plan '%s'"
                    % (breakdown_row.get("plan"), plan_slug))
    try:
        pslug = checkpoints.plan_slug(streams_row.get("plan"))
    except ValueError:
        pslug = None
    if pslug != plan_slug:
        errs.append("streams: the plan of streams.yml ('%s') differs from the program plan '%s'"
                    % (streams_row.get("plan"), plan_slug))
    for sid, a in sts.items():
        t = a.get("stacked_on")
        if type(t) is not str or t not in bds or sid not in bds:
            continue
        try:
            subs = sorted(breakdown_sub_blocks(breakdown_row).get(sid, ()))
            for b in subs:
                if not comes_before(breakdown_row, "merged:" + t, "merged:%s/%s" % (sid, b)):
                    errs.append("stacked_on: stream %s sub-block %s is not ordered after merged:%s by the "
                                "breakdown's edges" % (sid, b, t))
        except ValueError as e:
            errs.append("stacked_on: stream %s: %s" % (sid, e))
    return errs
