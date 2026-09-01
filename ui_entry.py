"""Windows desktop entry point.

A double-click launch has no arguments, so open the current six-axis workstation
by default. Explicit command-line arguments still pass through unchanged when
the executable is launched from a terminal.
"""
from __future__ import annotations

import sys

from dancer import main


def desktop_main() -> int:
    if len(sys.argv) == 1:
        sys.argv.append("--multiaxis")
    return int(main() or 0)


if __name__ == "__main__":
    raise SystemExit(desktop_main())
