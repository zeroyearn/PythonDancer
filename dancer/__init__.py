"""PythonDancer package entry point."""
from __future__ import annotations


def _install_tcode_runtime_safety():
    from . import tcode
    from .tcode_speed import SpeedAwareTCodePlaybackController

    if tcode.TCodePlaybackController is not SpeedAwareTCodePlaybackController:
        tcode.TCodePlaybackController = SpeedAwareTCodePlaybackController

    serial_class = tcode.SerialTCodeDevice
    if not getattr(serial_class, "_python_dancer_exception_safe_exit", False):
        original_exit = serial_class.__exit__

        def exception_safe_exit(self, exc_type, exc, tb):
            if exc_type is not None and self.is_open:
                try:
                    self.stop()
                except Exception:
                    pass
            return original_exit(self, exc_type, exc, tb)

        serial_class.__exit__ = exception_safe_exit
        serial_class._python_dancer_exception_safe_exit = True


_install_tcode_runtime_safety()


def main():
    from .runtime import prepare_runtime_path
    from .util import cli_args

    prepare_runtime_path()
    args = cli_args().parse_args()
    if args.cli:
        from .cli_v26_release import cmd
        return cmd(args)

    if args.multiaxis:
        from .workstation_ui_v26_release import ux
        ux(args)
        return 0

    from .ui import ux
    ux(args)
    return 0


__all__ = ["main"]
