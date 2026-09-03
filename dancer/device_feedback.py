"""Hardware-in-the-loop telemetry calibration and Device Twin dynamics for 3.0."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .multiaxis import AXIS_ORDER


@dataclass(frozen=True)
class TelemetrySample:
    timestamp: float
    commanded: Mapping[str, float]
    actual: Mapping[str, float]
    temperature_c: Mapping[str, float] = field(default_factory=dict)
    current_a: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self):
        return {
            "timestamp": float(self.timestamp),
            "commanded": {axis: float(self.commanded.get(axis, 50.0)) for axis in AXIS_ORDER},
            "actual": {axis: float(self.actual.get(axis, 50.0)) for axis in AXIS_ORDER},
            "temperature_c": {str(k): float(v) for k, v in self.temperature_c.items()},
            "current_a": {str(k): float(v) for k, v in self.current_a.items()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            timestamp=float(payload.get("timestamp", 0.0)),
            commanded={str(k): float(v) for k, v in dict(payload.get("commanded") or {}).items()},
            actual={str(k): float(v) for k, v in dict(payload.get("actual") or {}).items()},
            temperature_c={str(k): float(v) for k, v in dict(payload.get("temperature_c") or {}).items()},
            current_a={str(k): float(v) for k, v in dict(payload.get("current_a") or {}).items()},
        )


@dataclass(frozen=True)
class FeedbackCalibration:
    latency_ms: float = 0.0
    gain: Mapping[str, float] = field(default_factory=lambda: {axis: 1.0 for axis in AXIS_ORDER})
    bias: Mapping[str, float] = field(default_factory=lambda: {axis: 0.0 for axis in AXIS_ORDER})
    rms_error: Mapping[str, float] = field(default_factory=lambda: {axis: 0.0 for axis in AXIS_ORDER})
    samples: int = 0
    enabled: bool = False

    def correct_command(self, axis: str, value: float) -> float:
        if not self.enabled:
            return float(value)
        gain = float(self.gain.get(axis, 1.0))
        bias = float(self.bias.get(axis, 0.0))
        if abs(gain) < .05:
            return float(value)
        # actual ~= gain * command + bias; invert that model.
        return float(np.clip((float(value) - bias) / gain, 0.0, 100.0))

    def to_dict(self):
        return {
            "version": "1.0",
            "enabled": bool(self.enabled),
            "latency_ms": float(self.latency_ms),
            "gain": {axis: float(self.gain.get(axis, 1.0)) for axis in AXIS_ORDER},
            "bias": {axis: float(self.bias.get(axis, 0.0)) for axis in AXIS_ORDER},
            "rms_error": {axis: float(self.rms_error.get(axis, 0.0)) for axis in AXIS_ORDER},
            "samples": int(self.samples),
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", False)),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            gain={axis: float((payload.get("gain") or {}).get(axis, 1.0)) for axis in AXIS_ORDER},
            bias={axis: float((payload.get("bias") or {}).get(axis, 0.0)) for axis in AXIS_ORDER},
            rms_error={axis: float((payload.get("rms_error") or {}).get(axis, 0.0)) for axis in AXIS_ORDER},
            samples=int(payload.get("samples", 0)),
        )


def estimate_feedback(samples: Sequence[TelemetrySample]) -> FeedbackCalibration:
    samples = sorted(samples, key=lambda item: item.timestamp)
    if len(samples) < 3:
        return FeedbackCalibration(samples=len(samples), enabled=False)
    timestamps = np.asarray([item.timestamp for item in samples], dtype=np.float64)
    dt = float(np.median(np.diff(timestamps))) if len(timestamps) > 1 else 0.0
    gain = {}
    bias = {}
    rms = {}
    for axis in AXIS_ORDER:
        x = np.asarray([float(item.commanded.get(axis, 50.0)) for item in samples], dtype=np.float64)
        y = np.asarray([float(item.actual.get(axis, 50.0)) for item in samples], dtype=np.float64)
        if np.std(x) < 1e-6:
            g = 1.0
            b = float(np.mean(y - x))
        else:
            matrix = np.column_stack((x, np.ones_like(x)))
            g, b = np.linalg.lstsq(matrix, y, rcond=None)[0]
        prediction = g * x + b
        gain[axis] = float(np.clip(g, .25, 2.0))
        bias[axis] = float(np.clip(b, -30.0, 30.0))
        rms[axis] = float(np.sqrt(np.mean((prediction - y) ** 2)))

    # Estimate lag with normalized cross-correlation of total motion velocity.
    command = np.column_stack([[float(item.commanded.get(axis, 50.0)) for item in samples] for axis in AXIS_ORDER])
    actual = np.column_stack([[float(item.actual.get(axis, 50.0)) for item in samples] for axis in AXIS_ORDER])
    command_motion = np.linalg.norm(np.diff(command, axis=0), axis=1)
    actual_motion = np.linalg.norm(np.diff(actual, axis=0), axis=1)
    command_motion -= np.mean(command_motion)
    actual_motion -= np.mean(actual_motion)
    max_lag = min(20, max(1, len(command_motion) // 4))
    best_lag, best_score = 0, float("-inf")
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = command_motion[:len(command_motion)-lag or None], actual_motion[lag:]
        else:
            a, b = command_motion[-lag:], actual_motion[:len(actual_motion)+lag]
        if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
            continue
        score = float(np.corrcoef(a, b)[0, 1])
        if score > best_score:
            best_score, best_lag = score, lag
    latency_ms = max(0.0, best_lag * dt * 1000.0)
    return FeedbackCalibration(latency_ms, gain, bias, rms, len(samples), True)


@dataclass(frozen=True)
class DeviceDynamicsProfile:
    ambient_c: float = 25.0
    thermal_time_constant_s: float = 90.0
    cooling_time_constant_s: float = 150.0
    warning_c: float = 60.0
    maximum_c: float = 75.0
    power_coefficient: float = .022
    reversal_penalty: float = .14
    velocity_derate: float = 1.0

    def to_dict(self):
        return {name: float(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


@dataclass(frozen=True)
class DynamicLoadReport:
    peak_temperature_c: float
    final_temperature_c: float
    mean_load: float
    peak_load: float
    reversal_density: float
    warning_ratio: float

    def to_dict(self):
        return {name: float(getattr(self, name)) for name in self.__dataclass_fields__}


def simulate_dynamic_load(plan, profile: DeviceDynamicsProfile | None = None, *, sample_hz: float = 20.0) -> DynamicLoadReport:
    profile = profile or DeviceDynamicsProfile()
    duration = max((float(t) for axis in AXIS_ORDER for t, _ in plan.get(axis, ())), default=0.0)
    if duration <= 0:
        return DynamicLoadReport(profile.ambient_c, profile.ambient_c, 0.0, 0.0, 0.0, 0.0)
    times = np.linspace(0.0, duration, max(3, int(duration * sample_hz) + 1))
    matrix = []
    for axis in AXIS_ORDER:
        rows = sorted((float(t), float(p)) for t, p in plan.get(axis, ()))
        if rows:
            x = np.asarray([row[0] for row in rows]); y = np.asarray([row[1] for row in rows])
            matrix.append(np.interp(times, x, y, left=y[0], right=y[-1]))
        else:
            matrix.append(np.full(times.size, 50.0))
    matrix = np.column_stack(matrix)
    velocity = np.gradient(matrix, times, axis=0)
    acceleration = np.gradient(velocity, times, axis=0)
    normalized = np.sqrt(np.mean((velocity / 200.0) ** 2, axis=1) + .35 * np.mean((acceleration / 1200.0) ** 2, axis=1))
    reversals = np.mean(np.sign(velocity[1:]) != np.sign(velocity[:-1]), axis=1)
    load = np.clip(normalized + profile.reversal_penalty * np.pad(reversals, (1, 0)), 0.0, 3.0)
    temp = profile.ambient_c
    peak = temp
    warnings = 0
    for i in range(1, len(times)):
        step = max(times[i] - times[i-1], 1e-4)
        heating = profile.power_coefficient * load[i] * load[i] * 100.0
        cooling = (temp - profile.ambient_c) / max(profile.cooling_time_constant_s, 1.0)
        temp += step * (heating - cooling)
        peak = max(peak, temp)
        if temp >= profile.warning_c:
            warnings += 1
    return DynamicLoadReport(
        float(peak), float(temp), float(np.mean(load)), float(np.max(load)),
        float(np.mean(reversals)) if reversals.size else 0.0,
        float(warnings / max(1, len(times)-1)),
    )
