"""Serializable choreography profiles and reference-funscript style learning."""
from __future__ import annotations

from dataclasses import dataclass, field
from json import dump, load
from pathlib import Path
from typing import Mapping

import numpy as np

SECONDARY_AXES = ("L1", "L2", "R0", "R1", "R2")
GESTURE_NAMES = ("pulse", "sway", "rock", "circle", "spiral", "wave", "accent")
SECTION_LABELS = ("intro", "verse", "build", "chorus", "drop", "breakdown", "outro")
BUNDLE_SUFFIXES = {
    "L0": "",
    "L1": ".surge",
    "L2": ".sway",
    "R0": ".twist",
    "R1": ".roll",
    "R2": ".pitch",
}
REFERENCE_BASE_AMPLITUDE = {"L1": 17.0, "L2": 18.0, "R0": 30.0, "R1": 20.0, "R2": 19.0}


def _finite(value: float, default: float) -> float:
    value = float(value)
    return value if np.isfinite(value) else float(default)


def _bounded_map(values: Mapping[str, float] | None, allowed: tuple[str, ...], *, low: float = 0.0, high: float = 4.0) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in dict(values or {}).items():
        key = str(key)
        if key not in allowed:
            continue
        number = _finite(value, 1.0)
        result[key] = float(np.clip(number, low, high))
    return result


@dataclass(frozen=True)
class ChoreographyProfile:
    """Portable style overrides applied on top of the selected built-in preset."""

    name: str = "default"
    axis_scale: Mapping[str, float] = field(default_factory=dict)
    gesture_gain: Mapping[str, float] = field(default_factory=dict)
    section_gain: Mapping[str, float] = field(default_factory=dict)
    coupling_gain: Mapping[str, float] = field(default_factory=dict)
    reactive_mix: float = 0.34
    smoothing: float = 0.20
    stem_influence: float = 1.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "name", str(self.name or "default"))
        object.__setattr__(self, "axis_scale", _bounded_map(self.axis_scale, SECONDARY_AXES, low=0.0, high=3.0))
        object.__setattr__(self, "gesture_gain", _bounded_map(self.gesture_gain, GESTURE_NAMES, low=0.0, high=3.0))
        object.__setattr__(self, "section_gain", _bounded_map(self.section_gain, SECTION_LABELS, low=0.0, high=3.0))
        coupling_keys = ("sway_roll", "surge_pitch", "stroke_twist", "stroke_bass_l1")
        object.__setattr__(self, "coupling_gain", _bounded_map(self.coupling_gain, coupling_keys, low=0.0, high=3.0))
        object.__setattr__(self, "reactive_mix", float(np.clip(_finite(self.reactive_mix, 0.34), 0.0, 1.0)))
        object.__setattr__(self, "smoothing", float(np.clip(_finite(self.smoothing, 0.20), 0.0, 0.49)))
        object.__setattr__(self, "stem_influence", float(np.clip(_finite(self.stem_influence, 1.0), 0.0, 3.0)))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def axis_multiplier(self, axis: str) -> float:
        return float(self.axis_scale.get(axis, 1.0))

    def gesture_multiplier(self, gesture: str) -> float:
        return float(self.gesture_gain.get(gesture, 1.0))

    def section_multiplier(self, section: str) -> float:
        return float(self.section_gain.get(section, 1.0))

    def coupling_multiplier(self, coupling: str) -> float:
        return float(self.coupling_gain.get(coupling, 1.0))

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "name": self.name,
            "axis_scale": dict(self.axis_scale),
            "gesture_gain": dict(self.gesture_gain),
            "section_gain": dict(self.section_gain),
            "coupling_gain": dict(self.coupling_gain),
            "reactive_mix": self.reactive_mix,
            "smoothing": self.smoothing,
            "stem_influence": self.stem_influence,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "ChoreographyProfile":
        return cls(
            name=payload.get("name", "default"),
            axis_scale=payload.get("axis_scale", {}),
            gesture_gain=payload.get("gesture_gain", {}),
            section_gain=payload.get("section_gain", {}),
            coupling_gain=payload.get("coupling_gain", {}),
            reactive_mix=payload.get("reactive_mix", 0.34),
            smoothing=payload.get("smoothing", 0.20),
            stem_influence=payload.get("stem_influence", 1.0),
            metadata=payload.get("metadata", {}),
        )


def load_profile(path: str | Path) -> ChoreographyProfile:
    with Path(path).open("r", encoding="utf8") as handle:
        payload = load(handle)
    if not isinstance(payload, dict):
        raise ValueError("choreography profile must contain a JSON object")
    return ChoreographyProfile.from_dict(payload)


def save_profile(path: str | Path, profile: ChoreographyProfile) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf8") as handle:
        dump(profile.to_dict(), handle, indent=2)
    return output


def _bundle_paths(prefix: str | Path) -> dict[str, Path]:
    path = Path(prefix)
    text = str(path)
    for suffix in BUNDLE_SUFFIXES.values():
        ending = suffix + ".funscript"
        if suffix and text.lower().endswith(ending):
            text = text[: -len(ending)]
            break
    if text.lower().endswith(".funscript"):
        text = text[: -len(".funscript")]
    return {axis: Path(text + suffix + ".funscript") for axis, suffix in BUNDLE_SUFFIXES.items()}


def _load_actions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if not path.exists():
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    import json

    payload = json.loads(path.read_text(encoding="utf8"))
    rows = payload.get("actions", []) if isinstance(payload, dict) else []
    valid = []
    for row in rows:
        try:
            at = float(row["at"]) / 1000.0
            pos = float(row["pos"])
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(at) and np.isfinite(pos):
            valid.append((max(0.0, at), float(np.clip(pos, 0.0, 100.0))))
    if not valid:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    valid.sort()
    return np.asarray([row[0] for row in valid]), np.asarray([row[1] for row in valid])


def _sample(times: np.ndarray, positions: np.ndarray, grid: np.ndarray) -> np.ndarray:
    if grid.size == 0:
        return np.asarray([], dtype=np.float64)
    if times.size == 0:
        return np.full(grid.size, 50.0, dtype=np.float64)
    if times.size == 1:
        return np.full(grid.size, float(positions[0]), dtype=np.float64)
    return np.interp(grid, times, positions, left=float(positions[0]), right=float(positions[-1]))


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 3 or b.size != a.size or np.std(a) < 1e-8 or np.std(b) < 1e-8:
        return 0.0
    value = float(np.corrcoef(a, b)[0, 1])
    return value if np.isfinite(value) else 0.0


def learn_profile_from_bundle(prefix: str | Path, *, name: str | None = None) -> ChoreographyProfile:
    """Infer a compact motion style from an existing MultiFunPlayer bundle.

    The learner extracts statistical movement character only. Timestamps and
    positions are never copied into the new song's choreography.
    """
    paths = _bundle_paths(prefix)
    loaded = {axis: _load_actions(path) for axis, path in paths.items()}
    present = [axis for axis, (times, _) in loaded.items() if times.size]
    if "L0" not in present:
        raise ValueError(f"reference bundle is missing L0: {paths['L0']}")

    duration = max((float(times[-1]) for times, _ in loaded.values() if times.size), default=0.0)
    if duration <= 0:
        raise ValueError("reference bundle contains no usable timeline")
    grid = np.arange(0.0, duration + 1e-9, 0.05, dtype=np.float64)
    sampled = {axis: _sample(*loaded[axis], grid) for axis in loaded}
    centers = {axis: float(np.median(values)) if values.size else 50.0 for axis, values in sampled.items()}
    signals = {axis: values - centers[axis] for axis, values in sampled.items()}

    amplitudes: dict[str, float] = {}
    activity: dict[str, float] = {}
    for axis in SECONDARY_AXES:
        signal = signals[axis]
        robust_amp = float(np.quantile(np.abs(signal), 0.90)) if signal.size else 0.0
        baseline = REFERENCE_BASE_AMPLITUDE[axis]
        amplitudes[axis] = float(np.clip(robust_amp / baseline, 0.20, 2.50)) if axis in present else 1.0
        if signal.size > 1 and robust_amp > 1e-6:
            speed = np.abs(np.diff(signal)) / 0.05
            activity[axis] = float(np.clip(np.quantile(speed, 0.75) / max(robust_amp * 8.0, 1.0), 0.0, 1.0))
        else:
            activity[axis] = 0.0

    mean_activity = float(np.mean(list(activity.values())))
    smoothness = float(np.clip(1.0 - mean_activity, 0.0, 1.0))
    gesture_gain = {
        "pulse": float(np.clip(0.75 + 0.90 * activity["R0"], 0.4, 1.8)),
        "accent": float(np.clip(0.65 + 1.15 * mean_activity, 0.4, 1.8)),
        "wave": float(np.clip(0.70 + 0.80 * smoothness, 0.4, 1.8)),
        "rock": float(np.clip(0.70 + 0.35 * amplitudes["L1"] + 0.35 * amplitudes["R2"], 0.4, 1.8)),
        "sway": float(np.clip(0.65 + 0.55 * amplitudes["L2"], 0.4, 1.8)),
        "circle": float(np.clip(0.60 + 0.30 * amplitudes["L1"] + 0.30 * amplitudes["L2"], 0.4, 1.8)),
        "spiral": float(np.clip(0.55 + 0.35 * amplitudes["R0"] + 0.25 * amplitudes["L2"], 0.4, 1.8)),
    }

    coupling_gain = {
        "sway_roll": float(np.clip(0.75 + max(0.0, -_correlation(signals["L2"], signals["R1"])), 0.5, 1.75)),
        "surge_pitch": float(np.clip(0.75 + max(0.0, -_correlation(signals["L1"], signals["R2"])), 0.5, 1.75)),
        "stroke_twist": float(np.clip(0.65 + 0.75 * abs(_correlation(signals["L0"], signals["R0"])), 0.5, 1.75)),
        "stroke_bass_l1": 1.0,
    }

    return ChoreographyProfile(
        name=name or f"learned:{Path(prefix).stem}",
        axis_scale=amplitudes,
        gesture_gain=gesture_gain,
        coupling_gain=coupling_gain,
        reactive_mix=float(np.clip(0.18 + 0.42 * mean_activity, 0.15, 0.60)),
        smoothing=float(np.clip(0.10 + 0.24 * smoothness, 0.08, 0.34)),
        metadata={
            "source_bundle": str(prefix),
            "duration": duration,
            "present_axes": present,
            "reference_centers": centers,
            "learner": "PythonDancer statistical reference style v1",
        },
    )
