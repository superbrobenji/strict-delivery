"""The stream breakdown (``breakdown/1``) checks of a program start (plan Task P2.2, owner answer Q-PL-1 (a); decisions
D-Q14 to D-Q18 of its table, D-B7, D-B9, D-A26).

Standard library only. ``breakdown_errors(row, plans=None, plan_state=None)`` judges a ``breakdown/1`` row that has
passed its schema (a wrong-typed value inside the row is skipped where the schema names it); ``plan_errors(plan_text,
row)`` refuses an outline-only plan. Both return ``(suffix, reason)`` pairs. Headings are read with the regular
expressions of ``checkpoints.block_ids`` (one definition), by ASCII classes only, so the verdict is the same on
every interpreter. No ``int()`` runs on text here.
"""
from __future__ import annotations

import bisect
import re
from typing import Optional

from gates.lib import checkpoints, config, programs

_TASK_ID = re.compile(r"[0-9A-Za-z]+\.[0-9A-Za-z]+")
_TASK_HEAD = re.compile(r"#{3,4} Task ([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*):")
_HEAD = re.compile(r"(#{1,6}) (.*)")
_LATER = re.compile(r'Planned in full in section "([^"]*)"')
_SUBLIST = re.compile(r"\(sub-blocks ([0-9A-Za-z]+(?:, [0-9A-Za-z]+)*)\)")


def _ints_ok(v: object) -> bool:
    return type(v) is int and v >= 1


def _streams(row: dict) -> list:
    sts = row.get("streams")
    return [s for s in sts if type(s) is dict and type(s.get("id")) is str] if type(sts) is list else []


def _tasks_of(st: dict) -> list:
    t = st.get("tasks")
    return [x for x in t if type(x) is str] if type(t) is list else []


def _items(st: dict) -> list:
    p = st.get("paths")
    return list(p) if type(p) is list else []


def _bounds(st: dict, ids: set) -> tuple:
    """``(reasons, never_open)`` of the stream's ``period``."""
    per = st.get("period")
    errs = []
    if type(per) is not dict:
        return errs
    for k in ("from", "until"):
        if k in per:
            why = programs.event_problem(per[k], ids)
            if why:
                errs.append("stream %s: period %s: %s" % (st["id"], k, why))
    if not errs and type(per.get("from")) is str and type(per.get("until")) is str and _never(per["from"], per["until"]):
        errs.append("stream %s: period %s .. %s can never open" % (st["id"], per["from"], per["until"]))
    return errs


def _never(lo: str, hi: str) -> bool:
    return lo == hi or lo == programs.PROGRAM_CLOSE or hi == programs.PROGRAM_START


def _find_cycle(nodes: list, adj: dict) -> Optional[list]:
    """One cycle of the graph as a node list closed on its first node; iterative, nodes visited in sorted order."""
    colour: dict = {}
    for root in sorted(nodes):
        if colour.get(root):
            continue
        colour[root] = 1
        path = [root]
        its = [iter(sorted(adj.get(root, ())))]
        while its:
            nxt = next(its[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                its.pop()
                continue
            c = colour.get(nxt)
            if c == 1:
                return path[path.index(nxt):] + [nxt]
            if not c:
                colour[nxt] = 1
                path.append(nxt)
                its.append(iter(sorted(adj.get(nxt, ()))))
    return None


def breakdown_errors(row: dict, plans: Optional[dict] = None, plan_state: Optional[str] = None) -> list:
    """The ``(suffix, reason)`` pairs of a ``breakdown/1`` row (plan P:2736; decisions D-Q15, D-Q16, D-B7, D-B9).
    Suffixes: ``streams``, ``tasks``, ``done``, ``residual``, ``period``, ``paths``, ``edges``, ``groups``, ``limits``.
    ``plans`` (stream id to plan slug) adds each stream's implicit plan workspace, a whole-program entry, to the
    overlap check; ``plan_state`` defaults to ``paths.plan_state`` of the default config. A non-dict ``row`` or a
    ``plans`` that is not a dict of strings is a ``ValueError`` naming the argument."""
    if type(row) is not dict:
        raise ValueError("row: must be a mapping")
    if plans is not None and (type(plans) is not dict or any(type(k) is not str or type(v) is not str
                                                             for k, v in plans.items())):
        raise ValueError("plans: must be a dict of stream id to plan slug")
    if plan_state is None:
        plan_state = config.DEFAULTS["paths"]["plan_state"]
    errs: list = []
    sts = _streams(row)
    # limits
    for k in ("max_concurrent", "max_depth"):
        if k in row and not _ints_ok(row[k]):
            errs.append(("limits", "%s: must be an integer of at least 1" % k))
    # stream ids
    seen: dict = {}
    for st in sts:
        sid = st["id"]
        why = programs.stream_problem(sid)
        if why:
            errs.append(("streams", "stream id '%s': %s" % (sid, why)))
        if sid in seen:
            if seen[sid] == 1:
                errs.append(("streams", "duplicate stream id '%s'" % sid))
            seen[sid] += 1
        else:
            seen[sid] = 1
    ids = set(seen)
    # residual
    res = [st["id"] for st in sts if st.get("residual") is True]
    if len(res) > 1:
        errs.append(("residual", "at most one residual stream (%s)" % ", ".join(res)))
    for st in sts:
        if st.get("residual") is True:
            if _items(st) or "paths" in st:
                errs.append(("residual", "stream %s is residual and has paths" % st["id"]))
        elif not _items(st):
            errs.append(("paths", "stream %s is not residual and has no paths" % st["id"]))
    # tasks
    owner: dict = {}
    by_sub: dict = {}
    for st in sts:
        sid = st["id"]
        own = set()
        for t in _tasks_of(st):
            if "." not in t:
                errs.append(("tasks", "task '%s' of stream %s has no '.', so no sub-block" % (t, sid)))
            elif _TASK_ID.fullmatch(t) is None:
                errs.append(("tasks", "task '%s' of stream %s: the id must be <block>.<n> of [0-9A-Za-z]+ parts"
                             % (t, sid)))
            if t in own:
                errs.append(("tasks", "task %s is listed twice in stream %s" % (t, sid)))
                continue
            own.add(t)
            if t in owner and owner[t] != sid:
                errs.append(("tasks", "task %s is in streams %s and %s" % ((t,) + tuple(sorted((owner[t], sid))))))
            owner.setdefault(t, sid)
            b = programs.sub_block(t)
            if b is not None:
                by_sub.setdefault(b, {}).setdefault(sid, None)
    for b, ss in sorted(by_sub.items()):
        if len(ss) > 1:
            errs.append(("tasks", "sub-block %s has tasks in streams %s" % (b, " and ".join(sorted(ss)))))
    # done
    done = row.get("done")
    done = [d for d in done if type(d) is str] if type(done) is list else []
    edges = row.get("edges")
    edges = [e for e in edges if type(e) is dict and type(e.get("from")) is str and type(e.get("to")) is str] \
        if type(edges) is list else []
    in_edge = {e["from"] for e in edges} | {e["to"] for e in edges}
    dseen = set()
    for d in done:
        if d in dseen:
            errs.append(("done", "done lists %s twice" % d))
        dseen.add(d)
        if d in owner:
            errs.append(("done", "task %s is done and also in stream %s" % (d, owner[d])))
        if d in in_edge:
            errs.append(("done", "task %s is done and named by an edge" % d))
    # period and window bounds
    win_ok = {}
    for st in sts:
        errs.extend(("period", r) for r in _bounds(st, ids))
        for i, it in enumerate(_items(st)):
            if type(it) is str:
                path = it
            elif type(it) is dict and type(it.get("path")) is str and set(it) <= {"path", "from", "until"}:
                path = it["path"]
            else:
                errs.append(("paths", "stream %s: item %d is neither a path nor a path/from/until map" % (st["id"], i)))
                continue
            bad = False
            if type(it) is dict:
                for k in ("from", "until"):
                    if k in it:
                        why = programs.event_problem(it[k], ids)
                        if why:
                            errs.append(("paths", "stream %s: %s %s: %s" % (st["id"], path, k, why)))
                            bad = True
            try:
                win = programs.window_of(st, it)
            except ValueError:
                continue
            if not bad and type(it) is dict and _never(*win):
                errs.append(("paths", "stream %s: %s: window %s .. %s can never open" % (st["id"], path, win[0], win[1])))
                bad = True
            if not bad and programs.event_problem(win[0], ids) == "" and programs.event_problem(win[1], ids) == "":
                win_ok[(st["id"], i)] = win
    # overlaps
    entries = []
    for st in sts:
        for i, it in enumerate(_items(st)):
            win = win_ok.get((st["id"], i))
            if win is None:
                continue
            path = it if type(it) is str else it["path"]
            try:
                entries.append((st["id"], path, programs._ends(path), win))
            except (ValueError, TypeError):
                continue
        if plans is not None and st["id"] in plans:
            ws = "%s/%s/" % (plan_state, plans[st["id"]])
            entries.append((st["id"], ws, programs._ends(ws), (programs.PROGRAM_START, programs.PROGRAM_CLOSE)))
    cache: dict = {}

    def before(a: str, b: str) -> bool:
        if (a, b) not in cache:
            try:
                cache[(a, b)] = programs.comes_before(row, a, b)
            except ValueError:
                cache[(a, b)] = False
        return cache[(a, b)]

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            if a[0] == b[0] or not programs._entries_overlap(a[2], b[2]):
                continue
            wa, wb = a[3], b[3]
            if wa[1] == wb[0] or wb[1] == wa[0] or before(wa[1], wb[0]) or before(wb[1], wa[0]):
                continue
            errs.append(("paths", "%s (stream %s) overlaps %s (stream %s) while both windows can be open"
                         % (a[1], a[0], b[1], b[0])))
    # edges
    known = set(owner)
    graph: dict = {}
    for e in edges:
        f, t = e["from"], e["to"]
        bad = [x for x in (f, t) if x not in known]
        if bad:
            errs.append(("edges", "edge %s -> %s names unknown task %s" % (f, t, " and ".join(bad))))
            continue
        if f == t:
            errs.append(("edges", "edge %s -> %s is an edge from a task to itself" % (f, t)))
            continue
        graph.setdefault(f, set()).add(t)
    cyc = _find_cycle(sorted(known), graph)
    if cyc:
        errs.append(("edges", "cycle %s" % " -> ".join(cyc)))
    else:
        lifted: dict = {}
        for f, ts in graph.items():
            for t in ts:
                a, b = (owner[f], programs.sub_block(f)), (owner[t], programs.sub_block(t))
                if a[0] != b[0] and a[1] is not None and b[1] is not None:
                    lifted.setdefault("merged:%s/%s" % a, set()).add("merged:%s/%s" % b)
        nodes = set(lifted) | {n for v in lifted.values() for n in v}
        cyc = _find_cycle(sorted(nodes), lifted)
        if cyc:
            errs.append(("edges", "sub-block cycle %s" % " -> ".join(cyc)))
    # groups
    groups = row.get("groups")
    groups = [g for g in groups if type(g) is dict] if type(groups) is list else []
    gseen: set = set()
    in_group: dict = {}
    limit = row.get("max_concurrent") if _ints_ok(row.get("max_concurrent")) else None
    for g in groups:
        gid = g.get("id")
        if type(gid) is str:
            if gid in gseen:
                errs.append(("groups", "duplicate group id '%s'" % gid))
            gseen.add(gid)
        tasks = [t for t in g.get("tasks") or [] if type(t) is str] if type(g.get("tasks")) is list else []
        for t in tasks:
            if t not in known:
                errs.append(("groups", "group %s names unknown task %s" % (gid, t)))
            elif t in in_group and in_group[t] != gid:
                errs.append(("groups", "task %s is in groups %s and %s" % (t, in_group[t], gid)))
            in_group.setdefault(t, gid)
        if limit is not None and len(tasks) > limit:
            errs.append(("groups", "group %s holds %d tasks, more than max_concurrent %d" % (gid, len(tasks), limit)))
        inside = [t for t in dict.fromkeys(tasks) if t in known]
        fwd = {}
        for t in inside:
            seen_n, todo = set(), [t]
            while todo:
                for n in graph.get(todo.pop(), ()):
                    if n not in seen_n:
                        seen_n.add(n)
                        todo.append(n)
            fwd[t] = seen_n
        for x in range(len(inside)):
            for y in range(x + 1, len(inside)):
                a, b = inside[x], inside[y]
                if b in fwd[a] or a in fwd[b]:
                    errs.append(("groups", "group %s holds %s and %s, joined by a path of edges" % (gid, a, b)))
    return errs


# ---------------------------------------------------------------- plan_errors

def _need_plan_args(plan_text: object, row: object) -> None:
    if type(plan_text) is not str:
        raise ValueError("plan_text: must be a string")
    if type(row) is not dict:
        raise ValueError("row: must be a mapping")


def plan_errors(plan_text: str, row: dict) -> list:
    """The ``(suffix, reason)`` pairs of an outline-only plan (plan P:2737-2743; decisions D-Q17, D-Q18). Line based,
    split on ``\\n``, fences not special. Suffixes: ``outline.structure``, ``outline.block.<id>``,
    ``outline.later.<n>`` (1-based), ``outline.task.<id>``, ``outline.event.<event>``, ``outline.unplanned.<id>``."""
    _need_plan_args(plan_text, row)
    lines = plan_text.split("\n")
    heads = []      # (line, level, text, block id or None, is_umbrella_list)
    tasks = []      # (line, id)
    in_stream = False
    for n, line in enumerate(lines):
        if line.startswith("## "):
            in_stream = line.startswith("## Stream ")
        m = _TASK_HEAD.match(line)
        if m is not None:
            tasks.append((n, m.group(1)))
        h = _HEAD.match(line)
        if h is None:
            continue
        bid = None
        bm = checkpoints._BLOCK.match(line)
        if bm is not None and (bm.group(1) == "" or in_stream):
            bid = bm.group(2)
        else:
            sm = checkpoints._STREAM.match(line)
            if sm is not None:
                bid = sm.group(1)
        heads.append((n, len(h.group(1)), h.group(2), bid))
    # section ends, linear
    end = [len(lines)] * len(heads)
    stack: list = []
    for i, (_, lvl, _, _) in enumerate(heads):
        while stack and heads[stack[-1]][1] >= lvl:
            end[stack.pop()] = heads[i][0]
        stack.append(i)
    task_lines = [t[0] for t in tasks]
    blocks = [i for i, h in enumerate(heads) if h[3] is not None]
    errs: list = []
    if not blocks:
        errs.append(("outline.structure", "the plan has no block heading"))
    memo: dict = {}

    def passes(k: int) -> bool:
        if k in memo:
            return memo[k]
        bid = heads[blocks[k]][3]
        lo = bisect.bisect_left(task_lines, heads[blocks[k]][0])
        hi = bisect.bisect_left(task_lines, end[blocks[k]])
        ok = any(tasks[x][1].startswith(bid + ".") for x in range(lo, hi))
        if not ok:
            subs = [q for q in range(k + 1, len(blocks))
                    if heads[blocks[q]][3].startswith(bid) and len(heads[blocks[q]][3]) > len(bid)]
            ok = bool(subs) and all(passes(q) for q in subs)
        memo[k] = ok
        return ok

    reported = set()
    for k, bi in enumerate(blocks):
        bid = heads[bi][3]
        if not passes(k) and bid not in reported:
            reported.add(bid)
            errs.append(("outline.block.%s" % bid, "block %s has no task heading 'Task %s.<n>:' and is no umbrella "
                         "of passing sub-blocks" % (bid, bid)))
    by_text = {}
    for k, bi in enumerate(blocks):
        by_text.setdefault(heads[bi][2], []).append(k)
    id_ok = {}
    for k, bi in enumerate(blocks):
        id_ok[heads[bi][3]] = id_ok.get(heads[bi][3], True) and passes(k)

    def resolves(text: str) -> bool:
        if text in by_text:
            return all(passes(k) for k in by_text[text])
        for (_, lvl, t, bid) in heads:
            if t == text and bid is None and lvl == 2:
                m = _SUBLIST.search(t)
                if m is not None:
                    return all(id_ok.get(x, False) for x in m.group(1).split(", "))
        return False

    n_bullet = 0
    in_later = False
    for line in lines:
        if line.startswith("#"):
            in_later = line.startswith("## Later blocks")
            continue
        if in_later and line.startswith("- "):
            n_bullet += 1
            m = _LATER.search(line)
            if m is None:
                errs.append(("outline.later.%d" % n_bullet, "the bullet does not read 'Planned in full in section \"<X>\"'"))
            elif not resolves(m.group(1)):
                errs.append(("outline.later.%d" % n_bullet, "section \"%s\" is no passing block heading of the plan"
                             % m.group(1)))
    # tasks and events against the breakdown
    headed = {t[1] for t in tasks}
    sts = _streams(row)
    done = row.get("done")
    done = [d for d in done if type(d) is str] if type(done) is list else []
    covered = set(done)
    for st in sts:
        covered.update(_tasks_of(st))
    for t in dict.fromkeys(done + [t for st in sts for t in _tasks_of(st)]):
        if t not in headed:
            errs.append(("outline.task.%s" % t, "task %s has no task heading in the plan" % t))
    for _, t in tasks:
        if t not in covered:
            errs.append(("outline.unplanned.%s" % t, "the plan's task %s is in no stream and not in done" % t))
            covered.add(t)
    heading_ids = {h[3] for h in heads if h[3] is not None}
    sub_of = {st["id"]: {programs.sub_block(t) for t in _tasks_of(st)} for st in sts}
    events = []
    for st in sts:
        per = st.get("period")
        if type(per) is dict:
            events += [per.get("from"), per.get("until")]
        for it in _items(st):
            if type(it) is dict:
                events += [it.get("from"), it.get("until")]
    for ev in dict.fromkeys(e for e in events if type(e) is str and e.startswith("merged:") and "/" in e):
        s, _, b = ev[7:].partition("/")
        if b not in sub_of.get(s, set()) or b not in heading_ids:
            errs.append(("outline.event.%s" % ev, "event %s: %s is not a sub-block of stream %s's tasks with a block "
                         "heading in the plan" % (ev, b, s)))
    return errs
