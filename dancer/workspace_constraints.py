"""Physical safety pass for non-destructive workstation edits."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from .mechanical_safety import project_plan_to_safe
from .motion import apply_constraints
from .multiaxis import AXIS_ORDER, MultiAxisConfig, SECONDARY_LIMITS
from .optimizer import optimize_multiaxis


def constrain_workspace_plan(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    config: MultiAxisConfig | None,
) -> dict[str, list[tuple[float, float]]]:
    """Re-run kinematic and mechanical safety after non-destructive edits.

    Gesture overlays, curve interpolation, local splices, axis links, and gap
    filling happen after the automatic planner. The final workstation pass must
    therefore restore speed/acceleration/jerk constraints and, when enabled,
    project the edited trajectory back into the configured SR6 safe set before
    it can be exported or sent to a live device.

    Empty axes remain empty throughout the optimizer/projection pipeline so a
    muted channel is never reintroduced by safety processing.
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

    optimizer = replace(config.optimizer, neutral=float(config.neutral))
    constrained = optimize_multiaxis(result, optimizer)
    if not config.mechanical.enabled:
        return constrained

    mechanical = replace(config.mechanical, neutral=float(config.neutral))
    projected, _ = project_plan_to_safe(constrained, config.geometry, mechanical)

    # Projection can insert cross-clock corrections. Re-run the multiaxis jerk
    # limiter, then project once more exactly as the automatic planner does so
    # smoothing cannot interpolate the trajectory back outside the safe set.
    smoothed = optimize_multiaxis(projected, optimizer)
    final, _ = project_plan_to_safe(smoothed, config.geometry, mechanical)
    return final
