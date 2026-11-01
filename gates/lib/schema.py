"""Schema checker (spec Appendix A): schema files, ``validate``, ``validate_markdown``, producer kinds, file lists.

Standard library only. Reasons are returned unescaped: ``Result.render`` escapes them once.
"""
from __future__ import annotations

import fnmatch
import importlib
import os
import re
import stat
from typing import List, Optional

from gates.lib import config, gitinfo, ids, yamlsub
from gates.lib.result import GateError

KNOWN_KINDS = ("config", "decision", "finding", "claim", "request", "streams", "context", "handoff", "ledger",
               "status", "sync-log", "overview", "in-force", "decision-index", "finding-index",
               "mutation-transcript", "review-report", "receipt", "claude-block", "gitignore-block")
GENERATED_KINDS = ("decision-index", "finding-index", "in-force", "overview")  # OQ-17: skipped when absent
TYPES = ("str", "text", "int", "bool", "enum", "list", "map", "any-map", "id", "sha", "glob", "cite", "sha-path")
ID_KINDS = ("decision", "finding", "claim", "request")
FORMATS = ("yaml", "markdown")
SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

_SPEC_KEYS = ("type", "required", "nullable", "values", "items", "fields", "id_kind", "min", "required_when",
              "absent_when")
_USES = {"enum": ("values",), "list": ("items", "min"), "int": ("min",), "map": ("fields",), "id": ("id_kind",)}
_NEEDS = {"enum": "values", "list": "items", "map": "fields", "id": "id_kind"}
_TAG = re.compile(r"([a-z][a-z-]*)/([1-9][0-9]*)")
_SHA = re.compile(r"[0-9a-f]{7,40}")


class SchemaError(Exception):
    """A malformed schema file (or a schema that names an unknown paths key); names the file and the key."""


class LayoutError(GateError):
    """A ``files`` directory that cannot be listed safely; ``rel`` is the repo-relative path at fault."""

    def __init__(self, rel: str, reason: str) -> None:
        super().__init__(reason)
        self.rel = rel


class Schema:
    def __init__(self, path: str, data: dict) -> None:
        self.path = path
        self.kind = data["kind"]
        self.version = data["version"]
        self.format = data["format"]
        self.files = data["files"]
        self.fields = data.get("fields")
        self.first_line = data.get("first_line")
        self.table = data.get("table")
        self.headings = data.get("headings")


# ---------------------------------------------------------------- schema files

def _err(path: str, key: str, problem: str) -> SchemaError:
    return SchemaError("%s: %s: %s" % (path, key, problem))


def _scalar_list(v: object) -> bool:
    return type(v) is list and all(type(x) in (str, int, bool) for x in v)


def _check_spec(path: str, where: str, spec: object, siblings: set) -> None:
    if type(spec) is not dict:
        raise _err(path, where, "a field spec must be a mapping")
    for k in spec:
        if k not in _SPEC_KEYS:
            raise _err(path, "%s.%s" % (where, k), "unknown field-spec key")
    t = spec.get("type")
    if type(t) is not str or t not in TYPES:
        raise _err(path, where + ".type", "must be one of " + ", ".join(TYPES))
    for k in ("required", "nullable"):
        if k in spec and type(spec[k]) is not bool:
            raise _err(path, "%s.%s" % (where, k), "must be true or false")
    for k in ("values", "items", "min", "fields", "id_kind"):
        if k in spec and k not in _USES.get(t, ()):
            raise _err(path, "%s.%s" % (where, k), "not used by type %s" % t)
    if t in _NEEDS and _NEEDS[t] not in spec:
        raise _err(path, "%s.%s" % (where, _NEEDS[t]), "required by type %s" % t)
    if "values" in spec:
        vals = spec["values"]
        if type(vals) is not list or not vals or not all(type(x) in (str, int, bool) for x in vals) \
                or len({type(x) for x in vals}) != 1:
            raise _err(path, where + ".values", "must be a non-empty list of strings, or of integers, or of booleans")
    if "min" in spec and (type(spec["min"]) is not int or spec["min"] < 0):
        raise _err(path, where + ".min", "must be an integer of at least 0")
    if "id_kind" in spec and spec["id_kind"] not in ID_KINDS:
        raise _err(path, where + ".id_kind", "must be one of " + ", ".join(ID_KINDS))
    if "items" in spec:
        _check_spec(path, where + ".items", spec["items"], set())
    if "fields" in spec:
        _check_fields(path, where + ".fields", spec["fields"])
    for k in ("required_when", "absent_when"):
        if k not in spec:
            continue
        conds = spec[k]
        if type(conds) is not list:
            raise _err(path, "%s.%s" % (where, k), "must be a list of conditions")
        for c in conds:
            if type(c) is not dict:
                raise _err(path, "%s.%s" % (where, k), "each condition must be a mapping")
            for sib, vals in c.items():
                if type(sib) is not str or sib not in siblings:
                    raise _err(path, "%s.%s" % (where, k), "condition names '%s', which this map does not declare" % sib)
                if not _scalar_list(vals):
                    raise _err(path, "%s.%s.%s" % (where, k, sib), "must be a list of values")
    if "absent_when" in spec and "required_when" not in spec and spec.get("required", True) is True:
        raise _err(path, where, "absent_when on a required field can never be satisfied; "
                   "write required: false or a required_when")


def _check_fields(path: str, where: str, fields: object) -> None:
    if type(fields) is not dict:
        raise _err(path, where, "must be a mapping of field names to specs")
    for name, spec in fields.items():
        if type(name) is not str or name == "":
            raise _err(path, where, "field names must be non-empty strings")
        _check_spec(path, "%s.%s" % (where, name), spec, set(fields))


def _check_files(path: str, files: object) -> None:
    if type(files) is not list or not files:
        raise _err(path, "files", "must be a non-empty list")
    for i, item in enumerate(files):
        where = "files.%d" % i
        if type(item) is not dict:
            raise _err(path, where, "must be a mapping")
        for k in item:
            if k not in ("path", "dir", "glob", "exclude"):
                raise _err(path, "%s.%s" % (where, k), "unknown key")
        if "path" in item:
            if set(item) != {"path"} or type(item["path"]) is not str or item["path"] == "":
                raise _err(path, where, "a path item is exactly {path: <paths key>}")
        else:
            for k in ("dir", "glob"):
                if type(item.get(k)) is not str or item[k] == "":
                    raise _err(path, "%s.%s" % (where, k), "a dir item needs a non-empty string dir and glob")
            ex = item.get("exclude", [])
            if type(ex) is not list or not all(type(x) is str for x in ex):
                raise _err(path, where + ".exclude", "must be a list of strings")


def _check_markdown(path: str, data: dict) -> None:
    fl = data["first_line"]
    if type(fl) is not str or fl == "":
        raise _err(path, "first_line", "must be a non-empty string")
    if "table" in data and "headings" in data:
        raise _err(path, "headings", "table and headings cannot both be given")
    for key in ("table", "headings"):
        if key in data:
            v = data[key]
            if type(v) is not list or not v or not all(type(x) is str and x != "" for x in v):
                raise _err(path, key, "must be a non-empty list of non-empty strings")
    for h in data.get("headings", []):
        if not h.startswith("## "):
            raise _err(path, "headings", "each heading is a full line starting '## '")


def load_schema(path: str) -> Schema:
    try:
        data = yamlsub.load(path, path)
    except yamlsub.YamlError as e:
        raise SchemaError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None
    if type(data) is not dict:
        raise _err(path, "top level", "must be a mapping")
    stem = os.path.basename(path)
    if stem.endswith(".yml"):
        stem = stem[:-4]
    if type(data.get("kind")) is not str or data["kind"] != stem:
        raise _err(path, "kind", "must equal the file stem '%s'" % stem)
    if type(data.get("version")) is not int or data["version"] < 1:
        raise _err(path, "version", "must be a positive integer")
    fmt = data.get("format")
    if type(fmt) is not str or fmt not in FORMATS:
        raise _err(path, "format", "must be yaml or markdown")
    body = ("fields",) if fmt == "yaml" else ("first_line", "table", "headings")
    for k in data:
        if k not in ("kind", "version", "format", "files") + body:
            raise _err(path, str(k), "unknown key for a %s schema" % fmt)
    for k in ("files", body[0]):
        if k not in data:
            raise _err(path, k, "required key is missing")
    _check_files(path, data["files"])
    if fmt == "yaml":
        _check_fields(path, "fields", data["fields"])
        s = data["fields"].get("schema")
        if s is None or s["type"] != "str" or s.get("required", True) is not True or s.get("nullable", False) \
                or "required_when" in s or "absent_when" in s:
            raise _err(path, "fields.schema", "must be declared as a required, non-nullable str")
    else:
        _check_markdown(path, data)
    return Schema(path, data)


def scan_dir(dirpath: Optional[str] = None) -> tuple:
    """``(loaded, problems)``: ``loaded`` maps kind to Schema; ``problems`` is a list of ``(entry name, reason)``
    for every entry that is not a loadable schema file of a known kind. A missing directory is empty."""
    d = SCHEMAS_DIR if dirpath is None else dirpath
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return {}, []
    except OSError as e:
        raise SchemaError("%s: cannot read the schemas directory (%s)" % (d, e.strerror or type(e).__name__)) from None
    loaded: dict = {}
    problems: list = []
    for name in names:
        full = os.path.join(d, name)
        try:
            mode = os.lstat(full).st_mode
        except OSError as e:
            problems.append((name, "%s: cannot read (%s)" % (name, e.strerror or type(e).__name__)))
            continue
        if not name.endswith(".yml") or not stat.S_ISREG(mode):
            problems.append((name, "%s: not a regular *.yml schema file" % name))
        elif name[:-4] not in KNOWN_KINDS:
            problems.append((name[:-4], "%s: kind '%s' is not in KNOWN_KINDS" % (name, name[:-4])))
        else:
            try:
                loaded[name[:-4]] = load_schema(full)
            except SchemaError as e:
                problems.append((name[:-4], str(e)))
    return loaded, problems


def schemas(dirpath: Optional[str] = None) -> dict:
    """kind -> Schema for every file in the schemas directory; the first problem raises SchemaError."""
    loaded, problems = scan_dir(dirpath)
    if problems:
        raise SchemaError(problems[0][1])
    return loaded


# ---------------------------------------------------------------- validation

def _path_ok(s: str) -> bool:
    """config.load's path rule: normalised, repo-relative, printable, non-empty."""
    return (s.isprintable() and not s.startswith("/") and ".." not in s.split("/") and s != "."
            and os.path.normpath(s).replace(os.sep, "/") == s)


def _in(v: object, values: list) -> bool:
    return any(type(x) is type(v) and x == v for x in values)


def _text(x: object) -> str:
    return x if type(x) is str else str(x)


def _check_value(spec: dict, v: object, path: str, cfg: dict, errs: list) -> None:
    if v is None:
        if not spec.get("nullable", False):
            errs.append("%s: must not be null" % path)
        return
    t = spec["type"]
    if t == "str":
        if type(v) is not str or v == "":
            errs.append("%s: must be a non-empty string" % path)
    elif t == "text":
        if type(v) is not str:
            errs.append("%s: must be a string" % path)
    elif t == "int":
        if type(v) is not int:
            errs.append("%s: must be an integer" % path)
        elif v < spec.get("min", v):
            errs.append("%s: must be at least %d" % (path, spec["min"]))
    elif t == "bool":
        if type(v) is not bool:
            errs.append("%s: must be true or false" % path)
    elif t == "enum":
        if not _in(v, spec["values"]):
            errs.append("%s: must be one of %s" % (path, ", ".join(str(x) for x in spec["values"])))
    elif t == "list":
        if type(v) is not list:
            errs.append("%s: must be a list" % path)
            return
        if len(v) < spec.get("min", 0):
            errs.append("%s: must hold at least %d items" % (path, spec["min"]))
        for i, item in enumerate(v):
            _check_value(spec["items"], item, "%s.%d" % (path, i), cfg, errs)
    elif t == "map":
        if type(v) is not dict:
            errs.append("%s: must be a mapping" % path)
        else:
            _check_map(spec["fields"], v, path + ".", cfg, errs)
    elif t == "any-map":
        if type(v) is not dict:
            errs.append("%s: must be a mapping" % path)
    elif t == "id":
        problem = ids.id_problem(v, cfg["ids"][spec["id_kind"]])
        if problem:
            errs.append("%s: %s" % (path, problem))
    elif t == "sha":
        if type(v) is not str or not _SHA.fullmatch(v):
            errs.append("%s: must be 7 to 40 lowercase hex digits" % path)
    elif t == "glob":
        if type(v) is not str or v == "":
            errs.append("%s: must be a non-empty glob" % path)
    elif t == "cite":
        p, sep, anchor = v.partition("#") if type(v) is str else ("", "", "")
        if not _path_ok(p) or (sep and (anchor == "" or "#" in anchor or not anchor.isprintable())):
            errs.append("%s: must be a normalised repo-relative path with an optional non-empty #anchor" % path)
    elif t == "sha-path":
        sha, _, p = v.partition(":") if type(v) is str else ("", "", "")
        if not _SHA.fullmatch(sha) or "#" in p or not _path_ok(p):
            errs.append("%s: must be <sha>:<normalised repo-relative path>" % path)


def _matches(conds: list, d: dict) -> bool:
    return any(all(k in d and _in(d[k], vals) for k, vals in c.items()) for c in conds)


def _check_map(fields: dict, d: dict, prefix: str, cfg: dict, errs: list) -> None:
    for name, spec in fields.items():
        path = prefix + name
        present = name in d
        if "absent_when" in spec and present and _matches(spec["absent_when"], d):
            errs.append("%s: must be absent (absent_when matches)" % path)
            continue
        if not present:
            if "required_when" in spec:
                if _matches(spec["required_when"], d):
                    errs.append("%s: required key is missing (required_when matches)" % path)
            elif spec.get("required", True):
                errs.append("%s: required key is missing" % path)
            continue
        _check_value(spec, d[name], path, cfg, errs)
    for k in d:
        if k not in fields:
            errs.append("%s%s: unknown key" % (prefix, k))


def validate(schema: Schema, value: object, cfg: dict) -> list:
    """Errors of ``value`` against the yaml ``schema``, each ``"<dotted.path>: <problem>"``; ``[]`` when valid."""
    if type(value) is not dict:
        return ["top level: must be a mapping"]
    expected = "%s/%d" % (schema.kind, schema.version)
    if "schema" not in value:
        return ["schema: expected %s, got (missing)" % expected]
    got = value["schema"]
    if type(got) is not str or got != expected:
        m = _TAG.fullmatch(got) if type(got) is str else None
        hint = "; run /strict-delivery:upgrade" if m and m.group(1) == schema.kind else ""
        return ["schema: expected %s, got %s%s" % (expected, _text(got), hint)]
    errs: list = []
    _check_map(schema.fields, value, "", cfg, errs)
    return errs


def validate_markdown(schema: Schema, text: str) -> list:
    if type(text) is not str:
        return ["first line: text must be a string"]
    lines = text.split("\n")
    if lines[0] != schema.first_line:
        return ["first line: expected '%s'" % schema.first_line]
    errs: list = []
    if schema.table is not None:
        header = "| " + " | ".join(schema.table) + " |"
        sep = "|" + "|".join("---" for _ in schema.table) + "|"
        rows = [i for i, ln in enumerate(lines) if ln.startswith("|")]
        if not rows:
            errs.append("table: missing; expected a header '%s'" % header)
        elif lines[rows[0]] != header:
            errs.append("table: header must be '%s', got '%s'" % (header, lines[rows[0]]))
        elif rows[0] + 1 >= len(lines) or lines[rows[0] + 1] != sep:
            errs.append("table: the line after the header must be '%s'" % sep)
    if schema.headings is not None:
        got = [ln for ln in lines if ln.startswith("## ")]
        if got != schema.headings:
            errs.append("headings: expected [%s], got [%s]" % (", ".join(schema.headings), ", ".join(got)))
    return errs


# ---------------------------------------------------------------- producers and files

def produced_kinds() -> set:
    """The union of ``PRODUCES`` over ``producers.PRODUCER_MODULES``; a module that cannot be used is a GateError."""
    from gates import producers
    out: set = set()
    for mod in producers.PRODUCER_MODULES:
        try:
            m = importlib.import_module(mod)
        except Exception as e:
            raise GateError("producer module %s cannot be imported (%s: %s)" % (mod, type(e).__name__, e)) from None
        produces = getattr(m, "PRODUCES", None)
        if type(produces) is not tuple or not all(type(k) is str for k in produces):
            raise GateError("producer module %s: PRODUCES must be a tuple of strings" % mod)
        out.update(produces)
    return out


def _paths_key(schema: Schema, key: str, cfg: dict) -> str:
    if key == "config":
        return config.CONFIG_PATH
    try:
        return cfg["paths"][key]
    except (KeyError, TypeError):
        raise SchemaError("%s: files: '%s' is not a key of paths" % (schema.path, key)) from None


def expected_paths(schema: Schema, cfg: dict) -> list:
    """The repo-relative paths named by the ``{path: ...}`` items, existing or not."""
    return [_paths_key(schema, item["path"], cfg) for item in schema.files if "path" in item]


def entries_of(schema: Schema, root: str, cfg: dict) -> list:
    """``(repo-relative path, from_glob)`` for every existing file the schema names, sorted per item. A glob match
    is any entry of the directory with a matching name, whatever its type: the caller refuses non-regular ones."""
    gitinfo._require_toplevel(root)
    out: list = []
    for item in schema.files:
        if "path" in item:
            rel = _paths_key(schema, item["path"], cfg)
            if os.path.lexists(os.path.join(root, *rel.split("/"))):
                out.append((rel, False))
            continue
        directory = _paths_key(schema, item["dir"], cfg)
        parts = directory.split("/")
        missing = False
        for i in range(1, len(parts) + 1):
            rel = "/".join(parts[:i])
            try:
                mode = os.lstat(os.path.join(root, *rel.split("/"))).st_mode
            except FileNotFoundError:
                missing = True
                break
            except OSError as e:
                raise LayoutError(rel, "cannot read (%s)" % (e.strerror or type(e).__name__)) from None
            if stat.S_ISLNK(mode):
                raise LayoutError(rel, "is a symlink; directories must be real directories")
            if not stat.S_ISDIR(mode):
                raise LayoutError(rel, "is not a directory")
        if missing:
            continue
        try:
            names = sorted(os.listdir(os.path.join(root, *parts)))
        except OSError as e:
            raise LayoutError(directory, "cannot read the directory (%s)" % (e.strerror or type(e).__name__)) from None
        exclude = item.get("exclude", [])
        for name in names:
            if fnmatch.fnmatchcase(name, item["glob"]) and name not in exclude:
                out.append((directory + "/" + name, True))
    return out


def files_of(schema: Schema, root: str, cfg: dict) -> List[str]:
    """Repo-relative paths that exist for the schema's ``files`` items."""
    return [rel for rel, _ in entries_of(schema, root, cfg)]
