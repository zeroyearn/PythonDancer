"""Independent per-axis timeline planning for PythonDancer 2.6.

2.5 and earlier generated secondary axes on L0's keyframe timestamps. This
planner gives every secondary axis its own musically-derived event schedule,
then samples the existing choreography synthesizer at those timestamps. The
result preserves the proven gesture/style layer while allowing drums, bass and
vocals to drive different temporal densities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .choreo_profile import synthesize_profiled_choreography
from .features import safe_normalize
from .intent import IntentEnvelope
from .motion import apply_constraints
from .style import ChoreographyProfile

SECONDARY_AXES = ("L1", "L2", "R0", "R1", "R2")
AXIS_FEATURE = {
    "L1": ("stem_bass_energy", "bass"),
    "L2": ("stem_drums_hihat", "high"),
    "R0": ("stem_vocals_pitch_motion", "pitch"),
    "R1": ("stem_drums_snare", "stem_drums_onset"),
    "R2": ("stem_vocals_energy", "harmonic"),
}
AXIS_SUBDIVISION = {"L1": 1, "L2": 2, "R0": 1, "R1": 2, "R2": 1}
AXIS_BASE_STRIDE = {"L1": 1, "L2": 1, "R0": 2, "R1": 1, "R2": 2}


@dataclass(frozen=True)
class IndependentAxisConfig:
    enabled: bool = True
    min_interval: float = 0.05
    density: float = 1.0
    accent_threshold: float = 0.62
    include_section_boundaries: bool = True

    def __post_init__(self):
        if not np.isfinite(self.min_interval) or self.min_interval <= 0:
            raise ValueError("independent-axis min_interval must be positive")
        if not np.isfinite(self.density) or self.density <= 0:
            raise ValueError("independent-axis density must be positive")
        object.__setattr__(self, "accent_threshold", float(np.clip(self.accent_threshold, 0.0, 1.0)))


def _feature(data: Mapping, primary: str, fallback: str, count: int) -> np.ndarray:
    value = data.get(primary)
    if value is None:
        value = data.get(fallback)
    if value is None:
        return np.zeros(count, dtype=np.float64)
    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.size < count:
        arr = np.pad(arr, (0, count - arr.size), mode="edge" if arr.size else "constant")
    return safe_normalize(arr[:count])


def _dedupe_times(values: Sequence[float], min_interval: float, duration: float) -> np.ndarray:
    ordered = sorted(float(np.clip(value, 0.0, duration)) for value in values if np.isfinite(value))
    result: list[float] = []
    for value in ordered:
        if not result or value - result[-1] >= min_interval - 1e-9:
            result.append(value)
        elif value > result[-1]:
            result[-1] = value
    if not result or result[0] > min_interval:
        result.insert(0, 0.0)
    if duration > 0 and (not result or duration - result[-1] >= min_interval):
        result.append(float(duration))
    return np.asarray(result, dtype=np.float64)


def axis_event_times(
    data: Mapping,
    axis: str,
    duration: float,
    *,
    config: IndependentAxisConfig,
    section_times: Sequence[float] = (),
) -> np.ndarray:
    if axis not in SECONDARY_AXES:
        raise ValueError(f"unsupported independent axis: {axis}")
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    beats = beats[np.isfinite(beats)]
    if beats.size == 0:
        step = max(config.min_interval, .5 / config.density)
        return _dedupe_times(np.arange(0.0, max(0.0, duration) + step, step), config.min_interval, duration)

    score = _feature(data, *AXIS_FEATURE[axis], beats.size)
    stride = max(1, int(round(AXIS_BASE_STRIDE[axis] / max(config.density, .25))))
    subdivisions = AXIS_SUBDIVISION[axis]
    values: list[float] = [0.0]
    for index, beat in enumerate(beats):
        if index % stride == 0:
            values.append(float(beat))
        if index + 1 >= beats.size:
            continue
        local = float(score[min(index, score.size - 1)]) if score.size else 0.0
        if local >= config.accent_threshold and subdivisions > 1:
            next_beat = float(beats[index + 1])
            for part in range(1, subdivisions):
                values.append(float(beat + (next_beat - beat) * part / subdivisions))
        # R0/R2 get extra phrase-scale inflection points only when vocals move.
        if axis in ("R0", "R2") and local > .78 and index % 2 == 1:
            values.append(float((beat + beats[index + 1]) * .5))

    if config.include_section_boundaries:
        values.extend(float(value) for value in section_times)
    values.append(float(duration))
    return _dedupe_times(values, config.min_interval, duration)


def _sample_l0(l0: Sequence[tuple[float, float]], times: np.ndarray) -> np.ndarray:
    if times.size == 0:
        return np.asarray([], dtype=np.float64)
    if not l0:
        return np.full(times.size, 50.0, dtype=np.float64)
    x = np.asarray([item[0] for item in l0], dtype=np.float64)
    y = np.asarray([item[1] for item in l0], dtype=np.float64)
    if x.size == 1:
        return np.full(times.size, float(y[0]), dtype=np.float64)
    return np.interp(times, x, y, left=float(y[0]), right=float(y[-1]))


def _intent_gain(axis: str, sampled: Mapping[str, np.ndarray]) -> np.ndarray:
    intensity = sampled["intensity"]
    aggression = sampled["aggression"]
    flow = sampled["flow"]
    complexity = sampled["complexity"]
    rotation = sampled["rotation_bias"]
    translation = sampled["translation_bias"]
    accents = sampled["accent_density"]
    if axis in ("L1", "L2"):
        gain = .68 + .45 * intensity + .28 * translation + .10 * complexity
    elif axis == "R1":
        gain = .62 + .34 * aggression + .24 * accents + .20 * rotation
    else:
        gain = .64 + .34 * flow + .28 * rotation + .16 * complexity
    return np.clip(gain, .45, 1.55)


def plan_independent_secondary_axes(
    data: Mapping,
    l0: Sequence[tuple[float, float]],
    *,
    preset: str,
    amplitudes: Mapping[str, float],
    strength: float,
    neutral: float,
    gesture_strength: float,
    beats_per_bar: int,
    bars_per_phrase: int,
    section_bars: int,
    profile: ChoreographyProfile | None,
    intent: IntentEnvelope,
    axis_config: IndependentAxisConfig,
    limits: Mapping[str, tuple[float, float]],
    section_times: Sequence[float] = (),
) -> dict[str, list[tuple[float, float]]]:
    duration = max((float(at) for at, _ in l0), default=0.0)
    profile = profile or ChoreographyProfile()
    neutral = float(np.clip(neutral, 0.0, 100.0))
    result: dict[str, list[tuple[float, float]]] = {}

    for axis in SECONDARY_AXES:
        times = axis_event_times(data, axis, duration, config=axis_config, section_times=section_times)
        l0_positions = _sample_l0(l0, times)
        signals, _ = synthesize_profiled_choreography(
            data,
            times,
            l0_positions,
            preset=preset,
            gesture_strength=gesture_strength,
            beats_per_bar=beats_per_bar,
            bars_per_phrase=bars_per_phrase,
            section_bars=section_bars,
            profile=profile,
        )
        sampled_intent = intent.sample(times)
        gain = _intent_gain(axis, sampled_intent)
        target = np.clip(
            neutral + float(amplitudes[axis]) * profile.axis_multiplier(axis) * float(strength) * gain * np.clip(signals[axis], -1.0, 1.0),
            0.0,
            100.0,
        )
        max_speed, max_accel = limits[axis]
        result[axis] = apply_constraints(
            zip(times.tolist(), target.tolist()),
            max_speed=max_speed,
            max_acceleration=max_accel,
            min_interval=axis_config.min_interval,
        )
    return result
