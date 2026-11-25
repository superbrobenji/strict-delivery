"""Task CI1: one shard of the test suite, for the parallel `shard` jobs of the CI workflow.

    python -m tests.ci_shards --shards N --index K        (K is 1-based)

Lists the test modules at the top of the tests directory (the files `test[A-Za-z0-9_]*.py`), splits them into N shards
greedily by weight (heaviest module first, each into the lightest shard so far, ties by name and by shard number),
prints shard K's module list, runs those modules with verbosity 2 and exits 0 only when the run succeeded and ran at
least one test. Exit 1: a test failure, an error, a module that does not import, or zero tests. Exit 2: any refused
input (the arguments, or a tests tree the runner cannot place); nothing is run then. The shards depend only on the
sorted module names and the integer weights below, so every interpreter and OS computes the same ones.

The command line takes no path: the tests directory is this file's own directory. `main(argv, root=...)` is the seam
the tests use to run the same code on fixture trees. The unittest discover run this replaces loads the same modules.
"""
import importlib
import os
import re
import stat
import sys
import traceback
import unittest

# Seconds per test module measured on `gates (macos-15, 3.9)` in the CI run 45445519707 (total 3079 s over the
# modules of that run; owner scope 2026-11-24). The three modules at 0 s are weighted 1 (see weight()).
WEIGHTS = {
    "test_argparse_text": 105, "test_batch": 0, "test_breakdown": 0, "test_breakdown_c": 3, "test_breakdown_d": 0,
    "test_checkpoints_lib": 14, "test_cites_lib": 9, "test_cites_perf": 7, "test_claims_cli": 36,
    "test_claims_lib": 37, "test_cleanup_lib": 83, "test_config": 11, "test_context_cli": 12, "test_context_lib": 11,
    "test_continue_cli": 46, "test_decisions_cli": 60, "test_decisions_lib": 5, "test_detect": 1,
    "test_dispatch_lib": 28, "test_evidence_lib": 15, "test_findings_cli": 113, "test_findings_lib": 18,
    "test_fold_table": 1, "test_gate_checkpoint": 165, "test_gate_cites": 10, "test_gate_claims": 46,
    "test_gate_cleanup": 130, "test_gate_context": 31, "test_gate_decisions": 26, "test_gate_dispatch": 33,
    "test_gate_evidence": 97, "test_gate_index": 33, "test_gate_register": 56, "test_gate_schema": 13,
    "test_gate_streams": 265, "test_gate_streams_rows": 226, "test_githooks": 110, "test_gitinfo": 148,
    "test_hook_entry": 14, "test_hook_session_start": 24, "test_hookio": 1, "test_ids": 11, "test_index": 103,
    "test_loopstats": 9, "test_loopstats_command": 2, "test_merge_lib": 16, "test_migrations": 0, "test_playbook": 10,
    "test_playbook_drift": 0, "test_plugin_manifest": 3, "test_print_table": 2, "test_program_cli": 64,
    "test_program_merged": 14, "test_program_rows": 39, "test_program_rows_c": 11, "test_program_rows_c2": 23,
    "test_program_rows_d": 15, "test_program_schemas": 1, "test_programs_lib": 53, "test_prompt_blocks": 16,
    "test_questions_cli": 178, "test_receipt_cli": 3, "test_receipts_lib": 25, "test_result": 4, "test_run_all": 97,
    "test_schema_lib": 8, "test_self_adoption": 185, "test_session_store": 5, "test_shellscan": 81, "test_skill": 17,
    "test_store": 32, "test_transcript": 0, "test_worktrees": 7, "test_yamlsub": 4,
}
# A module absent from the table weighs its file size in bytes over this many bytes per second, at least 1: 1700 is
# the median of file size / measured seconds over the 57 modules of the table that took 5 s or more (1665 bytes per
# second), rounded up. A wrong guess only moves a module to another shard; it never drops or repeats one.
BYTES_PER_SECOND = 1700
MODULE_FILE = re.compile(r"test[A-Za-z0-9_]*\.py")  # ASCII only: not isidentifier, whose Unicode tables differ by Python version
PACKAGE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER = re.compile(r"[1-9][0-9]{0,5}")  # at most six digits, so int() never sees long text (4300-digit limit of 3.11+)
USAGE = "usage: python -m tests.ci_shards --shards N --index K"
OPTIONS = ("--shards", "--index")


class Refused(Exception):
    """An input the runner refuses: main() prints it and exits 2."""


def show(text):
    """A bounded ASCII form of untrusted text for a message."""
    return ascii(text if len(text) <= 80 else text[:80] + "...")


def number(option, text):
    if NUMBER.fullmatch(text) is None:
        raise Refused("%s needs a whole number from 1 to 999999 (ASCII digits, no sign, no leading zero), got %s"
                      % (option, show(text)))
    return int(text)


def parse(argv):
    given = {}
    i = 0
    while i < len(argv):
        option = argv[i]
        if option not in OPTIONS:
            raise Refused("unknown argument %s; %s" % (show(option), USAGE))
        if option in given:
            raise Refused("%s given twice; %s" % (option, USAGE))
        if i + 1 >= len(argv):
            raise Refused("%s needs a value; %s" % (option, USAGE))
        given[option] = number(option, argv[i + 1])
        i += 2
    for option in OPTIONS:
        if option not in given:
            raise Refused("%s is required; %s" % (option, USAGE))
    return given["--shards"], given["--index"]


def check_package(path, label):
    """Refuse a package below the tests root (``label`` is its name relative to the root) that holds a test file:
    discover would load it, this runner cannot place it."""
    if not (os.path.isdir(path) and os.path.isfile(os.path.join(path, "__init__.py"))):
        return  # discover enters packages only
    if os.path.islink(path):
        raise Refused("package %s is a symbolic link" % show(label))
    for name in sorted(os.listdir(path)):
        child = os.path.join(label, name)
        if name.startswith("test") and name.endswith(".py"):
            raise Refused("%s sits inside a package; only top-level test modules can be placed" % show(child))
        check_package(os.path.join(path, name), child)


def list_modules(root):
    """The module names (file names without .py) at the top of ``root``, sorted; Refused for anything else discover loads."""
    if os.path.islink(root):
        raise Refused("tests root %s is a symbolic link" % show(root))
    if not os.path.isdir(root):
        raise Refused("tests root %s is not a directory" % show(root))
    names = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not (name.startswith("test") and name.endswith(".py")):
            check_package(path, name)
        elif MODULE_FILE.fullmatch(name) is None:
            raise Refused("%s is not named test[A-Za-z0-9_]*.py in ASCII" % show(name))
        elif not stat.S_ISREG(os.lstat(path).st_mode):  # lstat: a symbolic link, directory or FIFO is refused unopened
            raise Refused("%s is not a regular file (a symbolic link, directory or special file)" % show(name))
        else:
            names.append(name[:-3])
    return names


def weight(root, name):
    if name in WEIGHTS:
        return max(1, WEIGHTS[name])
    return max(1, os.lstat(os.path.join(root, name + ".py")).st_size // BYTES_PER_SECOND)


def split(weights, count):
    """``weights`` is {module: integer weight >= 1}. Returns count lists of module names, each sorted by name."""
    out = [[] for _ in range(count)]
    load = [0] * count
    for name in sorted(weights, key=lambda n: (-weights[n], n)):
        k = load.index(min(load))
        out[k].append(name)
        load[k] += weights[name]
    return [sorted(shard) for shard in out]


def run_modules(package, parent, names):
    """Load and run ``package``.<name> for each name (``parent`` holds the package); 0 only on success with tests run."""
    added = parent not in sys.path
    if added:
        sys.path.insert(0, parent)
    broken = []
    try:
        importlib.invalidate_caches()
        loader, suite = unittest.TestLoader(), unittest.TestSuite()
        for name in names:
            try:  # an ImportError becomes a failing test; any other error at import (a syntax error) is caught here
                suite.addTests(loader.loadTestsFromName("%s.%s" % (package, name)))
            except Exception:  # noqa: BLE001 - reported and counted, the other modules still run
                print("ci_shards: module %s did not load:" % name, file=sys.stderr)
                traceback.print_exc()
                broken.append(name)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    finally:
        if added:
            sys.path.remove(parent)
    if broken:
        return 1
    if result.testsRun == 0:
        print("ci_shards: no test ran in this shard", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def main(argv, root=None, run=run_modules):
    """Exit code of the command. ``root`` is the tests directory (default: this file's directory); ``run`` is called as
    run(package, parent, names) and is replaced only by tests that look at the split without running it."""
    root = os.path.abspath(root if root is not None else os.path.dirname(__file__))
    try:
        count, index = parse(argv)
        if index > count:
            raise Refused("--index %d is past --shards %d" % (index, count))
        package = os.path.basename(root)
        if PACKAGE_NAME.fullmatch(package) is None:
            raise Refused("tests root name %s is not an ASCII package name" % show(package))
        names = list_modules(root)
        if count > len(names):
            raise Refused("--shards %d asks for more shards than the %d test modules; a shard would be empty"
                          % (count, len(names)))
    except Refused as err:
        print("ci_shards: refused: %s" % err, file=sys.stderr)
        return 2
    weights = {name: weight(root, name) for name in names}
    mine = split(weights, count)[index - 1]
    print("ci_shards: shard %d of %d: %d modules, weight %d" % (index, count, len(mine), sum(weights[n] for n in mine)))
    for name in mine:
        print("  %s.%s" % (package, name))
    sys.stdout.flush()
    return run(package, os.path.dirname(root), mine)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
