"""PythonDancer package entry point."""
from __future__ import annotations


def main():
    from .runtime import prepare_runtime_path
    from .util import cli_args

    prepare_runtime_path()
    args = cli_args().parse_args()
    if args.cli:
        from .cli import cmd
        return cmd(args)

    if args.multiaxis:
        from .workstation_ui_v25 import ux
        ux(args)
        return 0

    from .ui import ux
    ux(args)
    return 0


__all__ = ["main"]
