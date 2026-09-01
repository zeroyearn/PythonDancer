"""Motion Quality Scorer for PythonDancer 2.7 Quality Intelligence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .features import safe_normalize
from .kinematics import AXES, SR6Geometry
from .mechanical_safety import MechanicalProjectionConfig, trajectory_mechanical_risk
from .optimizer import DEFAULT_ACCEL, DEFAULT_JERK, DEFAULT_SPEED
from .plan_window import slice_plan

METRICS = (
    "rhythm_alignment",
    "phrase_alignment",
    "smoothness",
    "axis_diversity",
    "cross_axis_coherence",
    "repetition",
    "mechanical_safety",
    "jerk_comfort",
    "stem_responsiveness",
)


@dataclass(frozen=True)
class QualityWeights:
    rhythm_alignment: float = 1.30
    phrase_alignment: float = 0.75
    smoothness: float = 1.00
    axis_diversity: float = 0.80
    cross_axis_coherence: float = 0.70
    repetition: float = 0.65
    mechanical_safety: float = 1.45
    jerk_comfort: float = 1.05
    stem_responsiveness: float = 0.80

    def as_dict(self) -> dict[str, float]:
        return {name: max(0.0, float(getattr(self, name))) for name in METRICS}


@dataclass(frozen=True)
class QualityWindow:
    start: float
    end: float
    score: float
    weakest_metric: str

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start, "end": self.end, "score": self.score, "weakest_metric": self.weakest_metric}


@dataclass(frozen=True)
class QualityReport:
    overall: float
    metrics: Mapping[str, float]
    weak_ranges: tuple[QualityWindow, ...] = ()
    mechanical: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "overall": float(self.overall),
            "metrics": {key: float(value) for key, value in self.metrics.items()},
            "weak_ranges": [item.to_dict() for item in self.weak_ranges],
            "mechanical": dict(self.mechanical),
        }


def _duration(plan: Mapping[str, Sequence[tuple[float, float]]], data: Mapping | None = None) -> float:
    values = [float(at) for axis in AXES for at, _ in plan.get(axis, ()) if np.isfinite(at)]
    if data is not None:
        values.extend(float(at) for at in np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1) if np.isfinite(at))
    return max(values, default=0.0)


def _sample_matrix(plan: Mapping[str, Sequence[tuple[float, float]]], duration: float, hz: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    if duration <= 0:
        return np.asarray([0.0]), np.full((1, len(AXES)), 50.0, dtype=np.float64)
    count = min(12000, max(3, int(np.ceil(duration * hz)) + 1))
    times = np.linspace(0.0, duration, count)
    columns = []
    for axis in AXES:
        rows = sorted((float(t), float(p)) for t, p in plan.get(axis, ()) if np.isfinite(t) and np.isfinite(p))
        if not rows:
            columns.append(np.full(count, 50.0, dtype=np.float64)); continue
        x = np.asarray([r[0] for r in rows], dtype=np.float64); y = np.asarray([r[1] for r in rows], dtype=np.float64)
        columns.append(np.interp(times, x, y, left=y[0], right=y[-1]))
    return times, np.column_stack(columns)


def _derivatives(times: np.ndarray, matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if times.size < 3:
        z = np.zeros_like(matrix)
        return z, z, z
    velocity = np.gradient(matrix, times, axis=0, edge_order=1)
    acceleration = np.gradient(velocity, times, axis=0, edge_order=1)
    jerk = np.gradient(acceleration, times, axis=0, edge_order=1)
    return velocity, acceleration, jerk


def _nearest_distance(values: np.ndarray, targets: np.ndarray) -> np.ndarray:
    if values.size == 0 or targets.size == 0:
        return np.asarray([], dtype=np.float64)
    index = np.searchsorted(targets, values)
    left = targets[np.clip(index - 1, 0, targets.size - 1)]
    right = targets[np.clip(index, 0, targets.size - 1)]
    return np.minimum(np.abs(values - left), np.abs(values - right))


def _rhythm_score(times: np.ndarray, velocity: np.ndarray, beats: np.ndarray) -> float:
    beats = beats[np.isfinite(beats)]
    if beats.size < 2 or times.size < 4:
        return 72.0
    motion = np.linalg.norm(velocity / np.asarray([DEFAULT_SPEED[a] for a in AXES])[None, :], axis=1)
    if np.max(motion) <= 1e-9:
        return 20.0
    threshold = float(np.percentile(motion, 72.0))
    peaks = np.where((motion[1:-1] >= motion[:-2]) & (motion[1:-1] >= motion[2:]) & (motion[1:-1] >= threshold))[0] + 1
    if peaks.size == 0:
        return 35.0
    peak_times = times[peaks]
    distances = _nearest_distance(peak_times, beats)
    beat_step = float(np.median(np.diff(beats)))
    tolerance = float(np.clip(beat_step * 0.20, 0.06, 0.24))
    return float(np.clip(100.0 * np.mean(np.exp(-((distances / tolerance) ** 2))), 0.0, 100.0))


def _phrase_score(times: np.ndarray, velocity: np.ndarray, beats: np.ndarray, sections: Sequence[Mapping] | None) -> float:
    motion = np.linalg.norm(velocity, axis=1)
    boundaries: list[float] = []
    if sections:
        for section in sections:
            if "start" in section:
                boundaries.append(float(section["start"]))
    if not boundaries and beats.size >= 17:
        boundaries = [float(beats[i]) for i in range(16, beats.size, 16)]
    boundaries = [v for v in boundaries if 0.5 < v < times[-1] - 0.5]
    if not boundaries:
        return 75.0
    contrasts = []
    for boundary in boundaries:
        pre = motion[(times >= boundary - 0.8) & (times < boundary)]
        post = motion[(times >= boundary) & (times <= boundary + 0.8)]
        if pre.size and post.size:
            denominator = max(1e-6, float(np.mean(pre) + np.mean(post)))
            contrasts.append(abs(float(np.mean(post) - np.mean(pre))) / denominator)
    return float(np.clip(60.0 + 80.0 * np.mean(contrasts or [0.18]), 0.0, 100.0))


def _smoothness_scores(acceleration: np.ndarray, jerk: np.ndarray) -> tuple[float, float]:
    accel_limits = np.asarray([DEFAULT_ACCEL[a] for a in AXES], dtype=np.float64)
    jerk_limits = np.asarray([DEFAULT_JERK[a] for a in AXES], dtype=np.float64)
    accel_load = float(np.sqrt(np.mean((acceleration / accel_limits[None, :]) ** 2)))
    jerk_load = float(np.sqrt(np.mean((jerk / jerk_limits[None, :]) ** 2)))
    smoothness = float(np.clip(100.0 / (1.0 + 1.8 * accel_load), 0.0, 100.0))
    jerk_comfort = float(np.clip(100.0 / (1.0 + 2.2 * jerk_load), 0.0, 100.0))
    return smoothness, jerk_comfort


def _axis_diversity(velocity: np.ndarray) -> float:
    activity = np.mean(np.abs(velocity), axis=0)
    total = float(np.sum(activity))
    if total <= 1e-9:
        return 0.0
    probabilities = activity / total
    entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12)))) / np.log(len(AXES))
    active_fraction = float(np.mean(activity > max(0.5, np.max(activity) * 0.08)))
    return float(np.clip(100.0 * (0.70 * entropy + 0.30 * active_fraction), 0.0, 100.0))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 3 or np.std(a) < 1e-8 or np.std(b) < 1e-8:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _coherence(velocity: np.ndarray) -> float:
    pairs = ((0, 3), (1, 5), (2, 4))
    expected = np.mean([abs(_corr(velocity[:, a], velocity[:, b])) for a, b in pairs])
    all_corr = []
    for a in range(len(AXES)):
        for b in range(a + 1, len(AXES)):
            all_corr.append(abs(_corr(velocity[:, a], velocity[:, b])))
    lockstep = max(0.0, float(np.mean(all_corr)) - 0.78) / 0.22 if all_corr else 0.0
    return float(np.clip(66.0 + 34.0 * expected - 22.0 * lockstep, 0.0, 100.0))


def _repetition(times: np.ndarray, velocity: np.ndarray) -> float:
    if times.size < 20 or times[-1] < 8.0:
        return 80.0
    segment = 4.0
    fingerprints = []
    start = 0.0
    while start + segment <= times[-1] + 1e-9:
        mask = (times >= start) & (times < start + segment)
        if np.sum(mask) >= 3:
            block = np.abs(velocity[mask])
            fingerprints.append(np.concatenate((np.mean(block, axis=0), np.std(block, axis=0))))
        start += segment
    if len(fingerprints) < 3:
        return 80.0
    fp = np.asarray(fingerprints, dtype=np.float64)
    norms = np.linalg.norm(fp, axis=1)
    similarities = []
    for i in range(len(fp)):
        for j in range(i + 2, len(fp)):
            denom = norms[i] * norms[j]
            if denom > 1e-9:
                similarities.append(float(np.dot(fp[i], fp[j]) / denom))
    repeated = float(np.mean(sorted(similarities, reverse=True)[:max(1, len(similarities)//4)])) if similarities else 0.0
    return float(np.clip(100.0 * (1.0 - 0.62 * max(0.0, repeated - 0.35)), 0.0, 100.0))


def _stem_score(data: Mapping | None, beats: np.ndarray, times: np.ndarray, velocity: np.ndarray) -> float:
    if not data or beats.size < 3:
        return 72.0
    mapping = {
        1: ("stem_bass_energy", "bass"),
        2: ("stem_drums_hihat", "high"),
        3: ("stem_vocals_pitch_motion", "pitch"),
        4: ("stem_drums_snare", "stem_drums_onset"),
        5: ("stem_vocals_energy", "harmonic"),
    }
    correlations = []
    for column, names in mapping.items():
        raw = data.get(names[0], data.get(names[1]))
        if raw is None:
            continue
        feature = np.asarray(raw, dtype=np.float64).reshape(-1)
        n = min(beats.size, feature.size)
        if n < 3:
            continue
        feature = safe_normalize(feature[:n])
        motion = np.interp(beats[:n], times, np.abs(velocity[:, column]))
        motion = safe_normalize(motion)
        correlations.append(max(0.0, _corr(feature, motion)))
    if not correlations:
        return 72.0
    return float(np.clip(50.0 + 50.0 * np.mean(correlations), 0.0, 100.0))


def _slice_sections(sections: Sequence[Mapping] | None, start: float, end: float) -> list[dict[str, object]]:
    """Clip global section metadata into one rebased local scoring window."""
    local: list[dict[str, object]] = []
    for section in sections or ():
        try:
            section_start = float(section.get("start", 0.0))
            section_end = float(section.get("end", end))
        except (TypeError, ValueError, AttributeError):
            continue
        clipped_start = max(float(start), section_start)
        clipped_end = min(float(end), section_end)
        if clipped_end <= clipped_start + 1e-9:
            continue
        item = dict(section)
        item["start"] = clipped_start - float(start)
        item["end"] = clipped_end - float(start)
        local.append(item)
    return local


def _weak_windows(plan, data, sections, geometry, mech_config, window_seconds: float, threshold: float) -> tuple[QualityWindow, ...]:
    duration = _duration(plan, data)
    if duration <= window_seconds * 0.75:
        return ()
    result = []
    start = 0.0
    while start < duration:
        end = min(duration, start + window_seconds)
        local_plan = slice_plan(plan, start, end, rebase=True)
        local_data = {}
        if data:
            beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
            mask = (beats >= start) & (beats <= end)
            local_beats = beats[mask] - start
            local_data["beats"] = local_beats
            indices = np.where(mask)[0]
            for key, raw in data.items():
                if key == "beats": continue
                try:
                    arr = np.asarray(raw).reshape(-1)
                except Exception:
                    continue
                if arr.size >= beats.size and indices.size:
                    local_data[key] = arr[indices]
        local_sections = _slice_sections(sections, start, end)
        report = score_plan(
            local_plan,
            local_data,
            sections=local_sections,
            geometry=geometry,
            mechanical_config=mech_config,
            compute_windows=False,
        )
        if report.overall < threshold:
            weakest = min(report.metrics, key=report.metrics.get)
            result.append(QualityWindow(float(start), float(end), float(report.overall), weakest))
        start += max(window_seconds * 0.75, 1.0)
    return tuple(sorted(result, key=lambda item: item.score))


def score_plan(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    data: Mapping | None = None,
    *,
    sections: Sequence[Mapping] | None = None,
    geometry: SR6Geometry | None = None,
    mechanical_config: MechanicalProjectionConfig | None = None,
    weights: QualityWeights | None = None,
    compute_windows: bool = True,
    window_seconds: float = 8.0,
    weak_threshold: float = 78.0,
) -> QualityReport:
    data = data or {}
    weights = weights or QualityWeights()
    mechanical_config = mechanical_config or MechanicalProjectionConfig()
    duration = _duration(plan, data)
    times, matrix = _sample_matrix(plan, duration)
    velocity, acceleration, jerk = _derivatives(times, matrix)
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    beats = beats[np.isfinite(beats)]
    smoothness, jerk_comfort = _smoothness_scores(acceleration, jerk)
    mechanical = trajectory_mechanical_risk(plan, geometry or SR6Geometry(), mechanical_config)
    safety_score = float(np.clip(100.0 * (1.0 - 0.62 * float(mechanical["mean_risk"]) - 0.38 * float(mechanical["unsafe_ratio"])), 0.0, 100.0))
    metrics = {
        "rhythm_alignment": _rhythm_score(times, velocity, beats),
        "phrase_alignment": _phrase_score(times, velocity, beats, sections),
        "smoothness": smoothness,
        "axis_diversity": _axis_diversity(velocity),
        "cross_axis_coherence": _coherence(velocity),
        "repetition": _repetition(times, velocity),
        "mechanical_safety": safety_score,
        "jerk_comfort": jerk_comfort,
        "stem_responsiveness": _stem_score(data, beats, times, velocity),
    }
    weight_map = weights.as_dict()
    denominator = sum(weight_map.values()) or 1.0
    overall = float(sum(metrics[name] * weight_map[name] for name in METRICS) / denominator)
    weak_ranges = _weak_windows(plan, data, sections, geometry or SR6Geometry(), mechanical_config, window_seconds, weak_threshold) if compute_windows else ()
    return QualityReport(float(np.clip(overall, 0.0, 100.0)), metrics, weak_ranges, mechanical)