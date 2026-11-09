"""The printed owner batch (session-resume design 3.6-3.8; plan Task 1d.3; owner L:415-L:421, Q-X27 (a)).

Pure: no I/O, the same input gives byte-identical output. Record text is printed raw (decision D-29): no
Unicode-data predicate runs on it, so the bytes are the same on every interpreter (row U1). Each ``\\r\\n``,
``\\r`` or ``\\n`` prints as the two characters ``\\n`` (as ``index._one_line``); any other line breaker or control
character is refused (owner Q-B2FX2-1 (a): a fixed code-point set, row Q13).
"""
from __future__ import annotations

from typing import List, Optional

from gates.lib.result import GateError

MODEL_POLICY = "model-policy"
# U+0000-U+0008, U+000B-U+001F, U+007F-U+009F, U+2028, U+2029 (tab, LF and CR are allowed; LF and CR are mapped).
_REFUSED = frozenset(list(range(0x00, 0x09)) + list(range(0x0B, 0x0D)) + list(range(0x0E, 0x20))
                     + list(range(0x7F, 0xA0)) + [0x2028, 0x2029])


def _text(field: str, value: object) -> str:
    """``value`` as one printed line, or a GateError naming ``field``."""
    if type(value) is not str:
        raise GateError("%s: must be text" % field)
    for c in value:
        if ord(c) in _REFUSED:
            raise GateError("%s: holds a character outside the batch text set (U+%04X)" % (field, ord(c)))
    return value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def _texts(field: str, value: object) -> List[str]:
    if type(value) is not list:
        raise GateError("%s: must be a list of text" % field)
    return [_text(field, v) for v in value]


def _options(row: dict) -> list:
    opts = row.get("options")
    if type(opts) is not list:
        raise GateError("options: must be a list of label and cost")
    out = []
    for o in opts:
        if type(o) is not dict or "label" not in o or "cost" not in o:
            raise GateError("options: each option must have a label and a cost")
        out.append((o["label"], _text("options", o["label"]), _text("options", o["cost"])))
    return out


def render_question(rid: str, row: dict) -> list:
    """The printed lines of one question, in the order of plan L:418; tool-only fields are never printed."""
    if type(row) is not dict:
        raise GateError("row: must be a mapping")
    cls = _text("class", row.get("class"))
    question = _text("question", row.get("question"))
    opts = _options(row)
    effect = _text("effect", row.get("effect"))
    topics = _texts("topics", row.get("topics"))
    globs = _texts("applies_to", row.get("applies_to"))
    lines = ["%s | class: %s" % (rid, cls), "Question: " + question]
    rest = opts
    if "recommended" in row:
        rec = row["recommended"]
        _text("recommended", rec)
        if row.get("class") == MODEL_POLICY:
            raise GateError("recommended: must be absent when class is %s" % MODEL_POLICY)
        hits = [o for o in opts if o[0] == rec]
        if len(hits) != 1:
            raise GateError("recommended: %s is not the label of exactly one option" % rec)
        lines.append("Recommended: %s -- cost: %s" % (hits[0][1], hits[0][2]))
        rest = [o for o in opts if o[0] != rec]
    else:
        lines.append("Recommended: none")
    lines.append("Alternatives:")
    lines.extend("- %s -- cost: %s" % (label, cost) for _, label, cost in rest)
    lines.append("Effect: " + effect)
    lines.append("Topics: " + (", ".join(topics) if topics else "none"))
    lines.append("Applies to: " + (", ".join(globs) if globs else "none"))
    return lines


def _source_key(row: dict) -> tuple:
    """Present sources in code-point order, then the records with no ``source`` (plan P:974, row R8)."""
    if "source" in row:
        return (0, _text("source", row["source"]))
    return (1, "")


def _section(head: str, records: list) -> list:
    groups: dict = {}
    for rid, row in records:
        groups.setdefault(_source_key(row), []).append((rid, row))
    lines = [head]
    for key in sorted(groups):
        lines.append("### source: " + (key[1] if key[0] == 0 else "none"))
        for rid, row in sorted(groups[key], key=lambda r: r[0]):
            lines.extend(render_question(rid, row))
            lines.append("")
    return lines


def _no_duplicates(records: list) -> None:
    seen: set = set()
    for rid, _ in records:
        if rid in seen:
            raise GateError("duplicate id %s" % rid)
        seen.add(rid)


def render(new: list, also_open: list, cut: Optional[str], cut_note: str) -> str:
    """The owner batch: a header, ``## New`` and, when there are any, ``## Also open`` (plan P:974)."""
    _no_duplicates(list(new) + list(also_open))
    lines = ["Owner questions: %d new, %d also open (cut-off %s%s)"
             % (len(new), len(also_open), cut if cut is not None else "none", cut_note), ""]
    lines.extend(_section("## New", new))
    if also_open:
        lines.extend(_section("## Also open", also_open))
    return "\n".join(lines) + "\n"


def render_answers(records: list, source: str, date: str) -> str:
    """The binding answers of one source for a restart brief (design 3.8): answered records whose ``source``
    equals ``source`` exactly, by id."""
    _no_duplicates(records)
    lines = ["Owner answers (%s), binding" % date]
    for rid, row in sorted(records, key=lambda r: r[0]):
        if row.get("status") != "answered" or "source" not in row or row["source"] != source:
            continue
        lines.append("%s: %s" % (rid, _text("question", row.get("question"))))
        lines.append("Answer: " + _text("answer", row.get("answer")))
    return "\n".join(lines) + "\n"
