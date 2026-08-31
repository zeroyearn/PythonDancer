"""PythonDancer package entry point."""
from __future__ import annotations


# Keep the public ``dancer.tcode.TCodePlaybackController`` name backward
# compatible while upgrading its live playback timing in 2.5. The subclass
# scales normal TCode I<ms> intervals with playback speed but leaves seek and
# Soft Start safety ramps in real milliseconds.
def _install_speed_aware_tcode_controller():
    from . import tcode
    from .tcode_speed import SpeedAwareTCodePlaybackController

    if tcode.TCodePlaybackController is not SpeedAwareTCodePlaybackController:
        tcode.TCodePlaybackController = SpeedAwareTCodePlaybackController


_install_speed_aware_tcode_controller()


def main():
    from .runtime import prepare_runtime_path
    from .util import cli_args

    prepare_runtime_path()
    args = cli_args().parse_args()
    if args.cli:
        from .cli import cmd
        return cmd(args)

    if args.multiaxis:
        from .workstation_ui_v25_final import ux
        ux(args)
        return 0

    from .ui import ux
    ux(args)
    return 0


__all__ = ["main"]
