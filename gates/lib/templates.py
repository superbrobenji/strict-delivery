"""Templates and their renderer (plan Task 4c.2): the CLAUDE.md and .gitignore managed-block bodies and the CI workflow.

``render`` fills ``{{key}}`` placeholders (key ``[a-z][a-z0-9_]*``) of a file under ``templates/`` in one pass; a GitHub
expression ``${{ ... }}`` is left verbatim and any other ``{{`` is refused. The block and workflow builders check their
input and fail closed with ``GateError``. Every character class is an explicit ASCII range, never a Unicode-version
dependent call (``print_table.is_printable`` is frozen to Unicode 13.0.0). Python 3.9+, standard library only."""
from __future__ import annotations

import os
import posixpath
import re
import stat
from typing import Optional

from gates.lib import print_table
from gates.lib.result import GateError

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")

_KEY = re.compile(r"[a-z][a-z0-9_]*")
_PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_SHA = re.compile(r"[0-9a-f]{40}")
_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_OWNER = re.compile(r"[A-Za-z0-9-]+")
_REPO_NAME = re.compile(r"[A-Za-z0-9._-]+")
_SLUG = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_FETCH_PREFIX = "git fetch --depth 1 https://github.com/"
_BREAKS = frozenset("\n\r\x00\x0b\x0c\x1c\x1d\x1e\x85  ")
_FILE_REFUSED = ("\r", "\x00", "﻿", "\t")
_NO_PIN = "no release tag and no framework commit to pin"


def _name_ok(name: str) -> bool:
    parts = name.split("/")
    return all(_COMPONENT.fullmatch(p) is not None and p != "." and p != ".." for p in parts)


def _read_template(name: str) -> str:
    path = TEMPLATES_DIR
    last = len(name.split("/")) - 1
    for i, part in enumerate(name.split("/")):
        path = os.path.join(path, part)
        try:
            st = os.lstat(path)
        except OSError as e:
            raise GateError("templates.render: %s: cannot read (%s)" % (name, e.strerror or type(e).__name__)) from None
        if stat.S_ISLNK(st.st_mode):
            raise GateError("templates.render: %s: %s: is a symbolic link" % (name, part))
        if i < last:
            if not stat.S_ISDIR(st.st_mode):
                raise GateError("templates.render: %s: %s: is not a directory" % (name, part))
        elif not stat.S_ISREG(st.st_mode):
            raise GateError("templates.render: %s: %s: is not a regular file" % (name, part))
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        raise GateError("templates.render: %s: cannot read (%s)" % (name, e.strerror or type(e).__name__)) from None
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as e:
        raise GateError("templates.render: %s: cannot read (%s)" % (name, e.strerror or type(e).__name__)) from None
    finally:
        os.close(fd)
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("templates.render: %s: not valid UTF-8" % name) from None
    if any(c in text for c in _FILE_REFUSED):
        raise GateError("templates.render: %s: holds a carriage return, tab, NUL or byte order mark" % name)
    if text == "":
        raise GateError("templates.render: %s: empty template" % name)
    return text


def _scan(name: str, text: str) -> list:
    """The template as a list of literal strings and ``(key,)`` tuples; refuses a ``{{`` that is neither a placeholder
    nor the start of a GitHub expression."""
    out = []
    pos = 0
    lit = 0
    while True:
        i = text.find("{{", pos)
        if i < 0:
            break
        if i > 0 and text[i - 1] == "$":
            j = text.find("}}", i + 2)
            if j >= 0:
                body = text[i + 2:j]
                if _KEY.fullmatch(body) is not None:
                    raise GateError("templates.render: %s: line %d: `${{%s}}` is not a placeholder"
                                    % (name, text.count("\n", 0, i) + 1, body))
                pos = j + 2
            else:
                pos = i + 2
            continue
        m = _PLACEHOLDER.match(text, i)
        if m is None:
            raise GateError("templates.render: %s: line %d: `{{` is not a placeholder"
                            % (name, text.count("\n", 0, i) + 1))
        out.append(text[lit:i])
        out.append((m.group(1),))
        pos = lit = m.end()
    out.append(text[lit:])
    return out


def render(name: str, ctx: dict) -> str:
    """The template ``name`` (``/``-separated, under ``TEMPLATES_DIR``) with each ``{{key}}`` replaced by ``ctx[key]``
    in one pass; the output always ends in ``"\\n"``."""
    if type(name) is not str:
        raise GateError("templates.render: name: must be a str")
    if not _name_ok(name):
        raise GateError("templates.render: %r: not a template name" % name)
    if type(ctx) is not dict:
        raise GateError("templates.render: %s: ctx: must be a dict" % name)
    for key in ctx:
        if type(key) is not str:
            raise GateError("templates.render: %s: ctx: every key must be a str" % name)
    parts = _scan(name, _read_template(name))
    used = {p[0] for p in parts if type(p) is tuple}
    for p in parts:
        if type(p) is tuple and p[0] not in ctx:
            raise GateError("templates.render: %s: missing value for {{%s}}" % (name, p[0]))
    for key in ctx:
        if key not in used:
            raise GateError("templates.render: %s: no placeholder uses key %s" % (name, key))
    for key in ctx:
        value = ctx[key]
        if type(value) is not str:
            raise GateError("templates.render: %s: value of %s is not a str" % (name, key))
        if any(c in _BREAKS for c in value):
            raise GateError("templates.render: %s: value of %s holds a line break" % (name, key))
    text = "".join(ctx[p[0]] if type(p) is tuple else p for p in parts)
    return text if text.endswith("\n") else text + "\n"


def _dict(value: object, what: str) -> dict:
    if type(value) is not dict:
        raise GateError("templates: %s must be a dict" % what)
    return value


def _paths(cfg: object, keys: tuple) -> dict:
    if type(cfg) is not dict:
        raise GateError("templates: cfg: must be a dict")
    if "paths" not in cfg:
        raise GateError("templates: cfg: paths is missing")
    paths = _dict(cfg["paths"], "cfg: paths")
    out = {}
    for key in keys:
        if key not in paths:
            raise GateError("templates: cfg: paths.%s is missing" % key)
        value = paths[key]
        if type(value) is not str:
            raise GateError("templates: cfg: paths.%s must be a string" % key)
        # the rule of config._check_path, held equal to it by a test
        if (value == "" or not print_table.is_printable(value) or value.startswith("/") or ".." in value.split("/")
                or value == "." or _normalised(value) != value):
            raise GateError("templates: cfg: paths.%s: must be a non-empty normalised repo-relative path of "
                            "printable characters" % key)
        out[key] = value
    return out


def _normalised(value: str) -> str:
    return posixpath.normpath(value)


def claude_block_body(cfg: dict) -> str:
    """The body of the CLAUDE.md managed block: the five document locations of ``cfg["paths"]`` and the precedence."""
    keys = ("specs", "plans", "reviews", "architecture", "playbooks")
    paths = _paths(cfg, keys)
    for key in keys:
        if "`" in paths[key]:
            raise GateError("templates: cfg: paths.%s must not hold a backtick" % key)
    return render("claude-block.md", paths)


def gitignore_block_body(cfg: dict) -> str:
    """The body of the .gitignore managed block: the four generated files and the receipts directory."""
    paths = _paths(cfg, ("decisions", "findings", "index", "receipts"))
    for key, value in paths.items():
        if value[0] in "#!" or value[-1] in " \\" or any(c in value for c in "*?["):
            raise GateError("templates: cfg: paths.%s: cannot be written as an ignore line" % key)
    body = render("gitignore-block.txt", paths)
    seen = set()
    for line in body.split("\n")[:-1]:
        if line in seen:
            raise GateError("two ignore lines are equal: %s" % line)
        seen.add(line)
    return body


def ci_pin(version: str, framework_sha: Optional[str]) -> str:
    """``v<version>`` for a release, else the 40-hex framework commit; never a branch."""
    if type(version) is not str:
        raise GateError("templates.ci_pin: version: must be a str")
    if _VERSION.fullmatch(version) is None:
        raise GateError("templates.ci_pin: version: must be X.Y.Z")
    if version != "0.0.0":
        return "v" + version
    if type(framework_sha) is str and _SHA.fullmatch(framework_sha) is not None:
        return framework_sha
    raise GateError(_NO_PIN)


def pin_of(text: str) -> Optional[str]:
    """The ref of the one framework fetch line of a rendered workflow, or ``None``."""
    if type(text) is not str:
        raise GateError("templates.pin_of: text must be a str")
    found = [line.lstrip(" ") for line in text.split("\n") if line.lstrip(" ").startswith(_FETCH_PREFIX)]
    if len(found) != 1:
        return None
    rest = found[0][len(_FETCH_PREFIX):]
    slug, sep, ref = rest.partition(" ")
    if sep == "" or _SLUG.fullmatch(slug) is None:
        return None
    if _SHA.fullmatch(ref) is None and _TAG.fullmatch(ref) is None:
        return None
    return ref


def _check_base(base: object) -> str:
    if type(base) is not str:
        raise GateError("templates.ci_workflow: cfg: base_branch must be a str")
    if (_BRANCH.fullmatch(base) is None or ".." in base or "//" in base or base.endswith(("/", ".", ".lock"))):
        raise GateError("templates.ci_workflow: cfg: base_branch %s is not a plain branch name" % _shown(base))
    return base


def _shown(value: str) -> str:
    return repr(value)


def ci_workflow(cfg: dict, pin: str, repository: str) -> str:
    """The generated CI workflow, its framework fetched at ``pin`` from ``https://github.com/<repository>``."""
    if type(cfg) is not dict:
        raise GateError("templates: cfg: must be a dict")
    if "base_branch" not in cfg:
        raise GateError("templates.ci_workflow: cfg: base_branch is missing")
    base = _check_base(cfg["base_branch"])
    if type(repository) is not str:
        raise GateError("templates.ci_workflow: repository: must be a str")
    owner, sep, name = repository.partition("/")
    if (sep == "" or _OWNER.fullmatch(owner) is None or owner[0] == "-" or owner[-1] == "-"
            or _REPO_NAME.fullmatch(name) is None or name.strip(".") == ""):
        raise GateError("templates.ci_workflow: repository: must be <owner>/<name> of letters, digits, '.', '_' and "
                        "'-'")
    if type(pin) is not str or (_SHA.fullmatch(pin) is None and _TAG.fullmatch(pin) is None):
        raise GateError("templates.ci_workflow: pin: must be v<X.Y.Z> or 40 lowercase hex")
    return render("ci/strict-delivery.yml", {"base_branch": base, "pin": pin, "repository": repository})
