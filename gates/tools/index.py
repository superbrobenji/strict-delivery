"""Tool ``index``: the generated decision and finding indexes, ``in-force.md`` and the overview ``INDEX.md``
(spec 5, 7.4; owner OQ-12, OQ-13, OQ-17, Q-1c3-1..3).

Standard library only. ``render`` builds the four files' text and writes nothing; ``regenerate`` writes them. The
four files are ignored by git (spec 5) and checked by ``gate_schema`` when present (OQ-17).
"""
from __future__ import annotations

import os
import posixpath
import stat
import sys
import tempfile
from typing import Optional

from gates.lib import checkpoints, cleanup, config, decisions, findings, gitinfo, ids, programs, yamlsub
from gates.lib.result import GateError, gate_args, repo_root, safe_text
from gates.lib.store import Store, store_errors

PRODUCES = ("decision-index", "finding-index", "in-force", "overview")

_IN_FORCE_HEAD = ["<!-- schema: in-force/1 -->", "# In-force decisions (generated; do not edit)", "",
                  "| id | topics | rule | landed_in |", "|---|---|---|---|"]


def _why(e: OSError) -> str:
    return e.strerror or str(e) or type(e).__name__


def _one_line(text: str, sep: str) -> str:
    """Each ``\\r\\n``, ``\\r`` or ``\\n`` in ``text`` as ``sep`` (owner Q-1c3-2 (a))."""
    return text.replace("\r\n", sep).replace("\r", sep).replace("\n", sep)


def _cell(text: str) -> str:
    return _one_line(text, "<br>").replace("|", "\\|")


def _records(root: str, kind: str, cfg: dict, validate) -> list:
    """The register's records sorted by id; the first record that fails ``validate`` or ``store_errors`` is a
    GateError naming its file (owner Q-1c3-3 (a))."""
    store = Store(root, kind, cfg)
    records = store.load()
    for rec in records:
        errs = validate(rec.row, cfg)
        if errs:
            raise GateError("%s: %s" % (rec.file, errs[0]))
    for suffix, reason in store_errors(records, store.prefix):
        what, _, rest = suffix.partition(".")
        raise GateError("%s: %s" % (rest, reason) if what in ("id", "name") else reason)
    return sorted(records, key=lambda r: r.id)


def _emit(value: dict, rel: str) -> str:
    try:
        return yamlsub.emit(value)
    except yamlsub.EmitError as e:
        raise GateError("%s: cannot emit (%s)" % (rel, e)) from None


def _owner(owner: dict) -> str:
    kind = owner["kind"]
    if kind == "plan":
        return "plan:%s/%s" % (owner["plan"], owner["task"])
    if kind == "issue":
        return "issue:%d" % owner["number"]
    return "roadmap:%s" % owner["plan"]


def _link(target: str, start_dir: str) -> str:
    """``target`` relative to the directory ``start_dir`` (both repo-relative; ``""`` is the root)."""
    t = target.split("/")
    s = start_dir.split("/") if start_dir else []
    n = 0
    while n < len(t) - 1 and n < len(s) and t[n] == s[n]:
        n += 1
    return "/".join([".."] * (len(s) - n) + t[n:])


_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")  # CommonMark 0.31 section 2.1: the 32


def _md_escape(s: str) -> str:
    """``s`` with a backslash before every ASCII punctuation character (CommonMark section 2.4). Every escaped
    character is literal, so no character reference (section 2.5), emphasis, code span, raw HTML or bracket can
    form; every other character is copied as it is (owner Q-1c3-RR2-1 (a), Q-1c3-F2-1 (a))."""
    return "".join("\\" + c if c in _ASCII_PUNCT else c for c in s)


def _md_link(text: str, dest: str) -> str:
    """The inline link ``[text](<dest>)`` (owner Q-1c3-R1 (a)) with both parts escaped by ``_md_escape``: a
    CommonMark reader gets back exactly ``text`` as the link text and ``dest`` as the destination. ``dest`` holds no
    line break (config paths are printable)."""
    return "[%s](<%s>)" % (_md_escape(text), _md_escape(dest))


def _architecture(root: str, rel: str) -> Optional[str]:
    """The text of the architecture file, None when it is absent; anything else unreadable is a GateError."""
    try:
        return decisions._regular_file_text(root, rel)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        why = "not valid UTF-8" if isinstance(e, UnicodeDecodeError) else _why(e)
        raise GateError("%s: cannot be read as a UTF-8 regular file (%s)" % (rel, why)) from None


def _norm_dir(path: object, what: str) -> str:
    """A normalised repo-relative directory: no empty, ``.`` or ``..`` segment, no leading or trailing ``/``."""
    if type(path) is not str or path == "" or any(s in ("", ".", "..") for s in path.split("/")):
        raise GateError("cfg: %s must be a normalised repo-relative directory" % what)
    return path


def _md_files(root: str, directory: str) -> list:
    """The repo-relative paths of the regular ``*.md`` files directly in ``directory`` of the working tree (a symlink,
    a directory, a fifo or a nested file is not listed), sorted by code point; an absent directory gives ``[]``
    (decision D-5b-Q1 (a))."""
    base = os.path.join(root, *directory.split("/"))
    try:
        names = os.listdir(base)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (directory, _why(e))) from None
    out = []
    for n in names:
        if not n.endswith(".md"):
            continue
        try:
            mode = os.lstat(os.path.join(base, n)).st_mode
        except OSError:
            continue
        if stat.S_ISREG(mode):
            out.append(directory + "/" + n)
    return sorted(out)


def _deleted_md(root: str, directory: str) -> list:
    """``*.md`` paths directly under ``directory`` that history reachable from ``HEAD`` deleted and ``HEAD`` lacks.
    A shallow clone lists only the deletions it holds (``deleted_paths``; decision D-5b-Q17 (a))."""
    return [p for p in gitinfo.deleted_paths(root, "HEAD", directory)
            if p.endswith(".md") and posixpath.dirname(p) == directory]


def _has_commit(root: str) -> bool:
    """False on an unborn ``HEAD``: the history is then empty (decision D-5b-Q2 (a))."""
    try:
        gitinfo.head_sha(root)
    except GateError:
        return False
    return True


def _handoff(text: str, where: str) -> tuple:
    """``(block, spec list)`` of a handoff text: ``block`` a non-empty ``str``, ``spec`` absent or a list of ``str``;
    anything else is a GateError naming ``where`` (decision D-5b-Q8 (a))."""
    try:
        row = checkpoints.parse_handoff(text)
    except ValueError as e:
        raise GateError("%s: %s" % (where, e)) from None
    block = row.get("block")
    if type(block) is not str or block == "":
        raise GateError("%s: block must be a non-empty string" % where)
    spec = row["spec"] if "spec" in row else []
    if type(spec) is not list or any(type(s) is not str for s in spec):
        raise GateError("%s: spec must be a list of strings" % where)
    return block, spec


def _tree_handoffs(root: str, plan_state: str) -> dict:
    """``{folder name: (block, specs)}`` for each real folder of ``plan_state`` in the working tree that holds a
    ``handoff.md``; one that does not read or load is a GateError naming the file."""
    try:
        names = sorted(os.listdir(os.path.join(root, *plan_state.split("/"))))
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (plan_state, _why(e))) from None
    out = {}
    for n in names:
        try:
            if not stat.S_ISDIR(os.lstat(os.path.join(root, *plan_state.split("/"), n)).st_mode):
                continue
        except OSError:
            continue
        rel = "%s/%s/handoff.md" % (plan_state, n)
        try:
            text = decisions._regular_file_text(root, rel)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError) as e:
            why = "not valid UTF-8" if isinstance(e, UnicodeDecodeError) else _why(e)
            raise GateError("%s: cannot be read as a UTF-8 regular file (%s)" % (rel, why)) from None
        out[n] = _handoff(text, rel)
    return out


def _live(root: str, cfg: dict) -> list:
    """``(name, ref, Program)`` per live program, sorted; each is read at the tip of ``refs/heads/<name>/integration``
    (decisions D-5b-Q10; Q-Pplan-12 (a))."""
    out = []
    for name in programs.live_programs(root, cfg):
        ref = "refs/heads/" + programs.branch_of(name)
        out.append((name, ref, programs.load_program(root, cfg, name, ref)))
    return out


def _status_rows(cfg: dict, prog: programs.Program) -> list:
    rows = programs.status_rows(prog.status_text)
    for r in rows:
        if "__error__" in r:
            raise GateError("%s/%s/status.md:%d: %s" % (cfg["paths"]["programs"], prog.name, r["__line__"],
                                                       r["__error__"]))
    return rows


def _program_streams(cfg: dict, prog: programs.Program) -> list:
    """``(stream id, plan path or None)`` per stream of ``streams.yml``; a stream that is not a mapping with a ``str``
    id (``branch_of`` accepts it) or a plan that is not a ``str`` is a GateError naming the file."""
    where = "%s/%s/streams.yml" % (cfg["paths"]["programs"], prog.name)
    items = prog.streams.get("streams", [])
    if type(items) is not list:
        raise GateError("%s: streams must be a list" % where)
    out = []
    for s in items:
        sid = s.get("id") if type(s) is dict else None
        plan = s.get("plan") if type(s) is dict else None
        try:
            if type(sid) is not str:
                raise ValueError("id is not a string")
            programs.branch_of(prog.name, sid)
        except ValueError as e:
            raise GateError("%s: stream id: %s" % (where, e)) from None
        if plan is not None and type(plan) is not str:
            raise GateError("%s: stream %s: plan must be a string" % (where, sid))
        out.append((sid, plan))
    return out


def _specs_and_plans(root: str, cfg: dict, progs: list) -> list:
    """The ``## Specs and plans`` lines (programs design 9: every state is derived)."""
    paths = cfg["paths"]
    plan_dir = _norm_dir(paths["plans"], "paths.plans")
    spec_dir = _norm_dir(paths["specs"], "paths.specs")
    plan_state = _norm_dir(paths["plan_state"], "paths.plan_state")
    hist = _has_commit(root)
    handoffs = _tree_handoffs(root, plan_state)
    named = {s for _, specs in handoffs.values() for s in specs}
    source = {}   # plan path -> in-progress suffix of the first live program naming it
    local = set(gitinfo.local_branches(root)) if progs else set()
    for name, ref, prog in progs:
        rows = _status_rows(cfg, prog)
        plan = prog.streams.get("plan")
        if type(plan) is str:
            source.setdefault(plan, " (program %s)" % safe_text(name))
        for sid, splan in _program_streams(cfg, prog):
            if splan is None:
                continue
            row = next((r for r in rows if r["stream"] == sid), None)
            suffix = " (program %s, stream %s%s)" % (safe_text(name), safe_text(sid),
                                                     ", block " + safe_text(row["block"]) if row else "")
            source.setdefault(splan, suffix)
            prefix = plan_dir + "/"
            if not (splan.startswith(prefix) and splan.endswith(".md") and "/" not in splan[len(prefix):-3]
                    and len(splan) > len(prefix) + 3):
                continue
            branch = programs.branch_of(name, sid)
            if branch not in local:
                continue
            hpath = "%s/%s/handoff.md" % (plan_state, splan[len(prefix):-3])
            text = gitinfo.show(root, "refs/heads/" + branch, hpath)
            if text is not None:
                named.update(_handoff(text, "refs/heads/%s:%s" % (branch, hpath))[1])
    todo, doing, done = {}, {}, {}
    present = _md_files(root, plan_dir)
    for path in present:
        slug = path[len(plan_dir) + 1:-3]
        if not cleanup.is_slug(slug):
            todo[path] = "- " + safe_text(path)
            continue
        final = cleanup.final_merge(root, cfg, slug) if hist else None
        if final is not None:
            done[path] = "- %s (merged %s; cleanup pending)" % (safe_text(path), safe_text(final["merge"]))
        elif slug in handoffs:
            doing[path] = "- %s (block %s)" % (safe_text(path), safe_text(handoffs[slug][0]))
        elif path in source:
            doing[path] = "- " + safe_text(path) + source[path]
        else:
            todo[path] = "- " + safe_text(path)
    if hist:
        for path in _deleted_md(root, plan_dir):
            if path in todo or path in doing or path in done:
                continue
            slug = path[len(plan_dir) + 1:-3]
            final = cleanup.final_merge(root, cfg, slug) if cleanup.is_slug(slug) else None
            done[path] = ("- %s (merged %s)" % (safe_text(path), safe_text(final["merge"])) if final is not None
                          else "- %s (merge not recorded)" % safe_text(path))
    for path in _md_files(root, spec_dir):
        if path not in named:
            todo[path] = "- " + safe_text(path)
    for path in named:
        doing[path] = "- " + safe_text(path)
    if hist:
        for path in _deleted_md(root, spec_dir):
            if path not in named and path not in todo:
                done[path] = "- " + safe_text(path)
    lines = ["### Todo", "### In progress", "### Done"]
    out = []
    for head, d in zip(lines, (todo, doing, done)):
        out.append(head)
        out.extend([d[k] for k in sorted(d)] or ["none"])
    return out


def _live_programs(root: str, cfg: dict, progs: list) -> list:
    """The ``## Live programs`` lines: per program its status rows, its open requests and its pending owner questions."""
    if not progs:
        return ["none"]
    where = cfg["paths"]["programs"]
    dec_prefix = cfg["ids"]["decision"]
    out = []
    for name, ref, prog in progs:
        rows = _status_rows(cfg, prog)
        out.append("### " + safe_text(name))
        out.extend("- %s | %s | %s | used %s of %s | blockers %s | pending %s" % tuple(
            safe_text(r[k]) for k in ("stream", "block", "status", "used", "estimate", "blockers",
                                      "pending decisions")) for r in rows)
        if not rows:
            out.append("none")
        reqs = []
        for rec in prog.requests:
            r = rec.row
            if type(rec.id) is not str or any(type(r.get(k)) is not str for k in
                                              ("need", "from_stream", "to_stream", "status")) \
                    or r["status"] not in programs.REQUEST_TRANSITIONS:
                raise GateError("%s: id, need, from_stream, to_stream and status must be strings and status one of "
                                "%s" % (rec.file, ", ".join(programs.REQUEST_TRANSITIONS)))
            if r["status"] in ("open", "accepted", "disputed"):
                reqs.append(rec)
        out.append("Open requests:")
        out.extend("- %s %s -> %s %s: %s" % tuple(safe_text(x) for x in (
            rec.id, rec.row["from_stream"], rec.row["to_stream"], rec.row["status"], rec.row["need"]))
            for rec in sorted(reqs, key=lambda x: x.id))
        if not reqs:
            out.append("none")
        pending = []
        for r in rows:
            if r["pending decisions"] == "none":
                continue
            for d in r["pending decisions"].split(","):
                if ids.id_problem(d, dec_prefix):
                    raise GateError("%s/%s/status.md: stream %s: pending decisions '%s' is not a decision id"
                                    % (where, name, r["stream"], d))
                if d not in pending:
                    pending.append(d)
        out.append("Pending owner questions:")
        questions = {}
        if pending:
            for rec in checkpoints.records_at(root, cfg, ref, "decision"):
                if rec.row.get("status") == "open":
                    if type(rec.row.get("question")) is not str:
                        raise GateError("%s: question must be a string" % rec.file)
                    questions[rec.id] = rec.row["question"]
        out.extend("- %s: %s" % (safe_text(d), safe_text(questions[d]) if d in questions else "no open record")
                   for d in pending)
        if not pending:
            out.append("none")
    return out


def _overview(root: str, cfg: dict, fins: list, n_in_force: int, in_force_rel: str) -> str:
    paths = cfg["paths"]
    here = posixpath.dirname(paths["index"])
    lines = ["<!-- schema: overview/2 -->", "", "## Architecture"]
    arch = _architecture(root, paths["architecture"])
    if arch is None:
        lines.append("none")
    else:
        lines.append(_md_link(posixpath.basename(paths["architecture"]), _link(paths["architecture"], here)))
        lines.extend("- " + _one_line(ln[3:], " ") for ln in arch.split("\n") if ln.startswith("## "))
    progs = _live(root, cfg)
    lines += ["", "## Specs and plans"] + _specs_and_plans(root, cfg, progs)
    lines += ["", "## Live programs"] + _live_programs(root, cfg, progs)
    lines += ["", "## Open findings"]
    open_ = [r for r in fins if not findings.is_resolved(r.row)]
    for sev in findings.SEVERITIES:
        lines.append("- %s: %d" % (sev, sum(1 for r in open_ if r.row["severity"] == sev)))
    for r in open_:
        lines.append("- %s (%s, %s): %s" % (r.id, r.row["severity"], r.row["status"], _one_line(r.row["class"], " ")))
    lines += ["", "## In-force decisions",
              "%d in force: %s" % (n_in_force, _md_link("in-force.md", _link(in_force_rel, here)))]
    return "\n".join(lines) + "\n"


def render(root: str, cfg: dict) -> dict:
    """Repo-relative path -> text for the four generated files, in a fixed order; writes nothing."""
    gitinfo._require_toplevel(root)
    decs = _records(root, "decision", cfg, decisions.validate)
    fins = _records(root, "finding", cfg, findings.validate)
    paths = cfg["paths"]
    rels = [paths["decisions"] + "/index.yml", paths["findings"] + "/index.yml", paths["decisions"] + "/in-force.md",
            paths["index"]]
    if len(set(rels)) != len(rels):
        raise GateError("two generated files would share a path (%s); configure distinct paths" % ", ".join(rels))
    gone = decisions.superseded_ids(decs)
    dec_entries = [{"id": r.id, "file": r.file,
                    "status": "superseded" if r.row["status"] == "answered" and r.id in gone else r.row["status"],
                    "class": r.row["class"], "topics": list(r.row["topics"])} for r in decs]
    fin_entries = [{"id": r.id, "file": r.file, "status": r.row["status"], "severity": r.row["severity"],
                    "owner": _owner(r.row["owner"])} for r in fins]
    force = decisions.in_force(decs)
    table = list(_IN_FORCE_HEAD)
    for r in force:
        cells = [r.id, ", ".join(r.row["topics"]), r.row.get("rule", ""), ", ".join(r.row["landed_in"])]
        table.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return {
        rels[0]: _emit({"schema": "decision-index/1", "decisions": dec_entries}, rels[0]),
        rels[1]: _emit({"schema": "finding-index/1", "findings": fin_entries}, rels[1]),
        rels[2]: "\n".join(table) + "\n",
        rels[3]: _overview(root, cfg, fins, len(force), rels[2]),
    }


def _check_target(root: str, rel: str) -> None:
    """Every existing parent of ``rel`` is a real directory; ``rel`` is absent, a regular file or a symlink."""
    parts = rel.split("/")
    for i in range(1, len(parts)):
        sub = "/".join(parts[:i])
        try:
            mode = os.lstat(os.path.join(root, *parts[:i])).st_mode
        except FileNotFoundError:
            return
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (sub, _why(e))) from None
        if stat.S_ISLNK(mode):
            raise GateError("%s: is a symlink; generated files are written only under real directories" % sub)
        if not stat.S_ISDIR(mode):
            raise GateError("%s: is not a directory" % sub)
    try:
        mode = os.lstat(os.path.join(root, *parts)).st_mode
    except FileNotFoundError:
        return
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
    if stat.S_ISDIR(mode):
        raise GateError("%s: is a directory" % rel)
    if not stat.S_ISREG(mode) and not stat.S_ISLNK(mode):  # a symlink is replaced (W2); owner Q-1c3-RR1 (a)
        raise GateError("%s: is not a regular file" % rel)


def _write(root: str, rel: str, text: str) -> None:
    """Write through a temp file in the same directory and ``os.replace`` (a symlink there is replaced). The mode
    follows Store (owner Q-1c3-R2 (b)): an existing regular file keeps its mode, as ``Store.replace``; anything else
    becomes a new file whose mode is 0666 less the umask, as ``Store.create``."""
    directory = os.path.join(root, *rel.split("/")[:-1])
    path = os.path.join(root, *rel.split("/"))
    try:
        st = os.lstat(path)
        mode = stat.S_IMODE(st.st_mode) if stat.S_ISREG(st.st_mode) else None
    except FileNotFoundError:
        mode = None
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
    if mode is None:
        mask = os.umask(0o022)  # read the umask; it is set back at once
        os.umask(mask)
        mode = 0o666 & ~mask
    try:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix="." + posixpath.basename(rel) + ".", suffix=".tmp")
    except OSError as e:
        raise GateError("%s: cannot write (%s)" % (rel, _why(e))) from None
    done = False
    try:
        try:
            fh = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with fh:
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
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


def regenerate(root: str, cfg: dict) -> list:
    """Render, check every target, create missing parents, write the four files; return their paths in order.
    A refusal before the first write writes nothing; a write failure leaves the files already replaced."""
    files = render(root, cfg)
    for rel in files:
        _check_target(root, rel)
    for rel in files:
        parent = posixpath.dirname(rel)
        if parent:
            try:
                os.makedirs(os.path.join(root, *parent.split("/")), exist_ok=True)
            except OSError as e:
                raise GateError("%s: cannot create the directory (%s)" % (parent, _why(e))) from None
    for rel, text in files.items():
        _write(root, rel, text)
    return list(files)


def _root(given: Optional[str]) -> str:
    root = given if given is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    gitinfo._require_toplevel(root)  # before the config is read (verifier O3)
    return root


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates index [--root R]``: print each written path; 2 on a usage error, 1 on a refusal."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        ns = gate_args("index").parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        root = _root(ns.root)
        written = regenerate(root, config.load(root))
    except GateError as e:
        sys.stderr.write("index: %s\n" % safe_text(e))
        return 1
    sys.stdout.write("".join(p + "\n" for p in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
