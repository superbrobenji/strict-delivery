"""The installed plugin's manifest: its directory, the version and the repository it names (plan Task 3d.1).

``manifest`` reads ``<framework_dir>/.claude-plugin/plugin.json`` strictly: UTF-8, JSON without duplicate keys,
``NaN``/``Infinity`` or an integer of more than 4300 digits (the ``int()`` limit of Python 3.11 and later, applied on
every interpreter), an object at the top. Every refusal is a ``GateError`` naming the file. Standard library only."""
from __future__ import annotations

import json
import os
import re
import stat

from gates.lib import result
from gates.lib.result import GateError

MANIFEST = ".claude-plugin/plugin.json"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
REPOSITORY = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?\Z")
MAX_DIGITS = 4300


class _Refused(Exception):
    """A manifest problem found while parsing; ``args[0]`` is the reason."""


class _IntText(str):
    """An integer of the manifest, kept as its text: no ``int()`` runs, so ``PYTHONINTMAXSTRDIGITS`` and the
    interpreter's version change nothing. It is not an exact ``str``, so a reader that wants a string refuses it."""


def _pairs(pairs: list) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Refused("duplicate key " + result._frozen_repr(key))
        out[key] = value
    return out


def _constant(name: str):
    raise _Refused("the constant %s is not allowed" % name)


def _integer(text: str) -> _IntText:
    if len(text.lstrip("-")) > MAX_DIGITS:
        raise _Refused("an integer of more than %d digits is not allowed" % MAX_DIGITS)
    return _IntText(text)


def framework_dir() -> str:
    """The directory holding the imported ``gates`` package: its parent, absolute."""
    import gates
    return os.path.dirname(os.path.dirname(os.path.abspath(gates.__file__)))


def manifest(framework_dir: str) -> dict:
    """The parsed ``<framework_dir>/.claude-plugin/plugin.json``; a ``GateError`` naming it for any problem."""
    path = os.path.join(framework_dir, *MANIFEST.split("/"))

    def refuse(reason: str) -> GateError:
        return GateError("%s: %s" % (MANIFEST, reason))
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise refuse("is not a regular file")
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise refuse("cannot be read (%s)" % result._type_name(e)) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("is not valid UTF-8") from None
    try:
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_integer)
    except _Refused as e:
        raise refuse(e.args[0]) from None
    except RecursionError:
        raise refuse("nesting is too deep") from None
    except ValueError:  # json.JSONDecodeError
        raise refuse("is not valid JSON") from None
    if type(data) is not dict:
        raise refuse("the top level must be an object")
    return data


def _shown(value: object) -> str:
    try:
        return result._raw(value)
    except Exception:
        return result._type_name(value)


def _string(framework_dir: str, key: str) -> str:
    data = manifest(framework_dir)
    if key not in data:
        raise GateError("%s: %s is missing" % (MANIFEST, key))
    value = data[key]
    if type(value) is not str:
        raise GateError("%s: %s must be a string, got %s" % (MANIFEST, key, _shown(value)))
    return value


def version(framework_dir: str) -> str:
    """The manifest's ``version``: an exact ``str`` of the form ``X.Y.Z`` (no ``v``, suffix, leading zero or space)."""
    value = _string(framework_dir, "version")
    if not VERSION.match(value):
        raise GateError("%s: version %s is not of the form X.Y.Z" % (MANIFEST, value))
    return value


def _repository(framework_dir: str):
    value = _string(framework_dir, "repository")
    m = REPOSITORY.match(value)
    if not m:
        raise GateError("%s: repository %s is not https://github.com/<owner>/<name>" % (MANIFEST, value))
    return value, m


def repository_url(framework_dir: str) -> str:
    """The manifest's ``repository`` as written, when it fully matches ``REPOSITORY``."""
    return _repository(framework_dir)[0]


def repository_slug(framework_dir: str) -> str:
    """``<owner>/<name>`` of the manifest's ``repository`` (a trailing ``.git`` dropped)."""
    m = _repository(framework_dir)[1]
    return "%s/%s" % (m.group(1), m.group(2))
