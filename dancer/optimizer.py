"""Cross-axis pose optimization and jerk limiting for PythonDancer 2.6."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
DEFAULT_SPEED = {"L0": 400., "L1": 180., "L2": 180., "R0": 300., "R1": 200., "R2": 200.}
DEFAULT_ACCEL = {"L0": 2400., "L1": 1000., "L2": 1000., "R0": 1800., "R1": 1200., "R2": 1200.}
DEFAULT_JERK = {"L0": 16000., "L1": 7000., "L2": 7000., "R0": 12000., "R1": 8000., "R2": 8000.}


@dataclass(frozen=True)
class OptimizerConfig:
    enabled: bool = True
    neutral: float = 50.0
    pose_budget: float = 1.85
    velocity_budget: float = 2.25
    iterations: int = 3
    max_speed: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_SPEED))
    max_acceleration: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_ACCEL))
    max_jerk: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_JERK))

    def __post_init__(self):
        for name in ("pose_budget", "velocity_budget"):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.iterations < 1:
            raise ValueError("optimizer iterations must be >= 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": bool(self.enabled),
            "neutral": float(self.neutral),
            "pose_budget": float(self.pose_budget),
            "velocity_budget": float(self.velocity_budget),
            "iterations": int(self.iterations),
            "max_speed": dict(self.max_speed),
            "max_acceleration": dict(self.max_acceleration),
            "max_jerk": dict(self.max_jerk),
        }


def _clean(actions: Sequence[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    rows = sorted((float(at), float(pos)) for at, pos in actions if np.isfinite(at) and np.isfinite(pos))
    if not rows:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    dedup = {}
    for at, pos in rows:
        dedup[max(0.0, at)] = float(np.clip(pos, 0.0, 100.0))
    times = np.asarray(sorted(dedup), dtype=np.float64)
    return times, np.asarray([dedup[float(at)] for at in times], dtype=np.float64)


def _union_grid(plan: Mapping[str, Sequence[tuple[float, float]]]) -> np.ndarray:
    values: set[float] = set()
    for axis in AXES:
        for at, _ in plan.get(axis, ()):
            if np.isfinite(at):
                values.add(max(0.0, float(at)))
    return np.asarray(sorted(values), dtype=np.float64)


def _sample(actions: Sequence[tuple[float, float]], grid: np.ndarray, neutral: float) -> np.ndarray:
    times, values = _clean(actions)
    if grid.size == 0:
        return np.asarray([], dtype=np.float64)
    if times.size == 0:
        return np.full(grid.size, neutral, dtype=np.float64)
    if times.size == 1:
        return np.full(grid.size, float(values[0]), dtype=np.float64)
    return np.interp(grid, times, values, left=float(values[0]), right=float(values[-1]))


def _clip_kinematics(values: np.ndarray, grid: np.ndarray, speed_limit: float, accel_limit: float, jerk_limit: float) -> np.ndarray:
    if values.size < 2:
        return values.copy()
    out = values.astype(np.float64, copy=True)
    velocity = 0.0
    acceleration = 0.0
    for index in range(1, values.size):
        dt = max(1e-4, float(grid[index] - grid[index - 1]))
        desired_velocity = (float(out[index]) - float(out[index - 1])) / dt
        desired_velocity = float(np.clip(desired_velocity, -speed_limit, speed_limit))
        desired_accel = (desired_velocity - velocity) / dt
        jerk_span = jerk_limit * dt
        desired_accel = float(np.clip(desired_accel, acceleration - jerk_span, acceleration + jerk_span))
        desired_accel = float(np.clip(desired_accel, -accel_limit, accel_limit))
        velocity = float(np.clip(velocity + desired_accel * dt, -speed_limit, speed_limit))
        acceleration = desired_accel
        out[index] = np.clip(out[index - 1] + velocity * dt, 0.0, 100.0)
    return out


def optimize_multiaxis(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    config: OptimizerConfig | None = None,
) -> dict[str, list[tuple[float, float]]]:
    config = config or OptimizerConfig()
    copied = {axis: [(float(at), float(pos)) for at, pos in plan.get(axis, ())] for axis in AXES}
    if not config.enabled:
        return copied
    grid = _union_grid(copied)
    if grid.size == 0:
        return copied

    neutral = float(np.clip(config.neutral, 0.0, 100.0))
    matrix = np.column_stack([_sample(copied[axis], grid, neutral) for axis in AXES])
    for _ in range(int(config.iterations)):
        deviations = (matrix - neutral) / 50.0
        pose_load = np.linalg.norm(deviations, axis=1)
        scale = np.ones_like(pose_load)
        mask = pose_load > config.pose_budget
        scale[mask] = config.pose_budget / np.maximum(pose_load[mask], 1e-9)
        matrix = neutral + deviations * scale[:, None] * 50.0

        if grid.size > 1:
            dt = np.maximum(np.diff(grid), 1e-4)
            normalized_velocity = np.zeros_like(matrix)
            for column, axis in enumerate(AXES):
                limit = max(1e-6, float(config.max_speed.get(axis, DEFAULT_SPEED[axis])))
                normalized_velocity[1:, column] = np.diff(matrix[:, column]) / dt / limit
            load = np.linalg.norm(normalized_velocity, axis=1)
            for index in range(1, grid.size):
                if load[index] <= config.velocity_budget:
                    continue
                factor = config.velocity_budget / max(load[index], 1e-9)
                matrix[index] = matrix[index - 1] + (matrix[index] - matrix[index - 1]) * factor

        for column, axis in enumerate(AXES):
            matrix[:, column] = _clip_kinematics(
                matrix[:, column],
                grid,
                float(config.max_speed.get(axis, DEFAULT_SPEED[axis])),
                float(config.max_acceleration.get(axis, DEFAULT_ACCEL[axis])),
                float(config.max_jerk.get(axis, DEFAULT_JERK[axis])),
            )

    result: dict[str, list[tuple[float, float]]] = {}
    for column, axis in enumerate(AXES):
        times, _ = _clean(copied[axis])
        if times.size == 0:
            result[axis] = []
            continue
        values = np.interp(times, grid, matrix[:, column])
        result[axis] = [(float(at), float(np.clip(pos, 0.0, 100.0))) for at, pos in zip(times, values)]
    return result


def optimizer_diagnostics(plan: Mapping[str, Sequence[tuple[float, float]]], neutral: float = 50.0) -> dict[str, float]:
    grid = _union_grid(plan)
    if grid.size == 0:
        return {"peak_pose_load": 0.0, "peak_normalized_velocity": 0.0}
    matrix = np.column_stack([_sample(plan.get(axis, ()), grid, neutral) for axis in AXES])
    pose = np.linalg.norm((matrix - neutral) / 50.0, axis=1)
    peak_velocity = 0.0
    if grid.size > 1:
        dt = np.maximum(np.diff(grid), 1e-4)
        components = []
        for column, axis in enumerate(AXES):
            components.append(np.diff(matrix[:, column]) / dt / DEFAULT_SPEED[axis])
        peak_velocity = float(np.max(np.linalg.norm(np.column_stack(components), axis=1)))
    return {"peak_pose_load": float(np.max(pose)), "peak_normalized_velocity": peak_velocity}
