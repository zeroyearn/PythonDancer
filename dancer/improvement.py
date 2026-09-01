"""Automatic weak-range regeneration loop for PythonDancer 2.7."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .candidates import CandidateResult, generate_candidates
from .kinematics import SR6Geometry
from .multiaxis import MultiAxisConfig
from .quality import QualityReport, score_plan
from .workspace import splice_plan


@dataclass(frozen=True)
class ImprovementConfig:
    max_iterations: int = 4
    target_score: float = 90.0
    minimum_improvement: float = 0.35
    candidates: int = 6
    blend_seconds: float = 0.30

    def __post_init__(self):
        if self.max_iterations < 1 or self.candidates < 1:
            raise ValueError("improvement iteration/candidate counts must be positive")
        if not 0.0 <= float(self.target_score) <= 100.0:
            raise ValueError("target_score must be within 0..100")
        if float(self.minimum_improvement) < 0.0:
            raise ValueError("minimum_improvement must be non-negative")
        if float(self.blend_seconds) < 0.0:
            raise ValueError("blend_seconds must be non-negative")


@dataclass(frozen=True)
class ImprovementStep:
    iteration: int
    start: float
    end: float
    candidate: str
    before: float
    after: float

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ImprovementResult:
    plan: Mapping[str, Sequence[tuple[float, float]]]
    quality: QualityReport
    history: tuple[ImprovementStep, ...]
    stopped_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "quality": self.quality.to_dict(),
            "history": [step.to_dict() for step in self.history],
            "stopped_reason": self.stopped_reason,
        }


def auto_improve(
    data: Mapping,
    base_plan,
    generation_config: MultiAxisConfig,
    *,
    config: ImprovementConfig | None = None,
    geometry: SR6Geometry | None = None,
    sections: Sequence[Mapping] | None = None,
    locked_axes: Sequence[str] = (),
) -> ImprovementResult:
    config = config or ImprovementConfig()
    geometry = geometry or generation_config.geometry
    mechanical = generation_config.mechanical
    current = {axis: list(rows) for axis, rows in base_plan.items()}
    report = score_plan(current, data, sections=sections, geometry=geometry, mechanical_config=mechanical)
    history: list[ImprovementStep] = []
    if report.overall >= config.target_score:
        return ImprovementResult(current, report, (), "target score already met")

    # Candidate generation is deterministic for a fixed analysis/config, so the
    # same candidate bank can be reused while the accepted workspace evolves.
    bank: list[CandidateResult] = generate_candidates(
        data, generation_config, count=config.candidates, geometry=geometry, sections=sections
    )
    reason = "iteration limit"
    for iteration in range(1, config.max_iterations + 1):
        report = score_plan(current, data, sections=sections, geometry=geometry, mechanical_config=mechanical)
        if report.overall >= config.target_score:
            reason = "target score met"; break
        if not report.weak_ranges:
            reason = "no weak ranges"; break
        weak = report.weak_ranges[0]
        best_plan = None
        best_score = report.overall
        best_name = ""
        for candidate in bank:
            merged = splice_plan(
                current,
                candidate.plan,
                weak.start,
                weak.end,
                locked_axes=locked_axes,
                blend=config.blend_seconds,
            )
            trial = score_plan(
                merged,
                data,
                sections=sections,
                geometry=geometry,
                mechanical_config=mechanical,
                compute_windows=False,
            )
            if trial.overall > best_score:
                best_score = trial.overall
                best_plan = merged
                best_name = candidate.name
        if best_plan is None or best_score - report.overall < config.minimum_improvement:
            reason = "improvement below threshold"; break
        history.append(ImprovementStep(iteration, weak.start, weak.end, best_name, report.overall, best_score))
        current = best_plan
    final = score_plan(current, data, sections=sections, geometry=geometry, mechanical_config=mechanical)
    return ImprovementResult(current, final, tuple(history), reason)
