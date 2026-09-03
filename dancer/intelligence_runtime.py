"""Shared 3.0 intelligence transform used by CLI and workstation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .copilot import CopilotPlan
from .motion_grammar import MotionProgram, blend_motion_program
from .multiaxis import AXIS_ORDER


@dataclass
class IntelligenceState:
    copilot_instruction: str = ""
    copilot_plan: CopilotPlan | None = None
    motion_program: MotionProgram = field(default_factory=MotionProgram)
    reference_plan: Mapping[str, Sequence[tuple[float, float]]] | None = None
    reference_amount: float = 0.0

    def to_dict(self):
        return {
            "copilot_instruction": self.copilot_instruction,
            "copilot_plan": self.copilot_plan.to_dict() if self.copilot_plan else None,
            "motion_program": self.motion_program.to_dict(),
            "reference_amount": self.reference_amount,
        }


def _axis_factor(operation, axis: str) -> float:
    value = float(operation.value) if isinstance(operation.value, (int, float)) else 1.0
    target = operation.target
    if operation.action == "style":
        if target == "aggressive":
            return 1.16 if axis in ("L0", "L1", "R0", "R1") else 1.08
        if target == "expressive":
            return 1.08 if axis != "L0" else 1.04
        if target == "rotation":
            return 1.20 if axis.startswith("R") else .92
        if target == "minimal":
            return .72
        if target == "smooth":
            return .90
        return 1.0
    if target == "energy":
        return value
    if target == "stroke_depth":
        return value if axis == "L0" else 1.0
    if target == "rotation_mix":
        return value if axis.startswith("R") else 1.0
    if target == "gesture_density":
        return .85 + .15 * value
    if target == "complexity":
        return .90 + .20 * value
    if target == "safety_aggressiveness":
        return .82 + .18 * value
    return 1.0


def apply_copilot_to_plan(plan, copilot: CopilotPlan | None):
    """Apply deterministic semantic edits directly to the raw editable plan.

    This is used for CLI section-aware Copilot edits where the 2.8 DAW objects
    are not exposed by the parent runtime. Device/optimizer passes still happen
    after this transform.
    """
    if copilot is None:
        return {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXIS_ORDER}
    result = {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXIS_ORDER}
    for operation in copilot.operations:
        start, end = float(operation.start), float(operation.end)
        if end <= start:
            continue
        for axis in AXIS_ORDER:
            factor = _axis_factor(operation, axis)
            if abs(factor - 1.0) <= 1e-9:
                continue
            updated = []
            for at, pos in result.get(axis, ()):
                if start <= at <= end:
                    pos = float(np.clip(50.0 + (pos - 50.0) * factor, 0.0, 100.0))
                updated.append((at, pos))
            result[axis] = updated
    for axis, density in copilot.axis_density.items():
        if axis not in result:
            continue
        factor = float(np.clip(density, .25, 2.0))
        result[axis] = [(at, float(np.clip(50.0 + (pos - 50.0) * (.8 + .2 * factor), 0.0, 100.0))) for at, pos in result[axis]]
    if copilot.motion_program.primitives:
        duration = max((float(t) for axis in AXIS_ORDER for t, _ in result.get(axis, ())), default=0.0)
        result = blend_motion_program(result, copilot.motion_program, duration=duration)
    return result


def blend_reference(plan, reference_plan, amount: float = .35):
    if not reference_plan or amount <= 0:
        return {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXIS_ORDER}
    amount = float(np.clip(amount, 0.0, 1.0))
    duration = max((float(t) for axis in AXIS_ORDER for t, _ in plan.get(axis, ())), default=0.0)
    count = max(2, int(np.ceil(duration * 20.0)) + 1)
    times = np.linspace(0.0, max(duration, .05), count)
    result = {}
    for axis in AXIS_ORDER:
        def sample(source):
            rows = sorted((float(t), float(p)) for t, p in source.get(axis, ()))
            if not rows:
                return np.full(times.size, 50.0)
            x = np.asarray([r[0] for r in rows]); y = np.asarray([r[1] for r in rows])
            return np.interp(times, x, y, left=y[0], right=y[-1])
        base = sample(plan)
        ref = sample(reference_plan)
        values = base + amount * (ref - 50.0)
        result[axis] = [(float(t), float(p)) for t, p in zip(times, np.clip(values, 0.0, 100.0))]
    return result


def apply_intelligence(plan, state: IntelligenceState):
    result = {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXIS_ORDER}
    result = apply_copilot_to_plan(result, state.copilot_plan)
    if state.motion_program.primitives:
        duration = max((float(t) for axis in AXIS_ORDER for t, _ in result.get(axis, ())), default=0.0)
        result = blend_motion_program(result, state.motion_program, duration=duration)
    result = blend_reference(result, state.reference_plan, state.reference_amount)
    return result
