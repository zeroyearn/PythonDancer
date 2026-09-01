"""Non-destructive editing model for PythonDancer's six-axis workstation."""
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
    axis_mix: Mapping[str, float] = field(default_factory=dict)
    phase_offset: float = 0.0
    cycles: float = 1.0
    direction: int = 1
    blend_in: float = 0.12
    blend_out: float = 0.12

    def __post_init__(self):
        if self.gesture not in GESTURES:
            raise ValueError(f"unknown gesture: {self.gesture}")
        if not np.isfinite(self.start) or not np.isfinite(self.end) or self.end <= self.start:
            raise ValueError("gesture end must be after start")
        if not np.isfinite(self.strength) or self.strength < 0:
            raise ValueError("gesture strength must be finite and non-negative")
        if not np.isfinite(self.cycles) or self.cycles <= 0:
            raise ValueError("gesture cycles must be positive")
        if self.direction not in (-1, 1):
            raise ValueError("gesture direction must be -1 or 1")
        clean_mix = {}
        for axis, value in dict(self.axis_mix or {}).items():
            if axis not in AXIS_ORDER:
                continue
            number = float(value)
            if np.isfinite(number):
                clean_mix[axis] = float(np.clip(number, -3.0, 3.0))
        self.axis_mix = clean_mix
        self.phase_offset = float(self.phase_offset) % 1.0
        self.blend_in = float(np.clip(self.blend_in, 0.0, 0.5))
        self.blend_out = float(np.clip(self.blend_out, 0.0, 0.5))

    def axis_multiplier(self, axis: str) -> float:
        return float(self.axis_mix.get(axis, 1.0))

    def to_dict(self) -> dict[str, object]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "gesture": self.gesture,
            "strength": float(self.strength),
            "axis_mix": dict(self.axis_mix),
            "phase_offset": float(self.phase_offset),
            "cycles": float(self.cycles),
            "direction": int(self.direction),
            "blend_in": float(self.blend_in),
            "blend_out": float(self.blend_out),
        }


@dataclass
class AxisControl:
    muted: bool = False
    locked: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {"muted": bool(self.muted), "locked": bool(self.locked)}


def copy_plan(plan: Mapping[str, Sequence[tuple[float, float]]]) -> dict[str, list[tuple[float, float]]]:
    return {axis: [(float(at), float(pos)) for at, pos in plan.get(axis, ())] for axis in AXIS_ORDER}


def sample_axis(actions: Sequence[tuple[float, float]], at: float, default: float = 50.0) -> float:
    if not actions:
        return float(default)
    times = np.asarray([item[0] for item in actions], dtype=np.float64)
    values = np.asarray([item[1] for item in actions], dtype=np.float64)
    if times.size == 1:
        return float(values[0])
    return float(np.interp(float(at), times, values, left=values[0], right=values[-1]))


def splice_actions(current, replacement, start: float, end: float, *, blend: float = 0.25) -> list[tuple[float, float]]:
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
    merged = list(before)
    for at, target in rep:
        source = sample_axis(cur, at, target)
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
    deduped = []
    for item in merged:
        if deduped and abs(item[0] - deduped[-1][0]) < 1e-9:
            deduped[-1] = item
        else:
            deduped.append(item)
    return deduped


def splice_plan(current, replacement, start: float, end: float, *, locked_axes: Sequence[str] = (), blend: float = 0.25):
    locked = set(locked_axes)
    result = copy_plan(current)
    for axis in AXIS_ORDER:
        if axis not in locked:
            result[axis] = splice_actions(result[axis], replacement.get(axis, ()), start, end, blend=blend)
    return result


def _gesture_delta(gesture: str, axis: str, phase: np.ndarray) -> np.ndarray:
    tau = 2.0 * np.pi
    if gesture == "pulse":
        weights = {"L0": .45, "L1": .75, "L2": .10, "R0": .42, "R1": .28, "R2": .22}
        return weights[axis] * np.sin(tau * phase * 4.0)
    if gesture == "sway":
        weights = {"L0": 0., "L1": .10, "L2": 1., "R0": .18, "R1": -.72, "R2": .08}
        return weights[axis] * np.sin(tau * phase)
    if gesture == "rock":
        weights = {"L0": .06, "L1": .18, "L2": .12, "R0": .10, "R1": .72, "R2": .90}
        return weights[axis] * np.sin(tau * phase)
    if gesture == "circle":
        if axis == "L1": return np.cos(tau * phase)
        if axis == "L2": return np.sin(tau * phase)
        if axis == "R1": return -.35 * np.sin(tau * phase)
        if axis == "R2": return .30 * np.cos(tau * phase)
        return .12 * np.sin(tau * phase)
    if gesture == "spiral":
        growth = .35 + .65 * np.mod(phase, 1.0)
        weights = {"L0": .12, "L1": .72, "L2": .82, "R0": 1., "R1": -.40, "R2": .36}
        offsets = {"L0": 0., "L1": 0., "L2": .25, "R0": .5, "R1": .25, "R2": 0.}
        return weights[axis] * growth * np.sin(tau * (phase + offsets[axis]))
    if gesture == "wave":
        weights = {"L0": .04, "L1": .24, "L2": .42, "R0": .56, "R1": .30, "R2": .76}
        offsets = {"L0": 0., "L1": .12, "L2": .24, "R0": .36, "R1": .48, "R2": .60}
        return weights[axis] * np.sin(tau * (phase + offsets[axis]))
    if gesture == "accent":
        weights = {"L0": .55, "L1": .42, "L2": .26, "R0": .78, "R1": .46, "R2": .32}
        envelope = np.exp(-8.0 * np.mod(phase * 4.0, 1.0))
        alternating = np.where((phase * 4.0).astype(int) % 2 == 0, 1.0, -1.0)
        return weights[axis] * envelope * alternating
    return np.zeros_like(phase)


def apply_gesture_blocks(plan, blocks: Sequence[GestureBlock]):
    result = copy_plan(plan)
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
            local = np.clip((times[mask] - block.start) / duration, 0.0, 1.0)
            phase = np.mod(block.phase_offset + block.direction * block.cycles * local, 1.0)
            edge = np.ones_like(local)
            if block.blend_in > 0:
                edge *= np.clip(local / block.blend_in, 0.0, 1.0)
            if block.blend_out > 0:
                edge *= np.clip((1.0 - local) / block.blend_out, 0.0, 1.0)
            edge = edge * edge * (3.0 - 2.0 * edge)
            delta = _gesture_delta(block.gesture, axis, phase) * block.axis_multiplier(axis)
            values[mask] = np.clip(values[mask] + delta * edge * 12.0 * block.strength, 0., 100.)
            result[axis] = list(zip(times.tolist(), values.tolist()))
    return result


def sections_from_analysis(analysis: ChoreographyAnalysis | None, beats: Sequence[float], duration: float) -> list[SectionBlock]:
    if analysis is None or not analysis.sections:
        return [SectionBlock(0.0, max(0.0, float(duration)), "verse")]
    beat_times = np.asarray(beats, dtype=np.float64).reshape(-1)
    result = []
    for section in analysis.sections:
        start = float(beat_times[section.start_beat]) if section.start_beat < beat_times.size else 0.0
        end = float(beat_times[section.end_beat]) if section.end_beat < beat_times.size else max(float(duration), float(beat_times[-1]) if beat_times.size else 0.0)
        result.append(SectionBlock(start, max(start, end), section.label))
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
    def from_analysis(cls, analysis, beats: Sequence[float], duration: float) -> "WorkspaceState":
        return cls(duration=float(duration), sections=sections_from_analysis(analysis, beats, duration))

    def set_selection(self, start: float, end: float) -> None:
        self.selection = TimeRange(start, end).normalized(self.duration)

    def locked_axes(self) -> tuple[str, ...]:
        return tuple(axis for axis in AXIS_ORDER if self.axes[axis].locked)

    def set_section_boundary(self, index: int, at: float) -> None:
        if index <= 0 or index >= len(self.sections):
            raise IndexError("section boundary index must be between adjacent sections")
        previous, following = self.sections[index - 1], self.sections[index]
        value = float(np.clip(at, previous.start + .05, following.end - .05))
        previous.end = value
        following.start = value

    def set_section_label(self, index: int, label: str) -> None:
        if label not in SECTION_LABELS:
            raise ValueError(f"unknown section label: {label}")
        self.sections[index].label = label

    def add_gesture(
        self,
        start: float,
        end: float,
        gesture: str,
        strength: float = 1.0,
        **kwargs,
    ) -> GestureBlock:
        selected = TimeRange(start, end).normalized(self.duration)
        block = GestureBlock(selected.start, selected.end, gesture, strength, **kwargs)
        self.gestures.append(block)
        self.gestures.sort(key=lambda item: (item.start, item.end))
        return block

    def output_plan(self, base_plan):
        """Plan used for export/device. Solo is intentionally preview-only."""
        result = apply_gesture_blocks(base_plan, self.gestures)
        for axis in AXIS_ORDER:
            if self.axes[axis].muted:
                result[axis] = []
        return result

    def preview_plan(self, base_plan):
        result = self.output_plan(base_plan)
        if self.solo_axis is not None:
            for axis in AXIS_ORDER:
                if axis != self.solo_axis:
                    result[axis] = []
        return result

    effective_plan = output_plan

    def to_dict(self) -> dict[str, object]:
        return {
            "duration": float(self.duration),
            "selection": self.selection.to_dict(),
            "sections": [item.to_dict() for item in self.sections],
            "gestures": [item.to_dict() for item in self.gestures],
            "axes": {axis: self.axes[axis].to_dict() for axis in AXIS_ORDER},
            "solo_axis": self.solo_axis,
        }
