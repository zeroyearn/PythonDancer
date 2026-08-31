"""Musical structure and gesture-driven six-axis choreography for PythonDancer.

The choreography layer sits above beat-aligned audio features and below the
per-axis physical constraint layer. It deliberately separates three concerns:

1. musical phase: continuous beat / bar / phrase coordinates;
2. section intent: intro / verse / build / chorus / drop / breakdown / outro;
3. gesture synthesis: reusable multi-axis motion primitives blended into a 6D pose.

L0 remains owned by the primary adaptive planner. This module synthesizes the
five secondary axes in normalized signal space (-1..1) and keeps a reactive
fallback for A/B comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from .features import safe_normalize

SECONDARY_AXES = ("L1", "L2", "R0", "R1", "R2")
SECTION_LABELS = ("intro", "verse", "build", "chorus", "drop", "breakdown", "outro")

SECTION_GAIN = {
    "intro": 0.52,
    "verse": 0.78,
    "build": 0.96,
    "chorus": 1.08,
    "drop": 1.20,
    "breakdown": 0.56,
    "outro": 0.46,
}

SECTION_GESTURES = {
    "intro": {"wave": 0.65, "rock": 0.25, "sway": 0.20, "circle": 0.10},
    "verse": {"sway": 0.45, "rock": 0.38, "pulse": 0.22, "wave": 0.18, "accent": 0.16},
    "build": {"circle": 0.48, "pulse": 0.36, "sway": 0.30, "spiral": 0.26, "accent": 0.26},
    "chorus": {"circle": 0.48, "spiral": 0.42, "sway": 0.38, "pulse": 0.30, "accent": 0.36},
    "drop": {"pulse": 0.56, "spiral": 0.50, "sway": 0.42, "circle": 0.32, "accent": 0.62},
    "breakdown": {"wave": 0.72, "rock": 0.42, "sway": 0.18, "spiral": 0.12},
    "outro": {"wave": 0.52, "rock": 0.20, "sway": 0.16},
}

PRESET_GESTURE_MULTIPLIERS = {
    "balanced": {"pulse": 1.0, "sway": 1.0, "rock": 1.0, "circle": 1.0, "spiral": 1.0, "wave": 1.0, "accent": 1.0},
    "rhythm": {"pulse": 1.35, "sway": 1.08, "rock": 0.92, "circle": 0.90, "spiral": 0.88, "wave": 0.68, "accent": 1.45},
    "expressive": {"pulse": 0.92, "sway": 1.12, "rock": 1.10, "circle": 1.24, "spiral": 1.36, "wave": 1.22, "accent": 0.82},
}


@dataclass(frozen=True)
class SectionSpan:
    start_beat: int
    end_beat: int
    label: str
    energy: float
    activity: float
    novelty: float

    @property
    def beat_count(self) -> int:
        return max(0, self.end_beat - self.start_beat)


@dataclass(frozen=True)
class ChoreographyAnalysis:
    sections: tuple[SectionSpan, ...]
    beats_per_bar: int
    bars_per_phrase: int
    section_bars: int

    def labels(self) -> tuple[str, ...]:
        return tuple(section.label for section in self.sections)

    def summary(self) -> str:
        if not self.sections:
            return ""
        parts: list[str] = []
        for section in self.sections:
            token = f"{section.label}:{section.start_beat}-{section.end_beat}"
            if parts and parts[-1].split(":", 1)[0] == section.label:
                parts[-1] = token
            else:
                parts.append(token)
        return " | ".join(parts)


def _feature(data: Mapping, name: str, length: int, fallback: str | None = None) -> np.ndarray:
    value = data.get(name)
    if value is None and fallback:
        value = data.get(fallback)
    if value is None:
        return np.zeros(length, dtype=np.float64)
    arr = np.asarray(value, dtype=np.float64).reshape(-1)
    if arr.size < length:
        arr = np.pad(arr, (0, length - arr.size), mode="edge" if arr.size else "constant")
    return arr[:length]


def _interp_feature(beat_times: np.ndarray, beat_values: np.ndarray, action_times: np.ndarray) -> np.ndarray:
    if action_times.size == 0:
        return np.asarray([], dtype=np.float64)
    count = min(beat_times.size, beat_values.size)
    if count == 0:
        return np.zeros(action_times.size, dtype=np.float64)
    x = np.asarray(beat_times[:count], dtype=np.float64)
    y = safe_normalize(np.asarray(beat_values[:count], dtype=np.float64))
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if x.size == 0:
        return np.zeros(action_times.size, dtype=np.float64)
    x, unique = np.unique(x, return_index=True)
    y = y[unique]
    if x.size == 1:
        return np.full(action_times.size, float(y[0]), dtype=np.float64)
    return np.interp(action_times, x, y, left=float(y[0]), right=float(y[-1]))


def _signed(values: np.ndarray) -> np.ndarray:
    return np.clip(2.0 * values - 1.0, -1.0, 1.0)


def musical_phase(
    beats: Sequence[float],
    action_times: Sequence[float],
    *,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
) -> dict[str, np.ndarray]:
    """Return continuous beat/bar/phrase phase for arbitrary action timestamps."""
    if beats_per_bar <= 0 or bars_per_phrase <= 0:
        raise ValueError("beats_per_bar and bars_per_phrase must be positive")
    beat_times = np.asarray(beats, dtype=np.float64).reshape(-1)
    beat_times = np.unique(beat_times[np.isfinite(beat_times)])
    times = np.asarray(action_times, dtype=np.float64).reshape(-1)
    if times.size == 0:
        empty = np.asarray([], dtype=np.float64)
        return {"beat_position": empty, "beat_phase": empty, "bar_phase": empty, "phrase_phase": empty, "beat_index": empty}
    if beat_times.size == 0:
        zeros = np.zeros(times.size, dtype=np.float64)
        return {"beat_position": zeros, "beat_phase": zeros, "bar_phase": zeros, "phrase_phase": zeros, "beat_index": zeros.astype(np.int64)}

    if beat_times.size > 1:
        intervals = np.diff(beat_times)
        finite_intervals = intervals[np.isfinite(intervals) & (intervals > 1e-6)]
        fallback_interval = float(np.median(finite_intervals)) if finite_intervals.size else 0.5
    else:
        fallback_interval = 0.5

    indices = np.searchsorted(beat_times, times, side="right") - 1
    indices = np.clip(indices, 0, beat_times.size - 1)
    starts = beat_times[indices]
    next_indices = np.clip(indices + 1, 0, beat_times.size - 1)
    ends = beat_times[next_indices]
    durations = ends - starts
    durations = np.where(durations > 1e-6, durations, fallback_interval)
    fractions = np.clip((times - starts) / durations, 0.0, 1.0)
    before_first = times < beat_times[0]
    fractions[before_first] = 0.0
    beat_position = indices.astype(np.float64) + fractions

    beat_phase = np.mod(beat_position, 1.0)
    bar_position = beat_position / float(beats_per_bar)
    bar_phase = np.mod(bar_position, 1.0)
    phrase_position = beat_position / float(beats_per_bar * bars_per_phrase)
    phrase_phase = np.mod(phrase_position, 1.0)
    return {
        "beat_position": beat_position,
        "beat_phase": beat_phase,
        "bar_phase": bar_phase,
        "phrase_phase": phrase_phase,
        "beat_index": np.floor(beat_position + 1e-9).astype(np.int64),
    }


def _window_metrics(data: Mapping, beat_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    energy = safe_normalize(_feature(data, "energy", beat_count))
    onset = safe_normalize(_feature(data, "onset", beat_count, "energy"))
    bass = safe_normalize(_feature(data, "bass", beat_count, "energy"))
    high = safe_normalize(_feature(data, "high", beat_count, "energy"))
    harmonic = safe_normalize(_feature(data, "harmonic", beat_count, "pitch"))
    percussive = safe_normalize(_feature(data, "percussive", beat_count, "onset"))
    mid = safe_normalize(_feature(data, "mid", beat_count, "energy"))

    energy_score = np.clip(0.42 * energy + 0.25 * bass + 0.18 * harmonic + 0.15 * mid, 0.0, 1.0)
    activity_score = np.clip(0.48 * onset + 0.34 * percussive + 0.18 * high, 0.0, 1.0)
    matrix = np.vstack((energy, onset, bass, mid, high, harmonic, percussive)).T
    if beat_count > 1:
        novelty = np.mean(np.abs(np.diff(matrix, axis=0)), axis=1)
        novelty = np.concatenate(([novelty[0]], novelty))
    else:
        novelty = np.zeros(beat_count, dtype=np.float64)
    novelty = safe_normalize(novelty)
    combined = np.clip(0.58 * energy_score + 0.42 * activity_score, 0.0, 1.0)
    return energy_score, activity_score, novelty, combined


def detect_sections(
    data: Mapping,
    *,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    section_bars: int = 4,
) -> ChoreographyAnalysis:
    """Detect coarse phrase-level song sections using beat-aligned dynamics/novelty.

    This is intentionally deterministic and lightweight: it is a musical-intent
    heuristic, not a semantic music classifier. Boundaries are phrase aligned.
    """
    if beats_per_bar <= 0 or bars_per_phrase <= 0 or section_bars <= 0:
        raise ValueError("musical grid values must be positive")
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    beat_count = beats.size
    if beat_count == 0:
        return ChoreographyAnalysis((), beats_per_bar, bars_per_phrase, section_bars)

    energy, activity, novelty, combined = _window_metrics(data, beat_count)
    window = max(beats_per_bar, beats_per_bar * section_bars)
    raw: list[dict[str, float | int]] = []
    for start in range(0, beat_count, window):
        end = min(beat_count, start + window)
        e = float(np.mean(energy[start:end]))
        a = float(np.mean(activity[start:end]))
        n = float(np.mean(novelty[start:end]))
        c = float(np.mean(combined[start:end]))
        half = max(1, (end - start) // 2)
        first = float(np.mean(combined[start:start + half]))
        second = float(np.mean(combined[max(start, end - half):end]))
        slope = second - first
        raw.append({"start": start, "end": end, "energy": e, "activity": a, "novelty": n, "combined": c, "slope": slope})

    combined_windows = np.asarray([float(item["combined"]) for item in raw], dtype=np.float64)
    activity_windows = np.asarray([float(item["activity"]) for item in raw], dtype=np.float64)
    novelty_windows = np.asarray([float(item["novelty"]) for item in raw], dtype=np.float64)
    q_low = float(np.quantile(combined_windows, 0.30)) if raw else 0.0
    q_high = float(np.quantile(combined_windows, 0.70)) if raw else 1.0
    med = float(np.median(combined_windows)) if raw else 0.5
    activity_med = float(np.median(activity_windows)) if raw else 0.5
    novelty_high = float(np.quantile(novelty_windows, 0.65)) if raw else 0.5

    spans: list[SectionSpan] = []
    for i, item in enumerate(raw):
        e = float(item["energy"])
        a = float(item["activity"])
        n = float(item["novelty"])
        c = float(item["combined"])
        slope = float(item["slope"])
        first = i == 0
        last = i == len(raw) - 1

        if first and c <= med * 0.95:
            label = "intro"
        elif last and c <= med * 0.90:
            label = "outro"
        elif c <= q_low and a <= activity_med * 1.05:
            label = "breakdown"
        elif slope >= 0.10 and (a >= activity_med * 0.90 or n >= novelty_high):
            label = "build"
        elif c >= q_high and a >= max(activity_med, 0.55):
            label = "drop" if n >= novelty_high or a >= 0.72 else "chorus"
        elif c >= med * 1.02 and a >= activity_med * 0.92:
            label = "chorus"
        else:
            label = "verse"

        spans.append(SectionSpan(int(item["start"]), int(item["end"]), label, e, a, n))

    return ChoreographyAnalysis(tuple(spans), beats_per_bar, bars_per_phrase, section_bars)


def _labels_for_actions(analysis: ChoreographyAnalysis, beat_indices: np.ndarray) -> np.ndarray:
    if beat_indices.size == 0:
        return np.asarray([], dtype=object)
    if not analysis.sections:
        return np.asarray(["verse"] * beat_indices.size, dtype=object)
    labels = np.asarray(["verse"] * beat_indices.size, dtype=object)
    for section in analysis.sections:
        mask = (beat_indices >= section.start_beat) & (beat_indices < section.end_beat)
        labels[mask] = section.label
    labels[beat_indices >= analysis.sections[-1].end_beat] = analysis.sections[-1].label
    return labels


def _gesture_library(
    phases: Mapping[str, np.ndarray],
    features: Mapping[str, np.ndarray],
    stroke: np.ndarray,
) -> dict[str, dict[str, np.ndarray]]:
    beat = 2.0 * np.pi * phases["beat_phase"]
    bar = 2.0 * np.pi * phases["bar_phase"]
    phrase = 2.0 * np.pi * phases["phrase_phase"]
    beat_index = phases["beat_index"].astype(np.int64)
    onset = features["onset"]
    percussive = features["percussive"]
    energy = features["energy"]
    bass_s = _signed(features["bass"])
    pitch_s = _signed(features["pitch"])
    high_s = _signed(features["high"])
    harmonic_s = _signed(features["harmonic"])
    activity = np.clip(0.55 * onset + 0.45 * percussive, 0.0, 1.0)
    dynamic = 0.40 + 0.60 * energy
    direction = np.where(beat_index % 2 == 0, 1.0, -1.0)
    accent_env = np.clip(0.58 * onset + 0.42 * percussive, 0.0, 1.0)

    zero = np.zeros_like(beat, dtype=np.float64)

    def pose(**kwargs: np.ndarray) -> dict[str, np.ndarray]:
        return {axis: np.asarray(kwargs.get(axis, zero), dtype=np.float64) for axis in SECONDARY_AXES}

    return {
        "pulse": pose(
            L1=0.28 * np.sin(beat) * dynamic + 0.18 * bass_s,
            L2=0.12 * np.sin(2.0 * beat) * activity,
            R0=0.62 * np.sin(beat + np.pi / 2.0) * (0.55 + 0.45 * activity) + 0.12 * pitch_s,
            R1=-0.34 * np.sin(beat) * accent_env,
            R2=0.10 * np.cos(beat) * dynamic,
        ),
        "sway": pose(
            L1=0.10 * np.cos(bar),
            L2=np.sin(bar) * (0.65 + 0.35 * activity),
            R0=0.18 * np.sin(bar + np.pi / 2.0),
            R1=-0.76 * np.sin(bar),
            R2=0.08 * np.cos(bar),
        ),
        "rock": pose(
            L1=np.cos(bar) * (0.70 + 0.30 * dynamic),
            L2=0.10 * np.sin(bar),
            R0=0.14 * np.sin(bar),
            R1=-0.10 * np.sin(bar),
            R2=-0.84 * np.cos(bar) + 0.12 * harmonic_s,
        ),
        "circle": pose(
            L1=np.cos(bar) * dynamic,
            L2=np.sin(bar) * dynamic,
            R0=0.20 * np.sin(2.0 * bar) + 0.10 * pitch_s,
            R1=-0.46 * np.sin(bar),
            R2=0.46 * np.cos(bar),
        ),
        "spiral": pose(
            L1=0.26 * np.cos(phrase),
            L2=0.46 * np.sin(bar + 0.35 * np.sin(phrase)),
            R0=np.sin(2.0 * phrase) * (0.70 + 0.30 * dynamic) + 0.18 * pitch_s,
            R1=-0.30 * np.sin(bar + phrase),
            R2=0.56 * np.cos(phrase) + 0.12 * harmonic_s,
        ),
        "wave": pose(
            L1=0.18 * np.sin(phrase + np.pi / 2.0),
            L2=0.24 * np.sin(phrase),
            R0=0.18 * np.sin(phrase + high_s * 0.4),
            R1=np.sin(phrase),
            R2=np.sin(phrase + np.pi / 2.0),
        ),
        "accent": pose(
            L1=0.28 * direction * accent_env * np.sign(stroke + 1e-9),
            L2=0.38 * direction * accent_env,
            R0=0.76 * direction * accent_env + 0.12 * high_s,
            R1=-0.52 * direction * accent_env,
            R2=0.22 * direction * accent_env,
        ),
    }


def reactive_signals(
    features: Mapping[str, np.ndarray],
    phases: Mapping[str, np.ndarray],
    stroke: np.ndarray,
    *,
    preset: str = "balanced",
) -> dict[str, np.ndarray]:
    """Compatibility version of the original secondary-axis reactive formulas."""
    n = stroke.size
    legacy_phase = np.arange(n, dtype=np.float64) * np.pi
    onset = features["onset"]
    percussive = features["percussive"]
    activity = np.clip(0.55 * onset + 0.45 * percussive, 0.0, 1.0)
    bass_s = _signed(features["bass"])
    mid_s = _signed(features["mid"])
    high_s = _signed(features["high"])
    pitch_s = _signed(features["pitch"])
    harmonic_s = _signed(features["harmonic"])
    perc_s = _signed(percussive)
    pitch_trend = np.gradient(features["pitch"]) if n > 1 else np.zeros(n, dtype=np.float64)

    surge = 0.46 * np.sin(legacy_phase * 0.50 + 0.35 * bass_s) + 0.29 * bass_s + 0.15 * harmonic_s + 0.10 * stroke
    sway = 0.48 * np.sin(legacy_phase * 0.75 + np.pi / 2.0) * (0.55 + 0.45 * activity) + 0.24 * high_s + 0.18 * mid_s + 0.10 * np.tanh(pitch_trend * 4.0)
    twist = 0.44 * np.sin(legacy_phase * 0.50 + np.pi / 2.0) + 0.34 * pitch_s + 0.14 * high_s + 0.08 * stroke
    roll = -0.42 * np.sin(legacy_phase * 0.75 + np.pi / 2.0) + 0.28 * perc_s + 0.18 * stroke + 0.12 * high_s
    pitch_axis = 0.46 * np.sin(legacy_phase * 0.25) + 0.30 * harmonic_s + 0.14 * pitch_s + 0.10 * np.tanh(pitch_trend * 5.0)

    if preset == "rhythm":
        surge = 0.75 * surge + 0.25 * bass_s
        sway = 0.65 * sway + 0.35 * perc_s
        twist = 0.75 * twist + 0.25 * perc_s
        roll = 0.60 * roll + 0.40 * perc_s
        pitch_axis *= 0.8
    elif preset == "expressive":
        surge = 0.85 * surge + 0.15 * harmonic_s
        sway = 0.85 * sway + 0.15 * pitch_s
        twist = 0.75 * twist + 0.25 * pitch_s
        roll = 0.85 * roll + 0.15 * mid_s
        pitch_axis = 0.75 * pitch_axis + 0.25 * harmonic_s

    return {"L1": surge, "L2": sway, "R0": twist, "R1": roll, "R2": pitch_axis}


def _smooth_signal(values: np.ndarray) -> np.ndarray:
    if values.size < 3:
        return values
    padded = np.pad(values, (1, 1), mode="edge")
    return 0.20 * padded[:-2] + 0.60 * padded[1:-1] + 0.20 * padded[2:]


def synthesize_choreography_signals(
    data: Mapping,
    action_times: Sequence[float],
    l0_positions: Sequence[float],
    *,
    preset: str = "balanced",
    gesture_strength: float = 1.0,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    section_bars: int = 4,
) -> tuple[dict[str, np.ndarray], ChoreographyAnalysis]:
    """Generate section-aware, gesture-driven normalized secondary-axis signals."""
    if preset not in PRESET_GESTURE_MULTIPLIERS:
        raise ValueError(f"unknown choreography preset: {preset}")
    if not np.isfinite(gesture_strength) or gesture_strength < 0:
        raise ValueError("gesture_strength must be finite and non-negative")

    times = np.asarray(action_times, dtype=np.float64).reshape(-1)
    l0 = np.asarray(l0_positions, dtype=np.float64).reshape(-1)
    n = min(times.size, l0.size)
    times, l0 = times[:n], l0[:n]
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    beat_count = beats.size
    phases = musical_phase(beats, times, beats_per_bar=beats_per_bar, bars_per_phrase=bars_per_phrase)
    analysis = detect_sections(data, beats_per_bar=beats_per_bar, bars_per_phrase=bars_per_phrase, section_bars=section_bars)
    if n == 0:
        return {axis: np.asarray([], dtype=np.float64) for axis in SECONDARY_AXES}, analysis

    features = {
        name: _interp_feature(beats, _feature(data, name, beat_count, fallback), times)
        for name, fallback in (
            ("energy", None), ("onset", "energy"), ("bass", "energy"), ("mid", "energy"),
            ("high", "energy"), ("pitch", None), ("harmonic", "pitch"), ("percussive", "onset"),
        )
    }
    stroke = np.clip((l0 - 50.0) / 50.0, -1.0, 1.0)
    reactive = reactive_signals(features, phases, stroke, preset=preset)
    gestures = _gesture_library(phases, features, stroke)
    labels = _labels_for_actions(analysis, phases["beat_index"])
    multipliers = PRESET_GESTURE_MULTIPLIERS[preset]

    gesture_mix = {axis: np.zeros(n, dtype=np.float64) for axis in SECONDARY_AXES}
    section_gain = np.ones(n, dtype=np.float64)
    for label in SECTION_LABELS:
        mask = labels == label
        if not np.any(mask):
            continue
        section_gain[mask] = SECTION_GAIN[label]
        weights = SECTION_GESTURES[label]
        denom = sum(abs(weight * multipliers.get(name, 1.0)) for name, weight in weights.items()) or 1.0
        for gesture_name, base_weight in weights.items():
            weight = base_weight * multipliers.get(gesture_name, 1.0)
            gesture = gestures[gesture_name]
            for axis in SECONDARY_AXES:
                gesture_mix[axis][mask] += (weight / denom) * gesture[axis][mask]

    results: dict[str, np.ndarray] = {}
    for axis in SECONDARY_AXES:
        # Reactive detail preserves local audio coupling while gesture intent owns
        # the larger musical movement.
        signal = 0.34 * reactive[axis] + 0.66 * gesture_strength * gesture_mix[axis]
        signal *= section_gain
        results[axis] = signal

    # Explicit cross-axis coupling creates coherent 6D poses instead of five
    # unrelated curves: sway counter-roll, surge counter-pitch, and twist/stroke.
    results["R1"] = results["R1"] - 0.24 * results["L2"]
    results["R2"] = results["R2"] - 0.20 * results["L1"]
    results["R0"] = results["R0"] + 0.12 * stroke
    results["L1"] = results["L1"] - 0.08 * np.abs(stroke) * _signed(features["bass"])

    for axis in SECONDARY_AXES:
        results[axis] = np.clip(_smooth_signal(results[axis]), -1.0, 1.0)
    return results, analysis
