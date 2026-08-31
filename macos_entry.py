"""macOS app entry point.

A Finder launch has no arguments, so open the modern six-axis choreography UI by
default. Command-line arguments still pass through unchanged when the app binary
is invoked from Terminal.
"""
from __future__ import annotations

import sys

from dancer import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--multiaxis")
    raise SystemExit(main() or 0)
