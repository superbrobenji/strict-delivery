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

from gates.lib import config, decisions, findings, gitinfo, yamlsub
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


def _dest(path: str) -> str:
    """``path`` as a CommonMark ``<...>`` link destination that reads back as exactly ``path`` (owner Q-1c3-R1 (a),
    Q-1c3-F1-1 (a)): ``\\`` first, then ``<`` and ``>``, are backslash-escaped."""
    return "<" + path.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>") + ">"


def _architecture(root: str, rel: str) -> Optional[str]:
    """The text of the architecture file, None when it is absent; anything else unreadable is a GateError."""
    try:
        return decisions._regular_file_text(root, rel)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        why = "not valid UTF-8" if isinstance(e, UnicodeDecodeError) else _why(e)
        raise GateError("%s: cannot be read as a UTF-8 regular file (%s)" % (rel, why)) from None


def _overview(root: str, cfg: dict, fins: list, n_in_force: int, in_force_rel: str) -> str:
    paths = cfg["paths"]
    here = posixpath.dirname(paths["index"])
    lines = ["<!-- schema: overview/1 -->", "", "## Architecture"]
    arch = _architecture(root, paths["architecture"])
    if arch is None:
        lines.append("none")
    else:
        lines.append("[%s](%s)" % (posixpath.basename(paths["architecture"]),
                                   _dest(_link(paths["architecture"], here))))
        lines.extend("- " + _one_line(ln[3:], " ") for ln in arch.split("\n") if ln.startswith("## "))
    lines += ["", "## Open findings"]
    open_ = [r for r in fins if not findings.is_resolved(r.row)]
    for sev in findings.SEVERITIES:
        lines.append("- %s: %d" % (sev, sum(1 for r in open_ if r.row["severity"] == sev)))
    for r in open_:
        lines.append("- %s (%s, %s): %s" % (r.id, r.row["severity"], r.row["status"], _one_line(r.row["class"], " ")))
    lines += ["", "## In-force decisions",
              "%d in force: [in-force.md](%s)" % (n_in_force, _dest(_link(in_force_rel, here)))]
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
