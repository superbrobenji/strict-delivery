"""Record ids: ``<PREFIX>-<YYYYMMDD>-<xxxx>`` (spec 7.2), standard library only.

The date is a valid calendar date and is never compared with the clock. The four characters are drawn from
``ALPHABET``: the 32 characters of ``0-9a-z`` without ``0``, ``1``, ``l`` and ``o``.
"""
from __future__ import annotations

import datetime
import random
import re

from gates.lib.result import GateError

ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"
_SUFFIX_COUNT = len(ALPHABET) ** 4


def id_pattern(prefix: str) -> "re.Pattern":
    """Pattern (use ``fullmatch``) for ids of ``prefix``; group 1 is the 8-digit date."""
    return re.compile(r"%s-([0-9]{8})-[%s]{4}" % (re.escape(prefix), ALPHABET))


def _form(prefix: str) -> str:
    return "expected %s-<YYYYMMDD>-<xxxx>: a valid calendar date and four characters from %s" % (prefix, ALPHABET)


def id_problem(value: object, prefix: str) -> str:
    """``""`` when ``value`` is a valid id of ``prefix``, else the reason (it states the expected form)."""
    if type(value) is not str:
        return "id is not a string (%s); %s" % (type(value).__name__, _form(prefix))
    m = id_pattern(prefix).fullmatch(value)
    if m is None:
        return "id does not match the form; %s" % _form(prefix)
    try:
        datetime.datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        return "id date %s is not a valid calendar date; %s" % (m.group(1), _form(prefix))
    return ""


def mint(prefix: str, existing: set, today: datetime.date, rng: random.Random) -> str:
    """A new id of ``prefix`` dated ``today`` that is not in ``existing``; redraws on a collision.

    Raises GateError, before drawing, when every suffix for that prefix and day is already taken."""
    head = "%s-%04d%02d%02d-" % (prefix, today.year, today.month, today.day)
    pat = id_pattern(prefix)
    taken = 0
    for e in existing:
        if type(e) is str and e.startswith(head) and pat.fullmatch(e):
            taken += 1
    if taken >= _SUFFIX_COUNT:
        raise GateError("no free id: all %d suffixes of %s on %04d%02d%02d are taken"
                        % (_SUFFIX_COUNT, prefix, today.year, today.month, today.day))
    while True:
        candidate = head + "".join(rng.choice(ALPHABET) for _ in range(4))
        if candidate not in existing:
            return candidate


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()
