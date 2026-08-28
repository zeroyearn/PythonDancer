"""Motion planning and physical constraints for PythonDancer 2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .features import safe_normalize


@dataclass(frozen=True)
class MotionConfig:
    energy_multiplier: float = 1.0
    pitch_range: float = 100.0
    overflow: int = 0
    amplitude_centering: float = 0.0
    center_offset: float = 0.0
    subdivision: int = 0
    max_speed: float = 400.0
    max_acceleration: float = 2400.0
    min_interval: float = 0.02


def _feature(data: dict, name: str, length: int, fallback: str | None = None) -> np.ndarray:
    value = data.get(name)
    if value is None and fallback:
        value = data.get(fallback)
    if value is None:
        return np.zeros(length, dtype=np.float64)
    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.size < length:
        arr = np.pad(arr, (0, length - arr.size), mode="edge" if arr.size else "constant")
    return arr[:length]


def _overflow_position(value: float, mode: int) -> float:
    if mode == 0:
        return float(np.clip(value, 0.0, 100.0))
    if mode == 1:
        wrapped = value % 200.0
        return float(200.0 - wrapped if wrapped > 100.0 else wrapped)
    if mode == 2:
        if 0.0 <= value <= 100.0:
            return float(value)
        overflow = abs(value - (0.0 if value < 0.0 else 100.0))
        folded = min(50.0, overflow * 0.5)
        return float(folded if value < 0.0 else 100.0 - folded)
    raise ValueError("overflow must be 0 (crop), 1 (bounce), or 2 (fold)")


def _choose_subdivision(configured: int, activity: float, interval: float, tempo: float) -> int:
    if configured not in (0, 1, 2, 4):
        raise ValueError("subdivision must be one of 0, 1, 2, 4")
    if configured:
        return configured
    if interval < 0.32 or tempo >= 175.0:
        return 1
    if activity >= 0.78 and interval >= 0.42:
        return 4
    if activity >= 0.50:
        return 2
    return 1


def apply_constraints(
    actions: Iterable[tuple[float, float]],
    *,
    max_speed: float = 400.0,
    max_acceleration: float = 2400.0,
    min_interval: float = 0.02,
) -> list[tuple[float, float]]:
    ordered = sorted((float(t), float(p)) for t, p in actions if np.isfinite(t) and np.isfinite(p))
    if not ordered:
        return []

    result: list[tuple[float, float]] = []
    previous_velocity = 0.0
    for at, target in ordered:
        target = float(np.clip(target, 0.0, 100.0))
        if not result:
            result.append((max(0.0, at), target))
            continue

        last_at, last_pos = result[-1]
        dt = at - last_at
        if dt <= 0.0:
            result[-1] = (last_at, target)
            continue
        if min_interval > 0.0 and dt < min_interval:
            continue

        delta = target - last_pos
        velocity = delta / dt
        if max_speed > 0.0:
            velocity = float(np.clip(velocity, -max_speed, max_speed))

        if max_acceleration > 0.0 and len(result) > 1:
            max_dv = max_acceleration * dt
            velocity = float(np.clip(
                velocity,
                previous_velocity - max_dv,
                previous_velocity + max_dv,
            ))

        constrained = float(np.clip(last_pos + velocity * dt, 0.0, 100.0))
        actual_velocity = (constrained - last_pos) / dt
        result.append((at, constrained))
        previous_velocity = actual_velocity

    return result


def plan_motion(data: dict, config: MotionConfig) -> list[tuple[float, float]]:
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    if beats.size == 0:
        return []
    beats = beats[np.isfinite(beats)]
    if beats.size == 0:
        return []

    length = beats.size
    energy = safe_normalize(_feature(data, "energy", length))
    pitch = safe_normalize(_feature(data, "pitch", length))
    onset = safe_normalize(_feature(data, "onset", length, fallback="energy"))
    bass = safe_normalize(_feature(data, "bass", length, fallback="energy"))
    high = safe_normalize(_feature(data, "high", length, fallback="energy"))
    percussive = safe_normalize(_feature(data, "percussive", length, fallback="onset"))
    harmonic = safe_normalize(_feature(data, "harmonic", length, fallback="pitch"))

    intensity = np.clip(
        0.38 * energy + 0.24 * onset + 0.22 * bass + 0.16 * percussive,
        0.0,
        1.0,
    )
    activity = np.clip(
        0.45 * onset + 0.30 * percussive + 0.15 * high + 0.10 * energy,
        0.0,
        1.0,
    )

    pitch_bias = (100.0 - config.pitch_range) / 2.0
    centers = (
        pitch * config.pitch_range
        + pitch_bias
        + config.amplitude_centering * energy
        + config.center_offset
    )
    harmonic_center = harmonic * config.pitch_range + pitch_bias + config.center_offset
    centers = 0.75 * centers + 0.25 * harmonic_center

    amplitudes = intensity * max(0.0, config.energy_multiplier) * 50.0
    tempo = float(data.get("tempo", 0.0) or 0.0)

    actions: list[tuple[float, float]] = []
    previous_at = 0.0
    direction = 1.0
    for i, beat_at in enumerate(beats):
        beat_at = max(float(beat_at), previous_at + 1e-6)
        interval = beat_at - previous_at
        subdivisions = _choose_subdivision(config.subdivision, float(activity[i]), interval, tempo)
        extrema_count = max(2, subdivisions * 2)

        center = float(centers[i])
        amplitude = float(amplitudes[i])
        amplitude *= 0.85 + 0.30 * float(onset[i])

        for step in range(1, extrema_count + 1):
            fraction = step / extrema_count
            at = previous_at + interval * fraction
            target = center + direction * amplitude
            actions.append((at, _overflow_position(target, config.overflow)))
            direction *= -1.0

        previous_at = beat_at

    return apply_constraints(
        actions,
        max_speed=config.max_speed,
        max_acceleration=config.max_acceleration,
        min_interval=config.min_interval,
    )
