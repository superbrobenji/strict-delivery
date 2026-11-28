"""Gate ``pr-body``: the pull-request body file has no unresolved placeholder (Task L2.1, process learnings C3).

``python3 -m gates check pr-body --body-file <file>`` reads one file (``prbody.read_raw``: one descriptor, no symlink,
no standard input) and prints, in this order, each later step only when the earlier passed: ``FAIL pr-body.input:
<reason>`` (no ``--body-file``, an empty value, ``-``, a read problem, the root or config errors); ``FAIL
pr-body.<check>: <reason>`` for the first encoding, line-ending or emptiness problem; then ``PASS pr-body.placeholders``
or one ``FAIL pr-body.placeholder.<line>: <tokens>`` per line holding a ``{{``, a ``}}``, a ``TBD`` or a ``TODO``. The
judged bytes are those read through the one descriptor; a later change of the file is not seen. The gate is in no
``run_all`` list: a pull request's body exists only when a pull request is about to be opened."""
from __future__ import annotations

import sys

from gates.lib import config, gitinfo, prbody
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate

PRODUCES: tuple = ()


def _args(args: list):
    p = gate_args("pr-body")
    p.add_argument("--body-file", default=None, action=_Once, help="the file holding the pull request body")
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root  # a root below the top level fails in config.load's _require_toplevel


def check(args: list) -> Result:
    ns = _args(args)
    path = ns.body_file
    if path is None:
        raise GateError("--body-file is required")
    if path == "":
        raise GateError("--body-file: empty")
    if path == "-":
        raise GateError("--body-file -: standard input is not read")
    root = _root(ns)
    config.load(root)
    try:
        raw = prbody.read_raw(path)
    except GateError as e:
        raise GateError("--body-file %s: %s" % (path, e)) from None
    res = Result("pr-body")
    problems = prbody.text_problems(raw)
    if problems:
        res.fail("pr-body." + problems[0][0], problems[0][1])
        return res
    by_line: dict = {}
    for line, token in prbody.placeholder_hits(raw.decode("utf-8")):
        by_line.setdefault(line, []).append(token)
    for line in sorted(by_line):
        res.fail("pr-body.placeholder.%d" % line, ", ".join(by_line[line]))
    if not by_line:
        res.passed("pr-body.placeholders")
    return res


def main(argv=None) -> int:
    if argv is not None and (type(argv) is not list or any(type(a) is not str for a in argv)):
        raise TypeError("argv must be None or an exact list of exact str, got %s" % type(argv).__name__)
    return run_gate("pr-body", check, argv)


if __name__ == "__main__":
    sys.exit(main())
