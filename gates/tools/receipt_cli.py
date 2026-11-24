"""Tool ``receipt``: ``python3 -m gates.tools.receipt_cli add --session S --path P [--root R]`` records that session S
read file P and prints the row as YAML (spec 9; plan Task 5a.2; task domain table 5a.2 with its decisions).

Exit 0 on success, 1 on any refusal (one stderr line ``receipt add: <reason>``), 2 on a usage error. The Read hook
calls ``receipts.record`` directly; the command exists for people and tests. The tool declares no produced kind.
"""
from __future__ import annotations

import sys
from typing import Optional

from gates.lib import config, receipts, yamlsub
from gates.lib.result import GateError, _GateParser, repo_root, safe_text

_ADD_FLAGS = ("--session", "--path", "--root")


def _once(flag: str, values: Optional[list]) -> Optional[str]:
    if values is None:
        return None
    if len(values) > 1:
        raise GateError("%s given more than once" % flag)
    return values[0]


def _add(ns) -> int:
    vals = {flag: _once(flag, getattr(ns, flag[2:])) for flag in _ADD_FLAGS}
    for flag in ("--session", "--path"):
        if vals[flag] is None:
            raise GateError("%s is required" % flag)
    root = vals["--root"]
    if root == "":
        raise GateError("--root: must not be empty")
    if root is None:
        root = repo_root()
    cfg = config.load(root)
    row = receipts.record(root, cfg, vals["--session"], vals["--path"])
    text = yamlsub.emit(row)
    try:
        text.encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        raise GateError("a path cannot be encoded for the output") from None
    sys.stdout.write(text)
    return 0


def _parser() -> _GateParser:
    p = _GateParser(prog="receipt", add_help=True)
    subs = p.add_subparsers(dest="sub", metavar="{add}")
    subs.required = True
    a = subs.add_parser("add", prog="receipt add")
    for flag in _ADD_FLAGS:
        a.add_argument(flag, default=None, action="append")
    return p


def main(argv: Optional[list] = None) -> int:
    """``python3 -m gates.tools.receipt_cli add ...``: 0, 1 (a refusal) or 2 (a usage error)."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("receipt: argv must be a list of str\n")
        return 2
    try:
        ns = _parser().parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _add(ns)
    except GateError as e:
        sys.stderr.write("receipt add: %s\n" % safe_text(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
