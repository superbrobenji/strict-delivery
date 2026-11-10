"""Schema migration registry (spec 15; plan Task 2a.1): one pure step per ``(kind, from_version)``.

Standard library only. A step never mutates its argument: it returns a new row that shares no nested value with
the old one. ``migrate`` leaves every row it cannot carry to the current version exactly as it is, so a caller
that compares rows (``store.base_errors``) compares an unmigratable row as it stands and fails closed.
"""
from __future__ import annotations

import copy
import os

from gates.lib import schema
from gates.lib.result import _raw


def _decision_1(row: dict) -> dict:
    """``decision/1`` -> ``decision/2``: the tag only; neither ``recommended`` nor ``source`` is added (design 5)."""
    new = copy.deepcopy(row)
    new["schema"] = "decision/2"
    return new


MIGRATIONS: dict = {("decision", 1): _decision_1}


def _check_kind(kind: object) -> str:
    """``kind`` when it is an exact ``str`` naming a known kind; else SchemaError, before any file is opened."""
    if type(kind) is not str or kind not in schema.KNOWN_KINDS:
        raise schema.SchemaError("%s: not a known schema kind" % _raw(kind))
    return kind


def current_version(kind: str) -> int:
    """The ``version`` of ``<SCHEMAS_DIR>/<kind>.yml``; a SchemaError (unknown kind, missing or bad file) passes
    through."""
    return schema.load_schema(os.path.join(schema.SCHEMAS_DIR, _check_kind(kind) + ".yml")).version


def migrate(kind: str, row: object) -> object:
    """``row`` carried to the current version of ``kind`` through the registered steps, in order. Returns ``row``
    itself when it is not a ``dict``, its tag is missing, malformed or of another kind, its version is at or above
    the current one, or a step from its version up is not registered. A mapping row with a bad ``kind`` raises
    SchemaError (a caller bug is never a silent unchanged row)."""
    if type(row) is not dict:
        return row
    _check_kind(kind)
    tag = row.get("schema")
    m = schema._TAG.fullmatch(tag) if type(tag) is str else None
    if m is None or m.group(1) != kind:
        return row
    digits = m.group(2)
    cur = current_version(kind)
    if len(digits) > len(str(cur)):
        return row  # more digits (no leading zero) than the current version: above it, decided without int() (FD2)
    n = int(digits)
    if any((kind, v) not in MIGRATIONS for v in range(n, cur)):
        return row  # a gap: never part way. At or above current the range is empty and ``row`` comes back below
    out = row
    for v in range(n, cur):
        out = MIGRATIONS[(kind, v)](out)
    return out
