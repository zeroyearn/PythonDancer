"""SR6 firmware-model kinematics diagnostics for PythonDancer 2.6.

The equations are an independent Python implementation of the public SR6
linkage model used by TempestMAx-derived ESP32 firmware. This module is for
preview/reachability diagnostics only: PythonDancer continues to send TCode
axes and leaves final servo control to device firmware.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, pi, sin, sqrt
from typing import Mapping, Sequence

import numpy as np

AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
SERVO_NAMES = ("lower_left", "upper_left", "left_pitch", "right_pitch", "upper_right", "lower_right")


@dataclass(frozen=True)
class SR6Geometry:
    receiver_x_hundredths_mm: float = 16248.0
    main_y_hundredths_mm: float = 1500.0
    pitch_y_hundredths_mm: float = 4500.0
    pitch_link_offset_hundredths_mm: float = 5500.0
    pitch_mount_angle_rad: float = 0.2618
    main_triangle_constant: float = 28125.0
    pitch_arm_square_constant: float = 36250.0
    pitch_triangle_constant: float = 5625.0
    main_denominator_factor: float = 100.0
    pitch_denominator_factor: float = 150.0
    pitcher_z_offset_mm: float = 75.0


@dataclass(frozen=True)
class SR6Solution:
    reachable: bool
    servo_angles_rad: Mapping[str, float]
    twist_normalized: float
    reason: str = ""

    @property
    def max_abs_angle_deg(self) -> float:
        values = [abs(float(value)) for value in self.servo_angles_rad.values() if np.isfinite(value)]
        return float(max(values, default=0.0) * 180.0 / pi)

    def to_dict(self) -> dict[str, object]:
        return {
            "reachable": bool(self.reachable),
            "servo_angles_deg": {name: float(value) * 180.0 / pi for name, value in self.servo_angles_rad.items()},
            "twist_normalized": float(self.twist_normalized),
            "reason": self.reason,
        }


def _axis(position: float, span: float) -> float:
    value = float(np.clip(position, 0.0, 100.0))
    return (value - 50.0) / 50.0 * float(span)


def _safe_acos(value: float) -> tuple[float, bool]:
    if not np.isfinite(value):
        return 0.0, False
    if value < -1.0 or value > 1.0:
        return acos(float(np.clip(value, -1.0, 1.0))), False
    return acos(value), True


def _main_angle(x_hundredths: float, y_hundredths: float, g: SR6Geometry) -> tuple[float, bool]:
    x = float(x_hundredths) / 100.0
    y = float(y_hundredths) / 100.0
    c_sq = x * x + y * y
    c = sqrt(max(c_sq, 0.0))
    if c <= 1e-9:
        return 0.0, False
    gamma = atan2(x, y)
    beta, valid = _safe_acos((c_sq - g.main_triangle_constant) / (g.main_denominator_factor * c))
    return gamma + beta - pi, valid


def _pitch_angle(x_hundredths: float, y_hundredths: float, z_hundredths: float, pitch_hundredths_deg: float, g: SR6Geometry) -> tuple[float, bool]:
    pitch = float(pitch_hundredths_deg) * (pi / 18000.0)
    x = float(x_hundredths) + g.pitch_link_offset_hundredths_mm * sin(g.pitch_mount_angle_rad + pitch)
    y = float(y_hundredths) - g.pitch_link_offset_hundredths_mm * cos(g.pitch_mount_angle_rad + pitch)
    x /= 100.0
    y /= 100.0
    z = float(z_hundredths) / 100.0
    b_sq = g.pitch_arm_square_constant - (g.pitcher_z_offset_mm + z) ** 2
    if b_sq <= 0.0:
        return 0.0, False
    c_sq = x * x + y * y
    c = sqrt(max(c_sq, 0.0))
    if c <= 1e-9:
        return 0.0, False
    gamma = atan2(x, y)
    beta, valid = _safe_acos((c_sq + g.pitch_triangle_constant - b_sq) / (g.pitch_denominator_factor * c))
    return gamma + beta - pi, valid


def solve_sr6_pose(pose: Mapping[str, float], geometry: SR6Geometry | None = None) -> SR6Solution:
    g = geometry or SR6Geometry()
    stroke = _axis(pose.get("L0", 50.0), 6000.0)
    forward = _axis(pose.get("L1", 50.0), 3000.0)
    side = _axis(pose.get("L2", 50.0), 3000.0)
    roll = _axis(pose.get("R1", 50.0), 3000.0)
    pitch = _axis(pose.get("R2", 50.0), 2500.0)
    twist = -_axis(pose.get("R0", 50.0), 1.0)

    x = g.receiver_x_hundredths_mm - forward
    targets = {
        "lower_left": (x, g.main_y_hundredths_mm + stroke + roll),
        "upper_left": (x, g.main_y_hundredths_mm - stroke - roll),
        "upper_right": (x, g.main_y_hundredths_mm - stroke + roll),
        "lower_right": (x, g.main_y_hundredths_mm + stroke - roll),
    }
    angles: dict[str, float] = {}
    valid = True
    for name, (tx, ty) in targets.items():
        angle, ok = _main_angle(tx, ty, g)
        angles[name] = angle
        valid &= ok

    left_pitch, left_ok = _pitch_angle(x, g.pitch_y_hundredths_mm - stroke, side - 1.5 * roll, -pitch, g)
    right_pitch, right_ok = _pitch_angle(x, g.pitch_y_hundredths_mm - stroke, -side + 1.5 * roll, -pitch, g)
    angles["left_pitch"] = left_pitch
    angles["right_pitch"] = right_pitch
    valid &= left_ok and right_ok
    ordered = {name: float(angles[name]) for name in SERVO_NAMES}
    return SR6Solution(valid, ordered, float(np.clip(twist, -1.0, 1.0)), "" if valid else "linkage acos domain / arm geometry exceeded")


def sample_plan_pose(plan: Mapping[str, Sequence[tuple[float, float]]], at: float) -> dict[str, float]:
    result = {}
    target = float(max(0.0, at))
    for axis in AXES:
        rows = sorted((float(t), float(p)) for t, p in plan.get(axis, ()) if np.isfinite(t) and np.isfinite(p))
        if not rows:
            result[axis] = 50.0
            continue
        times = np.asarray([row[0] for row in rows])
        values = np.asarray([row[1] for row in rows])
        result[axis] = float(np.interp(target, times, values, left=values[0], right=values[-1]))
    return result


def trajectory_kinematics_diagnostics(plan: Mapping[str, Sequence[tuple[float, float]]], geometry: SR6Geometry | None = None) -> dict[str, object]:
    times = sorted({float(at) for axis in AXES for at, _ in plan.get(axis, ()) if np.isfinite(at)})
    if not times:
        return {"samples": 0, "unreachable": 0, "unreachable_ratio": 0.0, "max_abs_servo_angle_deg": 0.0, "first_unreachable_at": None}
    unreachable = 0
    first = None
    max_angle = 0.0
    for at in times:
        solution = solve_sr6_pose(sample_plan_pose(plan, at), geometry)
        max_angle = max(max_angle, solution.max_abs_angle_deg)
        if not solution.reachable:
            unreachable += 1
            if first is None:
                first = float(at)
    return {
        "samples": len(times),
        "unreachable": unreachable,
        "unreachable_ratio": float(unreachable / len(times)),
        "max_abs_servo_angle_deg": float(max_angle),
        "first_unreachable_at": first,
    }
