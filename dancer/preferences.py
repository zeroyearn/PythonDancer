"""Online preference learning and personalized quality weighting for PythonDancer 3.0."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping

import numpy as np

from .quality import METRICS, QualityReport, QualityWeights


DEFAULT_TRAITS = (
    "flow",
    "rotation",
    "translation",
    "aggression",
    "complexity",
    "accent_density",
    "symmetry",
)


@dataclass(frozen=True)
class PreferenceEvent:
    selected: str
    rejected: str
    selected_features: Mapping[str, float]
    rejected_features: Mapping[str, float]
    section: str = ""
    source: str = "candidate-choice"

    def to_dict(self):
        return {
            "selected": self.selected,
            "rejected": self.rejected,
            "selected_features": dict(self.selected_features),
            "rejected_features": dict(self.rejected_features),
            "section": self.section,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            selected=str(payload.get("selected", "selected")),
            rejected=str(payload.get("rejected", "rejected")),
            selected_features={str(k): float(v) for k, v in dict(payload.get("selected_features") or {}).items()},
            rejected_features={str(k): float(v) for k, v in dict(payload.get("rejected_features") or {}).items()},
            section=str(payload.get("section", "")),
            source=str(payload.get("source", "candidate-choice")),
        )


@dataclass
class PreferenceModel:
    """Small online pairwise-ranking model.

    The model is deliberately local and deterministic: every explicit A/B choice
    updates feature weights in the direction of the selected candidate. It does
    not require cloud training and can be serialized inside a project/profile.
    """

    quality_weights: dict[str, float] = field(default_factory=lambda: QualityWeights().as_dict())
    trait_weights: dict[str, float] = field(default_factory=lambda: {name: 1.0 for name in DEFAULT_TRAITS})
    learning_rate: float = 0.08
    observations: int = 0
    events: list[PreferenceEvent] = field(default_factory=list)

    def __post_init__(self):
        defaults = QualityWeights().as_dict()
        self.quality_weights = {
            name: float(np.clip(dict(self.quality_weights or {}).get(name, defaults[name]), .10, 4.0))
            for name in METRICS
        }
        self.trait_weights = {
            name: float(np.clip(dict(self.trait_weights or {}).get(name, 1.0), .10, 4.0))
            for name in DEFAULT_TRAITS
        }
        self.learning_rate = float(np.clip(self.learning_rate, .001, .5))
        self.observations = max(0, int(self.observations))
        self.events = [item if isinstance(item, PreferenceEvent) else PreferenceEvent.from_dict(item) for item in self.events]

    def _update_group(self, target: dict[str, float], selected: Mapping[str, float], rejected: Mapping[str, float]):
        for name in tuple(target):
            delta = float(selected.get(name, 0.0)) - float(rejected.get(name, 0.0))
            # Feature values may be 0..1 or 0..100. Normalize large deltas.
            if abs(delta) > 2.0:
                delta /= 100.0
            target[name] = float(np.clip(target[name] + self.learning_rate * delta, .10, 4.0))
        mean = float(np.mean(list(target.values()))) if target else 1.0
        if mean > 1e-9:
            for name in tuple(target):
                target[name] = float(np.clip(target[name] / mean, .10, 4.0))

    def update(self, event: PreferenceEvent):
        self._update_group(self.quality_weights, event.selected_features, event.rejected_features)
        self._update_group(self.trait_weights, event.selected_features, event.rejected_features)
        self.observations += 1
        self.events.append(event)
        if len(self.events) > 500:
            del self.events[:-500]

    def record_reports(self, selected_name: str, selected: QualityReport, rejected_name: str, rejected: QualityReport, *, section=""):
        event = PreferenceEvent(
            selected=selected_name,
            rejected=rejected_name,
            selected_features=dict(selected.metrics),
            rejected_features=dict(rejected.metrics),
            section=section,
        )
        self.update(event)
        return event

    def as_quality_weights(self) -> QualityWeights:
        return QualityWeights(**{name: self.quality_weights[name] for name in METRICS})

    def personalized_score(self, report: QualityReport) -> float:
        weights = self.quality_weights
        numerator = sum(float(report.metrics.get(name, 0.0)) * weights[name] for name in METRICS)
        denominator = sum(weights.values()) or 1.0
        return float(np.clip(numerator / denominator, 0.0, 100.0))

    def trait_match(self, traits: Mapping[str, float]) -> float:
        if not traits:
            return 50.0
        values = []
        for name, weight in self.trait_weights.items():
            if name in traits:
                value = float(traits[name])
                if abs(value) <= 2.0:
                    value *= 100.0
                values.append(value * weight)
        if not values:
            return 50.0
        denominator = sum(self.trait_weights[name] for name in self.trait_weights if name in traits) or 1.0
        return float(np.clip(sum(values) / denominator, 0.0, 100.0))

    def to_dict(self):
        return {
            "version": "1.0",
            "quality_weights": dict(self.quality_weights),
            "trait_weights": dict(self.trait_weights),
            "learning_rate": self.learning_rate,
            "observations": self.observations,
            "events": [event.to_dict() for event in self.events[-100:]],
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls(
            quality_weights=dict(payload.get("quality_weights") or {}),
            trait_weights=dict(payload.get("trait_weights") or {}),
            learning_rate=float(payload.get("learning_rate", .08)),
            observations=int(payload.get("observations", 0)),
            events=[PreferenceEvent.from_dict(item) for item in payload.get("events", ())],
        )


def load_preference_model(path: str | Path) -> PreferenceModel:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("preference profile must contain a JSON object")
    return PreferenceModel.from_dict(payload)


def save_preference_model(path: str | Path, model: PreferenceModel) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return target
