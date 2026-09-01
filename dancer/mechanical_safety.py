"""Mechanical risk scoring and nearest-safe SR6 pose projection for PythonDancer 2.7."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .kinematics import AXES, SR6Geometry, sample_plan_pose, solve_sr6_pose


@dataclass(frozen=True)
class MechanicalProjectionConfig:
    enabled: bool = True
    max_risk: float = 0.82
    servo_limit_deg: float = 88.0
    soft_margin_deg: float = 12.0
    sensitivity_limit_deg_per_unit: float = 2.5
    finite_difference_step: float = 0.5
    binary_iterations: int = 10
    coordinate_iterations: int = 6
    neutral: float = 50.0

    def __post_init__(self):
        object.__setattr__(self, "max_risk", float(np.clip(self.max_risk, 0.0, 1.0)))
        if self.servo_limit_deg <= 0 or self.soft_margin_deg <= 0 or self.sensitivity_limit_deg_per_unit <= 0:
            raise ValueError("mechanical safety limits must be positive")
        if self.binary_iterations < 1 or self.coordinate_iterations < 0:
            raise ValueError("mechanical projection iterations are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": bool(self.enabled),
            "max_risk": float(self.max_risk),
            "servo_limit_deg": float(self.servo_limit_deg),
            "soft_margin_deg": float(self.soft_margin_deg),
            "sensitivity_limit_deg_per_unit": float(self.sensitivity_limit_deg_per_unit),
            "finite_difference_step": float(self.finite_difference_step),
            "binary_iterations": int(self.binary_iterations),
            "coordinate_iterations": int(self.coordinate_iterations),
            "neutral": float(self.neutral),
        }


@dataclass(frozen=True)
class MechanicalRisk:
    risk: float
    reachable: bool
    max_servo_angle_deg: float
    servo_margin_deg: float
    sensitivity: float
    singularity_risk: float
    reason: str = ""

    @property
    def safe(self) -> bool:
        return self.reachable and self.risk < 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "risk": float(self.risk),
            "reachable": bool(self.reachable),
            "max_servo_angle_deg": float(self.max_servo_angle_deg),
            "servo_margin_deg": float(self.servo_margin_deg),
            "sensitivity": float(self.sensitivity),
            "singularity_risk": float(self.singularity_risk),
            "reason": self.reason,
        }


def _angles_deg(pose: Mapping[str, float], geometry: SR6Geometry) -> tuple[np.ndarray, bool, str]:
    solution = solve_sr6_pose(pose, geometry)
    values = np.asarray([float(v) * 57.29577951308232 for v in solution.servo_angles_rad.values()], dtype=np.float64)
    return values, bool(solution.reachable), solution.reason


def mechanical_risk_at_pose(
    pose: Mapping[str, float],
    geometry: SR6Geometry | None = None,
    config: MechanicalProjectionConfig | None = None,
) -> MechanicalRisk:
    geometry = geometry or SR6Geometry()
    config = config or MechanicalProjectionConfig()
    base, reachable, reason = _angles_deg(pose, geometry)
    max_angle = float(np.max(np.abs(base))) if base.size else 0.0
    margin = float(config.servo_limit_deg - max_angle)
    if not reachable:
        return MechanicalRisk(1.0, False, max_angle, margin, float("inf"), 1.0, reason or "unreachable linkage geometry")

    step = max(0.05, float(config.finite_difference_step))
    sensitivity = 0.0
    for axis in ("L0", "L1", "L2", "R1", "R2"):
        center = float(pose.get(axis, config.neutral))
        low_pose = dict(pose); high_pose = dict(pose)
        low_pose[axis] = float(np.clip(center - step, 0.0, 100.0))
        high_pose[axis] = float(np.clip(center + step, 0.0, 100.0))
        low, low_ok, _ = _angles_deg(low_pose, geometry)
        high, high_ok, _ = _angles_deg(high_pose, geometry)
        if not low_ok or not high_ok:
            sensitivity = max(sensitivity, config.sensitivity_limit_deg_per_unit * 2.0)
            continue
        span = max(1e-6, high_pose[axis] - low_pose[axis])
        sensitivity = max(sensitivity, float(np.max(np.abs(high - low))) / span)

    angle_risk = float(np.clip((config.soft_margin_deg - margin) / config.soft_margin_deg, 0.0, 1.0))
    singularity = float(np.clip((sensitivity - 0.5) / max(1e-6, config.sensitivity_limit_deg_per_unit - 0.5), 0.0, 1.0))
    risk = float(np.clip(0.66 * angle_risk + 0.34 * singularity, 0.0, 1.0))
    return MechanicalRisk(risk, True, max_angle, margin, sensitivity, singularity, "")


def _is_safe(pose: Mapping[str, float], geometry: SR6Geometry, config: MechanicalProjectionConfig) -> bool:
    risk = mechanical_risk_at_pose(pose, geometry, config)
    return risk.reachable and risk.risk <= config.max_risk and risk.servo_margin_deg >= 0.0


def project_pose_to_safe(
    pose: Mapping[str, float],
    geometry: SR6Geometry | None = None,
    config: MechanicalProjectionConfig | None = None,
) -> tuple[dict[str, float], MechanicalRisk, bool]:
    geometry = geometry or SR6Geometry()
    config = config or MechanicalProjectionConfig()
    desired = {axis: float(np.clip(pose.get(axis, config.neutral), 0.0, 100.0)) for axis in AXES}
    initial = mechanical_risk_at_pose(desired, geometry, config)
    if not config.enabled or (initial.reachable and initial.risk <= config.max_risk and initial.servo_margin_deg >= 0.0):
        return desired, initial, False

    neutral = {axis: float(np.clip(config.neutral, 0.0, 100.0)) for axis in AXES}
    if not _is_safe(neutral, geometry, config):
        return neutral, mechanical_risk_at_pose(neutral, geometry, config), True

    lo, hi = 0.0, 1.0
    best = dict(neutral)
    for _ in range(config.binary_iterations):
        alpha = (lo + hi) * 0.5
        candidate = {axis: neutral[axis] + alpha * (desired[axis] - neutral[axis]) for axis in AXES}
        if _is_safe(candidate, geometry, config):
            best = candidate
            lo = alpha
        else:
            hi = alpha

    # Coordinate descent moves the radial projection closer to the requested
    # pose while preserving the safe-set constraint.
    for iteration in range(config.coordinate_iterations):
        fraction = 0.5 ** (iteration + 1)
        for axis in AXES:
            delta = (desired[axis] - best[axis]) * fraction
            if abs(delta) < 1e-4:
                continue
            candidate = dict(best)
            candidate[axis] = float(np.clip(best[axis] + delta, 0.0, 100.0))
            if _is_safe(candidate, geometry, config):
                best = candidate
    return best, mechanical_risk_at_pose(best, geometry, config), True


def _grid(plan: Mapping[str, Sequence[tuple[float, float]]]) -> list[float]:
    return sorted({max(0.0, float(at)) for axis in AXES for at, _ in plan.get(axis, ()) if np.isfinite(at)})


def project_plan_to_safe(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    geometry: SR6Geometry | None = None,
    config: MechanicalProjectionConfig | None = None,
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, object]]:
    geometry = geometry or SR6Geometry()
    config = config or MechanicalProjectionConfig()
    copied = {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXES}
    if not config.enabled:
        return copied, trajectory_mechanical_risk(copied, geometry, config)
    times = _grid(copied)
    if not times:
        return copied, trajectory_mechanical_risk(copied, geometry, config)
    projected: dict[float, dict[str, float]] = {}
    changed = 0
    for at in times:
        pose = sample_plan_pose(copied, at)
        safe_pose, _, did_change = project_pose_to_safe(pose, geometry, config)
        projected[at] = safe_pose
        changed += int(did_change)
    result: dict[str, list[tuple[float, float]]] = {}
    grid = np.asarray(times, dtype=np.float64)
    for axis in AXES:
        original = copied[axis]
        if not original:
            result[axis] = []
            continue
        values = np.asarray([projected[at][axis] for at in times], dtype=np.float64)
        original_times = np.asarray([row[0] for row in original], dtype=np.float64)
        sampled = np.interp(original_times, grid, values)
        result[axis] = [(float(at), float(np.clip(pos, 0.0, 100.0))) for at, pos in zip(original_times, sampled)]
    diagnostics = trajectory_mechanical_risk(result, geometry, config)
    diagnostics["projected_samples"] = int(changed)
    return result, diagnostics


def trajectory_mechanical_risk(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    geometry: SR6Geometry | None = None,
    config: MechanicalProjectionConfig | None = None,
) -> dict[str, object]:
    geometry = geometry or SR6Geometry()
    config = config or MechanicalProjectionConfig()
    times = _grid(plan)
    if not times:
        return {"samples": 0, "mean_risk": 0.0, "peak_risk": 0.0, "unsafe_ratio": 0.0, "singularity_ratio": 0.0, "min_servo_margin_deg": config.servo_limit_deg, "first_unsafe_at": None}
    risks = []
    singular = 0
    unsafe = 0
    first = None
    margins = []
    for at in times:
        risk = mechanical_risk_at_pose(sample_plan_pose(plan, at), geometry, config)
        risks.append(risk.risk)
        margins.append(risk.servo_margin_deg)
        if risk.singularity_risk >= 0.8:
            singular += 1
        if (not risk.reachable) or risk.risk > config.max_risk or risk.servo_margin_deg < 0.0:
            unsafe += 1
            if first is None:
                first = float(at)
    return {
        "samples": len(times),
        "mean_risk": float(np.mean(risks)),
        "peak_risk": float(np.max(risks)),
        "unsafe_ratio": float(unsafe / len(times)),
        "singularity_ratio": float(singular / len(times)),
        "min_servo_margin_deg": float(np.min(margins)),
        "first_unsafe_at": first,
    }
