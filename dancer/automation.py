"""DAW-style parameter automation and style morphing for PythonDancer 2.8."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .intent import MotionIntent


def _smoothstep(value: float) -> float:
    x = float(np.clip(value, 0.0, 1.0))
    return x * x * (3.0 - 2.0 * x)


def _ease(alpha: float, easing: str) -> float:
    value = float(np.clip(alpha, 0.0, 1.0))
    mode = str(easing or "linear").lower()
    if mode in ("smooth", "smoothstep", "ease-in-out"):
        return _smoothstep(value)
    if mode in ("ease-in", "in"):
        return value * value
    if mode in ("ease-out", "out"):
        return 1.0 - (1.0 - value) ** 2
    return value


@dataclass(frozen=True, order=True)
class AutomationPoint:
    time: float
    value: float
    easing: str = "linear"

    def __post_init__(self):
        time = float(self.time)
        value = float(self.value)
        if not np.isfinite(time) or time < 0:
            raise ValueError("automation point time must be finite and non-negative")
        if not np.isfinite(value):
            raise ValueError("automation point value must be finite")
        object.__setattr__(self, "time", time)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "easing", str(self.easing or "linear"))

    def to_dict(self):
        return {"time": self.time, "value": self.value, "easing": self.easing}

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(payload.get("time", 0.0), payload.get("value", 0.0), payload.get("easing", "linear"))


@dataclass
class AutomationLane:
    name: str
    minimum: float = 0.0
    maximum: float = 1.0
    default: float = 0.5
    points: list[AutomationPoint] = field(default_factory=list)

    def __post_init__(self):
        self.minimum = float(self.minimum)
        self.maximum = float(self.maximum)
        self.default = float(self.default)
        if not all(np.isfinite(value) for value in (self.minimum, self.maximum, self.default)):
            raise ValueError("automation lane bounds must be finite")
        if self.maximum <= self.minimum:
            raise ValueError("automation lane maximum must exceed minimum")
        self.default = float(np.clip(self.default, self.minimum, self.maximum))
        self.points = sorted(
            [point if isinstance(point, AutomationPoint) else AutomationPoint.from_dict(point) for point in self.points],
            key=lambda point: point.time,
        )

    def set_point(self, time: float, value: float, *, easing: str = "linear", tolerance: float = 1e-6):
        point = AutomationPoint(float(time), float(np.clip(value, self.minimum, self.maximum)), easing)
        self.points = [item for item in self.points if abs(item.time - point.time) > tolerance]
        self.points.append(point)
        self.points.sort(key=lambda item: item.time)
        return point

    def remove_near(self, time: float, tolerance: float = .05) -> bool:
        before = len(self.points)
        self.points = [point for point in self.points if abs(point.time - float(time)) > float(tolerance)]
        return len(self.points) != before

    def quantize(self, grid: Sequence[float]):
        targets = np.asarray(list(grid), dtype=np.float64)
        if targets.size == 0:
            return
        targets = targets[np.isfinite(targets)]
        if targets.size == 0:
            return
        dedup: dict[float, AutomationPoint] = {}
        for point in self.points:
            index = int(np.argmin(np.abs(targets - point.time)))
            at = float(max(0.0, targets[index]))
            dedup[at] = AutomationPoint(at, point.value, point.easing)
        self.points = [dedup[key] for key in sorted(dedup)]

    def sample(self, time: float) -> float:
        at = float(time)
        if not self.points:
            return self.default
        if at <= self.points[0].time:
            return float(np.clip(self.points[0].value, self.minimum, self.maximum))
        if at >= self.points[-1].time:
            return float(np.clip(self.points[-1].value, self.minimum, self.maximum))
        for left, right in zip(self.points[:-1], self.points[1:]):
            if left.time <= at <= right.time:
                span = max(right.time - left.time, 1e-9)
                alpha = _ease((at - left.time) / span, right.easing)
                value = left.value + (right.value - left.value) * alpha
                return float(np.clip(value, self.minimum, self.maximum))
        return self.default

    def sample_many(self, times: Sequence[float]) -> np.ndarray:
        return np.asarray([self.sample(time) for time in times], dtype=np.float64)

    def to_dict(self):
        return {
            "name": self.name,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "default": self.default,
            "points": [point.to_dict() for point in self.points],
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            name=str(payload.get("name", "automation")),
            minimum=float(payload.get("minimum", 0.0)),
            maximum=float(payload.get("maximum", 1.0)),
            default=float(payload.get("default", .5)),
            points=[AutomationPoint.from_dict(item) for item in payload.get("points", [])],
        )


DEFAULT_LANES = {
    "energy": (0.0, 1.5, 1.0),
    "stroke_depth": (0.0, 1.5, 1.0),
    "rotation_mix": (0.0, 1.5, 1.0),
    "gesture_density": (0.0, 2.0, 1.0),
    "smoothing": (0.0, 1.0, 0.0),
    "complexity": (0.0, 1.0, .5),
    "safety_aggressiveness": (0.0, 1.0, .5),
}


@dataclass
class AutomationSet:
    lanes: dict[str, AutomationLane] = field(default_factory=dict)

    def __post_init__(self):
        normalized = {}
        for name, (low, high, default) in DEFAULT_LANES.items():
            value = self.lanes.get(name)
            normalized[name] = value if isinstance(value, AutomationLane) else (
                AutomationLane.from_dict(value) if value else AutomationLane(name, low, high, default)
            )
        for name, lane in self.lanes.items():
            if name not in normalized:
                normalized[name] = lane if isinstance(lane, AutomationLane) else AutomationLane.from_dict(lane)
        self.lanes = normalized

    @property
    def active(self) -> bool:
        return any(lane.points for lane in self.lanes.values())

    def sample(self, time: float) -> dict[str, float]:
        return {name: lane.sample(time) for name, lane in self.lanes.items()}

    def to_dict(self):
        return {"version": "1.0", "lanes": {name: lane.to_dict() for name, lane in self.lanes.items()}}

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls({name: AutomationLane.from_dict(value) for name, value in dict(payload.get("lanes", {})).items()})


@dataclass(frozen=True)
class StyleKeyframe:
    time: float
    name: str
    intent: MotionIntent = MotionIntent()
    strength: float = 1.0
    easing: str = "smoothstep"

    def __post_init__(self):
        if not np.isfinite(self.time) or float(self.time) < 0:
            raise ValueError("style keyframe time must be finite and non-negative")
        if not np.isfinite(self.strength) or float(self.strength) < 0:
            raise ValueError("style strength must be finite and non-negative")
        object.__setattr__(self, "time", float(self.time))
        object.__setattr__(self, "strength", float(self.strength))
        if not isinstance(self.intent, MotionIntent):
            object.__setattr__(self, "intent", MotionIntent.from_dict(self.intent))

    def to_dict(self):
        return {
            "time": self.time,
            "name": self.name,
            "intent": self.intent.to_dict(),
            "strength": self.strength,
            "easing": self.easing,
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            float(payload.get("time", 0.0)),
            str(payload.get("name", "Style")),
            MotionIntent.from_dict(payload.get("intent", {})),
            float(payload.get("strength", 1.0)),
            str(payload.get("easing", "smoothstep")),
        )


@dataclass
class StyleMorphTimeline:
    keyframes: list[StyleKeyframe] = field(default_factory=list)

    def __post_init__(self):
        self.keyframes = sorted(
            [item if isinstance(item, StyleKeyframe) else StyleKeyframe.from_dict(item) for item in self.keyframes],
            key=lambda item: item.time,
        )

    @property
    def active(self) -> bool:
        return bool(self.keyframes)

    def sample(self, time: float) -> tuple[MotionIntent, float, str]:
        if not self.keyframes:
            return MotionIntent(), 1.0, "Default"
        at = float(time)
        if at <= self.keyframes[0].time:
            item = self.keyframes[0]
            return item.intent, item.strength, item.name
        if at >= self.keyframes[-1].time:
            item = self.keyframes[-1]
            return item.intent, item.strength, item.name
        for left, right in zip(self.keyframes[:-1], self.keyframes[1:]):
            if left.time <= at <= right.time:
                span = max(right.time - left.time, 1e-9)
                alpha = _ease((at - left.time) / span, right.easing)
                intent = left.intent.blend(right.intent, alpha)
                strength = left.strength + (right.strength - left.strength) * alpha
                name = left.name if alpha < .5 else right.name
                return intent, float(strength), name
        item = self.keyframes[-1]
        return item.intent, item.strength, item.name

    def intent_overrides(self, sections: Sequence) -> list[dict[str, object]]:
        result = []
        for index, section in enumerate(sections):
            start = float(getattr(section, "start", section.get("start", 0.0) if isinstance(section, Mapping) else 0.0))
            end = float(getattr(section, "end", section.get("end", start) if isinstance(section, Mapping) else start))
            middle = (start + end) * .5
            intent, strength, name = self.sample(middle)
            result.append({
                "section_index": index,
                "start": start,
                "end": end,
                "style": name,
                "intent": intent.to_dict(),
                "strength": strength,
            })
        return result

    def to_dict(self):
        return {"version": "1.0", "keyframes": [item.to_dict() for item in self.keyframes]}

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls([StyleKeyframe.from_dict(item) for item in payload.get("keyframes", [])])
