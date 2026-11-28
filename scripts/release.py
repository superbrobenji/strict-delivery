#!/usr/bin/env python3
"""Release script of the strict-delivery framework repository (plan Task 6R.2; spec section 15).

    python3 scripts/release.py <X.Y.Z> [--date YYYY-MM-DD] [--root R]

Bumps together every literal version the spec requires to agree (``RELEASE_SITES``) and rolls ``CHANGELOG.md``'s
``## Unreleased`` section into ``## <X.Y.Z> - <date>``. It never commits, pushes, tags or merges: it prints the changed
paths and the commands the owner runs next. Every check runs before the first write, so a refusal (exit 1, the
reason on stderr) leaves the tree as it was. ``--root`` defaults to the repository that holds this script and must be
that repository's top level. Every git question goes through ``gates.lib.gitinfo``. Standard library and the
framework's own ``gates`` package only."""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import shlex
import stat
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from gates.lib import config, gitinfo, managed, plugin  # noqa: E402
from gates.lib.result import GateError  # noqa: E402

PLUGIN_NAME = "strict-delivery"
CHANGELOG = "CHANGELOG.md"
UNRELEASED = "## Unreleased"
# Fail-closed narrowing of plugin.MAX_DIGITS (4300): a version component of more than this many digits is refused, so
# no int() of a long text runs and every interpreter gives the same verdict.
MAX_COMPONENT_DIGITS = 9

# (path, kind): the literal version sites of the controller ruling (6R), in the order the spec names them.
RELEASE_SITES = (
    (".claude-plugin/plugin.json", "plugin-json"),
    (".claude-plugin/marketplace.json", "marketplace-json"),
    ("CLAUDE.md", "claude-block"),
    (".gitignore", "gitignore-block"),
    (".strict-delivery/config.yml", "config-version"),
)
_BLOCK_STYLE = {"claude-block": managed.HTML, "gitignore-block": managed.HASH}
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_NEAR_MISS = re.compile(r"#+ *unreleased", re.ASCII | re.IGNORECASE)
_CONFIG_KEY = "framework_version:"
_CONFIG_LINE = re.compile(r'framework_version: "([^"\r\n]*)"\r?')
_PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]*")
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
_USAGE = "usage: python3 scripts/release.py <X.Y.Z> [--date YYYY-MM-DD] [--root R]"


class _Refusal(Exception):
    """A refusal found before anything was written; ``args[0]`` is the reason."""


def _type_name(value: object) -> str:
    return type(value).__name__


def _safe(text: str) -> str:
    """``text`` with every non-ASCII character escaped, so a path or argument never breaks the error stream."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _shown(text: str) -> str:
    """``text`` as ASCII ``repr``, cut to 40 characters, for a message."""
    shown = _safe(repr(text))
    return shown if len(shown) <= 40 else shown[:37] + "..."


def _need_argv(argv: object) -> None:
    if type(argv) is not list:
        raise TypeError("argv must be a list of str, got %s" % _type_name(argv))
    for i, arg in enumerate(argv):
        if type(arg) is not str:
            raise TypeError("argv[%d] must be a str, got %s" % (i, _type_name(arg)))


def _parse_args(argv: list) -> tuple:
    version = None
    date = None
    root = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--date", "--root"):
            if i + 1 >= len(argv):
                raise _Refusal("%s needs a value; %s" % (arg, _USAGE))
            if (date if arg == "--date" else root) is not None:
                raise _Refusal("%s is given twice" % arg)
            if arg == "--date":
                date = argv[i + 1]
            else:
                root = argv[i + 1]
            i += 2
        elif arg.startswith("-"):
            raise _Refusal("unknown option %s; %s" % (_safe(arg), _USAGE))
        else:
            if version is not None:
                raise _Refusal("one version only; %s" % _USAGE)
            version = arg
            i += 1
    if version is None:
        raise _Refusal("the version is missing; %s" % _USAGE)
    return version, date, root


def _version_tuple(text: str, what: str) -> tuple:
    if plugin.VERSION.match(text) is None:
        raise _Refusal("%s %s is not of the form MAJOR.MINOR.PATCH (decimal digits, no leading zeros)"
                       % (what, _shown(text)))
    parts = text.split(".")
    if any(len(p) > MAX_COMPONENT_DIGITS for p in parts):
        raise _Refusal("%s %s: a component of more than %d digits is refused"
                       % (what, _shown(text), MAX_COMPONENT_DIGITS))
    return tuple(int(p) for p in parts)


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _date(text):
    if text is None:
        return _today()
    m = _DATE.match(text)
    if m is not None:
        try:
            datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return text
        except ValueError:
            pass
    raise _Refusal("--date %s is not a real date of the form YYYY-MM-DD" % _shown(text))


def _read(root: str, rel: str) -> str:
    """The text of ``rel`` below ``root``: reached through descriptors (no component is a symbolic link), a regular
    file only (a FIFO is never opened), strict UTF-8, bytes unchanged (no newline translation)."""
    parts = rel.split("/")
    try:
        d = managed._open_parents(root, parts[:-1], False)
    except managed._NotDirectory:
        raise _Refusal("%s: a parent is a symbolic link or not a directory" % rel) from None
    except FileNotFoundError:
        raise _Refusal("%s: is missing" % rel) from None
    except OSError as e:
        raise _Refusal("%s: cannot be read (%s)" % (rel, e.strerror)) from None
    try:
        try:
            st = os.stat(parts[-1], dir_fd=d, follow_symlinks=False)
        except FileNotFoundError:
            raise _Refusal("%s: is missing" % rel) from None
        except OSError as e:
            raise _Refusal("%s: cannot be read (%s)" % (rel, e.strerror)) from None
        if stat.S_ISLNK(st.st_mode):
            raise _Refusal("%s: is a symbolic link" % rel)
        if stat.S_ISDIR(st.st_mode):
            raise _Refusal("%s: is a directory" % rel)
        if not stat.S_ISREG(st.st_mode):
            raise _Refusal("%s: is not a regular file" % rel)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
        except OSError as e:
            raise _Refusal("%s: cannot be read (%s)" % (rel, e.strerror)) from None
        try:
            now = os.fstat(fd)
            if not stat.S_ISREG(now.st_mode) or (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
                raise _Refusal("%s: changed while it was being read" % rel)
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as e:
            raise _Refusal("%s: cannot be read (%s)" % (rel, e.strerror)) from None
        finally:
            os.close(fd)
    finally:
        os.close(d)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        raise _Refusal("%s: is not valid UTF-8" % rel) from None


class _IntText(str):
    """The text of a JSON integer literal, kept as text: no ``int()`` runs on file text, so the 4300-digit limit of
    Python 3.11+ (and ``PYTHONINTMAXSTRDIGITS``) cannot change a verdict. A ``str`` subclass, so ``type(x) is str`` is
    false for it and a number is still not taken for a version string."""


def _parse_int(rel: str):
    def parse(literal: str) -> _IntText:
        if len(literal.lstrip("-")) > plugin.MAX_DIGITS:
            raise _Refusal("%s: holds an integer of more than %d digits" % (rel, plugin.MAX_DIGITS))
        return _IntText(literal)
    return parse


def _non_finite(rel: str) -> _Refusal:
    return _Refusal("%s: holds a non-finite number" % rel)


def _parse_constant(rel: str):
    def parse(_name: str):
        raise _non_finite(rel)
    return parse


def _parse_float(rel: str):
    def parse(literal: str) -> float:
        value = float(literal)
        if not math.isfinite(value):
            raise _non_finite(rel)
        return value
    return parse


def _no_repeated_key(rel: str):
    def pairs(items: list) -> dict:
        out: dict = {}
        for key, value in items:
            if key in out:
                raise _Refusal('%s: repeated key "%s"' % (rel, key))
            out[key] = value
        return out
    return pairs


def _json_object(rel: str, kind: str, text: str):
    """``(data, object)``: the parsed file and the object that holds the version of this repository's plugin."""
    try:
        data = json.loads(text[1:] if text.startswith(_BOM) else text, parse_int=_parse_int(rel),
                          parse_float=_parse_float(rel), parse_constant=_parse_constant(rel),
                          object_pairs_hook=_no_repeated_key(rel))
    except (ValueError, RecursionError):
        raise _Refusal("%s: is not valid JSON" % rel) from None
    if type(data) is not dict:
        raise _Refusal("%s: the top level must be an object" % rel)
    if kind == "plugin-json":
        return data, data
    plugins = data.get("plugins")
    if type(plugins) is not list:
        raise _Refusal("%s: plugins must be a list" % rel)
    hits = [p for p in plugins if type(p) is dict and p.get("name") == PLUGIN_NAME]
    if len(hits) != 1:
        raise _Refusal("%s: needs exactly one plugins entry named %s, found %d" % (rel, PLUGIN_NAME, len(hits)))
    return data, hits[0]


def _json_needle(rel: str, kind: str, text: str) -> tuple:
    """``(old version, needle)``: the one exact text ``"version": "<old>"`` that holds the version of the right object."""
    _data, obj = _json_object(rel, kind, text)
    old = obj.get("version")
    if type(old) is not str:
        raise _Refusal("%s: version is missing or not a string" % rel)
    if plugin.VERSION.match(old) is None:
        raise _Refusal("%s: version %s is not of the form MAJOR.MINOR.PATCH" % (rel, _shown(old)))
    needle = '"version": "%s"' % old
    n = text.count(needle)
    if n != 1:
        raise _Refusal("%s: the text %s matches %d times, not exactly once" % (rel, needle, n))
    return old, needle


def _block_of(rel: str, kind: str, text: str):
    try:
        block = managed.find_block(text, _BLOCK_STYLE[kind])
    except GateError as e:
        raise _Refusal("%s: %s" % (rel, e)) from None
    if block is None:
        raise _Refusal("%s: holds no strict-delivery managed block; run /strict-delivery:init" % rel)
    if block.kind != kind:
        raise _Refusal("%s: its block is %s, not %s; run /strict-delivery:upgrade" % (rel, block.kind, kind))
    return block


def _config_old(rel: str, text: str) -> str:
    lines = [ln for ln in text.split("\n") if ln.startswith(_CONFIG_KEY)]
    if len(lines) != 1:
        raise _Refusal("%s: needs exactly one framework_version line, found %d" % (rel, len(lines)))
    m = _CONFIG_LINE.fullmatch(lines[0])
    if m is None:
        raise _Refusal('%s: the framework_version line is not of the exact form framework_version: "<version>"' % rel)
    return m.group(1)


def _current(rel: str, kind: str, text: str) -> str:
    if kind in ("plugin-json", "marketplace-json"):
        return _json_needle(rel, kind, text)[0]
    if kind in _BLOCK_STYLE:
        return _block_of(rel, kind, text).version
    return _config_old(rel, text)


def _bumped(rel: str, kind: str, text: str, old: str, new: str) -> str:
    if kind in ("plugin-json", "marketplace-json"):
        needle = _json_needle(rel, kind, text)[1]
        out = text.replace(needle, '"version": "%s"' % new)
        data, obj = _json_object(rel, kind, text)
        obj["version"] = new
        again, _ = _json_object(rel, kind, out)
        if again != data:
            raise _Refusal("%s: the version text is not that of the %s object" % (rel, PLUGIN_NAME))
        return out
    if kind in _BLOCK_STYLE:
        block = _block_of(rel, kind, text)
        try:
            return managed.put_block(text, _BLOCK_STYLE[kind], kind, new, block.body)
        except GateError as e:
            raise _Refusal("%s: %s" % (rel, e)) from None
    old_line = '%s "%s"' % (_CONFIG_KEY, old)
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith(_CONFIG_KEY):
            lines[i] = '%s "%s"' % (_CONFIG_KEY, new) + ln[len(old_line):]
    return "\n".join(lines)


def _agree(versions: list) -> str:
    """The version every site holds, or a refusal listing each site that differs from the most common one."""
    counts: dict = {}
    for _rel, v in versions:
        counts[v] = counts.get(v, 0) + 1
    if len(counts) == 1:
        return versions[0][1]
    top = max(counts.values())
    ref = next(v for _rel, v in versions if counts[v] == top)
    odd = ["%s holds %s" % (rel, v) for rel, v in versions if v != ref]
    raise _Refusal("the sites disagree on the current version (most hold %s): %s" % (ref, "; ".join(odd)))


def _roll(text: str, new: str, date: str) -> str:
    if "\r" in text:
        raise _Refusal("%s: holds a carriage return (CR); only LF line ends are read" % CHANGELOG)
    lines = text.split("\n")
    heads = []
    for i, line in enumerate(lines):
        if line == UNRELEASED:
            heads.append(i)
        elif _NEAR_MISS.match(line):
            raise _Refusal("%s: line %d, %s, is not exactly '%s'" % (CHANGELOG, i + 1, _shown(line), UNRELEASED))
    if not heads:
        raise _Refusal("%s: has no '%s' heading" % (CHANGELOG, UNRELEASED))
    if len(heads) > 1:
        raise _Refusal("%s: has %d '%s' headings, not one" % (CHANGELOG, len(heads), UNRELEASED))
    start = heads[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("# "):
            end = j
            break
    if not any(ln.strip() != "" for ln in lines[start + 1:end]):
        raise _Refusal("%s: the section under '%s' is empty" % (CHANGELOG, UNRELEASED))
    lines[start] = "%s\n\n## %s - %s" % (UNRELEASED, new, date)
    return "\n".join(lines)


def _root_identity(root: str) -> tuple:
    """``((dev, ino) of the root path itself, (dev, ino) of what it leads to)``, or the empty tuple when either stat
    fails (a removed or unreadable root never equals the identity taken before, and an empty one is never accepted)."""
    try:
        link, target = os.lstat(root), os.stat(root)
    except OSError:
        return ()
    return (link.st_dev, link.st_ino), (target.st_dev, target.st_ino)


def _write_all(root: str, plan: list) -> None:
    """Write ``(path, old text, new text)`` of the plan: every file is read again and compared with the text the plan
    was made from before the first write, and again just before its own write; a mismatch names the file and the
    files already written. The identity of the root path (``lstat`` and ``stat``: the link itself and what it leads to)
    is taken before the first comparison and compared again just before each write: a root that was swapped (for a
    link, another directory, a file, or removed) in between is refused naming ``--root`` and the files already written.
    Stated limit: the window between that last comparison and the write itself stays open (``managed._write`` walks the
    root path again); closing it needs a descriptor-rooted write (owner question Q-RS9-2, not built here), and a root
    swapped for a path with the identical identity (a bind mount of the same directory) is not seen."""
    first = _root_identity(root)
    for rel, old, _new in plan:
        if _read(root, rel) != old:
            raise _Refusal("%s: changed after it was read; nothing written" % rel)
    written: list = []

    def fail(reason: str) -> _Refusal:
        tail = "; written before it: " + ", ".join(written) if written else "; nothing written"
        return _Refusal(reason + tail)
    for rel, old, new in plan:
        try:
            if _read(root, rel) != old:
                raise fail("%s: changed after it was read" % rel)
            if not first or _root_identity(root) != first:
                raise fail("--root: %s changed during the run" % root)
            managed._write(root, rel, new)
        except _Refusal as e:
            if written and "written before it" not in e.args[0]:
                raise fail(e.args[0]) from None
            raise
        except managed._NotDirectory:
            raise fail("%s: a parent is a symbolic link or not a directory" % rel) from None
        except OSError as e:
            raise fail("%s: cannot be written (%s)" % (rel, e.strerror)) from None
        written.append(rel)


def _run(argv: list) -> None:
    version, date_text, root_arg = _parse_args(argv)
    new_t = _version_tuple(version, "the version")
    date = _date(date_text)
    root = _REPO if root_arg is None else root_arg
    if root == "" or "\x00" in root:
        raise _Refusal("--root must be a non-empty path without a NUL character")
    try:
        top = gitinfo.toplevel(root)
    except GateError as e:
        raise _Refusal("--root: %s" % e) from None
    try:
        same = os.path.samefile(root, top)
    except OSError:
        same = False
    if not same:
        raise _Refusal("--root must be the repository top level")
    texts = {rel: _read(root, rel) for rel, _kind in RELEASE_SITES}
    changelog = _read(root, CHANGELOG)
    current = _agree([(rel, _current(rel, kind, texts[rel])) for rel, kind in RELEASE_SITES])
    cur_t = _version_tuple(current, "the current version")
    if not new_t > cur_t:
        raise _Refusal("the version %s is not greater than the current version %s" % (version, current))
    new_changelog = _roll(changelog, version, date)
    try:
        cfg = config.load(root)
    except GateError as e:
        raise _Refusal("%s" % e) from None
    if cfg["framework_version"] != current:
        raise _Refusal(".strict-delivery/config.yml: the merged config holds framework_version %s, not %s"
                       % (_safe(repr(cfg["framework_version"])), current))
    branch = gitinfo.current_branch(root)
    if branch is None:
        raise _Refusal("HEAD is detached; check out a release branch")
    base = cfg["base_branch"]
    if branch == base:
        raise _Refusal("the current branch %s is the base branch %s; check out a release branch"
                       % (_safe(repr(branch)), _safe(repr(base))))
    dirty = gitinfo.dirty_paths(root)
    if dirty:
        raise _Refusal("the tree is not clean: %s" % ", ".join(_safe(p) for p in dirty[:10]))
    for what, name in (("the current branch", branch), ("base_branch", base)):
        if _PRINTABLE_ASCII.fullmatch(name) is None:
            raise _Refusal("%s %s holds a character outside printable ASCII (U+0020-U+007E)" % (what, _shown(name)))
    plan = [(rel, texts[rel], _bumped(rel, kind, texts[rel], current, version)) for rel, kind in RELEASE_SITES]
    plan.append((CHANGELOG, changelog, new_changelog))
    _write_all(root, plan)
    paths = [rel for rel, _old, _new in plan]
    tag = "v" + version
    print("release: %s -> %s (%s)" % (current, version, date))
    print("changed:")
    for rel in paths:
        print("  " + rel)
    print("next commands (this script ran none of them):")
    print("  git add -- " + " ".join(shlex.quote(p) for p in paths))
    print("  git commit -m %s" % shlex.quote("release: " + tag))
    print("  git push -u origin %s" % shlex.quote(branch))
    print("  open a pull request into %s and merge it" % shlex.quote(base))
    print("  after the merge is read back from the host, on the merge commit: "
          "git tag -a %s -m %s <merge commit>" % (tag, shlex.quote("strict-delivery " + version)))
    print("  only on the owner's word: git push origin %s" % tag)


def main(argv: list) -> int:
    _need_argv(argv)
    try:
        _run(argv)
    except _Refusal as e:
        sys.stderr.write("release: %s\n" % _safe(e.args[0]))
        return 1
    except GateError as e:
        sys.stderr.write("release: %s\n" % _safe(str(e)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
