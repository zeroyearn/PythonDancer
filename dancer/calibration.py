"""Device calibration profiles and guided low-risk test motion for 2.6."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .tcode import DeviceProfile

AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
DEFAULT_SPEED = {"L0": 400., "L1": 180., "L2": 180., "R0": 300., "R1": 200., "R2": 200.}
DEFAULT_ACCEL = {"L0": 2400., "L1": 1000., "L2": 1000., "R0": 1800., "R1": 1200., "R2": 1200.}
DEFAULT_JERK = {"L0": 16000., "L1": 7000., "L2": 7000., "R0": 12000., "R1": 8000., "R2": 8000.}


@dataclass(frozen=True)
class AxisCalibration:
    minimum: float = 0.0
    maximum: float = 100.0
    neutral: float = 50.0
    inverted: bool = False
    max_speed: float = 200.0
    max_acceleration: float = 1200.0
    max_jerk: float = 8000.0

    def __post_init__(self):
        low = float(np.clip(self.minimum, 0.0, 100.0))
        high = float(np.clip(self.maximum, 0.0, 100.0))
        if high <= low:
            raise ValueError("axis calibration maximum must exceed minimum")
        object.__setattr__(self, "minimum", low)
        object.__setattr__(self, "maximum", high)
        object.__setattr__(self, "neutral", float(np.clip(self.neutral, low, high)))
        for field_name in ("max_speed", "max_acceleration", "max_jerk"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)

    def map_normalized(self, position: float) -> float:
        value = float(np.clip(position, 0.0, 100.0))
        if self.inverted:
            value = 100.0 - value
        if value <= 50.0:
            alpha = value / 50.0
            return float(self.minimum + (self.neutral - self.minimum) * alpha)
        alpha = (value - 50.0) / 50.0
        return float(self.neutral + (self.maximum - self.neutral) * alpha)

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "neutral": self.neutral,
            "inverted": bool(self.inverted),
            "max_speed": self.max_speed,
            "max_acceleration": self.max_acceleration,
            "max_jerk": self.max_jerk,
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "AxisCalibration":
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


@dataclass(frozen=True)
class DeviceCalibrationProfile:
    name: str = "default-device"
    axes: Mapping[str, AxisCalibration] = field(default_factory=dict)
    latency_ms: float = 0.0
    notes: str = ""

    def __post_init__(self):
        normalized = {}
        for axis in AXES:
            value = self.axes.get(axis) if self.axes else None
            if value is None:
                normalized[axis] = AxisCalibration(
                    max_speed=DEFAULT_SPEED[axis],
                    max_acceleration=DEFAULT_ACCEL[axis],
                    max_jerk=DEFAULT_JERK[axis],
                )
            elif isinstance(value, AxisCalibration):
                normalized[axis] = value
            else:
                normalized[axis] = AxisCalibration.from_dict(value)
        object.__setattr__(self, "axes", normalized)
        if not np.isfinite(self.latency_ms):
            raise ValueError("latency_ms must be finite")

    @classmethod
    def from_d2(cls, device: DeviceProfile, *, name: str = "D2 device") -> "DeviceCalibrationProfile":
        calibrations = {
            axis: AxisCalibration(max_speed=DEFAULT_SPEED[axis], max_acceleration=DEFAULT_ACCEL[axis], max_jerk=DEFAULT_JERK[axis])
            for axis in AXES
        }
        supported = sorted(device.axes) if device.axes else list(AXES)
        return cls(name=name, axes=calibrations, notes="D2 supported axes: " + ", ".join(supported))

    def to_dict(self) -> dict[str, object]:
        return {
            "version": "1.0",
            "name": self.name,
            "latency_ms": float(self.latency_ms),
            "notes": self.notes,
            "axes": {axis: calibration.to_dict() for axis, calibration in self.axes.items()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "DeviceCalibrationProfile":
        return cls(
            name=str(payload.get("name", "default-device")),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            notes=str(payload.get("notes", "")),
            axes={axis: AxisCalibration.from_dict(value) for axis, value in dict(payload.get("axes", {})).items()},
        )


def load_calibration_profile(path: str | Path) -> DeviceCalibrationProfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration profile must contain a JSON object")
    return DeviceCalibrationProfile.from_dict(payload)


def save_calibration_profile(path: str | Path, profile: DeviceCalibrationProfile) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return target


def apply_calibration(plan: Mapping[str, Sequence[tuple[float, float]]], profile: DeviceCalibrationProfile | None):
    if profile is None:
        return {axis: [(float(at), float(pos)) for at, pos in plan.get(axis, ())] for axis in AXES}
    result = {}
    for axis in AXES:
        calibration = profile.axes[axis]
        result[axis] = [(float(at), calibration.map_normalized(float(pos))) for at, pos in plan.get(axis, ())]
    return result


def calibration_test_plan(
    profile: DeviceCalibrationProfile,
    *,
    excursion: float = 5.0,
    step_seconds: float = 0.7,
) -> dict[str, list[tuple[float, float]]]:
    """Generate a conservative one-axis-at-a-time verification sequence."""
    excursion = float(np.clip(excursion, 0.5, 10.0))
    step_seconds = max(0.25, float(step_seconds))
    timeline = {axis: [(0.0, profile.axes[axis].neutral)] for axis in AXES}
    at = step_seconds
    for active in AXES:
        for direction in (1.0, -1.0):
            for axis in AXES:
                calibration = profile.axes[axis]
                value = calibration.neutral
                if axis == active:
                    span = calibration.maximum - calibration.minimum
                    value = float(np.clip(value + direction * span * excursion / 100.0, calibration.minimum, calibration.maximum))
                timeline[axis].append((at, value))
            at += step_seconds
            for axis in AXES:
                timeline[axis].append((at, profile.axes[axis].neutral))
            at += step_seconds
    return timeline
