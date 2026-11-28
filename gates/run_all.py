"""``python3 -m gates run_all [--json] [--root R] [--base REF]``: run the profile's gates and keep every line
(spec 12, 13; plan Task 2b.1). Not a gate in ``GATES``; its last line is ``run_all.version`` (plan Task 3d.1, which
Q-B2plan-24 (a) foresaw): the target's ``framework_version`` against the installed plugin's version."""
from __future__ import annotations

import importlib
import importlib.util

from gates.lib import config, gitinfo, plugin, programs, result

PROFILE_GATES: dict = {
    "light": ("schema", "register", "decisions"),
    "standard": ("schema", "register", "decisions", "claims", "cites", "evidence"),
    "strict": ("schema", "register", "decisions", "claims", "cites", "evidence"),
}
BASE_GATES: tuple = ("decisions", "register", "claims", "evidence")
# Task P2.3 (controller ruling, plan P:2843): appended to the profile's list while a program is live or the current branch
# is a program branch, whatever the profile; ``streams`` is not in ``BASE_GATES`` (decision D-Q6 (a)).
LIVE_PROGRAM_GATES: tuple = ("streams",)


def _args(args: list):
    p = result.gate_args("run_all")
    p.add_argument("--base", default=None, action=result._Once, help="the base ref, passed to the gates that take one")
    return p.parse_args(args)


def _missing(gate: str, reason: str) -> list:
    res = result.Result("run_all")
    res.fail("run_all.missing." + gate, reason)
    return res.lines


def _absent(name: str) -> bool:
    """True when the module's file is shown to be absent. A lookup that itself raises an ``Exception`` (a parent
    that is no package, a parent that is ``None`` or fails to re-import, a ``__spec__`` of ``None``, a finder that
    raises, or a ``SystemExit``, as at import) cannot show it, so the caller reports the import's own failure
    (CR-2); any other non-``Exception`` ``BaseException`` propagates."""
    try:
        return importlib.util.find_spec(name) is None
    except (Exception, SystemExit):
        return False


def _load(gate: str):
    """``(check, None)`` or ``(None, lines)`` when the gate cannot be loaded."""
    from gates import __main__ as entry
    if gate not in entry.GATES:
        return None, _missing(gate, "not registered in gates.__main__.GATES")
    name = entry.GATES[gate]
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as e:
        # "missing" means the file is absent (or sys.modules[name] is None); a module whose own code raised
        # ModuleNotFoundError naming itself is an import failure (F-FV-2)
        if e.name == name and _absent(name):
            return None, _missing(gate, "%s.py missing" % name.replace(".", "/"))
        return None, _missing(gate, "import of %s raised %s" % (name, result._type_name(e)))
    except (Exception, SystemExit) as e:
        return None, _missing(gate, "import of %s raised %s" % (name, result._type_name(e)))
    try:
        fn = module.check
    except AttributeError:
        return None, _missing(gate, "%s has no check" % name)
    except (Exception, SystemExit) as e:
        return None, _missing(gate, "reading %s.check raised %s" % (name, result._type_name(e)))
    if not callable(fn):
        return None, _missing(gate, "%s.check is not callable (%s)" % (name, result._type_name(fn)))
    return fn, None


def _version_line(cfg: dict) -> result.Line:
    """``PASS run_all.version`` when the target's ``framework_version`` is the installed plugin's version, else a
    FAIL line naming both and ``/strict-delivery:upgrade``; a manifest problem is that line's reason (fail closed)."""
    res = result.Result("run_all")
    try:
        want = plugin.version(plugin.framework_dir())
    except result.GateError as e:
        res.fail("run_all.version", str(e))
        return res.lines[0]
    if cfg["framework_version"] == want:
        res.passed("run_all.version")
    else:
        res.fail("run_all.version", "framework_version %s does not match the plugin version %s; "
                 "run /strict-delivery:upgrade" % (cfg["framework_version"], want))
    return res.lines[0]


def _run_gates(gates: tuple, root: str, base) -> list:
    out: list = []
    for gate in gates:
        fn, lines = _load(gate)
        if fn is not None:
            # one token per option: a value starting with "-" is then never read as an option (F-FV-1)
            gate_args = ["--root=" + root]
            if gate in BASE_GATES and base is not None:
                gate_args.append("--base=" + base)
            lines = result.run_check(gate, fn, gate_args).lines
        out.extend(lines)
    return out


def _program_live(root: str) -> bool:
    """True when a program is live (``programs.live_programs``) or the current branch is a program branch, a bad shape
    included (``streams`` then reports it)."""
    cfg = config.load(root)
    if programs.live_programs(root, cfg):
        return True
    branch = gitinfo.current_branch(root)
    if branch is None:
        return False
    try:
        return programs.parse_branch(branch) is not None
    except ValueError:
        return True


def check(args: list) -> result.Result:
    ns = _args(args)
    root = ns.root if ns.root is not None else result.repo_root()
    cfg = config.load(root)
    res = result.Result("run_all")
    res.lines.extend(_run_gates(PROFILE_GATES[cfg["profile"]], root, ns.base))
    try:
        live = _program_live(root)
    except (result.GateError, ValueError) as e:   # decision D-Q22 (b): the profile gates still ran
        res.fail("run_all.streams", "the live-program check failed: %s" % e)
        live = False
    if live:
        res.lines.extend(_run_gates(LIVE_PROGRAM_GATES, root, ns.base))
    res.lines.append(_version_line(cfg))
    return res


def main(argv: list) -> int:
    return result.run_gate("run_all", check, argv)
