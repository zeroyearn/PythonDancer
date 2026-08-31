"""Profile- and stem-aware choreography synthesis built on the 2.2 primitives."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from .choreography import (
    PRESET_GESTURE_MULTIPLIERS,
    SECTION_GAIN,
    SECTION_GESTURES,
    SECTION_LABELS,
    SECONDARY_AXES,
    _feature,
    _gesture_library,
    _interp_feature,
    _labels_for_actions,
    _signed,
    detect_sections,
    musical_phase,
    reactive_signals,
)
from .style import ChoreographyProfile


def _blend(base: np.ndarray, extra: np.ndarray, amount: float) -> np.ndarray:
    if base.size == 0 or extra.size != base.size or amount <= 0:
        return base
    amount = float(np.clip(amount, 0.0, 0.85))
    return np.clip((1.0 - amount) * base + amount * extra, 0.0, 1.0)


def _profile_smooth(values: np.ndarray, alpha: float) -> np.ndarray:
    if values.size < 3 or alpha <= 0:
        return values
    alpha = float(np.clip(alpha, 0.0, 0.49))
    center = 1.0 - 2.0 * alpha
    padded = np.pad(values, (1, 1), mode="edge")
    return alpha * padded[:-2] + center * padded[1:-1] + alpha * padded[2:]


def synthesize_profiled_choreography(
    data: Mapping,
    action_times: Sequence[float],
    l0_positions: Sequence[float],
    *,
    preset: str = "balanced",
    gesture_strength: float = 1.0,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    section_bars: int = 4,
    profile: ChoreographyProfile | None = None,
):
    """Generate secondary axes with optional learned profile and separated stems."""
    profile = profile or ChoreographyProfile()
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

    stem_amount = float(np.clip(profile.stem_influence, 0.0, 3.0))
    if stem_amount > 0 and beat_count:
        stem_keys = {
            "drums_energy": "stem_drums_energy",
            "drums_onset": "stem_drums_onset",
            "bass_energy": "stem_bass_energy",
            "vocals_energy": "stem_vocals_energy",
            "vocals_pitch": "stem_vocals_pitch",
            "other_energy": "stem_other_energy",
        }
        stem = {
            name: _interp_feature(beats, _feature(data, key, beat_count), times)
            for name, key in stem_keys.items()
            if key in data
        }
        features["onset"] = _blend(features["onset"], stem.get("drums_onset", features["onset"]), 0.42 * stem_amount)
        features["percussive"] = _blend(features["percussive"], stem.get("drums_energy", features["percussive"]), 0.36 * stem_amount)
        features["bass"] = _blend(features["bass"], stem.get("bass_energy", features["bass"]), 0.55 * stem_amount)
        features["pitch"] = _blend(features["pitch"], stem.get("vocals_pitch", features["pitch"]), 0.48 * stem_amount)
        features["harmonic"] = _blend(features["harmonic"], stem.get("vocals_energy", features["harmonic"]), 0.30 * stem_amount)
        features["energy"] = _blend(features["energy"], stem.get("other_energy", features["energy"]), 0.16 * stem_amount)

    stroke = np.clip((l0 - 50.0) / 50.0, -1.0, 1.0)
    reactive = reactive_signals(features, phases, stroke, preset=preset)
    gestures = _gesture_library(phases, features, stroke)
    labels = _labels_for_actions(analysis, phases["beat_index"])
    preset_multipliers = PRESET_GESTURE_MULTIPLIERS[preset]

    gesture_mix = {axis: np.zeros(n, dtype=np.float64) for axis in SECONDARY_AXES}
    section_gain = np.ones(n, dtype=np.float64)
    for label in SECTION_LABELS:
        mask = labels == label
        if not np.any(mask):
            continue
        section_gain[mask] = SECTION_GAIN[label] * profile.section_multiplier(label)
        weights = SECTION_GESTURES[label]
        weighted = {
            name: base * preset_multipliers.get(name, 1.0) * profile.gesture_multiplier(name)
            for name, base in weights.items()
        }
        denom = sum(abs(value) for value in weighted.values()) or 1.0
        for gesture_name, weight in weighted.items():
            gesture = gestures[gesture_name]
            for axis in SECONDARY_AXES:
                gesture_mix[axis][mask] += (weight / denom) * gesture[axis][mask]

    reactive_mix = float(profile.reactive_mix)
    gesture_mix_amount = 1.0 - reactive_mix
    results: dict[str, np.ndarray] = {}
    for axis in SECONDARY_AXES:
        signal = reactive_mix * reactive[axis] + gesture_mix_amount * gesture_strength * gesture_mix[axis]
        results[axis] = signal * section_gain

    results["R1"] = results["R1"] - 0.24 * profile.coupling_multiplier("sway_roll") * results["L2"]
    results["R2"] = results["R2"] - 0.20 * profile.coupling_multiplier("surge_pitch") * results["L1"]
    results["R0"] = results["R0"] + 0.12 * profile.coupling_multiplier("stroke_twist") * stroke
    results["L1"] = results["L1"] - 0.08 * profile.coupling_multiplier("stroke_bass_l1") * np.abs(stroke) * _signed(features["bass"])

    for axis in SECONDARY_AXES:
        results[axis] = np.clip(_profile_smooth(results[axis], profile.smoothing), -1.0, 1.0)
    return results, analysis
