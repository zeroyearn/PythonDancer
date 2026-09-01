"""Bridge device calibration limits into the 2.6 generation optimizer."""
from __future__ import annotations

from dataclasses import replace

from .calibration import DeviceCalibrationProfile
from .optimizer import OptimizerConfig


def optimizer_from_calibration(
    config: OptimizerConfig,
    profile: DeviceCalibrationProfile | None,
) -> OptimizerConfig:
    """Return an optimizer config using the calibrated per-axis dynamics.

    Calibration minimum/maximum/neutral remain an output-space mapping.  The
    generation optimizer consumes only dynamic limits here, so canonical
    funscript positions stay normalized while velocity, acceleration and jerk
    already respect the selected real-device envelope.
    """
    if profile is None:
        return config
    return replace(
        config,
        max_speed={axis: float(item.max_speed) for axis, item in profile.axes.items()},
        max_acceleration={axis: float(item.max_acceleration) for axis, item in profile.axes.items()},
        max_jerk={axis: float(item.max_jerk) for axis, item in profile.axes.items()},
    )
