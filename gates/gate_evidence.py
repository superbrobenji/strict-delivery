"""Gate ``evidence``: every pinned finding carries a review package, a mutation transcript and a passing re-run
(spec 13a; plan Task 6E.2; owner answers Q-B6plan-1 (a), Q-B6plan-4 (b)).

Lines: ``evidence.config`` and ``evidence.scope`` (always printed, so a tree with no pin is never an empty run), then,
per pinned finding in scope and in register order, ``evidence.package.<id>``, ``evidence.transcript.<id>`` and
``evidence.rerun.<id>``. Scope by profile: ``light`` none, ``standard`` the pinned rows new or changed against the merge
base with ``--base``, ``strict`` every pinned row. ``--base`` is resolved under every profile. The module declares no
registry entry itself: Rq-6-1..Rq-6-4 are requests to the registry owner."""
from __future__ import annotations

import sys
from typing import Optional

from gates.gate_decisions import _keys, _root
from gates.lib import config, evidence, findings, gitinfo
from gates.lib.result import GateError, Result, _Once, gate_args, run_gate
from gates.lib import tipread
from gates.lib.store import Store, _merge_base_rows, _row_changed

PRODUCES: tuple = ("mutation-transcript", "review-report")


def _args(args: list):
    p = gate_args("evidence")
    p.add_argument("--base", default=None, action=_Once, help="the base ref (default: config base_branch)")
    return p.parse_args(args)


def _show(root: str, sha: str, path: str):
    """``(text, problem)``: the blob at ``sha:path``, or why it cannot be read (a GateError of ``show`` is a problem of
    this row, never of the run: Q9)."""
    try:
        text = tipread.show_file(root, sha, path)
    except GateError as e:
        return None, "%s:%s: %s" % (sha, path, e)
    if text is None:
        return None, "%s is not a regular file at %s" % (path, sha)
    return text, ""


def _under(path: str, directory: str) -> bool:
    return path.startswith(directory + "/")


def _report_shape(path: str, reviews: str) -> bool:
    """``<reviews>/<one directory>/<name>.md``: the shape ``gate_schema`` lists (``*/*.md``)."""
    rest = path[len(reviews) + 1:]
    parts = rest.split("/")
    return len(parts) == 2 and parts[1].endswith(".md")


def _transcript_location(path: str, plan_state: str) -> str:
    """"" when ``path`` is ``<plan_state>/<one directory>/mutations/<file>``, else the rule it breaks."""
    base = plan_state.split("/")
    parts = path.split("/")
    ok = len(parts) == len(base) + 3 and parts[:len(base)] == base and parts[len(base) + 1] == "mutations"
    if ok:
        return ""
    return ("%s is not directly in a mutations/ folder: a transcript is %s/<plan>/mutations/<file>"
            % (path, plan_state))


def _candidates(entries: list, reviews: str):
    """``([(entry, sha, path)], [misshaped path])``: the ``<sha>:<path>`` entries under ``reviews``, split by whether
    their path has the report shape."""
    good: list = []
    odd: list = []
    for e in entries:
        cite = evidence.split_cite(e)
        if cite is None or not _under(cite[1], reviews):
            continue
        (good if _report_shape(cite[1], reviews) else odd).append((e, cite[0], cite[1]))
    return [(e, s, p) for e, s, p in good], [p for _, _, p in odd]


def _package(root: str, cfg: dict, fid: str, pin: dict, entries: list, runs: Optional[list]):
    """``(problems, command)``: why no review report holds a full package for ``fid`` (empty list: one does), and the
    package command the transcript is compared with (None when no report holds a group for ``fid``). ``runs`` are the
    transcript's parsed runs, None when the transcript cannot be read."""
    reviews = cfg["paths"]["reviews"]
    cands, odd = _candidates(entries, reviews)
    if not cands:
        why = "no evidence entry is a review report cited as <sha>:%s/<dir>/<name>.md" % reviews
        if odd:
            why += " (not that shape: %s)" % ", ".join(p for p in odd)
        return [why], None
    problems: list = []
    source = None
    source_rank = 9
    for entry, sha, path in cands:
        where = "%s:%s" % (sha, path)
        text, why = _show(root, sha, path)
        if text is None:
            problems.append("review report " + why)
            continue
        try:
            group = evidence.package_entries(text).get(fid)
        except ValueError as e:
            problems.append("review report %s: %s" % (where, str(e)))
            continue
        if group is None:
            problems.append("review report %s holds no PIN group for %s" % (where, fid))
            continue
        diffs = [k for k, want in (("test", pin["test"]), ("transcript", pin["transcript"])) if group[k] != want]
        rank = 0 if not diffs else 1
        if rank < source_rank:
            source, source_rank = group["command"], rank
        if diffs:
            problems.append("review report %s: %s" % (where, "; ".join(
                "%s: expected %s, got %s" % (k, pin[k], group[k]) for k in diffs)))
            continue
        # An unreadable transcript is the transcript line's failure; the command is then not compared here.
        bad = [r["n"] for r in runs if r["command"] != group["command"]] if runs is not None else []
        if bad:
            problems.append("review report %s: command: %s differs from the transcript's RUN %s"
                            % (where, group["command"], ", ".join(str(n) for n in bad)))
            continue
        return [], group["command"]
    return problems, source


def _transcript(root: str, cfg: dict, fid: str, pin: dict):
    """``(parsed, problem)``: the parsed transcript at ``pin.transcript``, or why it cannot be read."""
    sha, path = evidence.split_cite(pin["transcript"])  # a row that passed findings.validate holds <sha>:<path>
    rule = _transcript_location(path, cfg["paths"]["plan_state"])
    if rule:
        return None, rule
    text, why = _show(root, sha, path)
    if text is None:
        return None, "transcript " + why
    try:
        return evidence.parse_transcript(text), ""
    except ValueError as e:
        return None, "transcript %s:%s: %s" % (sha, path, str(e))


def check(args: list) -> Result:
    ns = _args(args)
    root = _root(ns.root)
    cfg = config.load(root)
    base = ns.base if ns.base is not None else cfg["base_branch"]
    profile = cfg["profile"]
    at_mb: dict = {}
    if profile == "standard":
        store = Store(root, "finding", cfg)
        at_mb = _merge_base_rows(root, store.directory, base)
    else:
        gitinfo.merge_base(root, base, "HEAD")  # resolved under every profile (D-2-Q1 (b))
    res = Result("evidence")
    rows: list = []  # (key, row) in scope
    if profile != "light":
        store = Store(root, "finding", cfg)
        records = store.load()
        key = _keys(records, store.prefix)
        for r in records:
            if findings.validate(r.row, cfg) != [] or r.row.get("pin") is None:
                continue
            if profile == "standard" and not _row_changed(r, at_mb, "finding"):
                continue
            rows.append((key[r.file], r.row))
    if rows:
        try:
            evidence.render_pin(cfg, rows[0][1]["pin"]["test"])
        except GateError as e:
            res.fail("evidence.config", str(e))
            res.passed("evidence.scope")
            return res
    res.passed("evidence.config")
    res.passed("evidence.scope")
    for k, row in rows:
        fid, pin = row["id"], row["pin"]
        parsed, tproblem = _transcript(root, cfg, fid, pin)
        runs = parsed["runs"] if parsed is not None else None
        problems, command = _package(root, cfg, fid, pin, row.get("evidence") or [], runs)
        if problems:
            res.fail("evidence.package." + k, "; ".join(problems))
        else:
            res.passed("evidence.package." + k)
        if parsed is None:
            res.fail("evidence.transcript." + k, tproblem)
        elif command is None:
            res.fail("evidence.transcript." + k, "no package command to compare with: no review report holds a PIN group "
                     "for %s" % fid)
        else:
            errs = evidence.transcript_errors(parsed, fid, pin["test"], command, cfg)
            if errs:
                res.fail("evidence.transcript." + k, "; ".join(errs))
            else:
                res.passed("evidence.transcript." + k)
        try:
            display, run = evidence.render_pin(cfg, pin["test"])
        except GateError as e:
            res.fail("evidence.rerun." + k, str(e))
            continue
        code = evidence.run_pin(root, run)
        if code == 0:
            res.passed("evidence.rerun." + k)
        else:
            res.fail("evidence.rerun." + k, "%s: exit %d" % (display, code))
    return res


def main(argv=None) -> int:
    return run_gate("evidence", check, argv)


if __name__ == "__main__":
    sys.exit(main())
