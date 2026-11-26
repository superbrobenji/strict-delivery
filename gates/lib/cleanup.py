"""Per-effort sets, the plan's final merge and the deletion proof (Task P3.2; owner answers OQ-5, OQ-6, Q-15 (a), Q-M4 (a),
Q-Pplan-9 (a); the binding decisions D-Q6 to D-Q13 of the task table). Standard library only; no Unicode property or case
method is read, and no ``int()`` is made of any text. Every git read goes through ``gitinfo``.

Public names: ``plan_ledger``, ``final_merge``, ``plan_effort``, ``program_effort``, ``cited_decisions``, ``is_slug``.
"""
from __future__ import annotations

import os
import posixpath
import re
import stat
from typing import List, Optional

from gates.lib import checkpoints, claims, findings, gitinfo, ids, programs, store
from gates.lib.merge import merged_errors
from gates.lib.result import GateError
from gates.lib import tipread

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
_FILE_MODES = ("100644", "100755")
_TREE = "040000"


def is_slug(plan: object) -> bool:
    """True for a plan slug: ``[a-z0-9][a-z0-9-]*`` in a ``str`` (a subclass is refused)."""
    return type(plan) is str and _SLUG.fullmatch(plan) is not None


def _need_slug(who: str, plan: object) -> str:
    if not is_slug(plan):
        raise ValueError("%s: plan must be a plan slug of a-z, 0-9 and '-'" % who)
    return plan  # type: ignore[return-value]


def _cfg_text(cfg: object, *keys: str) -> str:
    node: object = cfg
    for k in keys:
        if type(node) is not dict or k not in node:
            raise GateError("cfg: %s is missing" % ".".join(keys))
        node = node[k]
    if type(node) is not str or node == "":
        raise GateError("cfg: %s must be a non-empty string" % ".".join(keys))
    return node


def plan_ledger(root: str, cfg: dict, plan: str) -> Optional[str]:
    """The text of ``<paths.plan_state>/<plan>/ledger.md``: the regular file in the working tree when there is one
    (a symlink or another kind of entry is a GateError; decision D-Q6), else ``gitinfo.last_text(root, "HEAD", ...)``,
    which reads the version a cleanup commit deleted. ``None`` when the ledger never existed. A line only the working
    tree holds still has to pass ``merged_errors``, which reads git alone."""
    gitinfo._need_root(root)
    _need_slug("plan_ledger", plan)
    rel = "%s/%s/ledger.md" % (_cfg_text(cfg, "paths", "plan_state"), plan)
    gitinfo._require_toplevel(root)
    path = os.path.join(root, *rel.split("/"))
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        mode = None
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None
    if mode is None:
        now = tipread.show_file(root, "HEAD", rel)  # a symlink, tree or gitlink at HEAD is refused, never read as absent
        if now is not None:
            return now
        return gitinfo.last_text(root, "HEAD", rel)
    if not stat.S_ISREG(mode):
        raise GateError("%s: is not a regular file" % rel)
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("%s: not valid UTF-8" % rel) from None
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)) from None


def final_merge(root: str, cfg: dict, plan: str) -> Optional[dict]:
    """The first ``MERGED`` line with ``final=yes`` of the plan ledger (``checkpoints.merged_lines``' dict, ``pr`` an
    ``int``; decisions D-Q7, D-Q8) that passes ``merge.merged_errors(root, cfg, plan, line)``, else ``None``. A line a
    check cannot read (a ``ValueError``) does not pass. A bad ``plan`` is a ``ValueError``, a bad root or cfg a
    GateError. The plan has merged when this exists; every earlier ``MERGED`` line is a merge of the plan, not its end."""
    text = plan_ledger(root, cfg, plan)
    if text is None:
        return None
    for line in checkpoints.merged_lines(text):
        if line["final"] != "yes":
            continue
        try:
            if merged_errors(root, cfg, plan, line) == []:
                return line
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- plan_effort

def _walk(root: str, at: str, directory: str) -> List[str]:
    """Every regular file under ``directory`` at ``at``, recursively; a symlink or gitlink is a GateError naming it."""
    out: List[str] = []
    for mode, _, path in gitinfo.ls_tree_entries(root, at, directory):
        if mode in _FILE_MODES:
            out.append(path)
        elif mode == _TREE:
            out.extend(_walk(root, at, path))
        else:
            raise GateError("%s: is a symlink or a gitlink (mode %s); a per-effort directory holds regular files only"
                            % (path, mode))
    return out


def _spec_list(text: str) -> object:
    """The ``spec`` value of the handoff ``text``; ``ValueError`` when the front matter does not parse."""
    return checkpoints.parse_handoff(text).get("spec")


def _other_specs(root: str, cfg: dict, plan: str) -> Optional[set]:
    """The spec paths the handoffs of the other plans at the tip of ``base_branch`` name; ``None`` when one of those
    handoffs cannot be read (it then counts as naming every spec; decision D-Q11)."""
    base = _cfg_text(cfg, "base_branch")
    if base not in gitinfo.local_branches(root):
        raise GateError("%s is not a local branch; update %s from the remote" % (base, base))
    ref = "refs/heads/" + base
    plan_state = _cfg_text(cfg, "paths", "plan_state")
    named: set = set()
    for mode, _, path in gitinfo.ls_tree_entries(root, ref, plan_state):
        if mode != _TREE or posixpath.basename(path) == plan:
            continue
        try:
            text = tipread.show_file(root, ref, path + "/handoff.md")
            if text is None:
                continue
            specs = _spec_list(text)
        except (GateError, ValueError):
            return None
        if type(specs) is not list or any(type(s) is not str for s in specs):
            return None
        named.update(specs)
    return named


def _own_specs(root: str, cfg: dict, plan: str, at: str) -> List[str]:
    """The ``spec`` paths of the plan's own handoff at ``at`` (none when it is absent); a bad item is a GateError."""
    rel = "%s/%s/handoff.md" % (_cfg_text(cfg, "paths", "plan_state"), plan)
    text = tipread.show_file(root, at, rel)
    if text is None:
        return []
    try:
        specs = _spec_list(text)
    except ValueError as e:
        raise GateError("%s: %s" % (rel, e)) from None
    if type(specs) is not list or not specs:
        raise GateError("%s: spec must be a non-empty list of paths" % rel)
    out = []
    prefix = _cfg_text(cfg, "paths", "specs") + "/"
    for i, s in enumerate(specs):
        if type(s) is not str:
            raise GateError("%s: spec.%d must be a string" % (rel, i))
        try:
            gitinfo._check_norm(s, "spec")
        except GateError as e:
            raise GateError("%s: spec.%d: %s" % (rel, i, e)) from None
        if not s.startswith(prefix):
            raise GateError("%s: spec.%d: %s is not under %s" % (rel, i, s, prefix[:-1]))
        if not gitinfo.blob_exists(root, at, s):
            raise GateError("%s: spec.%d: %s is not a regular file at %s" % (rel, i, s, at))
        out.append(s)
    return out


def plan_effort(root: str, cfg: dict, plan: str, at: str) -> list:
    """The repo-relative per-effort paths of plan slug ``plan`` as of commit ``at``, sorted and unique (programs design
    §7.2; decision D-Q10: everything is read from ``at``'s tree): ``<paths.plans>/<plan>.md``; every file under
    ``<paths.plan_state>/<plan>/`` and ``<paths.reviews>/<plan>/``; each ``spec`` the plan's handoff names, unless the
    handoff of another live plan at the tip of ``base_branch`` names it too (an unreadable other handoff keeps every
    spec; decision D-Q11); every claim file whose ``document`` is one of these; every finding record with a resolved
    status and ``resolved_by: <plan>``. A bad ``spec`` item of the plan's own handoff, a symlink or gitlink in a
    per-effort directory and an unreadable record are each a GateError naming it; ``at`` is a non-empty ``str`` that is
    a commit."""
    gitinfo._need_root(root)
    _need_slug("plan_effort", plan)
    gitinfo._need_revision(at, "at")
    plans = _cfg_text(cfg, "paths", "plans")
    plan_state = _cfg_text(cfg, "paths", "plan_state")
    reviews = _cfg_text(cfg, "paths", "reviews")
    claims_dir = _cfg_text(cfg, "paths", "claims")
    findings_dir = _cfg_text(cfg, "paths", "findings")
    gitinfo._require_toplevel(root)
    if not gitinfo.commit_exists(root, at):
        raise GateError("at: %s is not a commit in this repository" % at)
    out: set = set()
    plan_md = "%s/%s.md" % (plans, plan)
    if tipread.is_file(root, at, plan_md):  # a symlink, tree or gitlink plan file is refused, never left out
        out.add(plan_md)
    out.update(_walk(root, at, "%s/%s" % (plan_state, plan)))
    out.update(_walk(root, at, "%s/%s" % (reviews, plan)))
    own = _own_specs(root, cfg, plan, at)
    if own:
        others = _other_specs(root, cfg, plan)
        if others is not None:
            out.update(s for s in own if s not in others)
    for name, row in claims._rows_at(root, at, claims_dir, at, ""):
        doc = row.get("document")
        if type(doc) is str and doc in out:
            if posixpath.basename(name) != claims.slug(doc) + ".yml":
                raise GateError("%s: the file name does not match its document %s" % (name, doc))
            out.add(name)
    for name, row in store._records_at(root, at, findings_dir, at, ""):
        if findings.is_resolved(row) and type(row.get("resolved_by")) is str and row["resolved_by"] == plan:
            out.add(name)
    return sorted(out)


# ---------------------------------------------------------------- program_effort

def _str_path(value: object, what: str, directory: str, suffix: str) -> str:
    if type(value) is not str:
        raise GateError("streams.yml: %s must be a string" % what)
    gitinfo._check_norm(value, "streams.yml: %s" % what)
    rest = value[len(directory) + 1:-len(suffix)] if suffix else value[len(directory) + 1:]
    if (not value.startswith(directory + "/") or (suffix and not value.endswith(suffix)) or rest == ""
            or (suffix and "/" in rest)):
        raise GateError("streams.yml: %s: %s is not %s/<name>%s" % (what, value, directory, suffix))
    return value


def program_effort(root: str, cfg: dict, program: str, at: Optional[str]) -> list:
    """The program's ``plan`` and ``specs`` from ``streams.yml`` (read at ``refs/heads/<program>/integration``), and
    ``plan_effort`` of each stream plan at its own final merge; sorted and unique. The program folder never reaches
    ``base_branch`` (Q-M4 (a)) and is not in the set. ``at`` is ``None`` or a revision string and does not change the
    reads (decision D-Q12). A stream plan with no final merge is a GateError naming it; ``load_program``'s errors pass
    through."""
    gitinfo._need_root(root)
    if at is not None:
        gitinfo._need_revision(at, "at")
    why = programs.program_problem(program)
    if why:
        raise GateError("program name: %s" % why)
    prog = programs.load_program(root, cfg, program, "refs/heads/%s/integration" % program)
    plans = _cfg_text(cfg, "paths", "plans")
    specs_dir = _cfg_text(cfg, "paths", "specs")
    streams = prog.streams
    out: set = set()
    out.add(_str_path(streams.get("plan"), "plan", plans, ".md"))
    specs = streams.get("specs")
    if type(specs) is not list:
        raise GateError("streams.yml: specs must be a list")
    for i, s in enumerate(specs):
        out.add(_str_path(s, "specs.%d" % i, specs_dir, ""))
    rows = streams.get("streams")
    if type(rows) is not list:
        raise GateError("streams.yml: streams must be a list")
    slugs = set()
    for i, row in enumerate(rows):
        path = _str_path(row.get("plan") if type(row) is dict else None, "streams.%d.plan" % i, plans, ".md")
        out.add(path)
        slugs.add(checkpoints.plan_slug(path))
    for slug in sorted(slugs):
        fm = final_merge(root, cfg, slug)
        if fm is None:
            raise GateError("stream plan %s has no final merge; the program is not finished" % slug)
        out.update(plan_effort(root, cfg, slug, fm["merge"]))
    return sorted(out)


# ---------------------------------------------------------------- cited_decisions

def cited_decisions(root: str, paths: list, at: str, prefix: str) -> list:
    """The decision ids of ``prefix`` found as whole tokens (the characters around them outside ``[0-9A-Za-z_-]``) in the
    files ``paths`` at ``at``, sorted and unique. Fences and backticks are not special. A path absent at ``at`` adds no
    id; a file that is not valid UTF-8 is a GateError naming it (decision D-Q13). The class is written out, never ``\\w``,
    so the answer does not depend on the interpreter's Unicode tables."""
    gitinfo._need_root(root)
    if type(paths) is not list or any(type(p) is not str for p in paths):
        raise GateError("paths must be a list of str")
    if type(prefix) is not str or prefix == "":
        raise GateError("prefix must be a non-empty string")
    gitinfo._need_revision(at, "at")
    gitinfo._require_toplevel(root)
    if not gitinfo.commit_exists(root, at):
        raise GateError("at: %s is not a commit in this repository" % at)
    pattern = re.compile(r"(?<![0-9A-Za-z_-])(%s)(?![0-9A-Za-z_-])" % ids.id_pattern(prefix).pattern)
    found: set = set()
    for path in paths:
        gitinfo._check_norm(path, "path")
        text = tipread.show_file(root, at, path)
        if text is None:
            continue
        for m in pattern.finditer(text):
            if ids.id_problem(m.group(1), prefix) == "":
                found.add(m.group(1))
    return sorted(found)
