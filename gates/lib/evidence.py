"""Evidence parsing for pinned findings (spec 13a), standard library only.

``render_pin`` and ``run_pin`` build and run the project's single-test command (``commands.test_one``);
``parse_transcript`` and ``transcript_errors`` read a mutation transcript; ``package_entries`` reads a review package;
``split_cite`` splits a ``<sha>:<path>`` entry. The line vocabulary of both files is in ``gates/schemas``
(``mutation-transcript.yml``, ``review-report.yml``): this module only reads what ``validate_markdown`` has accepted. Text
is split on ``"\\n"`` only (never the str method that also breaks at U+2028), so a command holding U+2028 or U+0085
round-trips. No integer is converted from unbounded text (the ``exit=`` pattern allows at most three digits), so the verdict does not depend on the
interpreter's integer-string limit. Neither kind is declared (no ``PRODUCES``) until the registry request Rq-6-2 lands."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Optional

from gates.lib import ids, schema
from gates.lib.result import GateError, safe_text

_BAD_ID_CHARS = re.compile("[\n\r\x00\ud800-\udfff]")  # a one-line record and an exec cannot carry these (D-1-Q4)
_BAD_EXEC_CHARS = re.compile("[\x00\ud800-\udfff]")  # NUL and a lone surrogate make subprocess raise, not return
_RUN_KEYS = ("n", "phase", "exit", "command")
_INT_BOUND = 999  # the schema's exit field has at most three digits


def _load(kind: str) -> "schema.Schema":
    return schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))


def _checked_lines(kind: str, text: object) -> list:
    """The lines after the first, once ``text`` conforms to the schema of ``kind``; ValueError lists every error."""
    errors = schema.validate_markdown(_load(kind), text)
    if errors:
        raise ValueError("; ".join(errors))
    return text.split("\n")[1:]


# ---------------------------------------------------------------- the pin command
def _template_error(why: str) -> GateError:
    return GateError("commands.test_one: %s" % why)


def render_pin(cfg: dict, test_id: str) -> tuple:
    """``(display, run)`` for the test ``test_id``: ``run`` is the shell string (every ``{id}`` replaced by
    ``shlex.quote(test_id)``) or the argv list (``{id}`` replaced literally in each element); ``display`` is the
    string, or ``shlex.join`` of the list. GateError names ``commands.test_one`` or ``test_id``."""
    if type(cfg) is not dict or type(cfg.get("commands")) is not dict or "test_one" not in cfg["commands"]:
        raise _template_error("is not set (a template holding {id})")
    template = cfg["commands"]["test_one"]
    if type(test_id) is not str:
        raise GateError("test_id: must be a str")
    if test_id == "" or _BAD_ID_CHARS.search(test_id):
        raise GateError("test_id: must be non-empty and hold no newline, carriage return, NUL or lone surrogate")
    if type(template) is str:
        if template == "" or "{id}" not in template:
            raise _template_error("must be a non-empty string or list holding {id}")
        if _BAD_EXEC_CHARS.search(template):
            raise _template_error("holds NUL or a lone surrogate")
        run = template.replace("{id}", shlex.quote(test_id))
        return run, run
    if type(template) is list and template and all(type(e) is str for e in template):
        if not any("{id}" in e for e in template):
            raise _template_error("must be a non-empty string or list holding {id}")
        if any(_BAD_EXEC_CHARS.search(e) for e in template):
            raise _template_error("holds NUL or a lone surrogate")
        run = [e.replace("{id}", test_id) for e in template]
        return shlex.join(run), run
    raise _template_error("must be a non-empty string or list of strings holding {id}")


def run_pin(root: str, run: object) -> int:
    """The exit code of ``run`` at ``root`` (a shell string through ``/bin/sh -c``, a list with no shell), with the
    inherited environment, no timeout, stdin from /dev/null and the output discarded. ``OSError`` is 127. A signal-killed
    child gives the negative signal number. GateError for a ``run`` or ``root`` that is not the exact type, or that
    holds NUL or a lone surrogate."""
    if type(root) is not str:
        raise GateError("root: must be a str path")
    if _BAD_EXEC_CHARS.search(root):
        raise GateError("root: holds NUL or a lone surrogate")
    if type(run) is str and run != "":
        bad = _BAD_EXEC_CHARS.search(run)
    elif type(run) is list and run and all(type(e) is str for e in run):
        bad = any(_BAD_EXEC_CHARS.search(e) for e in run)
    else:
        raise GateError("run: must be a non-empty str or a non-empty list of str")
    if bad:
        raise GateError("run: holds NUL or a lone surrogate")
    try:
        p = subprocess.run(run, cwd=root, shell=type(run) is str, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return 127
    return p.returncode


# ---------------------------------------------------------------- the mutation transcript
def parse_transcript(text: str) -> dict:
    """``{finding, test, mutant, runs}``: the first three are lists of the texts found, in file order (so a repeated or
    missing line is visible to ``transcript_errors``); ``runs`` is ``[{n, phase, exit, command}]`` with int ``n`` and
    ``exit``. ValueError lists every schema error."""
    out: dict = {"finding": [], "test": [], "mutant": [], "runs": []}
    for line in _checked_lines("mutation-transcript", text):
        token = line.split(" ", 1)[0]
        if token == "FINDING":
            out["finding"].append(line[len("FINDING "):])
        elif token == "TEST":
            out["test"].append(line[len("TEST "):])
        elif token == "MUTANT":
            out["mutant"].append(line[len("MUTANT "):])
        elif token == "RUN":
            n, phase, code, command = line[len("RUN "):].split(" ", 3)
            out["runs"].append({"n": int(n), "phase": phase, "exit": int(code[len("exit="):]),
                                "command": command[len("command="):]})
    return out


def _str_list(v: object) -> bool:
    return type(v) is list and all(type(e) is str for e in v)


def _small_int(v: object) -> bool:
    return type(v) is int and -_INT_BOUND <= v <= _INT_BOUND


def _check_parsed(parsed: object) -> None:
    def bad(why: str) -> GateError:
        return GateError("parsed: %s" % why)

    if type(parsed) is not dict or set(parsed) != {"finding", "test", "mutant", "runs"}:
        raise bad("must be the dict parse_transcript returns")
    for k in ("finding", "test", "mutant"):
        if not _str_list(parsed[k]):
            raise bad("%s must be a list of str" % k)
    if type(parsed["runs"]) is not list:
        raise bad("runs must be a list")
    for r in parsed["runs"]:
        if type(r) is not dict or set(r) != set(_RUN_KEYS):
            raise bad("every run must be a dict of n, phase, exit and command")
        if not _small_int(r["n"]) or not _small_int(r["exit"]):
            raise bad("run n and exit must be ints from -999 to 999")
        if type(r["phase"]) is not str or type(r["command"]) is not str:
            raise bad("run phase and command must be str")


def transcript_errors(parsed: dict, finding_id: str, test_id: str, command: str, cfg: dict) -> list:
    """Every way ``parsed`` fails to pin ``finding_id`` / ``test_id`` / ``command`` (spec 13a): one each of FINDING, TEST
    and MUTANT; the finding and test equal the arguments (no strip, no case fold), the finding id valid for
    ``cfg['ids']['finding']``; three RUN lines numbered 1, 2, 3 with phases fix, mutant, fix, each with exactly
    ``command``; runs 1 and 3 exit 0; run 2 exits non-zero and neither 126 nor 127 (controller ruling 6E)."""
    _check_parsed(parsed)
    for name, v in (("finding_id", finding_id), ("test_id", test_id), ("command", command)):
        if type(v) is not str:
            raise GateError("%s: must be a str" % name)
    if type(cfg) is not dict or type(cfg.get("ids")) is not dict or type(cfg["ids"].get("finding")) is not str:
        raise GateError("cfg: must hold ids.finding (a str)")
    errors: list = []
    for key, word in (("finding", "FINDING"), ("test", "TEST"), ("mutant", "MUTANT")):
        if len(parsed[key]) != 1:
            errors.append("%s: expected exactly one %s line, got %s" % (key, word, len(parsed[key])))
    if len(parsed["finding"]) == 1:
        got = parsed["finding"][0]
        if got != finding_id:
            errors.append("finding: expected %s, got %s" % (safe_text(finding_id), safe_text(got)))
        problem = ids.id_problem(got, cfg["ids"]["finding"])
        if problem:
            errors.append("finding: " + problem)
    if len(parsed["test"]) == 1 and parsed["test"][0] != test_id:
        errors.append("test: expected %s, got %s" % (safe_text(test_id), safe_text(parsed["test"][0])))
    runs = parsed["runs"]
    if len(runs) != 3:
        errors.append("RUN: expected exactly three lines, got %s" % len(runs))
    if [r["n"] for r in runs] != [1, 2, 3]:
        errors.append("RUN numbers: expected 1, 2, 3 in file order, got %s" % ", ".join(str(r["n"]) for r in runs))
    if [r["phase"] for r in runs] != ["fix", "mutant", "fix"]:
        errors.append("RUN phases: expected fix, mutant, fix in file order, got %s" % ", ".join(r["phase"] for r in runs))
    for i, r in enumerate(runs):
        if r["command"] != command:
            errors.append("RUN %s: command: expected %s, got %s" % (i + 1, safe_text(command), safe_text(r["command"])))
        code = r["exit"]
        if i in (0, 2) and code != 0:
            errors.append("RUN %s: exit %s: a run on the fixed code must exit 0" % (i + 1, code))
        if i == 1 and code in (0, 126, 127):
            errors.append("RUN 2: exit %s: the run with the mutant must fail, so it exits non-zero and neither 126 nor 127"
                          % code)
    return errors


# ---------------------------------------------------------------- the review package
def package_entries(text: str) -> dict:
    """Finding id to ``{transcript, test, command}``, from the PIN, PIN-TEST and PIN-COMMAND lines of a review report.
    ValueError on a schema error, on a finding with only some of its three lines, and on a line repeated for one id.
    No id prefix is checked (D-1-Q11)."""
    fields = {"PIN": "transcript", "PIN-TEST": "test", "PIN-COMMAND": "command"}
    groups: dict = {}
    for line in _checked_lines("review-report", text):
        token = line.split(" ", 1)[0]
        if token not in fields:
            continue
        _, fid, value = line.split(" ", 2)
        if token == "PIN":
            value = value[len("transcript="):]
        entry = groups.setdefault(fid, {})
        if fields[token] in entry:
            raise ValueError("%s: %s line repeated" % (fid, token))
        entry[fields[token]] = value
    for fid, entry in groups.items():
        missing = [word for word, key in fields.items() if key not in entry]
        if missing:
            raise ValueError("%s: missing %s" % (fid, ", ".join(missing)))
    return groups


def split_cite(entry: str) -> Optional[tuple]:
    """``(sha, path)`` for ``<sha>:<path>``: the text before the first ``:`` fullmatches ``schema._SHA`` and the path is
    non-empty; else None (also for a bare sha and for a value that is not a str)."""
    if type(entry) is not str:
        return None
    head, sep, path = entry.partition(":")
    if sep and path and schema._SHA.fullmatch(head):
        return head, path
    return None
