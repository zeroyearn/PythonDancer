"""Section-level motion retrieval for PythonDancer 3.0.

The index stores compact musical/motion descriptors and retrieves the most
similar reference section without depending on an external vector database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .multiaxis import AXIS_ORDER


FEATURES = (
    "bpm",
    "energy",
    "bass",
    "vocal",
    "high",
    "duration",
    "rotation",
    "translation",
    "complexity",
)

SCALES = {
    "bpm": 180.0,
    "energy": 1.0,
    "bass": 1.0,
    "vocal": 1.0,
    "high": 1.0,
    "duration": 30.0,
    "rotation": 1.0,
    "translation": 1.0,
    "complexity": 1.0,
}


def feature_vector(features: Mapping[str, float]) -> np.ndarray:
    values = []
    for name in FEATURES:
        value = float(features.get(name, 0.0))
        scale = float(SCALES[name])
        values.append(value / scale)
    vector = np.asarray(values, dtype=np.float64)
    vector[~np.isfinite(vector)] = 0.0
    return vector


def plan_motion_features(plan: Mapping[str, Sequence[tuple[float, float]]], *, duration: float = 0.0) -> dict[str, float]:
    activity = {}
    total_points = 0
    for axis in AXIS_ORDER:
        rows = sorted((float(t), float(p)) for t, p in plan.get(axis, ()))
        total_points += len(rows)
        if len(rows) < 2:
            activity[axis] = 0.0
            continue
        dt = np.diff(np.asarray([item[0] for item in rows], dtype=np.float64))
        dp = np.diff(np.asarray([item[1] for item in rows], dtype=np.float64))
        valid = dt > 1e-6
        activity[axis] = float(np.mean(np.abs(dp[valid] / dt[valid]))) if np.any(valid) else 0.0
        duration = max(duration, rows[-1][0])
    rotation = float(np.mean([activity.get(axis, 0.0) for axis in ("R0", "R1", "R2")])) / 100.0
    translation = float(np.mean([activity.get(axis, 0.0) for axis in ("L0", "L1", "L2")])) / 100.0
    complexity = min(1.0, total_points / max(1.0, duration * len(AXIS_ORDER) * 20.0))
    return {"duration": duration, "rotation": rotation, "translation": translation, "complexity": complexity}


@dataclass(frozen=True)
class ReferenceSection:
    identifier: str
    label: str
    features: Mapping[str, float]
    source: str = ""
    payload: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self):
        return {
            "identifier": self.identifier,
            "label": self.label,
            "features": {str(k): float(v) for k, v in self.features.items()},
            "source": self.source,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            identifier=str(payload.get("identifier", "reference")),
            label=str(payload.get("label", "section")),
            features={str(k): float(v) for k, v in dict(payload.get("features") or {}).items()},
            source=str(payload.get("source", "")),
            payload=dict(payload.get("payload") or {}),
        )


@dataclass(frozen=True)
class RetrievalMatch:
    reference: ReferenceSection
    similarity: float

    def to_dict(self):
        return {"similarity": self.similarity, "reference": self.reference.to_dict()}


@dataclass
class ReferenceSectionIndex:
    sections: list[ReferenceSection] = field(default_factory=list)

    def add(self, section: ReferenceSection):
        self.sections = [item for item in self.sections if item.identifier != section.identifier]
        self.sections.append(section)

    def query(self, features: Mapping[str, float], *, top_k: int = 5, label: str | None = None) -> tuple[RetrievalMatch, ...]:
        target = feature_vector(features)
        target_norm = float(np.linalg.norm(target))
        candidates = []
        for section in self.sections:
            if label and section.label.lower() != str(label).lower():
                continue
            vector = feature_vector(section.features)
            denom = target_norm * float(np.linalg.norm(vector))
            similarity = float(np.dot(target, vector) / denom) if denom > 1e-12 else 0.0
            # Keep cosine in an intuitive 0..1 range.
            similarity = float(np.clip((similarity + 1.0) * .5, 0.0, 1.0))
            candidates.append(RetrievalMatch(section, similarity))
        candidates.sort(key=lambda item: (-item.similarity, item.reference.identifier))
        return tuple(candidates[:max(1, int(top_k))])

    def to_dict(self):
        return {"version": "1.0", "sections": [item.to_dict() for item in self.sections]}

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls([ReferenceSection.from_dict(item) for item in payload.get("sections", ())])


def adapt_reference_plan(plan, *, source_duration: float, target_duration: float, amplitude: float = 1.0):
    source_duration = max(float(source_duration), 1e-6)
    target_duration = max(float(target_duration), 1e-6)
    time_scale = target_duration / source_duration
    amplitude = float(np.clip(amplitude, 0.0, 2.0))
    result = {}
    for axis in AXIS_ORDER:
        result[axis] = [
            (float(t) * time_scale, float(np.clip(50.0 + (float(p) - 50.0) * amplitude, 0.0, 100.0)))
            for t, p in plan.get(axis, ())
        ]
    return result


def load_reference_index(path: str | Path) -> ReferenceSectionIndex:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("reference index must contain a JSON object")
    return ReferenceSectionIndex.from_dict(payload)


def save_reference_index(path: str | Path, index: ReferenceSectionIndex) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return target
