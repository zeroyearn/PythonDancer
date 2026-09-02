"""Multi-candidate choreography generation for PythonDancer 2.7."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

import numpy as np

from .independent_planner import IndependentAxisConfig
from .kinematics import SR6Geometry
from .multiaxis import MultiAxisConfig, plan_multiaxis
from .optimizer import OptimizerConfig
from .quality import QualityReport, QualityWeights, score_plan


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    preset: str
    strength_mul: float = 1.0
    gesture_mul: float = 1.0
    density_mul: float = 1.0
    accent_offset: float = 0.0
    pose_budget_mul: float = 1.0
    velocity_budget_mul: float = 1.0
    intent_bias: Mapping[str, float] = None
    intent_amount: float = 0.0


def candidate_config_to_dict(config: MultiAxisConfig) -> dict[str, object]:
    return {
        "preset": config.preset,
        "strength": float(config.strength),
        "gesture_strength": float(config.gesture_strength),
        "independent": {
            "enabled": bool(config.independent.enabled),
            "min_interval": float(config.independent.min_interval),
            "density": float(config.independent.density),
            "accent_threshold": float(config.independent.accent_threshold),
            "include_section_boundaries": bool(config.independent.include_section_boundaries),
            "intent_override": dict(config.independent.intent_override),
            "intent_override_amount": float(config.independent.intent_override_amount),
        },
        "optimizer": config.optimizer.to_dict(),
    }


def candidate_config_from_dict(base: MultiAxisConfig, payload: Mapping | None) -> MultiAxisConfig:
    payload = dict(payload or {})
    independent_data = dict(payload.get("independent") or {})
    optimizer_data = dict(payload.get("optimizer") or {})
    independent = base.independent
    optimizer = base.optimizer
    if independent_data:
        independent = IndependentAxisConfig(**{
            key: value for key, value in independent_data.items()
            if key in IndependentAxisConfig.__dataclass_fields__
        })
    if optimizer_data:
        optimizer = OptimizerConfig(**{
            key: value for key, value in optimizer_data.items()
            if key in OptimizerConfig.__dataclass_fields__
        })
    return replace(
        base,
        preset=str(payload.get("preset", base.preset)),
        strength=float(payload.get("strength", base.strength)),
        gesture_strength=float(payload.get("gesture_strength", base.gesture_strength)),
        independent=independent,
        optimizer=optimizer,
    )


@dataclass(frozen=True)
class CandidateResult:
    name: str
    config: MultiAxisConfig
    plan: Mapping[str, Sequence[tuple[float, float]]]
    quality: QualityReport

    def to_dict(self, include_plan: bool = False) -> dict[str, object]:
        payload = {
            "name": self.name,
            "score": float(self.quality.overall),
            "quality": self.quality.to_dict(),
            "preset": self.config.preset,
            "strength": float(self.config.strength),
            "gesture_strength": float(self.config.gesture_strength),
            "config": candidate_config_to_dict(self.config),
        }
        if include_plan:
            payload["plan"] = {axis: [[float(t), float(p)] for t, p in rows] for axis, rows in self.plan.items()}
        return payload


def default_candidate_specs() -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec("Balanced", "balanced"),
        CandidateSpec("Expressive", "expressive", 1.05, 1.15, 1.00, -.03, 1.00, 1.00, {"flow": .76, "rotation_bias": .68, "complexity": .62}, .32),
        CandidateSpec("Rhythm Heavy", "rhythm", 1.02, 1.18, 1.24, -.12, .96, 1.02, {"aggression": .78, "accent_density": .88, "translation_bias": .72}, .38),
        CandidateSpec("Smooth Flow", "balanced", .92, .78, .84, .08, .90, .84, {"flow": .88, "aggression": .28, "complexity": .38}, .44),
        CandidateSpec("Rotation Heavy", "expressive", .96, 1.08, 1.04, -.04, .94, .94, {"rotation_bias": .92, "translation_bias": .32, "flow": .72}, .48),
        CandidateSpec("Deep Translation", "balanced", 1.08, 1.02, .96, .00, .97, .94, {"translation_bias": .92, "rotation_bias": .30, "intensity": .78}, .46),
        CandidateSpec("Accent Dense", "rhythm", 1.00, 1.24, 1.34, -.18, .94, .96, {"accent_density": .96, "aggression": .72, "complexity": .72}, .50),
        CandidateSpec("Experimental", "expressive", 1.00, 1.16, 1.42, -.16, 1.00, 1.00, {"complexity": .94, "rotation_bias": .78, "symmetry": .24, "flow": .58}, .52),
    )


def config_for_candidate(base: MultiAxisConfig, spec: CandidateSpec) -> MultiAxisConfig:
    current_override = dict(base.independent.intent_override)
    for key, value in dict(spec.intent_bias or {}).items():
        current_override[key] = float(np.clip(value, 0.0, 1.0))
    independent = replace(
        base.independent,
        density=max(.2, float(base.independent.density) * float(spec.density_mul)),
        accent_threshold=float(np.clip(base.independent.accent_threshold + spec.accent_offset, 0.0, 1.0)),
        intent_override=current_override,
        intent_override_amount=max(float(base.independent.intent_override_amount), float(spec.intent_amount)),
    )
    optimizer = replace(
        base.optimizer,
        pose_budget=max(.2, float(base.optimizer.pose_budget) * float(spec.pose_budget_mul)),
        velocity_budget=max(.2, float(base.optimizer.velocity_budget) * float(spec.velocity_budget_mul)),
    )
    return replace(
        base,
        preset=spec.preset,
        strength=max(0.0, float(base.strength) * float(spec.strength_mul)),
        gesture_strength=max(0.0, float(base.gesture_strength) * float(spec.gesture_mul)),
        independent=independent,
        optimizer=optimizer,
    )


def generate_candidates(
    data: Mapping,
    base_config: MultiAxisConfig,
    *,
    count: int = 6,
    specs: Sequence[CandidateSpec] | None = None,
    geometry: SR6Geometry | None = None,
    sections: Sequence[Mapping] | None = None,
    weights: QualityWeights | None = None,
    score_transform: Callable[[Mapping[str, Sequence[tuple[float, float]]], MultiAxisConfig], Mapping[str, Sequence[tuple[float, float]]]] | None = None,
) -> list[CandidateResult]:
    """Generate and rank candidates, optionally scoring their effective output.

    ``plan`` stored in CandidateResult remains the raw candidate base plan so it
    can be adopted non-destructively. ``score_transform`` may apply workstation
    gestures, curves, safety shaping and physical constraints to a snapshot for
    ranking. Weak-range scans are intentionally skipped for candidate ranking.
    """
    available = list(specs or default_candidate_specs())
    count = max(1, min(int(count), len(available)))
    results: list[CandidateResult] = []
    for spec in available[:count]:
        config = config_for_candidate(base_config, spec)
        plan = plan_multiaxis(data, config)
        scored_plan = score_transform(plan, config) if score_transform is not None else plan
        report = score_plan(
            scored_plan,
            data,
            sections=sections,
            geometry=geometry or config.geometry,
            mechanical_config=config.mechanical,
            weights=weights,
            compute_windows=False,
        )
        results.append(CandidateResult(spec.name, config, plan, report))
    results.sort(key=lambda item: (-item.quality.overall, item.name))
    return results