"""Continuous motion-intent inference for PythonDancer 2.6.

Motion intent is the semantic bridge between musical analysis and concrete
multi-axis gestures. It intentionally stays deterministic and inspectable: the
values are continuous 0..1 controls that can be stored, edited, blended with a
reference style, and sampled at arbitrary timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .choreography import ChoreographyAnalysis
from .features import safe_normalize

INTENT_FIELDS = (
    "intensity",
    "aggression",
    "flow",
    "complexity",
    "symmetry",
    "rotation_bias",
    "translation_bias",
    "accent_density",
)


def _feature(data: Mapping, name: str, count: int, fallback: str | None = None) -> np.ndarray:
    value = data.get(name)
    if value is None and fallback:
        value = data.get(fallback)
    if value is None:
        return np.zeros(count, dtype=np.float64)
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.size < count:
        array = np.pad(array, (0, count - array.size), mode="edge" if array.size else "constant")
    return safe_normalize(array[:count])


@dataclass(frozen=True)
class MotionIntent:
    intensity: float = 0.5
    aggression: float = 0.5
    flow: float = 0.5
    complexity: float = 0.5
    symmetry: float = 0.5
    rotation_bias: float = 0.5
    translation_bias: float = 0.5
    accent_density: float = 0.5

    def __post_init__(self):
        for field in INTENT_FIELDS:
            value = float(getattr(self, field))
            object.__setattr__(self, field, float(np.clip(value if np.isfinite(value) else 0.5, 0.0, 1.0)))

    def to_dict(self) -> dict[str, float]:
        return {field: float(getattr(self, field)) for field in INTENT_FIELDS}

    @classmethod
    def from_dict(cls, payload: Mapping) -> "MotionIntent":
        return cls(**{field: payload.get(field, 0.5) for field in INTENT_FIELDS})

    def blend(self, other: "MotionIntent", amount: float) -> "MotionIntent":
        alpha = float(np.clip(amount, 0.0, 1.0))
        return MotionIntent(**{
            field: (1.0 - alpha) * float(getattr(self, field)) + alpha * float(getattr(other, field))
            for field in INTENT_FIELDS
        })


@dataclass(frozen=True)
class IntentEnvelope:
    beats: tuple[float, ...]
    fields: Mapping[str, tuple[float, ...]]
    global_intent: MotionIntent
    sections: tuple[dict[str, object], ...] = ()

    def sample(self, times: Sequence[float]) -> dict[str, np.ndarray]:
        target = np.asarray(times, dtype=np.float64).reshape(-1)
        beats = np.asarray(self.beats, dtype=np.float64)
        result: dict[str, np.ndarray] = {}
        for field in INTENT_FIELDS:
            values = np.asarray(self.fields.get(field, ()), dtype=np.float64)
            if target.size == 0:
                result[field] = np.asarray([], dtype=np.float64)
            elif beats.size == 0 or values.size == 0:
                result[field] = np.full(target.size, float(getattr(self.global_intent, field)), dtype=np.float64)
            elif beats.size == 1:
                result[field] = np.full(target.size, float(values[0]), dtype=np.float64)
            else:
                n = min(beats.size, values.size)
                result[field] = np.interp(target, beats[:n], values[:n], left=float(values[0]), right=float(values[n - 1]))
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "version": "1.0",
            "global": self.global_intent.to_dict(),
            "beats": list(self.beats),
            "fields": {key: list(value) for key, value in self.fields.items()},
            "sections": [dict(item) for item in self.sections],
        }


def infer_motion_intent(data: Mapping, analysis: ChoreographyAnalysis | None = None) -> IntentEnvelope:
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    count = beats.size
    if count == 0:
        neutral = MotionIntent()
        return IntentEnvelope((), {field: () for field in INTENT_FIELDS}, neutral, ())

    energy = _feature(data, "energy", count)
    onset = _feature(data, "onset", count, "energy")
    percussive = _feature(data, "percussive", count, "onset")
    bass = _feature(data, "bass", count, "energy")
    mid = _feature(data, "mid", count, "energy")
    high = _feature(data, "high", count, "energy")
    harmonic = _feature(data, "harmonic", count, "pitch")
    pitch = _feature(data, "pitch", count)

    drums = _feature(data, "stem_drums_energy", count, "percussive")
    drums_onset = _feature(data, "stem_drums_onset", count, "onset")
    bass_stem = _feature(data, "stem_bass_energy", count, "bass")
    vocal = _feature(data, "stem_vocals_energy", count, "harmonic")
    vocal_pitch = _feature(data, "stem_vocals_pitch", count, "pitch")
    other = _feature(data, "stem_other_energy", count, "mid")

    novelty = np.zeros(count, dtype=np.float64)
    if count > 1:
        matrix = np.vstack((energy, onset, bass, mid, high, harmonic, pitch)).T
        novelty[1:] = np.mean(np.abs(np.diff(matrix, axis=0)), axis=1)
        novelty = safe_normalize(novelty)

    pitch_motion = np.zeros(count, dtype=np.float64)
    if count > 1:
        pitch_motion[1:] = np.abs(np.diff(vocal_pitch))
        pitch_motion = safe_normalize(pitch_motion)

    intensity = np.clip(.32 * energy + .22 * drums + .18 * bass_stem + .14 * vocal + .14 * onset, 0., 1.)
    aggression = np.clip(.38 * drums_onset + .26 * percussive + .20 * high + .16 * bass_stem, 0., 1.)
    flow = np.clip(.34 * harmonic + .24 * vocal + .18 * other + .14 * (1. - drums_onset) + .10 * (1. - novelty), 0., 1.)
    complexity = np.clip(.34 * novelty + .22 * high + .18 * pitch_motion + .14 * onset + .12 * mid, 0., 1.)
    symmetry = np.clip(.58 * (1. - novelty) + .24 * harmonic + .18 * (1. - aggression), 0., 1.)
    rotation_bias = np.clip(.34 * vocal_pitch + .24 * vocal + .18 * high + .14 * harmonic + .10 * complexity, 0., 1.)
    translation_bias = np.clip(.34 * bass_stem + .26 * drums + .18 * energy + .12 * other + .10 * (1. - rotation_bias), 0., 1.)
    accent_density = np.clip(.46 * drums_onset + .24 * onset + .18 * percussive + .12 * novelty, 0., 1.)

    arrays = {
        "intensity": intensity,
        "aggression": aggression,
        "flow": flow,
        "complexity": complexity,
        "symmetry": symmetry,
        "rotation_bias": rotation_bias,
        "translation_bias": translation_bias,
        "accent_density": accent_density,
    }
    global_intent = MotionIntent(**{field: float(np.mean(values)) for field, values in arrays.items()})

    sections: list[dict[str, object]] = []
    if analysis is not None:
        for section in analysis.sections:
            start = max(0, min(count, int(section.start_beat)))
            end = max(start + 1, min(count, int(section.end_beat)))
            section_intent = MotionIntent(**{field: float(np.mean(values[start:end])) for field, values in arrays.items()})
            sections.append({
                "start_beat": start,
                "end_beat": end,
                "label": section.label,
                "intent": section_intent.to_dict(),
            })

    return IntentEnvelope(
        tuple(float(value) for value in beats),
        {field: tuple(float(value) for value in values) for field, values in arrays.items()},
        global_intent,
        tuple(sections),
    )
