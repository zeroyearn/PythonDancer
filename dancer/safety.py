"""Safety, diagnostics, gap filling, and axis-linking for PythonDancer 2.5."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .multiaxis import AXIS_ORDER, SECONDARY_LIMITS
from .workspace import copy_plan, sample_axis


@dataclass(frozen=True)
class SmartLimitProfile:
    name: str = "safe"
    l0_extreme: float = 34.0
    l0_rotation_scale: float = 0.72
    l1_extreme: float = 30.0
    l1_pitch_scale: float = 0.72
    sway_roll_budget: float = 58.0
    simultaneous_velocity_budget: float = 2.6


SMART_LIMIT_PRESETS = {
    "safe": SmartLimitProfile("safe", 30.0, .62, 27.0, .62, 48.0, 2.1),
    "balanced": SmartLimitProfile("balanced", 34.0, .72, 30.0, .72, 58.0, 2.6),
    "open": SmartLimitProfile("open", 39.0, .84, 35.0, .84, 70.0, 3.2),
}


@dataclass
class AxisLink:
    source: str
    target: str
    gain: float = 0.35
    delay_ms: float = 0.0
    smoothing: float = 0.2
    mode: str = "position"  # position or velocity
    only_if_empty: bool = False

    def __post_init__(self):
        if self.source not in AXIS_ORDER or self.target not in AXIS_ORDER:
            raise ValueError("axis link source/target must be six-axis channel names")
        if self.source == self.target:
            raise ValueError("axis link source and target must differ")
        if self.mode not in ("position", "velocity"):
            raise ValueError("axis link mode must be position or velocity")
        if not np.isfinite(self.gain):
            raise ValueError("axis link gain must be finite")
        if not np.isfinite(self.delay_ms):
            raise ValueError("axis link delay must be finite")
        if not 0.0 <= float(self.smoothing) <= 1.0:
            raise ValueError("axis link smoothing must be within 0..1")

    def to_dict(self):
        return {
            "source": self.source,
            "target": self.target,
            "gain": float(self.gain),
            "delay_ms": float(self.delay_ms),
            "smoothing": float(self.smoothing),
            "mode": self.mode,
            "only_if_empty": bool(self.only_if_empty),
        }


@dataclass
class SafetySettings:
    smart_limits: bool = True
    profile: str = "balanced"
    soft_start_ms: int = 750
    auto_home: bool = True
    home_ms: int = 700
    gap_fill: str = "ambient"  # none / ambient / beat / repeat
    gap_threshold: float = 1.75
    links: list[AxisLink] = field(default_factory=list)

    def __post_init__(self):
        if self.profile not in SMART_LIMIT_PRESETS:
            raise ValueError(f"unknown smart-limit profile: {self.profile}")
        if self.gap_fill not in ("none", "ambient", "beat", "repeat"):
            raise ValueError(f"unknown gap-fill mode: {self.gap_fill}")
        if int(self.soft_start_ms) < 0:
            raise ValueError("soft_start_ms must be non-negative")
        if int(self.home_ms) < 50:
            raise ValueError("home_ms must be at least 50 ms")
        if not np.isfinite(self.gap_threshold) or float(self.gap_threshold) <= 0:
            raise ValueError("gap_threshold must be positive and finite")

    def to_dict(self):
        return {
            "smart_limits": bool(self.smart_limits),
            "profile": self.profile,
            "soft_start_ms": int(self.soft_start_ms),
            "auto_home": bool(self.auto_home),
            "home_ms": int(self.home_ms),
            "gap_fill": self.gap_fill,
            "gap_threshold": float(self.gap_threshold),
            "links": [link.to_dict() for link in self.links],
        }


def _limits(axis: str) -> tuple[float, float]:
    return (400.0, 2400.0) if axis == "L0" else SECONDARY_LIMITS[axis]


def _axis_grid(plan: Mapping[str, Sequence[tuple[float, float]]], *, duration: float | None = None, hz: float = 20.0):
    max_time = max((actions[-1][0] for actions in plan.values() if actions), default=0.0)
    duration = max(max_time, float(duration or 0.0))
    count = max(2, int(np.ceil(duration * hz)) + 1)
    times = np.linspace(0.0, duration, count, dtype=np.float64)
    values = {axis: np.asarray([sample_axis(plan.get(axis, ()), at, 50.0) for at in times]) for axis in AXIS_ORDER}
    return times, values


def motion_heatmap(plan, *, duration: float | None = None, bins: int = 80):
    """Return per-axis 0..1 movement intensity bins."""
    times, values = _axis_grid(plan, duration=duration, hz=25.0)
    if times[-1] <= 0:
        return {axis: np.zeros(bins, dtype=np.float64) for axis in AXIS_ORDER}
    edges = np.linspace(0.0, times[-1], bins + 1)
    result = {}
    for axis in AXIS_ORDER:
        delta = np.abs(np.gradient(values[axis], times, edge_order=1))
        scores = []
        for i in range(bins):
            mask = (times >= edges[i]) & (times <= edges[i + 1])
            scores.append(float(np.mean(delta[mask])) if np.any(mask) else 0.0)
        arr = np.asarray(scores, dtype=np.float64)
        peak = float(np.percentile(arr, 95)) if arr.size else 0.0
        result[axis] = np.clip(arr / max(peak, 1e-9), 0.0, 1.0)
    return result


def risk_heatmap(plan, *, duration: float | None = None, bins: int = 80):
    """Estimate risk from excursion, velocity, acceleration, and axis coupling."""
    times, values = _axis_grid(plan, duration=duration, hz=25.0)
    if times[-1] <= 0:
        return np.zeros(bins, dtype=np.float64)
    axis_risk = []
    normalized_velocity = []
    for axis in AXIS_ORDER:
        value = values[axis]
        velocity = np.gradient(value, times, edge_order=1)
        acceleration = np.gradient(velocity, times, edge_order=1)
        speed_limit, accel_limit = _limits(axis)
        excursion = np.abs(value - 50.0) / 50.0
        local = .22 * excursion + .43 * np.abs(velocity) / speed_limit + .35 * np.abs(acceleration) / accel_limit
        axis_risk.append(local)
        normalized_velocity.append(np.abs(velocity) / speed_limit)
    combined = np.max(np.vstack(axis_risk), axis=0)
    combined += .15 * np.clip(np.sum(np.vstack(normalized_velocity), axis=0) / 2.6, 0.0, 1.5)
    combined += .22 * np.clip((np.abs(values["L2"] - 50.0) + np.abs(values["R1"] - 50.0) - 50.0) / 50.0, 0.0, 1.0)
    combined += .16 * np.clip((np.abs(values["L1"] - 50.0) + np.abs(values["R2"] - 50.0) - 50.0) / 50.0, 0.0, 1.0)
    edges = np.linspace(0.0, times[-1], bins + 1)
    result = []
    for i in range(bins):
        mask = (times >= edges[i]) & (times <= edges[i + 1])
        result.append(float(np.max(combined[mask])) if np.any(mask) else 0.0)
    return np.clip(np.asarray(result, dtype=np.float64), 0.0, 1.5)


def _normalized_velocity_load(plan, at: float, span: float = 0.06) -> float:
    """Approximate simultaneous six-axis velocity as a sum of limit fractions."""
    left = max(0.0, float(at) - span)
    right = float(at) + span
    dt = max(right - left, 1e-6)
    load = 0.0
    for axis in AXIS_ORDER:
        actions = plan.get(axis, ())
        if not actions:
            continue
        speed_limit, _ = _limits(axis)
        before = sample_axis(actions, left, 50.0)
        after = sample_axis(actions, right, 50.0)
        load += abs(after - before) / dt / max(speed_limit, 1e-9)
    return float(load)


def apply_smart_limits(plan, profile: SmartLimitProfile | str = "balanced"):
    if isinstance(profile, str):
        profile = SMART_LIMIT_PRESETS[profile]
    result = copy_plan(plan)
    timeline = sorted({float(at) for actions in result.values() for at, _ in actions})
    if not timeline:
        return result
    for axis in AXIS_ORDER:
        if not result[axis]:
            continue
        adjusted = []
        for at, pos in result[axis]:
            l0 = sample_axis(result["L0"], at, 50.0)
            l1 = sample_axis(result["L1"], at, 50.0)
            l2 = sample_axis(result["L2"], at, 50.0)
            r1 = sample_axis(result["R1"], at, 50.0)
            value = float(pos)
            if axis in ("R0", "R1") and abs(l0 - 50.0) > profile.l0_extreme:
                value = 50.0 + (value - 50.0) * profile.l0_rotation_scale
            if axis == "R2" and abs(l1 - 50.0) > profile.l1_extreme:
                value = 50.0 + (value - 50.0) * profile.l1_pitch_scale
            if axis in ("L2", "R1"):
                total = abs(l2 - 50.0) + abs(r1 - 50.0)
                if total > profile.sway_roll_budget:
                    scale = profile.sway_roll_budget / max(total, 1e-9)
                    value = 50.0 + (value - 50.0) * scale
            velocity_load = _normalized_velocity_load(result, at)
            if velocity_load > profile.simultaneous_velocity_budget:
                scale = profile.simultaneous_velocity_budget / max(velocity_load, 1e-9)
                anchor = sample_axis(result[axis], max(0.0, at - .06), value)
                value = anchor + (value - anchor) * scale
            adjusted.append((at, float(np.clip(value, 0.0, 100.0))))
        result[axis] = adjusted
    return result


def _smooth_values(values: np.ndarray, amount: float) -> np.ndarray:
    """Low-pass without erasing or reversing the source motion character."""
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount <= 0 or values.size < 3:
        return values
    out = values.astype(np.float64, copy=True)
    passes = 1 + int(np.floor(amount * 3.0))
    blend = min(0.75, amount)
    for _ in range(passes):
        filtered = out.copy()
        filtered[1:-1] = .25 * out[:-2] + .5 * out[1:-1] + .25 * out[2:]
        out = out * (1.0 - blend) + filtered * blend
    return out


def apply_axis_links(plan, links: Sequence[AxisLink]):
    result = copy_plan(plan)
    for link in links:
        source = result[link.source]
        if not source or (link.only_if_empty and result[link.target]):
            continue
        times = np.asarray([at + link.delay_ms / 1000.0 for at, _ in source], dtype=np.float64)
        values = np.asarray([pos for _, pos in source], dtype=np.float64)
        if link.mode == "velocity" and len(values) > 1:
            raw_times = np.asarray([at for at, _ in source], dtype=np.float64)
            velocity = np.gradient(values, raw_times, edge_order=1)
            scale = max(float(np.percentile(np.abs(velocity), 90)), 1e-9)
            values = 50.0 + 50.0 * np.clip(velocity / scale, -1.0, 1.0)
        linked = 50.0 + (values - 50.0) * float(link.gain)
        linked = _smooth_values(linked, link.smoothing)
        generated = [(float(at), float(np.clip(pos, 0.0, 100.0))) for at, pos in zip(times, linked) if at >= 0.0]
        if link.only_if_empty or not result[link.target]:
            result[link.target] = generated
        else:
            target = result[link.target]
            result[link.target] = [
                (at, float(np.clip(.75 * pos + .25 * sample_axis(generated, at, 50.0), 0.0, 100.0)))
                for at, pos in target
            ]
    return result


def _beat_candidates(beats: Sequence[float], start: float, end: float) -> list[float]:
    arr = np.asarray(beats, dtype=np.float64).reshape(-1)
    return [float(at) for at in arr if np.isfinite(at) and start < at < end]


def fill_motion_gaps(plan, beats: Sequence[float], *, mode: str = "ambient", threshold: float = 1.75):
    if mode == "none":
        return copy_plan(plan)
    if mode not in ("ambient", "beat", "repeat"):
        raise ValueError(f"unknown gap-fill mode: {mode}")
    result = copy_plan(plan)
    axis_amp = {"L0": 7.0, "L1": 5.0, "L2": 5.0, "R0": 8.0, "R1": 5.0, "R2": 4.0}
    for axis in AXIS_ORDER:
        actions = result[axis]
        if len(actions) < 2:
            continue
        additions = []
        for (a_t, a_p), (b_t, b_p) in zip(actions[:-1], actions[1:]):
            gap = b_t - a_t
            if gap <= threshold:
                continue
            candidates = _beat_candidates(beats, a_t, b_t)
            if not candidates:
                step = min(0.75, gap / 3.0)
                candidates = list(np.arange(a_t + step, b_t, step))
            for index, at in enumerate(candidates):
                alpha = (at - a_t) / max(gap, 1e-9)
                baseline = a_p * (1.0 - alpha) + b_p * alpha
                if mode == "ambient":
                    delta = axis_amp[axis] * np.sin(np.pi * alpha) * (1 if index % 2 == 0 else -1)
                elif mode == "beat":
                    delta = axis_amp[axis] * 1.35 * (1 if index % 2 == 0 else -1)
                else:
                    delta = (a_p - 50.0) * .55 * (1 if index % 2 == 0 else -1)
                additions.append((float(at), float(np.clip(baseline + delta, 0.0, 100.0))))
        result[axis] = sorted([*actions, *additions], key=lambda item: item[0])
    return result


def add_soft_start(plan, start_at: float, *, duration_ms: int = 750, neutral: float = 50.0):
    """Add a neutral-to-selected-pose ramp for offline/live helpers."""
    result = copy_plan(plan)
    ramp = max(0.05, int(duration_ms) / 1000.0)
    start_at = max(0.0, float(start_at))
    shift = max(0.0, ramp - start_at)
    for axis in AXIS_ORDER:
        if not result[axis]:
            continue
        target = sample_axis(result[axis], start_at, neutral)
        ramp_end = start_at + shift
        retained = [(at + shift, pos) for at, pos in result[axis] if at > start_at + 1e-9]
        result[axis] = sorted(
            [(max(0.0, ramp_end - ramp), float(neutral)), (ramp_end, target), *retained],
            key=lambda item: item[0],
        )
    return result


def add_auto_home(plan, *, home_ms: int = 700, neutral: float = 50.0):
    result = copy_plan(plan)
    ramp = max(0.05, int(home_ms) / 1000.0)
    for axis in AXIS_ORDER:
        if not result[axis]:
            continue
        last_at, _ = result[axis][-1]
        result[axis].append((float(last_at + ramp), float(neutral)))
    return result
