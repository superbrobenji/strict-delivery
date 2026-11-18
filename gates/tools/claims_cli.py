"""Tool ``claims``: ``add`` and ``verify`` write claim records (spec 7.2, 7.3; plan Task 2c.1; owner Q-B2plan-2,
Q-B2plan-4, Q-B2plan-6 (a); task domain table 2c.1, binding controller decisions D-Q1..D-Q30).

Standard library only. ``python3 -m gates claims <sub>``. An argument error exits 2 with the usage on stderr; a
refusal exits 1 with one stderr line ``claims <sub>: <reason>`` and writes nothing. Every flag is read and checked
before the first git or file call. Free text is printable ASCII on one line (the decisions family's whitelist,
owner Q-B2FX2-1 (a)), so the record bytes are the same on every interpreter; no ``int()`` runs on argv text. The
tool never runs a claim's commands and starts no process but git (through ``gitinfo``).
"""
from __future__ import annotations

import copy
import os
import random
import stat
import sys
import tempfile
from typing import List, Optional

from gates.lib import claims, config, gitinfo, ids, migrations, yamlsub
from gates.lib.result import GateError, _GateParser, safe_text
from gates.lib.store import Store
from gates.tools import index

PRODUCES = ("claim",)

_rng = random.SystemRandom()  # the mint's generator; tests patch it to force a collision

_PLACEHOLDER_ID = "C-20260101-aaaa"  # stands in for the real id while the argv forms are checked before git runs
_PLACEHOLDER_BLOB = "0" * 40
_ADD_FLAGS = ("--document", "--text", "--cite", "--direct", "--contradiction", "--by", "--root")
_VERIFY_FLAGS = ("--by", "--root")


# ---------------------------------------------------------------- argv whitelists (decision D-Q5)

def _text(flag: str, value: str) -> str:
    """``value`` when it is non-empty printable ASCII (U+0020-U+007E) with no leading or trailing space; the refusal
    names the first offending code point, never the text."""
    if value == "":
        raise GateError("%s: must not be empty" % flag)
    for c in value:
        o = ord(c)
        if not 0x20 <= o <= 0x7E:
            raise GateError("%s: U+%04X is not allowed; the text must be printable ASCII (U+0020-U+007E)"
                            % (flag, o))
    if value[0] == " " or value[-1] == " ":
        raise GateError("%s: must not start or end with a space" % flag)
    return value


def _once(flag: str, values: Optional[list]) -> Optional[str]:
    """The one value of a single-valued flag: None when absent, a refusal when given more than once (D-Q3)."""
    if values is None:
        return None
    if len(values) > 1:
        raise GateError("%s given more than once" % flag)
    return values[0]


def _required(flag: str, values: Optional[list]) -> str:
    v = _once(flag, values)
    if v is None:
        raise GateError("%s is required" % flag)
    return _text(flag, v)


def _root_arg(values: Optional[list]) -> Optional[str]:
    """``--root``: absent, or one non-empty value (a root path may hold any character, so no whitelist)."""
    v = _once("--root", values)
    if v == "":
        raise GateError("--root: must not be empty")
    return v


def _cite(value: str) -> tuple:
    """``(path, lines or None)`` of a ``--cite PATH[:LINES]`` value (D-Q7); at most one ``:``."""
    _text("--cite", value)
    if value.count(":") > 1:
        raise GateError("--cite: at most one ':'")
    path, sep, lines = value.partition(":")
    if path == "":
        raise GateError("--cite: the path must not be empty")
    if sep and lines == "":
        raise GateError("--cite: the lines must not be empty")
    return path, (lines if sep else None)


# ---------------------------------------------------------------- shared steps

def _row_errors(row: dict, cfg: dict) -> None:
    errs = claims.validate(row, cfg)
    if errs:
        raise GateError("; ".join(errs))


def _load_all(root: str, cfg: dict) -> list:
    """Every claim file of the register, loaded and validated; any problem anywhere refuses (D-Q14, D-Q22)."""
    files = claims.load(root, cfg)
    errs = []
    for cf in files:
        errs += ["%s: %s" % (cf.file, e) for e in claims.validate(cf.row, cfg)]
    errs += ["%s: %s" % (s, r) for s, r in claims.file_errors(files, cfg["ids"]["claim"])]
    if errs:
        raise GateError("; ".join(errs))
    return files


def _not_regular(root: str, rel: str) -> bool:
    """True when ``rel`` exists in the work tree (``lstat``, no link followed) and is not a regular file."""
    try:
        return not stat.S_ISREG(os.lstat(os.path.join(root, *rel.split("/"))).st_mode)
    except OSError:
        return False


def _check_cited(root: str, paths: list, tracked: frozenset) -> None:
    """Every cited path is tracked, not flagged and has no unstaged change (D-Q8, D-Q17, D-Q23); each refusal names
    every offending path."""
    bad = [p for p in paths if p not in tracked]
    if bad:
        # ``tracked_files`` lists regular files only, so a tracked symlink is "not tracked" to it; a path that is
        # present but is no regular file is named as such (the ``gitinfo.blob_id`` wording), never as untracked
        odd = [p for p in bad if _not_regular(root, p)]
        reasons = ["%s: is not a regular file" % ", ".join(odd)] if odd else []
        rest = [p for p in bad if p not in odd]
        if rest:
            reasons.append("%s: is not tracked" % ", ".join(rest))
        raise GateError("; ".join(reasons))
    flagged = set(gitinfo.flagged_paths(root))
    bad = [p for p in paths if p in flagged]
    if bad:
        raise GateError("%s: is flagged assume-unchanged or skip-worktree; git cannot see its changes"
                        % ", ".join(bad))
    unstaged = set(gitinfo.unstaged_paths(root))
    bad = [p for p in paths if p in unstaged]
    if bad:
        raise GateError("%s: has unstaged changes; git add it so the recorded blob holds the verified text"
                        % ", ".join(bad))


def _canonical(root: str, cf: "claims.ClaimFile") -> None:
    """The file is exactly what ``yamlsub.emit`` writes for what it holds (D-Q13), so a rewrite loses nothing."""
    try:
        with open(os.path.join(root, *cf.file.split("/")), "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise GateError("%s: cannot read (%s)" % (cf.file, getattr(e, "strerror", None) or type(e).__name__)) \
            from None
    try:
        same = yamlsub.emit(cf.row) == text
    except yamlsub.EmitError:
        same = False
    if not same:
        raise GateError("%s: not in canonical form; rewrite it with the claims tool" % cf.file)


def _why(e: OSError) -> str:
    return e.strerror or type(e).__name__


def _write(root: str, directory: str, rel: str, row: dict, existing: bool) -> None:
    """Emit ``row`` and write it to ``rel``: an exclusive create for a new file, a temp file in the claims directory
    and ``os.replace`` for an existing one; a partial file or temp file is removed on every failure path (D-Q18).
    Check-then-write window accepted (owner Q-1a3rr-1, D-Q19)."""
    try:
        text = yamlsub.emit(row)
    except yamlsub.EmitError as e:
        raise GateError("%s: cannot emit the claim file (%s)" % (rel, e)) from None
    path = os.path.join(root, *rel.split("/"))
    if not existing:
        claims._dir_exists(root, directory)
        try:
            os.makedirs(os.path.join(root, *directory.split("/")), exist_ok=True)
        except OSError as e:
            raise GateError("%s: cannot create the claims directory (%s)" % (directory, _why(e))) from None
        try:
            fh = open(path, "x", encoding="utf-8", newline="")
        except FileExistsError:
            raise GateError("%s: already exists" % rel) from None
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
            if not done:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return
    try:
        st = os.lstat(path)
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (rel, _why(e))) from None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.join(root, *directory.split("/")), prefix=".claims.", suffix=".tmp")
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


# ---------------------------------------------------------------- add

def _add(ns) -> int:
    document = _required("--document", ns.document)
    text = _required("--text", ns.text)
    if ns.cite is None:
        raise GateError("--cite is required")
    cites = [_cite(v) for v in ns.cite]
    seen: list = []
    for v, c in zip(ns.cite, cites):
        if c in seen:
            raise GateError("--cite: %s given twice" % v)
        seen.append(c)
    direct = _required("--direct", ns.direct)
    contradiction = _required("--contradiction", ns.contradiction)
    by = _required("--by", ns.by)
    given_root = _root_arg(ns.root)
    # the argv forms are checked against the default config before git runs; the real config re-checks the row below
    sample = {"schema": "claim/%d" % migrations.current_version("claim"), "document": document,
              "claims": [{"id": _PLACEHOLDER_ID, "text": text,
                          "cites": [_cite_row(p, ln, _PLACEHOLDER_BLOB) for p, ln in cites],
                          "direct": direct, "contradiction": contradiction, "by": by}]}
    _row_errors(sample, config.DEFAULTS)
    root = index._root(given_root)
    cfg = config.load(root)
    directory = cfg["paths"]["claims"]
    prefix = cfg["ids"]["claim"]
    tracked = gitinfo.tracked_files(root)
    if document not in tracked:
        raise GateError("%s: is not a tracked file" % document)
    _plain(root, document)
    paths = list(dict.fromkeys(p for p, _ in cites))
    _check_cited(root, paths, tracked)
    files = _load_all(root, cfg)
    existing = {c["id"] for cf in files for c in claims._claims(cf.row) if type(c.get("id")) is str}
    for kind in ("decision", "finding"):
        existing.update(r.id for r in Store(root, kind, cfg).load())
    rid = ids.mint(prefix, existing, ids.utc_today(), _rng)
    blobs = gitinfo.blob_ids(root, paths)
    claim = {"id": rid, "text": text, "cites": [_cite_row(p, ln, blobs[p]) for p, ln in cites], "direct": direct,
             "contradiction": contradiction, "by": by}
    rel = "%s/%s.yml" % (directory, claims.slug(document))
    current = [cf for cf in files if cf.file == rel]
    if current:
        _canonical(root, current[0])
        row = copy.deepcopy(current[0].row)
        row["claims"].append(claim)
    else:
        row = {"schema": sample["schema"], "document": document, "claims": [claim]}
    _row_errors(row, cfg)
    errs = claims.file_errors([cf for cf in files if cf.file != rel] + [claims.ClaimFile(rel, row)], prefix)
    if errs:
        raise GateError("; ".join("%s: %s" % e for e in errs))
    _write(root, directory, rel, row, bool(current))
    sys.stdout.write(rid + "\n")
    return 0


def _cite_row(path: str, lines: Optional[str], blob: str) -> dict:
    row = {"path": path}
    if lines is not None:
        row["lines"] = lines
    row["blob"] = blob
    return row


def _plain(root: str, rel: str) -> None:
    """``rel`` is a regular file in the work tree, every ancestor a real directory (``lstat``, no link followed)."""
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        try:
            mode = os.lstat(os.path.join(root, *parts[:i])).st_mode
        except OSError:
            raise GateError("%s: does not exist" % rel) from None
        if not (stat.S_ISREG(mode) if i == len(parts) else stat.S_ISDIR(mode)):
            raise GateError("%s: is not a regular file" % rel)


# ---------------------------------------------------------------- verify

def _verify(ns) -> int:
    if not ns.id:
        raise GateError("ID is required")
    by = _required("--by", ns.by)
    given_root = _root_arg(ns.root)
    _text("ID", ns.id[0])
    root = index._root(given_root)
    cfg = config.load(root)
    rid = ns.id[0]
    problem = ids.id_problem(rid, cfg["ids"]["claim"])
    if problem:
        raise GateError("ID: %s" % problem)
    files = _load_all(root, cfg)
    hit = None
    for cf in files:
        for i, c in enumerate(claims._claims(cf.row)):
            if c.get("id") == rid:
                hit = (cf, i)
    if hit is None:
        raise GateError("%s: no such claim" % rid)
    cf, _ = hit
    row = copy.deepcopy(cf.row)
    claim = [c for c in row["claims"] if c.get("id") == rid][0]
    paths = list(dict.fromkeys(c["path"] for c in claim["cites"]))
    _check_cited(root, paths, gitinfo.tracked_files(root))
    blobs = gitinfo.blob_ids(root, paths)
    changed = claim["by"] != by
    for c in claim["cites"]:
        if c["blob"] != blobs[c["path"]]:
            c["blob"] = blobs[c["path"]]
            changed = True
    claim["by"] = by
    if changed:
        _row_errors(row, cfg)
        _canonical(root, cf)
        _write(root, cfg["paths"]["claims"], cf.file, row, True)
    sys.stdout.write(rid + "\n")
    return 0


# ---------------------------------------------------------------- argv

def _parser() -> _GateParser:
    p = _GateParser(prog="claims", add_help=True)
    subs = p.add_subparsers(dest="sub", metavar="{add,verify}")
    subs.required = True
    a = subs.add_parser("add", prog="claims add")
    for flag in _ADD_FLAGS:
        a.add_argument(flag, default=None, action="append")
    v = subs.add_parser("verify", prog="claims verify")
    v.add_argument("id", metavar="ID", nargs="*")
    for flag in _VERIFY_FLAGS:
        v.add_argument(flag, default=None, action="append")
    return p


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates claims add|verify ...``: print the claim id; 2 on a usage error, 1 on a refusal."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("claims: argv must be a list of str\n")
        return 2
    try:
        p = _parser()
        ns = p.parse_args(args)
        if ns.sub == "verify" and len(ns.id) > 1:
            p.error("unrecognized arguments: %s" % " ".join(ns.id[1:]))
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return (_add if ns.sub == "add" else _verify)(ns)
    except GateError as e:
        sys.stderr.write("claims %s: %s\n" % (ns.sub, safe_text(e)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
