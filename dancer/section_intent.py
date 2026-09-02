"""Section-level Motion Intent overrides for PythonDancer 2.7."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .intent import INTENT_FIELDS, IntentEnvelope, MotionIntent


@dataclass(frozen=True)
class SectionIntentOverride:
    start: float
    end: float
    intent: MotionIntent = field(default_factory=MotionIntent)
    amount: float = 1.0
    label: str = ""
    blend_seconds: float = 0.35

    def __post_init__(self):
        start = float(self.start)
        end = float(self.end)
        amount = float(self.amount)
        blend_seconds = float(self.blend_seconds)
        if not np.isfinite(start) or not np.isfinite(end):
            raise ValueError("section intent range must be finite")
        start = max(0.0, start)
        end = max(0.0, end)
        if end <= start:
            raise ValueError("section intent end must be after start")
        if not np.isfinite(amount):
            raise ValueError("section intent amount must be finite")
        if not np.isfinite(blend_seconds) or blend_seconds < 0:
            raise ValueError("section intent blend_seconds must be finite and non-negative")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "amount", float(np.clip(amount, 0.0, 1.0)))
        object.__setattr__(self, "blend_seconds", blend_seconds)
        if not isinstance(self.intent, MotionIntent):
            object.__setattr__(self, "intent", MotionIntent.from_dict(dict(self.intent)))

    def to_dict(self) -> dict[str, object]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "label": self.label,
            "amount": float(self.amount),
            "blend_seconds": float(self.blend_seconds),
            "intent": self.intent.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SectionIntentOverride":
        return cls(
            float(data.get("start", 0.0)),
            float(data.get("end", 0.0)),
            MotionIntent.from_dict(data.get("intent", {}) if isinstance(data.get("intent"), Mapping) else {}),
            float(data.get("amount", 1.0)),
            str(data.get("label", "")),
            float(data.get("blend_seconds", 0.35)),
        )


def _edge_weight(beats: np.ndarray, block: SectionIntentOverride) -> np.ndarray:
    inside = (beats >= block.start) & (beats <= block.end)
    envelope = np.zeros(beats.size, dtype=np.float64)
    envelope[inside] = 1.0
    blend = min(block.blend_seconds, max(0.0, (block.end - block.start) * 0.5))
    if blend > 1e-9:
        left = inside & (beats < block.start + blend)
        right = inside & (beats > block.end - blend)
        envelope[left] *= np.clip((beats[left] - block.start) / blend, 0.0, 1.0)
        envelope[right] *= np.clip((block.end - beats[right]) / blend, 0.0, 1.0)
        envelope = envelope * envelope * (3.0 - 2.0 * envelope)
    return float(block.amount) * envelope


def apply_section_intent_overrides(
    envelope: IntentEnvelope,
    overrides: Sequence[SectionIntentOverride],
) -> IntentEnvelope:
    if not overrides or not envelope.beats:
        return envelope
    beats = np.asarray(envelope.beats, dtype=np.float64)
    fields = {
        name: np.asarray(envelope.fields.get(name, ()), dtype=np.float64).copy()
        for name in INTENT_FIELDS
    }
    for name in INTENT_FIELDS:
        if fields[name].size != beats.size:
            fields[name] = np.full(beats.size, float(getattr(envelope.global_intent, name)), dtype=np.float64)
    for block in sorted(overrides, key=lambda item: (item.start, item.end)):
        alpha = _edge_weight(beats, block)
        if not np.any(alpha > 0):
            continue
        for name in INTENT_FIELDS:
            target = float(getattr(block.intent, name))
            fields[name] = np.clip(fields[name] * (1.0 - alpha) + target * alpha, 0.0, 1.0)
    global_intent = MotionIntent(**{name: float(np.mean(fields[name])) for name in INTENT_FIELDS})
    sections = list(envelope.sections)
    sections.extend({"start": block.start, "end": block.end, "label": block.label, "amount": block.amount, "intent": block.intent.to_dict()} for block in overrides)
    return IntentEnvelope(
        tuple(float(v) for v in beats),
        {name: tuple(float(v) for v in fields[name]) for name in INTENT_FIELDS},
        global_intent,
        tuple(sections),
    )


def overrides_to_dict(values: Sequence[SectionIntentOverride]) -> list[dict[str, object]]:
    return [item.to_dict() for item in values]


def overrides_from_dict(values: Sequence[Mapping[str, object]]) -> tuple[SectionIntentOverride, ...]:
    return tuple(SectionIntentOverride.from_dict(item) for item in values)
