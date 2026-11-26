"""``context.yml``: the lookup behind ``python3 -m gates context <kind>`` (spec 9, Appendix A; plan Task 5a.1; task
domain table 5a.1 with its binding controller decisions).

Standard library only. Regular expressions are printable ASCII and matched with ``fullmatch``; nothing here uses
``str.lower``, ``isdigit``, ``isprintable`` or ``splitlines`` (the verdicts must not depend on the interpreter's
Unicode tables): a path character is judged by ``print_table.is_printable``, a line is a run of bytes ended by
``\\n``. Every git call goes through ``gitinfo``.
"""
from __future__ import annotations

import os
import posixpath
import re
import stat
from typing import List, Optional

from gates.lib import config, dispatch, gitinfo, print_table, programs, schema, yamlsub
from gates.lib.result import GateError, safe_text

KINDS = ("plan", "program", "program-controller", "stream-block", "sync")
PLACEHOLDERS = ("plan", "program", "stream", "brief", "integration")
HANDOFFS = {"plan": "{paths.plan_state}/{plan}/handoff.md", "stream-block": "{paths.plan_state}/{plan}/handoff.md"}

_STREAM_KIND = re.compile("stream-(" + programs.NAME_RE + ")-block")
_NAME = re.compile(programs.NAME_RE)
_LINES = re.compile("([0-9]{1,%d})-([0-9]{1,%d}|end)" % (dispatch.MAX_DIGITS, dispatch.MAX_DIGITS))
_ENTRY_KEYS = ("path", "lines", "why")
_MAX_PATH = 4096
_MAX_BRIEF = 4096


# ---------------------------------------------------------------- kinds

def kind_of(name: str) -> tuple:
    """``("stream-block", "<id>")`` for ``stream-<id>-block`` (``<id>`` matching ``NAME_RE``), ``(name, None)`` for a
    member of ``KINDS``; a ``ValueError`` naming ``KINDS`` otherwise (exact compare; a ``str`` subclass is refused)."""
    if type(name) is str:
        if name in KINDS:
            return (name, None)
        m = _STREAM_KIND.fullmatch(name)
        if m is not None:
            return ("stream-block", m.group(1))
    raise ValueError("unknown kind %s; the kinds are %s, or stream-<id>-block"
                     % (safe_text(name) if type(name) is str else type(name).__name__, ", ".join(KINDS)))


# ---------------------------------------------------------------- placeholders

def _paths_keys(cfg: object) -> tuple:
    paths = cfg.get("paths") if type(cfg) is dict else None
    return tuple(k for k in paths if type(k) is str) if type(paths) is dict else ()


def _tokens(path: str) -> list:
    """``path`` as a list of ``("text", s)`` and ``("ph", name)``; a ``ValueError`` for an unmatched brace."""
    out: list = []
    i, n, buf = 0, len(path), []
    while i < n:
        c = path[i]
        if c == "{":
            j = path.find("}", i + 1)
            if j < 0 or "{" in path[i + 1:j]:
                raise ValueError("unmatched brace")
            if buf:
                out.append(("text", "".join(buf)))
                buf = []
            out.append(("ph", path[i + 1:j]))
            i = j + 1
        elif c == "}":
            raise ValueError("unmatched brace")
        else:
            buf.append(c)
            i += 1
    if buf:
        out.append(("text", "".join(buf)))
    return out


def _known(name: str, keys: tuple) -> bool:
    return name in PLACEHOLDERS or (name.startswith("paths.") and name[6:] in keys)


def _path_problem(path: str, cfg: object) -> str:
    """The first reason ``path`` is not a valid entry path, or ``""``."""
    if len(path) > _MAX_PATH:
        return "path is longer than %d characters" % _MAX_PATH
    if not print_table.is_printable(path):
        return "path holds a character that is not printable"
    try:
        toks = _tokens(path)
    except ValueError:
        return "path '%s' has an unmatched brace" % safe_text(path)
    keys = _paths_keys(cfg)
    for kind, v in toks:
        if kind == "ph" and not _known(v, keys):
            return "unknown placeholder {%s} in '%s'" % (safe_text(v), safe_text(path))
    names = [v for kind, v in toks if kind == "ph"]
    if "brief" in names and path != "{brief}":
        return "{brief} may stand only alone in '%s'" % safe_text(path)
    if "integration" in names:
        if names.count("integration") > 1 or toks[0] != ("ph", "integration"):
            return "{integration} may stand only first in '%s'" % safe_text(path)
        if len(toks) == 1:
            return "{integration} alone names a directory, not a file"
    flat = "".join("x" if kind == "ph" else v for kind, v in toks)
    if flat == "" or flat == ".":
        return "path '%s' is empty" % safe_text(path)
    if flat.startswith("/"):
        return "path '%s' must be relative (no leading '/')" % safe_text(path)
    if ".." in flat.split("/"):
        return "path '%s' must not hold '..'" % safe_text(path)
    if posixpath.normpath(flat) != flat:
        return "path '%s' is not a normalised path" % safe_text(path)
    return ""


# ---------------------------------------------------------------- lines

def parse_lines(lines: str) -> tuple:
    """``(a, b)`` of a ``lines`` value, ``b`` ``None`` for ``<a>-end``; a ``ValueError`` naming the reason when it is
    outside the grammar (``<a>-<b>``, ``1 <= a <= b``, decimal without a leading zero, at most 600 digits, or
    ``<a>-end``)."""
    m = _LINES.fullmatch(lines) if type(lines) is str else None
    if m is None:
        raise ValueError("lines '%s' must be <a>-<b> or <a>-end (decimal, at most %d digits)"
                         % (safe_text(lines), dispatch.MAX_DIGITS))
    sa, sb = m.group(1), m.group(2)
    if sa[0] == "0" or (sb != "end" and sb[0] == "0"):
        raise ValueError("lines '%s': a number must be at least 1 and have no leading zero" % lines)
    a = int(sa)
    if sb == "end":
        return (a, None)
    b = int(sb)
    if b < a:
        raise ValueError("lines '%s': b must not be less than a" % lines)
    return (a, b)


# ---------------------------------------------------------------- the row

def _entry_errors(where: str, e: object, cfg: object) -> list:
    if type(e) is not dict:
        shown = " (got '%s')" % safe_text(e) if type(e) is str else ""
        return ["%s: an entry is a map {path, lines, why}%s" % (where, shown)]
    errs: list = []
    for k in e:
        if k not in _ENTRY_KEYS:
            errs.append("%s.%s: unknown key" % (where, safe_text(k)))
    if "path" not in e:
        errs.append("%s.path: required key is missing" % where)
    elif type(e["path"]) is not str or e["path"] == "":
        errs.append("%s.path: must be a non-empty string" % where)
    else:
        why = _path_problem(e["path"], cfg)
        if why:
            errs.append("%s.path: %s" % (where, why))
    if "why" not in e:
        errs.append("%s.why: required key is missing" % where)
    elif type(e["why"]) is not str or e["why"] == "":
        errs.append("%s.why: must be a non-empty string" % where)
    elif not print_table.is_printable(e["why"]) or e["why"].replace(" ", "") == "":
        errs.append("%s.why: must be one line of printable text" % where)
    if "lines" in e:
        if type(e["lines"]) is not str or e["lines"] == "":
            errs.append("%s.lines: must be a non-empty string" % where)
        else:
            try:
                parse_lines(e["lines"])
            except ValueError as x:
                errs.append("%s.lines: %s" % (where, x))
    return errs


def _list_errors(where: str, entries: list, cfg: object) -> list:
    errs: list = []
    seen: set = set()
    for i, e in enumerate(entries):
        w = "%s.%d" % (where, i)
        errs += _entry_errors(w, e, cfg)
        if type(e) is dict and type(e.get("path")) is str and e["path"] != "" \
                and (e.get("lines") is None or type(e.get("lines")) is str):
            key = (e["path"], e.get("lines"))
            if key in seen:
                errs.append("%s: '%s' listed twice%s" % (w, safe_text(e["path"]),
                            "" if key[1] is None else " with lines %s" % safe_text(key[1])))
            seen.add(key)
    return errs


def context_errors(row: dict, cfg: dict) -> list:
    """Every problem of a ``context/1`` row that the schema does not name, plus the entry rules for ``roles`` and the
    placeholder, path, ``lines`` and duplicate rules for every list. Pure; never raises on a ``dict`` row."""
    if type(row) is not dict:
        return ["context: must be a mapping"]
    errs: list = []
    if type(row.get("every")) is list:
        errs += _list_errors("every", row["every"], cfg)
    if type(row.get("kinds")) is dict:
        for k, v in row["kinds"].items():
            if k in KINDS and type(v) is list:
                errs += _list_errors("kinds.%s" % k, v, cfg)
    roles = row.get("roles")
    if type(roles) is dict:
        for k, v in roles.items():
            shown = safe_text(k) if type(k) is str else type(k).__name__
            if type(k) is not str or k not in dispatch.ROLES:
                errs.append("roles.%s: not a role (the roles are %s)" % (shown, ", ".join(dispatch.ROLES)))
            if type(v) is not list:
                errs.append("roles.%s: must be a list of entries" % shown)
            else:
                errs += _list_errors("roles.%s" % shown, v, cfg)
    return errs


def _need_root(root: object) -> None:
    gitinfo._need_root(root)


def load(root: str, cfg: dict) -> dict:
    """The ``context/1`` row at ``<paths.context>``; a ``GateError`` for a missing file (naming
    ``/strict-delivery:init``) and one listing every problem otherwise."""
    _need_root(root)
    gitinfo._require_toplevel(root)
    rel = cfg["paths"]["context"]
    path = os.path.join(root, rel)
    if not os.path.lexists(path):
        raise GateError("%s: missing; run /strict-delivery:init" % rel)
    try:
        raw = yamlsub._read_regular_file(path, rel)
    except yamlsub.YamlError as e:
        raise GateError("%s: %s" % (rel, "%s (line %d)" % (e.reason, e.line) if e.line else e.reason)) from None
    # the pre-request load only formatted rel with %s, so a str subclass was shown by its __str__; load_text takes exactly
    # str, and the join makes the text exact on 3.9 too (there "%s" % (x,) hands a str-subclass __str__ result back as is)
    return load_text(raw, "".join(("%s" % (rel,),)), cfg)


def load_text(text: bytes, rel: str, cfg: dict) -> dict:
    """Validate the already-read bytes ``text`` of the context file named ``rel`` exactly as ``load`` validates the
    bytes it reads (one leading BOM stripped, CRLF normalised, UTF-8, ``yamlsub.parse``, the ``context/1`` schema,
    ``context_errors``); the row, or a ``GateError`` listing every problem. A YAML error keeps today's doubled prefix
    ``<rel>: <rel>: <reason>``. ``text`` must be exactly ``bytes`` and ``rel`` exactly ``str`` (``TypeError``)."""
    if type(text) is not bytes:
        raise TypeError("text must be bytes, got %s" % type(text).__name__)
    if type(rel) is not str:
        raise TypeError("rel must be str, got %s" % type(rel).__name__)
    try:
        body = yamlsub._file_text(text)
    except UnicodeDecodeError:
        raise GateError("%s: %s: not valid UTF-8" % (rel, rel)) from None
    try:
        data = yamlsub.parse(body)
    except yamlsub.YamlError as e:
        reason = "%s: %s" % (rel, e.reason)
        raise GateError("%s: %s" % (rel, "%s (line %d)" % (reason, e.line) if e.line else reason)) from None
    try:
        sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "context.yml"))
    except schema.SchemaError as e:
        raise GateError(str(e)) from None
    errs = schema.validate(sch, data, cfg)
    if type(data) is dict:
        for e in context_errors(data, cfg):
            where = e.split(": an entry is a map")[0]
            if e not in errs and where + ": must be a mapping" not in errs:
                errs.append(e)
    if errs:
        raise GateError("%s: %s" % (rel, "; ".join(errs)))
    return data


# ---------------------------------------------------------------- the reads

def _need_str(x: object, what: str) -> None:
    if type(x) is not str:
        raise ValueError("%s must be a string" % what)


def _value(values: dict, name: str) -> Optional[str]:
    v = values.get(name)
    if v is None or v == "":
        return None
    _need_str(v, "value of %s" % name)
    return v


def _paths_of(cfg: Optional[dict]) -> dict:
    return config.DEFAULTS["paths"] if cfg is None else cfg["paths"]


def _substitute(path: str, values: dict, paths: dict) -> Optional[str]:
    out = []
    for kind, v in _tokens(path):
        if kind == "text":
            out.append(v)
        elif v.startswith("paths.") and v[6:] in paths:
            out.append(paths[v[6:]])
        elif v in PLACEHOLDERS and _value(values, v) is not None:
            out.append(values[v])
        else:
            return None
    return "".join(out)


def needs(path: str, values: dict) -> Optional[str]:
    """The first placeholder (text order) of ``path`` that has no value in ``values``, or ``None``."""
    for kind, v in _tokens(path):
        if kind == "ph" and v in PLACEHOLDERS and _value(values, v) is None:
            return v
    return None


def required(ctx: dict, kind: str, role: Optional[str], values: dict, extras: list = (),
             cfg: Optional[dict] = None) -> list:
    """``(entry, resolved)`` pairs: ``every``, ``kinds[kind]``, ``roles[role]``, then ``extras``, in file order, a later
    ``(path, lines)`` dropped. ``resolved`` is the substituted path, ``None`` when a placeholder has no value;
    ``paths.<key>`` comes from ``cfg`` (the defaults when ``cfg`` is ``None``). A value is substituted once, as given."""
    if type(ctx) is not dict or type(values) is not dict or type(extras) not in (list, tuple):
        raise ValueError("required: ctx and values must be dicts and extras a list")
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("unknown kind; the kinds are %s" % ", ".join(KINDS))
    if role is not None and type(role) is not str:
        raise ValueError("role must be a string or None")
    kinds = ctx.get("kinds") if type(ctx.get("kinds")) is dict else {}
    roles = ctx.get("roles") if type(ctx.get("roles")) is dict else {}
    paths = _paths_of(cfg)
    out, seen = [], set()
    for entries in (ctx.get("every"), kinds.get(kind), roles.get(role) if role is not None else None, extras):
        if entries is None:
            continue
        if type(entries) not in (list, tuple):
            raise ValueError("an entry list must be a list")
        for e in entries:
            if type(e) is not dict or type(e.get("path")) is not str:
                raise ValueError("an entry must be a map with a path")
            key = (e["path"], e.get("lines"))
            if key in seen:
                continue
            seen.add(key)
            out.append((e, _substitute(e["path"], values, paths)))
    return out


def handoff_reads(path: str, cfg: dict) -> list:
    """The ``required_reads`` of the ``handoff/1`` front matter at ``path`` (``[]`` when absent); a missing or
    non-regular file, a failing front matter or an item breaking the entry rules is a ``GateError`` naming it."""
    _need_str(path, "path")
    try:
        st = os.lstat(path)
    except OSError:
        raise GateError("%s: missing" % path) from None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("%s: not a regular file" % path)
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise GateError("%s: cannot read (%s)" % (path, type(e).__name__)) from None
    try:
        sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "handoff.yml"))
    except schema.SchemaError as e:
        raise GateError(str(e)) from None
    errs = schema.validate_front_matter(sch, text, cfg)
    if errs:
        raise GateError("%s: %s" % (path, "; ".join(errs[:5])))
    lines = text.split("\n")
    value = yamlsub.parse("\n".join(lines[1:lines.index("---", 1)]))
    reads = value.get("required_reads", [])
    errs = _list_errors("required_reads", reads, cfg)
    if errs:
        raise GateError("%s: %s" % (path, "; ".join(errs[:5])))
    return reads


def split(path: str, lines: Optional[str], cfg: dict) -> list:
    """``(a, b)`` chunks of ``lines`` (``None`` is ``1-end``) of the file at ``path``: consecutive, each at most
    ``cfg["context"]["max_lines"]`` lines and ``max_bytes`` bytes (a line over ``max_bytes`` is its own chunk). Lines
    are separated by ``\\n`` in the raw bytes; the last line counts without a final newline. A range past the end
    (an empty file included) or outside the grammar is a ``GateError`` naming the entry."""
    _need_str(path, "path")
    if lines is not None:
        _need_str(lines, "lines")
    lim = cfg.get("context") if type(cfg) is dict else None
    if type(lim) is not dict:
        raise ValueError("cfg must hold context limits")
    for k in ("max_lines", "max_bytes"):
        if type(lim.get(k)) is not int or lim[k] < 1:
            raise ValueError("context.%s must be an integer of at least 1" % k)
    entry = "%s lines %s" % (safe_text(path), "1-end" if lines is None else safe_text(lines))
    try:
        a, b = parse_lines("1-end" if lines is None else lines)
    except ValueError as e:
        raise GateError("%s: %s" % (entry, e)) from None
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        raise GateError("%s: missing" % safe_text(path)) from None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("%s: not a regular file" % safe_text(path))
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (safe_text(path), e.strerror or type(e).__name__)) from None
    sizes = [len(p) + 1 for p in data.split(b"\n")]
    if data.endswith(b"\n") or data == b"":
        sizes.pop()  # the empty piece after the last newline is not a line; an empty file has none
    else:
        sizes[-1] -= 1  # a last line without a newline has no terminator byte
    n = len(sizes)
    if b is None:
        b = n
    if a > n or b > n:
        raise GateError("%s: past the end (the file has %d lines)" % (entry, n))
    out, start, count, size = [], a, 0, 0
    for i in range(a, b + 1):
        s = sizes[i - 1]
        if count and (count + 1 > lim["max_lines"] or size + s > lim["max_bytes"]):
            out.append((start, i - 1))
            start, count, size = i, 0, 0
        count += 1
        size += s
    out.append((start, b))
    return out


# ---------------------------------------------------------------- values

def _name_value(what: str, v: object) -> Optional[str]:
    if v is None or v == "":
        return None
    if type(v) is not str or _NAME.fullmatch(v) is None:
        raise ValueError("--%s: must match %s" % (what, programs.NAME_RE))
    return v


def values_for(root: str, cfg: dict, kind: str, plan: Optional[str] = None, program: Optional[str] = None,
               stream: Optional[str] = None, brief: Optional[str] = None) -> dict:
    """The placeholder values: the given ones (``None`` and ``""`` are no value), ``stream`` from a
    ``stream-<id>-block`` kind, and with ``program`` also ``integration``, the integration worktree the main
    worktree's ``streams.yml`` row names."""
    _need_root(root)
    _, sid = kind_of(kind)
    vals: dict = {}
    p = _name_value("plan", plan)
    if p:
        vals["plan"] = p
    st = _name_value("stream", stream)
    if sid is not None:
        if st is not None and st != sid:
            raise ValueError("--stream %s disagrees with the kind stream-%s-block" % (st, sid))
        st = sid
    if st:
        vals["stream"] = st
    if brief is not None and brief != "":
        if type(brief) is not str or len(brief) > _MAX_BRIEF or not print_table.is_printable(brief):
            raise ValueError("--brief: must be one line of printable text of at most %d characters" % _MAX_BRIEF)
        vals["brief"] = brief
    if program is not None and program != "":
        why = programs.program_problem(program)
        if why:
            raise ValueError("--program: %s" % why)
        vals["program"] = program
        prog = programs.load_program(root, cfg, program, "refs/heads/%s/integration" % program)
        vals["integration"] = posixpath.join(programs.worktrees_dir(root, prog.streams), program, "integration")
    return vals


def absolute(root: str, resolved: str) -> str:
    """``realpath`` of ``resolved`` joined to the repository top level (an absolute path stands as given)."""
    _need_root(root)
    _need_str(resolved, "resolved")
    if "\0" in resolved:
        raise GateError("path holds a NUL character")
    return os.path.realpath(os.path.join(gitinfo.toplevel(root), resolved))


def resolve(path: str, values: dict, cfg: Optional[dict] = None) -> Optional[str]:
    """``path`` with its placeholders replaced (``paths.<key>`` from ``cfg``, the defaults when ``None``), or ``None``
    when one has no value in ``values``."""
    _need_str(path, "path")
    if type(values) is not dict:
        raise ValueError("values must be a dict")
    return _substitute(path, values, _paths_of(cfg))


# ---------------------------------------------------------------- enforcement

_PROFILES = ("light", "standard", "strict")


def enforced(cfg: dict) -> bool:
    """True when ``cfg["profile"]`` is ``strict`` (spec 12: context read receipts are enforced on strict only). A cfg
    that is not a dict, or whose ``profile`` is not an exact ``str`` among light, standard, strict (one
    ``config.load`` would have refused), is a ``ValueError``: it fails closed (decision D-Q1 (b))."""
    if type(cfg) is not dict or type(cfg.get("profile")) is not str or cfg["profile"] not in _PROFILES:
        raise ValueError("cfg: profile must be one of %s" % ", ".join(_PROFILES))
    return cfg["profile"] == "strict"
