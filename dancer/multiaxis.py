"""SR6/OSR6-style six-axis motion planning and funscript bundle export."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from json import dump
from pathlib import Path
from typing import Mapping

import numpy as np

from .choreography import ChoreographyAnalysis, detect_sections
from .choreo_profile import synthesize_profiled_choreography
from .features import safe_normalize
from .independent_planner import IndependentAxisConfig, plan_independent_secondary_axes
from .intent import IntentEnvelope, infer_motion_intent
from .kinematics import SR6Geometry
from .mechanical_safety import MechanicalProjectionConfig, project_plan_to_safe
from .motion import MotionConfig, apply_constraints, plan_motion
from .optimizer import OptimizerConfig, optimize_multiaxis
from .section_intent import SectionIntentOverride, apply_section_intent_overrides
from .style import ChoreographyProfile

AXIS_ORDER = ("L0", "L1", "L2", "R0", "R1", "R2")
AXIS_CHANNELS = {"L0": "stroke", "L1": "surge", "L2": "sway", "R0": "twist", "R1": "roll", "R2": "pitch"}
AXIS_DESCRIPTIONS = {
    "L0": "Main linear stroke / up-down",
    "L1": "Forward-backward surge",
    "L2": "Left-right sway",
    "R0": "Twist around the main axis",
    "R1": "Side-to-side roll",
    "R2": "Forward-backward pitch",
}
FUNSCRIPT_SUFFIXES = {"L0": "", "L1": ".surge", "L2": ".sway", "R0": ".twist", "R1": ".roll", "R2": ".pitch"}
SECONDARY_LIMITS = {"L1": (180.0, 1000.0), "L2": (180.0, 1000.0), "R0": (300.0, 1800.0), "R1": (200.0, 1200.0), "R2": (200.0, 1200.0)}
_PRESET_AMPLITUDES = {
    "balanced": {"L1": 17.0, "L2": 18.0, "R0": 30.0, "R1": 20.0, "R2": 19.0},
    "rhythm": {"L1": 14.0, "L2": 20.0, "R0": 24.0, "R1": 23.0, "R2": 15.0},
    "expressive": {"L1": 21.0, "L2": 22.0, "R0": 38.0, "R1": 26.0, "R2": 26.0},
}


@dataclass(frozen=True)
class MultiAxisConfig:
    motion: MotionConfig = field(default_factory=MotionConfig)
    preset: str = "balanced"
    strength: float = 1.0
    neutral: float = 50.0
    mode: str = "choreography"
    gesture_strength: float = 1.0
    beats_per_bar: int = 4
    bars_per_phrase: int = 4
    section_bars: int = 4
    profile: ChoreographyProfile | None = None
    independent: IndependentAxisConfig = field(default_factory=IndependentAxisConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    section_intents: tuple[SectionIntentOverride, ...] = ()
    mechanical: MechanicalProjectionConfig = field(default_factory=MechanicalProjectionConfig)
    geometry: SR6Geometry = field(default_factory=SR6Geometry)

    def __post_init__(self):
        if self.preset not in _PRESET_AMPLITUDES:
            raise ValueError(f"unknown multi-axis preset: {self.preset}")
        if self.mode not in ("choreography", "reactive"):
            raise ValueError("mode must be 'choreography' or 'reactive'")
        if not np.isfinite(self.strength) or self.strength < 0:
            raise ValueError("strength must be a finite non-negative number")
        if not np.isfinite(self.gesture_strength) or self.gesture_strength < 0:
            raise ValueError("gesture_strength must be a finite non-negative number")
        if not np.isfinite(self.neutral):
            raise ValueError("neutral must be finite")
        if self.beats_per_bar <= 0 or self.bars_per_phrase <= 0 or self.section_bars <= 0:
            raise ValueError("musical grid values must be positive")
        if self.profile is not None and not isinstance(self.profile, ChoreographyProfile):
            raise TypeError("profile must be a ChoreographyProfile")
        if not isinstance(self.independent, IndependentAxisConfig):
            raise TypeError("independent must be an IndependentAxisConfig")
        if not isinstance(self.optimizer, OptimizerConfig):
            raise TypeError("optimizer must be an OptimizerConfig")
        if not isinstance(self.mechanical, MechanicalProjectionConfig):
            raise TypeError("mechanical must be a MechanicalProjectionConfig")
        if not isinstance(self.geometry, SR6Geometry):
            raise TypeError("geometry must be an SR6Geometry")
        if any(not isinstance(item, SectionIntentOverride) for item in self.section_intents):
            raise TypeError("section_intents must contain SectionIntentOverride values")


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


def _reactive_signals(data: Mapping, action_times: np.ndarray, l0_positions: np.ndarray, preset: str) -> dict[str, np.ndarray]:
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
    bass_s, mid_s, high_s = _signed(bass), _signed(mid), _signed(high)
    pitch_s, harmonic_s, perc_s = _signed(pitch), _signed(harmonic), _signed(percussive)
    surge = 0.46 * np.sin(phase * 0.50 + 0.35 * bass_s) + 0.29 * bass_s + 0.15 * harmonic_s + 0.10 * stroke
    sway = 0.48 * np.sin(phase * 0.75 + np.pi / 2.0) * (0.55 + 0.45 * activity) + 0.24 * high_s + 0.18 * mid_s + 0.10 * np.tanh(pitch_trend * 4.0)
    twist = 0.44 * np.sin(phase * 0.50 + np.pi / 2.0) + 0.34 * pitch_s + 0.14 * high_s + 0.08 * stroke
    roll = -0.42 * np.sin(phase * 0.75 + np.pi / 2.0) + 0.28 * perc_s + 0.18 * stroke + 0.12 * high_s
    pitch_axis = 0.46 * np.sin(phase * 0.25) + 0.30 * harmonic_s + 0.14 * pitch_s + 0.10 * np.tanh(pitch_trend * 5.0)
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


def analyze_multiaxis(data: Mapping, config: MultiAxisConfig) -> ChoreographyAnalysis:
    return detect_sections(data, beats_per_bar=config.beats_per_bar, bars_per_phrase=config.bars_per_phrase, section_bars=config.section_bars)


def analyze_intent(data: Mapping, config: MultiAxisConfig) -> IntentEnvelope:
    envelope = infer_motion_intent(data, analyze_multiaxis(data, config))
    return apply_section_intent_overrides(envelope, config.section_intents)


def _secondary_targets(data: Mapping, action_times: np.ndarray, l0_positions: np.ndarray, config: MultiAxisConfig) -> dict[str, np.ndarray]:
    if config.mode == "choreography":
        signals, _ = synthesize_profiled_choreography(
            data,
            action_times,
            l0_positions,
            preset=config.preset,
            gesture_strength=config.gesture_strength,
            beats_per_bar=config.beats_per_bar,
            bars_per_phrase=config.bars_per_phrase,
            section_bars=config.section_bars,
            profile=config.profile,
        )
    else:
        signals = _reactive_signals(data, action_times, l0_positions, config.preset)
    amplitudes = _PRESET_AMPLITUDES[config.preset]
    profile = config.profile or ChoreographyProfile()
    neutral = float(np.clip(config.neutral, 0.0, 100.0))
    strength = float(config.strength)
    return {
        axis: np.clip(
            neutral + amplitudes[axis] * profile.axis_multiplier(axis) * strength * np.clip(signals[axis], -1.0, 1.0),
            0.0,
            100.0,
        )
        for axis in AXIS_ORDER[1:]
    }


def _section_times(data: Mapping, analysis: ChoreographyAnalysis) -> list[float]:
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    values: list[float] = []
    for section in analysis.sections:
        if 0 <= section.start_beat < beats.size:
            values.append(float(beats[section.start_beat]))
        if 0 <= section.end_beat < beats.size:
            values.append(float(beats[section.end_beat]))
    return values


def plan_multiaxis(data: Mapping, config: MultiAxisConfig) -> dict[str, list[tuple[float, float]]]:
    l0 = plan_motion(dict(data), config.motion)
    if not l0:
        return {axis: [] for axis in AXIS_ORDER}

    axes: dict[str, list[tuple[float, float]]] = {"L0": l0}
    if config.mode == "choreography" and config.independent.enabled:
        analysis = analyze_multiaxis(data, config)
        intent = apply_section_intent_overrides(infer_motion_intent(data, analysis), config.section_intents)
        axes.update(plan_independent_secondary_axes(
            data,
            l0,
            preset=config.preset,
            amplitudes=_PRESET_AMPLITUDES[config.preset],
            strength=config.strength,
            neutral=config.neutral,
            gesture_strength=config.gesture_strength,
            beats_per_bar=config.beats_per_bar,
            bars_per_phrase=config.bars_per_phrase,
            section_bars=config.section_bars,
            profile=config.profile,
            intent=intent,
            axis_config=config.independent,
            limits=SECONDARY_LIMITS,
            section_times=_section_times(data, analysis),
        ))
    else:
        action_times = np.asarray([at for at, _ in l0], dtype=np.float64)
        l0_positions = np.asarray([pos for _, pos in l0], dtype=np.float64)
        targets = _secondary_targets(data, action_times, l0_positions, config)
        for axis in AXIS_ORDER[1:]:
            speed_limit, acceleration_limit = SECONDARY_LIMITS[axis]
            axes[axis] = apply_constraints(zip(action_times, targets[axis]), max_speed=speed_limit, max_acceleration=acceleration_limit, min_interval=config.motion.min_interval)

    optimizer = replace(config.optimizer, neutral=float(config.neutral))
    optimized = optimize_multiaxis(axes, optimizer)
    if not config.mechanical.enabled:
        return optimized
    mechanical = replace(config.mechanical, neutral=float(config.neutral))
    projected, _ = project_plan_to_safe(optimized, config.geometry, mechanical)
    # Projection can introduce a sharp local correction. Re-apply the existing
    # kinematic optimizer, then project once more so the final trajectory is
    # both jerk-limited and inside the mechanical safe set.
    smoothed = optimize_multiaxis(projected, optimizer)
    final, _ = project_plan_to_safe(smoothed, config.geometry, mechanical)
    return final


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
    encoded = [{"at": int(round(float(at) * 1000)), "pos": int(round(float(pos)))} for at, pos in actions if np.isfinite(at) and np.isfinite(pos)]
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
    path = Path(base_path)
    text = str(path)
    prefix = text[: -len(".funscript")] if text.lower().endswith(".funscript") else text
    return {axis: Path(prefix + FUNSCRIPT_SUFFIXES[axis] + ".funscript") for axis in AXIS_ORDER}


def export_funscript_bundle(base_path: str | Path, plan: Mapping[str, list[tuple[float, float]]], *, metadata: Mapping | None = None, manifest: bool = True) -> dict[str, Path]:
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
            "version": "1.5",
            "metadata": dict(metadata or {}),
            "axes": {
                axis: {"channel": AXIS_CHANNELS[axis], "description": AXIS_DESCRIPTIONS[axis], "file": paths[axis].name, "actions": len(plan[axis])}
                for axis in AXIS_ORDER
            },
        }
        with manifest_path.open("w", encoding="utf8") as handle:
            dump(payload, handle, indent=2)
        paths["manifest"] = manifest_path
    return paths
