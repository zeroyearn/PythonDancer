"""Physical safety pass for non-destructive workstation edits."""
from __future__ import annotations

from typing import Mapping, Sequence

from .motion import apply_constraints
from .multiaxis import AXIS_ORDER, MultiAxisConfig, SECONDARY_LIMITS


def constrain_workspace_plan(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    config: MultiAxisConfig | None,
) -> dict[str, list[tuple[float, float]]]:
    """Re-run per-axis speed/acceleration limits after manual edits.

    Automatic plans are already constrained, but gesture overlays and local
    splices are applied after planning. This pass makes the edited plan safe to
    hand to funscript export or the live TCode controller.
    """
    result: dict[str, list[tuple[float, float]]] = {}
    if config is None:
        return {
            axis: [(float(at), float(pos)) for at, pos in plan.get(axis, ())]
            for axis in AXIS_ORDER
        }

    motion = config.motion
    for axis in AXIS_ORDER:
        actions = list(plan.get(axis, ()))
        if not actions:
            result[axis] = []
            continue
        if axis == "L0":
            speed, acceleration = float(motion.max_speed), float(motion.max_acceleration)
        else:
            speed, acceleration = SECONDARY_LIMITS[axis]
        result[axis] = apply_constraints(
            actions,
            max_speed=speed,
            max_acceleration=acceleration,
            min_interval=float(motion.min_interval),
        )
    return result
