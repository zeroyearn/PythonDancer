"""SR6/OSR6-style six-axis motion planning and funscript bundle export."""
from __future__ import annotations

from dataclasses import dataclass, field
from json import dump
from pathlib import Path
from typing import Mapping

import numpy as np

from .features import safe_normalize
from .motion import MotionConfig, apply_constraints, plan_motion

AXIS_ORDER = ("L0", "L1", "L2", "R0", "R1", "R2")
AXIS_CHANNELS = {
    "L0": "stroke",
    "L1": "surge",
    "L2": "sway",
    "R0": "twist",
    "R1": "roll",
    "R2": "pitch",
}
AXIS_DESCRIPTIONS = {
    "L0": "Main linear stroke / up-down",
    "L1": "Forward-backward surge",
    "L2": "Left-right sway",
    "R0": "Twist around the main axis",
    "R1": "Side-to-side roll",
    "R2": "Forward-backward pitch",
}
FUNSCRIPT_SUFFIXES = {
    "L0": "",
    "L1": ".surge",
    "L2": ".sway",
    "R0": ".twist",
    "R1": ".roll",
    "R2": ".pitch",
}

SECONDARY_LIMITS = {
    "L1": (180.0, 1000.0),
    "L2": (180.0, 1000.0),
    "R0": (300.0, 1800.0),
    "R1": (200.0, 1200.0),
    "R2": (200.0, 1200.0),
}

_PRESET_AMPLITUDES = {
    "balanced": {"L1": 17.0, "L2": 18.0, "R0": 30.0, "R1": 20.0, "R2": 19.0},
    "rhythm": {"L1": 14.0, "L2": 20.0, "R0": 24.0, "R1": 23.0, "R2": 15.0},
    "expressive": {"L1": 21.0, "L2": 22.0, "R0": 38.0, "R1": 26.0, "R2": 26.0},
}


@dataclass(frozen=True)
class MultiAxisConfig:
    """Configuration for six-axis planning in normalized 0..100 space."""

    motion: MotionConfig = field(default_factory=MotionConfig)
    preset: str = "balanced"
    strength: float = 1.0
    neutral: float = 50.0

    def __post_init__(self):
        if self.preset not in _PRESET_AMPLITUDES:
            raise ValueError(f"unknown multi-axis preset: {self.preset}")
        if not np.isfinite(self.strength) or self.strength < 0:
            raise ValueError("strength must be a finite non-negative number")
        if not np.isfinite(self.neutral):
            raise ValueError("neutral must be finite")


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
    if beat_times.size == 0 or beat_values.size == 0:
        return np.zeros(action_times.size, dtype=np.float64)

    count = min(beat_times.size, beat_values.size)
    x = np.asarray(beat_times[:count], dtype=np.float64)
    y = safe_normalize(beat_values[:count])
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if x.size == 0:
        return np.zeros(action_times.size, dtype=np.float64)

    x, unique_indices = np.unique(x, return_index=True)
    y = y[unique_indices]
    if x.size == 1:
        return np.full(action_times.size, float(y[0]), dtype=np.float64)
    return np.interp(action_times, x, y, left=float(y[0]), right=float(y[-1]))


def _signed(values: np.ndarray) -> np.ndarray:
    return np.clip(2.0 * values - 1.0, -1.0, 1.0)


def _secondary_targets(data: Mapping, action_times: np.ndarray, l0_positions: np.ndarray, config: MultiAxisConfig) -> dict[str, np.ndarray]:
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    length = beats.size

    energy = _interp_feature(beats, _feature(data, "energy", length), action_times)
    onset = _interp_feature(beats, _feature(data, "onset", length, "energy"), action_times)
    bass = _interp_feature(beats, _feature(data, "bass", length, "energy"), action_times)
    mid = _interp_feature(beats, _feature(data, "mid", length, "energy"), action_times)
    high = _interp_feature(beats, _feature(data, "high", length, "energy"), action_times)
    pitch = _interp_feature(beats, _feature(data, "pitch", length), action_times)
    harmonic = _interp_feature(beats, _feature(data, "harmonic", length, "pitch"), action_times)
    percussive = _interp_feature(beats, _feature(data, "percussive", length, "onset"), action_times)

    n = action_times.size
    if n == 0:
        return {axis: np.asarray([], dtype=np.float64) for axis in AXIS_ORDER[1:]}

    phase = np.arange(n, dtype=np.float64) * np.pi
    stroke = np.clip((l0_positions - 50.0) / 50.0, -1.0, 1.0)
    activity = np.clip(0.55 * onset + 0.45 * percussive, 0.0, 1.0)
    pitch_trend = np.gradient(pitch) if n > 1 else np.zeros(n, dtype=np.float64)

    bass_s = _signed(bass)
    mid_s = _signed(mid)
    high_s = _signed(high)
    pitch_s = _signed(pitch)
    harmonic_s = _signed(harmonic)
    perc_s = _signed(percussive)

    surge = (
        0.46 * np.sin(phase * 0.50 + 0.35 * bass_s)
        + 0.29 * bass_s
        + 0.15 * harmonic_s
        + 0.10 * stroke
    )
    sway = (
        0.48 * np.sin(phase * 0.75 + np.pi / 2.0) * (0.55 + 0.45 * activity)
        + 0.24 * high_s
        + 0.18 * mid_s
        + 0.10 * np.tanh(pitch_trend * 4.0)
    )
    twist = (
        0.44 * np.sin(phase * 0.50 + np.pi / 2.0)
        + 0.34 * pitch_s
        + 0.14 * high_s
        + 0.08 * stroke
    )
    roll = (
        -0.42 * np.sin(phase * 0.75 + np.pi / 2.0)
        + 0.28 * perc_s
        + 0.18 * stroke
        + 0.12 * high_s
    )
    pitch_axis = (
        0.46 * np.sin(phase * 0.25)
        + 0.30 * harmonic_s
        + 0.14 * pitch_s
        + 0.10 * np.tanh(pitch_trend * 5.0)
    )

    if config.preset == "rhythm":
        surge = 0.75 * surge + 0.25 * bass_s
        sway = 0.65 * sway + 0.35 * perc_s
        twist = 0.75 * twist + 0.25 * perc_s
        roll = 0.60 * roll + 0.40 * perc_s
        pitch_axis *= 0.8
    elif config.preset == "expressive":
        surge = 0.85 * surge + 0.15 * harmonic_s
        sway = 0.85 * sway + 0.15 * pitch_s
        twist = 0.75 * twist + 0.25 * pitch_s
        roll = 0.85 * roll + 0.15 * mid_s
        pitch_axis = 0.75 * pitch_axis + 0.25 * harmonic_s

    signals = {"L1": surge, "L2": sway, "R0": twist, "R1": roll, "R2": pitch_axis}
    amplitudes = _PRESET_AMPLITUDES[config.preset]
    neutral = float(np.clip(config.neutral, 0.0, 100.0))
    strength = float(config.strength)

    return {
        axis: np.clip(neutral + amplitudes[axis] * strength * np.clip(signal, -1.0, 1.0), 0.0, 100.0)
        for axis, signal in signals.items()
    }


def plan_multiaxis(data: Mapping, config: MultiAxisConfig) -> dict[str, list[tuple[float, float]]]:
    """Plan synchronized L0/L1/L2/R0/R1/R2 trajectories."""
    l0 = plan_motion(dict(data), config.motion)
    if not l0:
        return {axis: [] for axis in AXIS_ORDER}

    action_times = np.asarray([at for at, _ in l0], dtype=np.float64)
    l0_positions = np.asarray([pos for _, pos in l0], dtype=np.float64)
    targets = _secondary_targets(data, action_times, l0_positions, config)

    axes: dict[str, list[tuple[float, float]]] = {"L0": l0}
    for axis in AXIS_ORDER[1:]:
        speed_limit, acceleration_limit = SECONDARY_LIMITS[axis]
        axes[axis] = apply_constraints(
            zip(action_times, targets[axis]),
            max_speed=speed_limit,
            max_acceleration=acceleration_limit,
            min_interval=config.motion.min_interval,
        )
    return axes


def validate_multiaxis(plan: Mapping[str, list[tuple[float, float]]]) -> None:
    missing = [axis for axis in AXIS_ORDER if axis not in plan]
    if missing:
        raise ValueError(f"missing axes: {', '.join(missing)}")

    for axis in AXIS_ORDER:
        previous_at = -1.0
        for at, pos in plan[axis]:
            if not np.isfinite(at) or not np.isfinite(pos):
                raise ValueError(f"{axis} contains non-finite action")
            if at < previous_at:
                raise ValueError(f"{axis} actions are not time ordered")
            if not 0.0 <= pos <= 100.0:
                raise ValueError(f"{axis} position outside 0..100")
            previous_at = at


def _funscript_payload(axis: str, actions: list[tuple[float, float]], metadata: Mapping | None) -> dict:
    encoded = [
        {"at": int(round(float(at) * 1000)), "pos": int(round(float(pos)))}
        for at, pos in actions
        if np.isfinite(at) and np.isfinite(pos)
    ]
    encoded.sort(key=lambda item: item["at"])
    duration = encoded[-1]["at"] if encoded else 0
    meta = {
        "creator": "PythonDancer 2",
        "description": f"Generated {axis} / {AXIS_CHANNELS[axis]} axis",
        "duration": duration,
        "license": "None",
        "notes": "",
        "performers": [],
        "script_url": "",
        "tags": ["multiaxis", axis, AXIS_CHANNELS[axis]],
        "title": "",
        "type": "basic",
        "video_url": "",
    }
    if metadata:
        meta.update(dict(metadata))
    meta["axis"] = axis
    meta["channel"] = AXIS_CHANNELS[axis]
    return {"actions": encoded, "inverted": False, "metadata": meta, "range": 100, "version": "1.0"}


def bundle_paths(base_path: str | Path) -> dict[str, Path]:
    """Return standard MultiFunPlayer-compatible paths for all six axes."""
    path = Path(base_path)
    text = str(path)
    prefix = text[: -len(".funscript")] if text.lower().endswith(".funscript") else text
    return {axis: Path(prefix + FUNSCRIPT_SUFFIXES[axis] + ".funscript") for axis in AXIS_ORDER}


def export_funscript_bundle(base_path: str | Path, plan: Mapping[str, list[tuple[float, float]]], *, metadata: Mapping | None = None, manifest: bool = True) -> dict[str, Path]:
    """Write a six-axis funscript bundle and optional inspection manifest."""
    validate_multiaxis(plan)
    paths = bundle_paths(base_path)

    for axis, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf8") as handle:
            dump(_funscript_payload(axis, list(plan[axis]), metadata), handle, indent=2)

    if manifest:
        l0_path = paths["L0"]
        manifest_path = l0_path.with_suffix(".motion.json")
        payload = {
            "version": "1.0",
            "axes": {
                axis: {
                    "channel": AXIS_CHANNELS[axis],
                    "description": AXIS_DESCRIPTIONS[axis],
                    "file": paths[axis].name,
                    "actions": len(plan[axis]),
                }
                for axis in AXIS_ORDER
            },
        }
        with manifest_path.open("w", encoding="utf8") as handle:
            dump(payload, handle, indent=2)
        paths["manifest"] = manifest_path

    return paths
