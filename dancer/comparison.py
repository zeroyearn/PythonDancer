"""A/B comparison and best-section merge tools for PythonDancer 2.7."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .candidates import CandidateResult
from .kinematics import AXES, SR6Geometry
from .mechanical_safety import MechanicalProjectionConfig
from .plan_window import slice_plan
from .quality import QualityReport, score_plan
from .workspace import splice_plan


@dataclass(frozen=True)
class ComparisonReport:
    score_a: float
    score_b: float
    score_delta: float
    metric_delta: Mapping[str, float]
    axis_rms_distance: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "score_a": self.score_a,
            "score_b": self.score_b,
            "score_delta": self.score_delta,
            "metric_delta": dict(self.metric_delta),
            "axis_rms_distance": dict(self.axis_rms_distance),
        }


def _rows(plan, axis):
    return sorted((float(t), float(p)) for t, p in plan.get(axis, ()) if np.isfinite(t) and np.isfinite(p))


def _axis_rms(a, b, axis: str) -> float:
    rows_a, rows_b = _rows(a, axis), _rows(b, axis)
    grid = sorted({t for t, _ in rows_a} | {t for t, _ in rows_b})
    if not grid:
        return 0.0
    x = np.asarray(grid, dtype=np.float64)

    def sample(rows):
        if not rows:
            return np.full(x.size, 50.0)
        t = np.asarray([v[0] for v in rows]); p = np.asarray([v[1] for v in rows])
        return np.interp(x, t, p, left=p[0], right=p[-1])

    return float(np.sqrt(np.mean((sample(rows_a) - sample(rows_b)) ** 2)))


def compare_plans(
    plan_a,
    plan_b,
    data: Mapping | None = None,
    *,
    report_a: QualityReport | None = None,
    report_b: QualityReport | None = None,
    geometry: SR6Geometry | None = None,
    mechanical_config: MechanicalProjectionConfig | None = None,
) -> ComparisonReport:
    report_a = report_a or score_plan(plan_a, data, geometry=geometry, mechanical_config=mechanical_config)
    report_b = report_b or score_plan(plan_b, data, geometry=geometry, mechanical_config=mechanical_config)
    metrics = sorted(set(report_a.metrics) | set(report_b.metrics))
    return ComparisonReport(
        float(report_a.overall),
        float(report_b.overall),
        float(report_b.overall - report_a.overall),
        {name: float(report_b.metrics.get(name, 0.0) - report_a.metrics.get(name, 0.0)) for name in metrics},
        {axis: _axis_rms(plan_a, plan_b, axis) for axis in AXES},
    )


def _range(section) -> tuple[float, float]:
    if isinstance(section, Mapping):
        return float(section.get("start", 0.0)), float(section.get("end", 0.0))
    return float(section.start), float(section.end)


def _slice_data(data: Mapping | None, start: float, end: float) -> dict:
    if not data:
        return {}
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    mask = (beats >= start) & (beats <= end)
    indices = np.where(mask)[0]
    result = {"beats": beats[mask] - start}
    for key, raw in data.items():
        if key == "beats":
            continue
        try:
            arr = np.asarray(raw).reshape(-1)
        except Exception:
            continue
        if arr.size >= beats.size and indices.size:
            result[key] = arr[indices]
    return result


def merge_candidate_sections(
    candidates: Sequence[CandidateResult],
    sections: Sequence,
    assignments: Mapping[int, int],
    *,
    base_candidate: int = 0,
    blend: float = 0.25,
    locked_axes: Sequence[str] = (),
):
    if not candidates:
        raise ValueError("at least one candidate is required")
    base_index = int(np.clip(base_candidate, 0, len(candidates) - 1))
    merged = {axis: list(candidates[base_index].plan.get(axis, ())) for axis in AXES}
    for index, section in enumerate(sections):
        selected = int(assignments.get(index, base_index))
        if not 0 <= selected < len(candidates):
            continue
        start, end = _range(section)
        if end <= start:
            continue
        replacement = slice_plan(candidates[selected].plan, start, end, rebase=False)
        merged = splice_plan(
            merged,
            replacement,
            start,
            end,
            locked_axes=locked_axes,
            blend=blend,
        )
    return merged


def best_section_merge(
    candidates: Sequence[CandidateResult],
    sections: Sequence,
    data: Mapping | None = None,
    *,
    geometry: SR6Geometry | None = None,
    mechanical_config: MechanicalProjectionConfig | None = None,
    blend: float = 0.25,
    locked_axes: Sequence[str] = (),
):
    if not candidates:
        raise ValueError("at least one candidate is required")
    choices: dict[int, int] = {}
    section_scores: dict[int, list[float]] = {}
    for index, section in enumerate(sections):
        start, end = _range(section)
        if end <= start:
            section_scores[index] = [0.0 for _ in candidates]
            choices[index] = 0
            continue
        local_data = _slice_data(data, start, end)
        scores = []
        for candidate in candidates:
            local = slice_plan(candidate.plan, start, end, rebase=True)
            effective_geometry = geometry or candidate.config.geometry
            effective_mechanical = mechanical_config or candidate.config.mechanical
            scores.append(float(score_plan(
                local,
                local_data,
                geometry=effective_geometry,
                mechanical_config=effective_mechanical,
                compute_windows=False,
            ).overall))
        choices[index] = int(np.argmax(scores))
        section_scores[index] = scores
    merged = merge_candidate_sections(
        candidates,
        sections,
        choices,
        base_candidate=0,
        blend=blend,
        locked_axes=locked_axes,
    )
    return merged, choices, section_scores
