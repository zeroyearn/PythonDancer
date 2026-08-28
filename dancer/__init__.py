"""PythonDancer package entry point."""
from __future__ import annotations


def main():
    from .util import cli_args

    args = cli_args().parse_args()
    if args.cli:
        from .cli import cmd
        return cmd(args)

    if args.multiaxis:
        from .multiaxis_ui import ux
        ux(args)
        return 0

    from .ui import ux
    ux(args)
    return 0


__all__ = ["main"]
