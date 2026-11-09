"""``python3 -m gates <command> [args]``: dispatch to a registered command."""
import importlib
import sys
from typing import Callable, Dict, List

GATES: Dict[str, str] = {"cites": "gates.gate_cites", "decisions": "gates.gate_decisions",
                         "register": "gates.gate_register",
                         "schema": "gates.gate_schema"}  # gate name -> module defining check(args)
_OWNER: Dict[str, str] = {"cites": " (stream C, Task C2.2)"}  # who delivers a gate module that may be absent


def _check(args: List[str]) -> int:
    if not args or args[0] not in GATES:
        sys.stderr.write("usage: python3 -m gates check <gate> [args]\ngates: %s\n"
                         % (", ".join(sorted(GATES)) or "(none registered)"))
        return 2
    from gates.lib.result import GateError, run_gate
    name = args[0]
    module = GATES[name]

    def run(gate_args: List[str]):
        # Imported here, inside the gate contract: an absent or broken module is a FAIL line, never a traceback,
        # and no other command imports it (owner Q-C2fin-1, Q-1c0-1).
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as e:
            if e.name == module:
                raise GateError("%s.py missing%s" % (module.replace(".", "/"), _OWNER.get(name, ""))) from None
            raise
        return mod.check(gate_args)

    return run_gate(name, run, args[1:])


def _index(args: List[str]) -> int:
    from gates.tools import index
    return index.main(args)


def _decisions(args: List[str]) -> int:
    from gates.tools import decisions_cli
    return decisions_cli.main(args)


COMMANDS: Dict[str, Callable[[List[str]], int]] = {"check": _check, "decisions": _decisions, "index": _index}


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        names = ", ".join(sorted(COMMANDS)) or "(none registered)"
        sys.stderr.write("usage: python3 -m gates <command> [args]\ncommands: %s\n" % names)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
