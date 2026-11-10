"""``python3 -m gates run_all [--json] [--root R] [--base REF]``: run the profile's gates and keep every line
(spec 12, 13; plan Task 2b.1). Not a gate in ``GATES``; it has no version line in block 2 (Q-B2plan-24 (a))."""
from __future__ import annotations

import importlib

from gates.lib import config, result

PROFILE_GATES: dict = {
    "light": ("schema", "register", "decisions"),
    "standard": ("schema", "register", "decisions", "claims", "cites"),
    "strict": ("schema", "register", "decisions", "claims", "cites"),
}
BASE_GATES: tuple = ("decisions", "register", "claims")


def _args(args: list):
    p = result.gate_args("run_all")
    p.add_argument("--base", default=None, action=result._Once, help="the base ref, passed to the gates that take one")
    return p.parse_args(args)


def _missing(gate: str, reason: str) -> list:
    res = result.Result("run_all")
    res.fail("run_all.missing." + gate, reason)
    return res.lines


def _load(gate: str):
    """``(check, None)`` or ``(None, lines)`` when the gate cannot be loaded."""
    from gates import __main__ as entry
    if gate not in entry.GATES:
        return None, _missing(gate, "not registered in gates.__main__.GATES")
    name = entry.GATES[gate]
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            return None, _missing(gate, "%s.py missing" % name.replace(".", "/"))
        return None, _missing(gate, "import of %s raised %s" % (name, result._type_name(e)))
    except (Exception, SystemExit) as e:
        return None, _missing(gate, "import of %s raised %s" % (name, result._type_name(e)))
    try:
        fn = module.check
    except AttributeError:
        return None, _missing(gate, "%s has no check" % name)
    except Exception as e:
        return None, _missing(gate, "reading %s.check raised %s" % (name, result._type_name(e)))
    if not callable(fn):
        return None, _missing(gate, "%s.check is not callable (%s)" % (name, result._type_name(fn)))
    return fn, None


def check(args: list) -> result.Result:
    ns = _args(args)
    root = ns.root if ns.root is not None else result.repo_root()
    cfg = config.load(root)
    res = result.Result("run_all")
    for gate in PROFILE_GATES[cfg["profile"]]:
        fn, lines = _load(gate)
        if fn is not None:
            gate_args = ["--root", root]
            if gate in BASE_GATES and ns.base is not None:
                gate_args += ["--base", ns.base]
            lines = result.run_check(gate, fn, gate_args).lines
        res.lines.extend(lines)
    return res


def main(argv: list) -> int:
    return result.run_gate("run_all", check, argv)
