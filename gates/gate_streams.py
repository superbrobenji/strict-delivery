"""Gate ``streams``: program ownership and the program files (plan Task P2.3; decisions D-Q1 to D-Q28 of its table).

Lines, in this order: ``streams.input`` | ``streams.none`` | ``streams.branch`` | per program (sorted) ``streams.map.<p>``,
``streams.status.<p>``, ``streams.request`` (``streams.request.<suffix>`` per failure) | on a program branch
``streams.owned`` (``streams.owned.<path>`` per failing path, reasons joined with ``"; "``, the commits named in them),
``streams.integration`` (``.<sha>`` per failing merge; stream, group and records branches), ``streams.shared``
(``.<path>``; stream and group branches). A PASS id prints once per run when its rule applied and nothing of its group
failed (D-Q14 (a)). The program files are read from ``<program>/integration`` (from the work tree when the branch is the
integration branch itself, D-Q11 (b)). ``--base`` is accepted and ignored: the base is derived (D-Q6 (a)).

``streams.integration`` (decision D-Q27, owner answer Q-A11-1 (c), 2026-11-18): "P2.3's ``streams.integration`` keeps the
plan's reachability test as the first filter, and fails only when the second parent lies on integration's first-parent
chain since the base (``rev_list(base..integration, first_parent=True)``). Build row IG4 that way and quote this answer."
A judged merge fails when its second parent is reachable from ``<program>/integration``, not from the tip of
``base_branch``, and on ``rev_list(base tip, integration tip, first_parent=True)``.

Known limit (decision D-Q21): a merge whose second parent is reachable from the tip of ``base_branch`` is exempt and not
judged at all, so a conflict resolution inside it that edits another stream's paths passes; proposed as a follow-up row
for the program controller. The pull-request body is never read (the test-file case of owner answers Q-A7-1 and Q-PV2-2
(b) admits the path only; the other conditions are checked by hand at review).
"""
from __future__ import annotations

import dataclasses
import sys

from gates.lib import checkpoints, config, gitinfo, programs, yamlsub
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate
from gates.lib import tipread

PRODUCES: tuple = ()

_LEDGER_FIRST = "<!-- schema: ledger/1 -->"
_MERGED_FIRST = "<!-- schema: merged-log/1 -->"
_NO_OWNER = "no stream owns it; the program controller assigns it (class `stream-ownership`)"
_ID_CHARS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.")
_BAD_BRANCH = frozenset(" ~^:?*[\\\x7f")


def _args(args: list):
    p = gate_args("streams")
    p.add_argument("--branch", default=None, action=_Once, help="the branch to judge (default: the current branch)")
    p.add_argument("--base", default=None, action=_Once, help="accepted and ignored: the base is derived")
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root


def _branch_problem(name: str) -> str:
    """Why ``name`` is no branch name (decision D-Q4 (b): what ``git check-ref-format --branch`` refuses, in plain code)."""
    if name == "" or name.startswith("-") or name.startswith("/") or name.endswith("/") or name.endswith(".") \
            or name.endswith(".lock") or "//" in name or ".." in name or "@{" in name or name == "@" or len(name) > 255:
        return "not a branch name"
    if any(c in _BAD_BRANCH or ord(c) < 32 for c in name) or any(p == "" or p.startswith(".") or p.endswith(".lock")
                                                                for p in name.split("/")):
        return "not a branch name"
    return ""


def _short(sha: str) -> str:
    return sha[:7]


class _Fail:
    """Failing ids in order of first failure; several reasons for one id are joined with ``"; "`` (D-Q15)."""

    def __init__(self) -> None:
        self.by: dict = {}

    def add(self, key: str, reason: str) -> None:
        got = self.by.setdefault(key, [])
        if reason not in got:
            got.append(reason)

    def emit(self, res: Result, prefix: str) -> bool:
        for k, rs in self.by.items():
            res.fail(prefix + "." + k, "; ".join(rs))
        return not self.by


def _read(root: str, ref, rel: str):
    return programs._fs_text(root, rel) if ref is None else tipread.show_file(root, ref, rel)


def _ref(b: str) -> str:
    return "refs/heads/" + b


def _is_test_file(path: str) -> bool:
    """``tests/test_*.py`` as plain code: ``tests/`` and one path segment that starts ``test_``, ends ``.py`` and has at
    least one character between (decision D-Q18 (a); ASCII code points, no case folding)."""
    if not path.startswith("tests/"):
        return False
    name = path[6:]
    return "/" not in name and name.startswith("test_") and name.endswith(".py") and len(name) > 8


def _sections(text: str) -> list:
    """``(first line, last line, id)`` of every ``### Task <id>:`` and ``#### Task <id>:`` section, 1-based. A section
    runs to the line before the next heading of the same or a higher level (decision D-Q10 (b)); the id ends at the
    colon that follows it at once."""
    lines = text.split("\n")
    heads = []
    for n, line in enumerate(lines, 1):
        k = len(line) - len(line.lstrip("#"))
        if 1 <= k <= 6 and line[k:k + 1] == " ":
            heads.append((n, k, line))
    out = []
    for i, (n, k, line) in enumerate(heads):
        for lead in ("### Task ", "#### Task "):
            if line.startswith(lead) and k == len(lead.split(" ")[0]):
                rest = line[len(lead):]
                tid = rest.partition(":")[0]
                if ":" in rest and tid != "" and all(c in _ID_CHARS for c in tid):
                    end = len(lines)
                    for n2, k2, _ in heads[i + 1:]:
                        if k2 <= k:
                            end = n2 - 1
                            break
                    out.append((n, end, tid))
    return out


def _inside(sections: list, tasks: set, first: int, count: int) -> bool:
    for line in range(first, first + count):
        covering = [s for s in sections if s[0] <= line <= s[1]]
        if not covering or max(covering)[2] not in tasks:   # the innermost section (the latest start) decides
            return False
    return True


class _Run:
    """One program's reads and the judgments over its branch."""

    def __init__(self, root: str, cfg: dict, name: str, parsed, branch: str) -> None:
        self.root, self.cfg, self.name, self.parsed, self.branch = root, cfg, name, parsed, branch
        self.kind = parsed[0] if parsed is not None and parsed[1] == name else None
        self.integ = "%s/integration" % name
        self.ref = None if self.kind == "integration" else _ref(self.integ)
        self.p = programs._paths(cfg)
        self.base_name = cfg["base_branch"]
        self.anc: dict = {}
        self.held_cache: dict = {}

    # ---------------------------------------------------------------- reads
    def ancestor(self, a: str, b: str) -> bool:
        if (a, b) not in self.anc:
            self.anc[(a, b)] = gitinfo.is_ancestor(self.root, a, b)
        return self.anc[(a, b)]

    def load(self) -> None:
        self.prog = programs.load_program(self.root, self.cfg, self.name, self.ref)
        self.streams = self.prog.streams
        self.sids = {s["id"] for s in programs._stream_list(self.streams)}
        self.plan_slug = programs._slug_of(self.streams.get("plan"), self.p["plans"])
        self.problems: list = []      # streams.map reasons
        self.plan_text = None
        self.bd = None
        try:
            self.plan_text = _read(self.root, self.ref, self.streams["plan"]) if type(self.streams.get("plan")) is str else None
        except GateError as e:
            self.problems.append(str(e))
        if self.plan_text is None:
            self.problems.append("the program plan %s cannot be read at the tip of %s" % (self.streams.get("plan"), self.integ))
        if self.plan_slug is not None:
            rel = "%s/%s/breakdown.yml" % (self.p["plan_state"], self.plan_slug)
            try:
                text = _read(self.root, self.ref, rel)
                if text is None:
                    self.problems.append("%s is missing at the tip of %s" % (rel, self.integ))
                else:
                    bd = yamlsub.parse(text)
                    if type(bd) is not dict:
                        raise GateError("%s: the top level must be a mapping" % rel)
                    self.bd = bd
            except (GateError, yamlsub.YamlError) as e:
                self.problems.append("%s: %s" % (rel, getattr(e, "reason", e)))
        self.sub_blocks: dict = {}
        self.counted: list = []
        self.merged: dict = {}
        self.carried: list = []
        if self.bd is not None:
            try:
                self.sub_blocks = programs.breakdown_sub_blocks(self.bd)
                self.counted, self.merged, errs = programs.counted_lines(self.prog, self.root, self.cfg, self.bd)
                self.problems += errs
                head = self.prog.merged_log.partition("\n")[0] + "\n"
                raw = {}
                for line in self.prog.merged_log.split("\n"):
                    if line.startswith("MERGED pr="):
                        raw[line.split(" ")[1]] = line + "\n"
                for ln in self.counted:
                    one = dataclasses.replace(self.prog, merged_log=head + raw["pr=%d" % ln["pr"]])
                    self.carried.append(programs.counted_lines(one, self.root, self.cfg, self.bd)[1])
            except ValueError as e:
                self.problems.append("breakdown.yml: %s" % e)
                self.sub_blocks, self.counted, self.merged, self.carried = {}, [], {}, []

    def held_for(self, rev: str) -> frozenset:
        """The held events of a judged commit: ``held_events`` over the counted lines whose ``merge`` is an ancestor of
        ``rev`` (owner answer Q-F80W-12 (a))."""
        key = frozenset(i for i, ln in enumerate(self.counted) if self.ancestor(ln["merge"], rev))
        if key not in self.held_cache:
            merged: dict = {}
            for i in sorted(key):
                for s, bs in self.carried[i].items():
                    merged.setdefault(s, set()).update(bs)
            self.held_cache[key] = programs.held_events(merged, self.sub_blocks)
        return self.held_cache[key]

    # ---------------------------------------------------------------- program file lines
    def map_reasons(self, committing) -> list:
        out = list(self.problems)
        sids = set(self.sids)
        held_all = programs.held_events(self.merged, self.sub_blocks)
        out += programs.streams_errors(self.streams, self.name, self.cfg, held_all)
        first, _, rest = self.prog.merged_log.partition("\n")
        if first != _MERGED_FIRST:
            out.append("merged.md: first line must be %s" % _MERGED_FIRST)
        else:
            out += ["merged.md: " + e for e in checkpoints.ledger_errors(_LEDGER_FIRST + "\n" + rest, self.cfg, self.plan_text,
                                                                         sids, per_stream=True)]
        seen = set()
        for ln in self.counted:
            st = programs._stream_row(self.streams, ln["stream"])
            slug = programs._slug_of(st.get("plan"), self.p["plans"])
            rel = "%s/%s/ledger.md" % (self.p["plan_state"], slug)
            if (ln["head"], rel) not in seen:
                seen.add((ln["head"], rel))
                try:
                    text = tipread.show_file(self.root, ln["head"], rel)
                except GateError as e:
                    text = None
                    out.append("pr %d: ledger %s at %s: %s" % (ln["pr"], rel, _short(ln["head"]), e))
                if text is not None:
                    out += ["pr %d: ledger %s at %s: %s" % (ln["pr"], rel, _short(ln["head"]), e)
                            for e in checkpoints.ledger_errors(text, self.cfg, self.plan_text, sids)]
            try:
                base_text = tipread.show_file(self.root, _ref(self.base_name), rel)
            except GateError as e:
                base_text = None
                out.append("pr %d: ledger %s at %s: %s" % (ln["pr"], rel, self.base_name, e))
            if base_text is not None:
                same = [m for m in checkpoints.merged_lines(base_text) if m["pr"] == ln["pr"]]
                if len(same) > 1:
                    out.append("pr %d: recorded twice in %s at %s" % (ln["pr"], rel, self.base_name))
                elif same and same[0] != ln:
                    out.append("pr %d: the merged record differs from the line of %s at %s" % (ln["pr"], rel, self.base_name))
        if committing is not None and self.kind in ("stream", "group"):
            rel = "%s/%s/ledger.md" % (self.p["plan_state"], committing[1])
            try:
                text = programs._fs_text(self.root, rel)
            except GateError as e:
                text = None
                out.append(str(e))
            if text is not None:
                out += ["own ledger %s: %s" % (rel, e) for e in checkpoints.ledger_errors(text, self.cfg, self.plan_text, sids)]
        if self.bd is not None and self.plan_slug is not None:
            try:
                out += programs.agreement_errors(self.streams, self.bd, self.plan_slug)
            except ValueError as e:
                out.append("breakdown.yml: %s" % e)
        return out

    def status_reasons(self) -> list:
        try:
            rows = programs.status_rows(self.prog.status_text)
            return programs.status_errors(rows, self.streams, cfg=self.cfg,
                                          request_ids={r.id for r in self.prog.requests if type(r.id) is str})
        except (ValueError, GateError) as e:
            return [str(e)]

    def request_failures(self) -> list:
        out = list(programs.request_errors(self.prog, self.root, self.cfg, self.bd if self.bd is not None else {}))
        base = None
        try:
            if self.kind == "integration":
                at = "HEAD"
            else:
                at = gitinfo.merge_base(self.root, _ref(self.integ), "HEAD")
            base = programs.load_program(self.root, self.cfg, self.name, at)
        except GateError:
            base = None    # no program at the merge base (decision D-Q12 (a)): every request is new
        if base is not None:
            out += programs.request_base_errors(self.prog, base)
        return out

    # ---------------------------------------------------------------- ownership
    def committing(self):
        """``(stream id, plan slug)`` of the branch's stream, ``None`` off a stream or group branch."""
        if self.kind not in ("stream", "group"):
            return None
        st = programs._stream_row(self.streams, self.parsed[2])
        return (self.parsed[2], programs._slug_of(st.get("plan"), self.p["plans"]))

    def in_records(self, path: str, skip_folder: bool = False) -> bool:
        keys = programs._records(self.streams, self.cfg, self.p)
        return any(programs._covers(k, programs._ends(path)) for k in (keys[1:] if skip_folder else keys))

    def plan_hunks(self, sid: str, path: str, a, b) -> str:
        """``""`` when every hunk of the committing stream's plan file lies in a task section of its own tasks."""
        tasks = set()
        for s in (self.bd or {}).get("streams") or []:
            if type(s) is dict and s.get("id") == sid:
                tasks = {t for t in s.get("tasks") or [] if type(t) is str}
        if self.bd is None:
            return "breakdown.yml cannot be read, so the task sections of stream %s are unknown" % sid
        try:
            old = tipread.show_file(self.root, a, path) if a is not None else None
            new = tipread.show_file(self.root, b, path) if b is not None else programs._fs_text(self.root, path)
        except GateError as e:
            return str(e)  # a symlink, tree or gitlink at a revision is refused by name, never "created or deleted"
        if old is None or new is None:
            return "the plan file is created or deleted: a hunk at line 1 lies outside the task sections of stream %s" % sid
        hunks = gitinfo.file_hunks(self.root, a, b, path)
        if not hunks:
            return "the plan file hunks cannot be read at line 1"
        so, sn = _sections(old), _sections(new)
        for os_, oc, ns_, nc in hunks:
            if (oc and not _inside(so, tasks, os_, oc)) or (nc and not _inside(sn, tasks, ns_, nc)):
                return "plan hunk at line %d lies outside the task sections of stream %s" % (ns_ if nc else os_, sid)
        return ""

    def stream_reason(self, path: str, held: frozenset, a, b):
        """Why ``path`` is not the committing stream's to change on a stream or group branch, else ``None``."""
        sid, _ = self.committing()
        if programs.shared_rule(self.streams, path) is not None:
            return None
        st = programs._stream_row(self.streams, sid)
        if type(st.get("plan")) is str and programs.path_key(path) == programs.path_key(st["plan"]):
            why = self.plan_hunks(sid, path, a, b)
            return why or None
        if self.in_records(path):
            return "a program record (program folder, global records, program plan file or workspace): only the program controller changes it"
        try:
            owner = programs.owner_of(self.streams, self.p["plan_state"], path, held, cfg=self.cfg)
        except ValueError as e:
            w = str(e).split(" ")   # "paths owned by streams a and b are both open for <path>"
            return "stream %s and stream %s are both open for it" % (w[4], w[6])
        if owner == sid:
            return None
        if owner is None:
            return _NO_OWNER
        if _is_test_file(path):
            return None
        return "owned by stream %s" % owner

    def judged(self, base_tip: str, range_base: str, stacked_tip):
        """``(commit, parents)`` of every judged commit, oldest first; merges whose second parents are all on the tip of
        ``base_branch`` (or of the stacked parent's branch) are not judged (owner answer Q-F80W-9 (a)). On the
        integration branch only its first-parent line is judged: the commits of a merged stream are that merge's."""
        out = []
        first = self.kind == "integration"
        for c in gitinfo.rev_list(self.root, gitinfo.merge_base(self.root, range_base, "HEAD"), "HEAD", first_parent=first):
            ps = gitinfo.parents(self.root, c)
            if len(ps) > 1 and all(self.ancestor(x, base_tip) or (stacked_tip is not None and self.ancestor(x, stacked_tip))
                                   for x in ps[1:]):
                continue
            out.append((c, ps))
        return out

    def tree_paths(self) -> list:
        out: list = []
        for x in gitinfo.changed_paths(self.root, "HEAD", None) + gitinfo.staged_paths(self.root):
            if x not in out:
                out.append(x)
        return out

    def owned_lines(self, res: Result) -> None:
        if self.kind not in ("stream", "group", "integration", "records"):
            return
        base_tip = _ref(self.base_name)
        fails, integ, shared = _Fail(), _Fail(), _Fail()
        unborn = not gitinfo.commit_exists(self.root, "HEAD")
        sid = self.committing()[0] if self.committing() else None
        range_base, stacked_tip = base_tip, None
        if self.kind in ("stream", "group") and not unborn:
            stacked = programs._stream_row(self.streams, sid).get("stacked_on")
            if type(stacked) is str and "merged:" + stacked not in self.held_for("HEAD"):
                range_base = stacked_tip = _ref(programs.branch_of(self.name, stacked))
        if unborn:
            commits, tree = [], gitinfo.staged_paths(self.root) + [x for x in gitinfo.dirty_paths(self.root)]
            if tree:
                fails.add("<unborn>", "the branch has no commit yet and the tree holds %s" % ", ".join(tree))
        else:
            commits = self.judged(base_tip, range_base, stacked_tip)
            tree = self.tree_paths()
        # a merge already made
        for c, ps in commits:
            held = self.held_for(c)
            if self.kind in ("stream", "group", "records") and len(ps) > 1:
                self.integration_check(c, ps, integ)
            self.judge(fails, shared, c, ps, held, sid)
        # the tree being committed
        mh = gitinfo.merge_head(self.root) if self.kind == "integration" and not unborn else None
        if tree and not unborn:
            held = self.held_for("HEAD")
            if mh is not None:
                if not self.ancestor(mh, base_tip):
                    self.judge_combined(fails, "tree", [None, mh], held, tree)
            else:
                self.judge_paths(fails, shared, "tree", ["HEAD"], held, sid, tree, None)
        if fails.emit(res, "streams.owned"):
            res.passed("streams.owned")
        if self.kind != "integration":
            if integ.emit(res, "streams.integration"):
                res.passed("streams.integration")
        if self.kind in ("stream", "group"):
            if shared.emit(res, "streams.shared"):
                res.passed("streams.shared")

    def integration_check(self, c: str, ps: list, integ: _Fail) -> None:
        base_tip = _ref(self.base_name)
        chain = None
        for sp in ps[1:]:
            if self.ancestor(sp, _ref(self.integ)) and not self.ancestor(sp, base_tip):
                if chain is None:
                    chain = set(gitinfo.rev_list(self.root, base_tip, _ref(self.integ), first_parent=True))
                if sp in chain:
                    integ.add(c, "the second parent %s is integration's own content (on the first-parent chain of %s since %s)"
                              % (sp, self.integ, self.base_name))

    def judge(self, fails: _Fail, shared: _Fail, c: str, ps: list, held: frozenset, sid) -> None:
        paths = gitinfo.commit_paths(self.root, c)
        if self.kind == "integration" and len(ps) > 1:
            self.judge_combined(fails, c, ps, held, paths)
            return
        self.judge_paths(fails, shared, c, ps[:1], held, sid, paths, c)

    def judge_paths(self, fails, shared, c, ps, held, sid, paths, b) -> None:
        a = ps[0] if ps else None
        who = _short(c) if c not in ("tree",) else "the tree being committed"
        if c == "tree":
            a = "HEAD"
        for path in paths:
            if self.kind in ("stream", "group"):
                why = self.stream_reason(path, held, a, b)
                if why is None and programs.shared_rule(self.streams, path) is not None:
                    bad = self.shared_problem(path, a, b, sid)
                    if bad:
                        shared.add(path, "%s (%s)" % (bad, who))
                elif why:
                    fails.add(path, "%s (%s)" % (why, who))
            elif self.kind == "integration":
                if not self.in_records(path):
                    fails.add(path, "only program records may change on %s (%s)" % (self.integ, who))
            elif not self.in_records(path, skip_folder=True):
                fails.add(path, "only the global records, the program plan file and its workspace may change on "
                                "%s/records (%s)" % (self.name, who))

    def judge_combined(self, fails: _Fail, c: str, ps: list, held: frozenset, paths: list) -> None:
        """A combined-testing merge on integration: only paths the merged stream owns (decision D-Q20 (a))."""
        who = _short(c) if c != "tree" else "the tree being committed"
        if len(ps) > 2:
            fails.add(c if paths == [] else paths[0], "an octopus merge on %s is refused (%s)" % (self.integ, who))
            return
        found = []
        for b in gitinfo.local_branches(self.root):
            parsed = programs.parse_branch(b) if b.startswith(self.name + "/") else None
            if parsed is not None and parsed[0] in ("stream", "group") and parsed[1] == self.name \
                    and self.ancestor(ps[1], _ref(b)) and parsed[2] not in found:
                found.append(parsed[2])
        if len(found) != 1:
            why = "no stream or group branch reaches the second parent" if not found else \
                "streams %s both reach the second parent" % " and ".join(found)
            for path in paths or [c]:
                fails.add(path, "%s (%s)" % (why, who))
            return
        for path in paths:
            try:
                owner = programs.owner_of(self.streams, self.p["plan_state"], path, held, cfg=self.cfg)
            except ValueError as e:
                owner = str(e)
            if owner != found[0] or self.in_records(path):
                fails.add(path, "a merge of stream %s may change only paths it owns (%s)" % (found[0], who))

    def shared_problem(self, path: str, a, b, sid: str) -> str:
        rule = programs.shared_rule(self.streams, path)
        try:
            old = tipread.show_file(self.root, a, path) if a is not None else None
            new = tipread.show_file(self.root, b, path) if b is not None else programs._fs_text(self.root, path)
        except GateError as e:
            return str(e)  # a symlink, tree or gitlink at a revision is refused by name, never "is deleted"
        if new is None:
            return "shared file %s is deleted (%s)" % (path, rule)
        if rule == "append-rows":
            base = old or ""
            if not new.startswith(base):
                return "append-rows: the text before the new rows differs from its base"
            rest = new[len(base):]
            if base and not base.endswith("\n"):
                if not rest.startswith("\n"):
                    return "append-rows: a row is appended to a base line that has no end"
                rest = rest[1:]
            rows = rest.split("\n")
            if rows[-1] == "":
                rows.pop()
            for line in rows:
                if not line.startswith("|"):
                    return "append-rows: '%s' is not a table row" % line[:40]
            return ""
        def foreign(text):
            return [ln for ln in (text or "").split("\n")
                    if not (ln.startswith("|") and ln[1:].split("|")[0].strip() == sid)]
        if foreign(old) != foreign(new):
            return "own-row: a line that is not a row of stream %s changed" % sid
        return ""


def _lines(run: _Run, res: Result, committing) -> None:
    why = run.map_reasons(committing)
    if why:
        res.fail("streams.map." + run.name, "; ".join(why))
    else:
        res.passed("streams.map." + run.name)
    why = run.status_reasons()
    if why:
        res.fail("streams.status." + run.name, "; ".join(why))
    else:
        res.passed("streams.status." + run.name)
    bad = run.request_failures()
    for suffix, reason in bad:
        res.fail("streams.request." + suffix, reason)
    if not bad:
        res.passed("streams.request")


def check(args: list) -> Result:
    ns = _args(args)
    root = _root(ns)
    cfg = config.load(root)
    res = Result("streams")
    branch = ns.branch if ns.branch is not None else gitinfo.current_branch(root)
    if branch is None:
        raise GateError("HEAD is detached; pass --branch NAME")
    if _branch_problem(branch):
        raise GateError("--branch: '%s' is not a branch name" % branch)
    try:
        parsed = programs.parse_branch(branch)
    except ValueError as e:
        res.fail("streams.branch", str(e))
        return res
    live = programs.live_programs(root, cfg)
    if parsed is None:
        names = live
        if not names:
            res.passed("streams.none")
            return res
    else:
        names = [parsed[1]]
        if parsed[1] + "/integration" not in gitinfo.local_branches(root):
            raise GateError("branch %s/integration does not exist locally; create it from the remote" % parsed[1])
    if gitinfo.is_shallow(root):
        raise GateError("shallow clone; fetch the full history")
    for name in names:
        run = _Run(root, cfg, name, parsed, branch)
        run.load()
        committing = None
        if run.kind in ("stream", "group"):
            if run.parsed[2] not in run.sids:
                res.fail("streams.branch", "stream %s is not in streams.yml" % run.parsed[2])
                return res
            committing = run.committing()
        _lines(run, res, committing)
        run.owned_lines(res)
    return res


def main(argv=None) -> int:
    return run_gate("streams", check, argv)


if __name__ == "__main__":
    sys.exit(main())
