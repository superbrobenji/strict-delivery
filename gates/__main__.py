"""``python3 -m gates <command> [args]``: dispatch to a registered command."""
import importlib
import sys
from typing import Callable, Dict, List

GATES: Dict[str, str] = {"schema": "gates.gate_schema"}  # gate name -> module defining check(args)


def _check(args: List[str]) -> int:
    if not args or args[0] not in GATES:
        sys.stderr.write("usage: python3 -m gates check <gate> [args]\ngates: %s\n"
                         % (", ".join(sorted(GATES)) or "(none registered)"))
        return 2
    from gates.lib.result import run_gate
    return run_gate(args[0], importlib.import_module(GATES[args[0]]).check, args[1:])


COMMANDS: Dict[str, Callable[[List[str]], int]] = {"check": _check}


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        names = ", ".join(sorted(COMMANDS)) or "(none registered)"
        sys.stderr.write("usage: python3 -m gates <command> [args]\ncommands: %s\n" % names)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
