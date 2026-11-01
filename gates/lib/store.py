"""The one-file-per-record register store (spec 7.2) and its base-branch checks, standard library only.

A register directory holds one ``<id>.yml`` per record, nothing else except the generated ``index.yml`` and
``in-force.md``. The store never validates fields; the schema checker does. Git is reached only through
``gates.lib.gitinfo``.
"""
from __future__ import annotations

import os
import posixpath
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable

from gates.lib import gitinfo, ids, yamlsub
from gates.lib.result import GateError, safe_text

_PATH_KEY = {"decision": "decisions", "finding": "findings"}
_GENERATED = ("index.yml", "in-force.md")


@dataclass(frozen=True)
class Record:
    id: object  # the row's ``id`` value, None when the row has none (the store does not validate)
    row: dict
    file: str   # repo-relative, "/"-separated


def _why(e: OSError) -> str:
    return e.strerror or type(e).__name__


def _is_record_name(name: str) -> bool:
    return name.endswith(".yml") and not name.startswith(".") and name not in _GENERATED


def _same(a: object, b: object) -> bool:
    """Parsed-value equality that tells ``1``, ``true`` and ``1.0`` apart (Python's ``==`` does not)."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _parse(text: str) -> object:
    return yamlsub.parse(yamlsub._file_text(text.encode("utf-8")))  # the same BOM and CRLF rules as load()


class Store:
    def __init__(self, root: str, kind: str, cfg: dict) -> None:
        if kind not in _PATH_KEY:
            raise GateError("store kind must be 'decision' or 'finding'")
        try:
            self.directory = cfg["paths"][_PATH_KEY[kind]]
            self.prefix = cfg["ids"][kind]
        except (KeyError, TypeError):
            raise GateError("config lacks paths.%s or ids.%s" % (_PATH_KEY[kind], kind)) from None
        self.root = root
        self.kind = kind

    def _abs(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def _check_id(self, id: object) -> None:
        problem = ids.id_problem(id, self.prefix)
        if problem:
            raise GateError("cannot use id %s: %s" % (id, problem))

    def path_for(self, id: str) -> str:
        """The repo-relative path of the record file for ``id``; the id must pass ``id_problem``."""
        self._check_id(id)
        return "%s/%s.yml" % (self.directory, id)

    def _dir_exists(self) -> bool:
        """True when the register directory exists; False when it or a parent is missing. Every component of
        the path from the repo root down to the register directory must be a real directory: a symlink or a
        non-directory is a GateError naming it (owner Q-1a3r-1). Components above the root are not checked."""
        parts = self.directory.split("/")
        for i in range(1, len(parts) + 1):
            rel = "/".join(parts[:i])
            try:
                mode = os.lstat(self._abs(rel)).st_mode
            except FileNotFoundError:
                return False
            except OSError as e:
                raise GateError("%s: cannot read (%s) (register directory %s)"
                                % (rel, _why(e), self.directory)) from None
            if stat.S_ISLNK(mode):
                raise GateError("%s: is a symlink; register paths must be real directories (register directory %s)"
                                % (rel, self.directory))
            if not stat.S_ISDIR(mode):
                raise GateError("%s: is not a directory (register directory %s)" % (rel, self.directory))
        return True

    def load(self) -> list:
        d = self._abs(self.directory)
        if not self._dir_exists():
            return []
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            raise GateError("%s: cannot read the register directory (%s)" % (self.directory, _why(e))) from None
        out = []
        for name in names:
            if name in _GENERATED:
                continue
            rel = "%s/%s" % (self.directory, name)
            path = os.path.join(d, name)
            try:
                mode = os.lstat(path).st_mode
            except OSError as e:
                raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
            if not _is_record_name(name) or not stat.S_ISREG(mode):
                raise GateError("%s: not a regular file named <id>.yml (only index.yml and in-force.md are "
                                "allowed besides records)" % rel)
            try:
                data = yamlsub.load(path, rel)
            except yamlsub.YamlError as e:
                raise GateError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
            if type(data) is not dict:
                raise GateError("%s: the top level must be a mapping" % rel)
            out.append(Record(data.get("id"), data, rel))
        return out

    def _prepare(self, row: object) -> tuple:
        if type(row) is not dict:
            raise GateError("a record must be a mapping")
        rel = self.path_for(row.get("id"))
        try:
            text = yamlsub.emit(row)
        except yamlsub.EmitError as e:
            raise GateError("%s: cannot emit the record (%s)" % (rel, e)) from None
        return rel, text

    def create(self, row: dict) -> str:
        """Write a new record file (exclusive create); return its repo-relative path."""
        rel, text = self._prepare(row)
        # Check-then-write window accepted (owner Q-1a3rr-1): a symlink planted between this check and the
        # write is not caught here; the next load refuses it.
        self._dir_exists()
        try:
            os.makedirs(self._abs(self.directory), exist_ok=True)
        except OSError as e:
            raise GateError("%s: cannot create the register directory (%s)" % (self.directory, _why(e))) from None
        path = self._abs(rel)
        try:
            fh = open(path, "x", encoding="utf-8", newline="")
        except FileExistsError:
            raise GateError("%s: already exists; use replace" % rel) from None
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
            if not done:  # the file is ours (exclusive create): a partial one is removed
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return rel

    def replace(self, row: dict) -> str:
        """Rewrite an existing record file through a temp file and ``os.replace``; return its path."""
        rel, text = self._prepare(row)
        # Same accepted check-then-write window as in create (owner Q-1a3rr-1).
        if not self._dir_exists():
            raise GateError("%s: does not exist; use create" % rel)
        path = self._abs(rel)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            raise GateError("%s: does not exist; use create" % rel) from None
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
        if not stat.S_ISREG(st.st_mode):
            raise GateError("%s: not a regular file" % rel)
        try:
            fd, tmp = tempfile.mkstemp(dir=self._abs(self.directory), prefix=".%s." % row["id"], suffix=".tmp")
        except OSError as e:
            raise GateError("%s: cannot write (%s)" % (rel, _why(e))) from None
        done = False
        try:
            try:
                fh = os.fdopen(fd, "w", encoding="utf-8", newline="")
            except BaseException:
                os.close(fd)
                raise
            with fh:
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
        return rel


def store_errors(records: list, prefix: str) -> list:
    """``(suffix, reason)`` pairs: ``id.<file>``, ``name.<file>`` and ``duplicate.<id>``."""
    out = []
    files_by_id: dict = {}
    for rec in records:
        problem = ids.id_problem(rec.id, prefix)
        if problem:
            out.append(("id." + rec.file, problem))
        stem = posixpath.basename(rec.file)[:-len(".yml")] if rec.file.endswith(".yml") else rec.file
        if stem != rec.id:
            out.append(("name." + rec.file, "file name %s.yml differs from the record id %s"
                        % (stem, rec.id)))
        if type(rec.id) is str:
            files_by_id.setdefault(rec.id, []).append(rec.file)
    for id_ in sorted(files_by_id):
        files = files_by_id[id_]
        if len(files) > 1:
            out.append(("duplicate." + id_, "id %s appears in %d files: %s" % (id_, len(files), ", ".join(files))))
    return out


def _records_at(root: str, ref: str, directory: str, base: str, where: str) -> list:
    """``(file, row)`` for every record file directly in ``directory`` at ``ref``; an unreadable one is a
    GateError naming ``<base>:<file>``."""
    out = []
    for name in sorted(gitinfo.ls_tree(root, ref, directory)):
        if not _is_record_name(posixpath.basename(name)):
            continue
        shown = "%s:%s%s" % (base, name, where)
        try:
            text = gitinfo.show(root, ref, name)
            if text is None:
                raise GateError("%s: missing" % shown)
            data = _parse(text)
        except GateError as e:
            raise GateError("%s: %s" % (shown, e)) from None
        except yamlsub.YamlError as e:
            raise GateError("%s: %s (line %d)" % (shown, e.reason, e.line)) from None
        if type(data) is not dict:
            raise GateError("%s: the top level must be a mapping" % shown)
        out.append((name, data))
    return out


def base_errors(root: str, store: Store, base: str, is_resolved: Callable[[dict], bool],
                may_delete: Callable[[dict], bool]) -> list:
    """``(suffix, reason)`` pairs from comparing the working tree with the base branch ``base``:
    ``deleted.<id>`` and ``immutable.<id>`` against the merge base with HEAD, ``collision.<id>`` against the
    tip of ``base``. Records are compared as parsed values, not as bytes."""
    if type(base) is not str:
        raise GateError("the base ref must be a string")
    mb = gitinfo.merge_base(root, base, "HEAD")
    now = store.load()
    now_by_file = {rec.file: rec for rec in now}
    at_mb = _records_at(root, mb, store.directory, base, " (at the merge base)")
    out = []
    mb_ids = set()
    for file, row in at_mb:
        rid = row.get("id")
        if type(rid) is str:
            mb_ids.add(rid)
        else:
            rid = posixpath.basename(file)[:-len(".yml")]
        cur = now_by_file.get(file)
        if cur is None:
            if not may_delete(row):
                out.append(("deleted." + rid, "%s exists on %s; records on the base branch are never deleted"
                            % (file, base)))
        elif is_resolved(row) and not _same(row, cur.row):
            if store.kind == "decision":
                remedy = "record the change as a new decision with supersedes: " + rid
            else:
                remedy = "record the change as a new finding"
            out.append(("immutable." + rid, "resolved records are immutable; " + remedy))
    tip: dict = {}
    for _, row in _records_at(root, base, store.directory, base, ""):
        if type(row.get("id")) is str:
            tip.setdefault(row["id"], []).append(row)
    seen = set()
    for rec in now:
        if type(rec.id) is str and rec.id not in mb_ids and rec.id not in seen and rec.id in tip:
            if any(not _same(rec.row, other) for other in tip[rec.id]):
                seen.add(rec.id)
                out.append(("collision." + rec.id, "id %s already exists on %s; mint a new id" % (rec.id, base)))
    return out
