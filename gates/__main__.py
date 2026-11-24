"""``python3 -m gates <command> [args]``: dispatch to a registered command."""
import importlib
import sys
from typing import Callable, Dict, List

GATES: Dict[str, str] = {"checkpoint": "gates.gate_checkpoint", "cites": "gates.gate_cites", "claims": "gates.gate_claims",
                         "cleanup": "gates.gate_cleanup",
                         "context": "gates.gate_context",
                         "decisions": "gates.gate_decisions",
                         "dispatch": "gates.gate_dispatch",
                         "evidence": "gates.gate_evidence",
                         "register": "gates.gate_register",
                         "schema": "gates.gate_schema",
                         "streams": "gates.gate_streams"}  # gate name -> module defining check(args)
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


def _claims(args: List[str]) -> int:
    from gates.tools import claims_cli
    return claims_cli.main(args)


def _context(args: List[str]) -> int:
    from gates.tools import context_cli
    return context_cli.main(args)


def _receipt(args: List[str]) -> int:
    from gates.tools import receipt_cli
    return receipt_cli.main(args)


def _continue(args: List[str]) -> int:
    from gates.tools import continue_cli
    return continue_cli.main(args)


def _decisions(args: List[str]) -> int:
    from gates.tools import decisions_cli
    return decisions_cli.main(args)


def _findings(args: List[str]) -> int:
    from gates.tools import findings_cli
    return findings_cli.main(args)


def _program(args: List[str]) -> int:
    from gates.tools import program_cli
    return program_cli.main(args)


def _questions(args: List[str]) -> int:
    from gates.tools import questions_cli
    return questions_cli.main(args)


def _loopstats(args: List[str]) -> int:
    from gates import loopstats
    return loopstats.main(args)


def _run_all(args: List[str]) -> int:
    from gates import run_all
    return run_all.main(args)


def _githook(args: List[str]) -> int:
    from gates.tools import githooks
    return githooks.main(args)


def _githooks(args: List[str]) -> int:
    from gates.tools import githooks
    return githooks.manage(args)


def _hook(args: List[str]) -> int:
    """Delegate to ``gates.hook.main(args)``, imported here (stream ``runtime``'s file). Fail closed with exit 2 and
    one stderr line: ``hook.missing`` when ``gates/hook.py`` is absent, ``hook.import`` when it cannot be used (a hook
    exit of 1 does not block). A ``SystemExit`` raised by the import is ``hook.import`` too; any other ``BaseException``
    that is not an ``Exception`` propagates, as does anything ``main`` itself raises."""
    import importlib.util
    try:
        mod = importlib.import_module("gates.hook")
    except ImportError as e:
        if type(e.name) is str and e.name == "gates.hook":   # the type first: no __eq__ of the caller's runs
            try:
                absent = importlib.util.find_spec("gates.hook") is None
            except Exception:
                absent = False
            if absent:
                sys.stderr.write("FAIL hook.missing: gates.hook is not installed\n")
                return 2
        from gates.lib import result
        shown = result.safe_text(e.name) if type(e.name) is str and e.name else result._type_name(e)
        sys.stderr.write("FAIL hook.import: %s\n" % shown)
        return 2
    except (Exception, SystemExit) as e:   # a SystemExit at import is a failure, whatever its code (plan :3266)
        from gates.lib import result
        sys.stderr.write("FAIL hook.import: %s\n" % result._type_name(e))
        return 2
    try:
        main_fn = mod.main
        usable = callable(main_fn)
    except Exception:
        usable = False
    if not usable:
        sys.stderr.write("FAIL hook.import: gates.hook has no callable main\n")
        return 2
    rc = main_fn(args)
    if type(rc) is not int:   # None would exit 0: fail open (plan :3266 "(fail closed)")
        from gates.lib import result
        sys.stderr.write("FAIL hook.result: gates.hook main returned %s\n" % result._type_name(rc))
        return 2
    return rc


COMMANDS: Dict[str, Callable[[List[str]], int]] = {"check": _check, "claims": _claims, "context": _context, "continue": _continue,
                                                   "decisions": _decisions,
                                                   "findings": _findings, "githook": _githook, "githooks": _githooks, "hook": _hook,
                                                   "index": _index, "loopstats": _loopstats, "program": _program, "questions": _questions,
                                                   "receipt": _receipt, "run_all": _run_all}


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        names = ", ".join(sorted(COMMANDS)) or "(none registered)"
        sys.stderr.write("usage: python3 -m gates <command> [args]\ncommands: %s\n" % names)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
