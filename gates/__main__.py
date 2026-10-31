"""``python3 -m gates <command> [args]``: dispatch to a registered command."""
import sys
from typing import Callable, Dict, List

COMMANDS: Dict[str, Callable[[List[str]], int]] = {}


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        names = ", ".join(sorted(COMMANDS)) or "(none registered)"
        sys.stderr.write("usage: python3 -m gates <command> [args]\ncommands: %s\n" % names)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
