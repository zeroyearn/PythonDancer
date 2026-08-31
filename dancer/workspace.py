"""Non-destructive editing model for PythonDancer's six-axis workstation.

The workspace sits after automatic planning and before export/TCode. It owns
manual sections, gesture overlays, selection, axis visibility/lock state, and
range splicing so GUI edits always affect the effective exported plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .choreography import ChoreographyAnalysis, SECTION_LABELS
from .multiaxis import AXIS_ORDER

GESTURES = ("pulse", "sway", "rock", "circle", "spiral", "wave", "accent")


@dataclass
class TimeRange:
    start: float = 0.0
    end: float = 0.0

    def normalized(self, duration: float | None = None) -> "TimeRange":
        start, end = sorted((float(self.start), float(self.end)))
        if duration is not None:
            start = float(np.clip(start, 0.0, max(0.0, duration)))
            end = float(np.clip(end, 0.0, max(0.0, duration)))
        return TimeRange(start, end)

    @property
    def duration(self) -> float:
        return max(0.0, float(self.end) - float(self.start))

    def to_dict(self) -> dict[str, float]:
        return {"start": float(self.start), "end": float(self.end)}


@dataclass
class SectionBlock:
    start: float
    end: float
    label: str

    def __post_init__(self):
        if self.label not in SECTION_LABELS:
            raise ValueError(f"unknown section label: {self.label}")
        if not np.isfinite(self.start) or not np.isfinite(self.end) or self.end < self.start:
            raise ValueError("invalid section range")

    def to_dict(self) -> dict[str, object]:
        return {"start": float(self.start), "end": float(self.end), "label": self.label}


@dataclass
class GestureBlock:
    start: float
    end: float
    gesture: str
    strength: float = 1.0

    def __post_init__(self):
        if self.gesture not in GESTURES:
            raise ValueError(f"unknown gesture: {self.gesture}")
        if not np.isfinite(self.start) or not np.isfinite(self.end) or self.end <= self.start:
            raise ValueError("gesture end must be after start")
        if not np.isfinite(self.strength) or self.strength < 0:
            raise ValueError("gesture strength must be finite and non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "gesture": self.gesture,
            "strength": float(self.strength),
        }


@dataclass
class AxisControl:
    muted: bool = False
    locked: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {"muted": bool(self.muted), "locked": bool(self.locked)}


def _copy_plan(plan: Mapping[str, Sequence[tuple[float, float]]]) -> dict[str, list[tuple[float, float]]]:
    return {
        axis: [(float(at), float(pos)) for at, pos in plan.get(axis, ())]
        for axis in AXIS_ORDER
    }


def _sample(actions: Sequence[tuple[float, float]], at: float, default: float = 50.0) -> float:
    if not actions:
        return float(default)
    times = np.asarray([item[0] for item in actions], dtype=np.float64)
    values = np.asarray([item[1] for item in actions], dtype=np.float64)
    if times.size == 1:
        return float(values[0])
    return float(np.interp(float(at), times, values, left=values[0], right=values[-1]))


def splice_actions(
    current: Sequence[tuple[float, float]],
    replacement: Sequence[tuple[float, float]],
    start: float,
    end: float,
    *,
    blend: float = 0.25,
) -> list[tuple[float, float]]:
    """Replace one time range and crossfade at both boundaries."""
    start, end = sorted((float(start), float(end)))
    if end <= start:
        return [(float(at), float(pos)) for at, pos in current]
    blend = max(0.0, min(float(blend), (end - start) / 2.0))
    cur = [(float(at), float(pos)) for at, pos in current]
    rep = [(float(at), float(pos)) for at, pos in replacement if start <= float(at) <= end]
    if not rep:
        return cur

    before = [(at, pos) for at, pos in cur if at < start]
    after = [(at, pos) for at, pos in cur if at > end]
    merged: list[tuple[float, float]] = list(before)
    for at, target in rep:
        source = _sample(cur, at, target)
        if blend > 0 and at < start + blend:
            alpha = np.clip((at - start) / blend, 0.0, 1.0)
        elif blend > 0 and at > end - blend:
            alpha = np.clip((end - at) / blend, 0.0, 1.0)
        else:
            alpha = 1.0
        alpha = float(alpha * alpha * (3.0 - 2.0 * alpha))
        merged.append((at, float(np.clip(source * (1.0 - alpha) + target * alpha, 0.0, 100.0))))
    merged.extend(after)
    merged.sort(key=lambda item: item[0])
    deduped: list[tuple[float, float]] = []
    for item in merged:
        if deduped and abs(item[0] - deduped[-1][0]) < 1e-9:
            deduped[-1] = item
        else:
            deduped.append(item)
    return deduped


def splice_plan(
    current: Mapping[str, Sequence[tuple[float, float]]],
    replacement: Mapping[str, Sequence[tuple[float, float]]],
    start: float,
    end: float,
    *,
    locked_axes: Sequence[str] = (),
    blend: float = 0.25,
) -> dict[str, list[tuple[float, float]]]:
    locked = set(locked_axes)
    result = _copy_plan(current)
    for axis in AXIS_ORDER:
        if axis in locked:
            continue
        result[axis] = splice_actions(result[axis], replacement.get(axis, ()), start, end, blend=blend)
    return result


def _gesture_delta(gesture: str, axis: str, phase: np.ndarray) -> np.ndarray:
    tau = 2.0 * np.pi
    if gesture == "pulse":
        weights = {"L0": 0.45, "L1": 0.75, "L2": 0.10, "R0": 0.42, "R1": 0.28, "R2": 0.22}
        return weights[axis] * np.sin(tau * phase * 4.0)
    if gesture == "sway":
        weights = {"L0": 0.0, "L1": 0.10, "L2": 1.0, "R0": 0.18, "R1": -0.72, "R2": 0.08}
        return weights[axis] * np.sin(tau * phase)
    if gesture == "rock":
        weights = {"L0": 0.06, "L1": 0.18, "L2": 0.12, "R0": 0.10, "R1": 0.72, "R2": 0.90}
        return weights[axis] * np.sin(tau * phase)
    if gesture == "circle":
        if axis == "L1":
            return np.cos(tau * phase)
        if axis == "L2":
            return np.sin(tau * phase)
        if axis == "R1":
            return -0.35 * np.sin(tau * phase)
        if axis == "R2":
            return 0.30 * np.cos(tau * phase)
        return 0.12 * np.sin(tau * phase)
    if gesture == "spiral":
        growth = 0.35 + 0.65 * phase
        weights = {"L0": 0.12, "L1": 0.72, "L2": 0.82, "R0": 1.0, "R1": -0.40, "R2": 0.36}
        offsets = {"L0": 0.0, "L1": 0.0, "L2": 0.25, "R0": 0.5, "R1": 0.25, "R2": 0.0}
        return weights[axis] * growth * np.sin(tau * (phase + offsets[axis]))
    if gesture == "wave":
        weights = {"L0": 0.04, "L1": 0.24, "L2": 0.42, "R0": 0.56, "R1": 0.30, "R2": 0.76}
        offsets = {"L0": 0.0, "L1": 0.12, "L2": 0.24, "R0": 0.36, "R1": 0.48, "R2": 0.60}
        return weights[axis] * np.sin(tau * (phase + offsets[axis]))
    if gesture == "accent":
        weights = {"L0": 0.55, "L1": 0.42, "L2": 0.26, "R0": 0.78, "R1": 0.46, "R2": 0.32}
        envelope = np.exp(-8.0 * np.mod(phase * 4.0, 1.0))
        alternating = np.where((phase * 4.0).astype(int) % 2 == 0, 1.0, -1.0)
        return weights[axis] * envelope * alternating
    return np.zeros_like(phase)


def apply_gesture_blocks(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    blocks: Sequence[GestureBlock],
) -> dict[str, list[tuple[float, float]]]:
    result = _copy_plan(plan)
    for block in blocks:
        duration = max(block.end - block.start, 1e-6)
        for axis in AXIS_ORDER:
            actions = result[axis]
            if not actions:
                continue
            times = np.asarray([item[0] for item in actions], dtype=np.float64)
            values = np.asarray([item[1] for item in actions], dtype=np.float64)
            mask = (times >= block.start) & (times <= block.end)
            if not np.any(mask):
                continue
            phase = np.clip((times[mask] - block.start) / duration, 0.0, 1.0)
            edge = np.sin(np.pi * phase) ** 0.6
            delta = _gesture_delta(block.gesture, axis, phase) * edge * 12.0 * float(block.strength)
            values[mask] = np.clip(values[mask] + delta, 0.0, 100.0)
            result[axis] = list(zip(times.tolist(), values.tolist()))
    return result


def sections_from_analysis(
    analysis: ChoreographyAnalysis | None,
    beats: Sequence[float],
    duration: float,
) -> list[SectionBlock]:
    if analysis is None or not analysis.sections:
        return [SectionBlock(0.0, max(0.0, float(duration)), "verse")]
    beat_times = np.asarray(beats, dtype=np.float64).reshape(-1)
    result: list[SectionBlock] = []
    for section in analysis.sections:
        start = float(beat_times[section.start_beat]) if section.start_beat < beat_times.size else 0.0
        if section.end_beat < beat_times.size:
            end = float(beat_times[section.end_beat])
        else:
            end = max(float(duration), float(beat_times[-1]) if beat_times.size else 0.0)
        result.append(SectionBlock(start, max(start, end), section.label))
    if result:
        result[0].start = 0.0
        result[-1].end = max(result[-1].end, float(duration))
    return result


@dataclass
class WorkspaceState:
    duration: float = 0.0
    selection: TimeRange = field(default_factory=TimeRange)
    sections: list[SectionBlock] = field(default_factory=list)
    gestures: list[GestureBlock] = field(default_factory=list)
    axes: dict[str, AxisControl] = field(default_factory=lambda: {axis: AxisControl() for axis in AXIS_ORDER})
    solo_axis: str | None = None

    @classmethod
    def from_analysis(cls, analysis: ChoreographyAnalysis | None, beats: Sequence[float], duration: float) -> "WorkspaceState":
        return cls(duration=float(duration), sections=sections_from_analysis(analysis, beats, duration))

    def set_selection(self, start: float, end: float) -> None:
        self.selection = TimeRange(start, end).normalized(self.duration)

    def locked_axes(self) -> tuple[str, ...]:
        return tuple(axis for axis in AXIS_ORDER if self.axes[axis].locked)

    def set_section_boundary(self, index: int, at: float) -> None:
        if index <= 0 or index >= len(self.sections):
            raise IndexError("section boundary index must be between adjacent sections")
        previous = self.sections[index - 1]
        following = self.sections[index]
        minimum = previous.start + 0.05
        maximum = following.end - 0.05
        value = float(np.clip(at, minimum, maximum))
        previous.end = value
        following.start = value

    def set_section_label(self, index: int, label: str) -> None:
        if label not in SECTION_LABELS:
            raise ValueError(f"unknown section label: {label}")
        self.sections[index].label = label

    def add_gesture(self, start: float, end: float, gesture: str, strength: float = 1.0) -> GestureBlock:
        block = GestureBlock(*TimeRange(start, end).normalized(self.duration).__dict__.values(), gesture, strength)
        self.gestures.append(block)
        self.gestures.sort(key=lambda item: (item.start, item.end))
        return block

    def effective_plan(self, base_plan: Mapping[str, Sequence[tuple[float, float]]]) -> dict[str, list[tuple[float, float]]]:
        result = apply_gesture_blocks(base_plan, self.gestures)
        for axis in AXIS_ORDER:
            muted = self.axes[axis].muted
            hidden_by_solo = self.solo_axis is not None and axis != self.solo_axis
            if muted or hidden_by_solo:
                result[axis] = []
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "duration": float(self.duration),
            "selection": self.selection.to_dict(),
            "sections": [item.to_dict() for item in self.sections],
            "gestures": [item.to_dict() for item in self.gestures],
            "axes": {axis: self.axes[axis].to_dict() for axis in AXIS_ORDER},
            "solo_axis": self.solo_axis,
        }
