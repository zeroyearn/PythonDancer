"""Final DAW shaping pass for PythonDancer 2.8."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from .automation import AutomationSet, StyleMorphTimeline
from .multiaxis import AXIS_ORDER
from .workspace import copy_plan

ROTATION_AXES = {"R0", "R1", "R2"}
TRANSLATION_AXES = {"L0", "L1", "L2"}


def apply_daw_transform(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    automation: AutomationSet | None = None,
    styles: StyleMorphTimeline | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Apply non-destructive DAW automation to a canonical six-axis plan.

    No Automation point + no Style keyframe is a strict identity operation so
    upgrading from 2.7 never changes a choreography merely by opening it in 2.8.
    The pass preserves independent keyframe clocks and empty/muted axes.
    """
    automation = automation or AutomationSet()
    styles = styles or StyleMorphTimeline()
    if not automation.active and not styles.active:
        return copy_plan(plan)

    result: dict[str, list[tuple[float, float]]] = {}
    for axis in AXIS_ORDER:
        source = [(float(at), float(pos)) for at, pos in plan.get(axis, ())]
        if not source:
            result[axis] = []
            continue
        rows = []
        previous = None
        for at, pos in source:
            controls = automation.sample(at)
            deviation = float(pos) - 50.0
            scale = float(controls.get("energy", 1.0))

            if styles.active:
                intent, style_strength, _ = styles.sample(at)
                scale *= max(0.0, style_strength)
                scale *= .55 + .65 * intent.intensity
                if axis in ROTATION_AXES:
                    scale *= .55 + .75 * intent.rotation_bias
                elif axis in TRANSLATION_AXES:
                    scale *= .55 + .75 * intent.translation_bias
            else:
                intent = None

            if axis == "L0":
                scale *= float(controls.get("stroke_depth", 1.0))
            if axis in ROTATION_AXES:
                scale *= float(controls.get("rotation_mix", 1.0))
            if axis not in ("L0", "R0"):
                complexity = float(controls.get("complexity", .5))
                density = float(controls.get("gesture_density", 1.0))
                scale *= (.72 + .56 * complexity) * (.60 + .40 * density)

            # 0.5 is neutral. Lower values pull the motion inward; higher values
            # allow more expressive excursion before the final mechanical pass.
            safety = float(controls.get("safety_aggressiveness", .5))
            scale *= .75 + .50 * safety
            shaped = float(np.clip(50.0 + deviation * scale, 0.0, 100.0))

            smoothing = float(np.clip(controls.get("smoothing", 0.0), 0.0, .95))
            if intent is not None:
                smoothing = float(np.clip(smoothing + .22 * intent.flow - .18 * intent.aggression, 0.0, .96))
            if previous is not None and smoothing > 0:
                shaped = float(previous * smoothing + shaped * (1.0 - smoothing))
            rows.append((at, shaped))
            previous = shaped
        result[axis] = rows
    return result
