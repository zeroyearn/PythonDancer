"""High-level motion grammar and deterministic six-axis compiler for PythonDancer 3.0.

The grammar is intentionally device-agnostic. It produces canonical 0..100
motion only; Device Twin, mechanical projection and optimizer passes remain the
authoritative physical safety layer downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import pi
from typing import Mapping, Sequence

import numpy as np

from .multiaxis import AXIS_ORDER


PRIMITIVES = (
    "hold",
    "drift",
    "pulse",
    "wave",
    "spiral",
    "orbit",
    "rock",
    "sweep",
    "twist",
    "accent",
    "recoil",
)


def _smoothstep(x):
    value = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _edge_envelope(alpha: np.ndarray, blend_in: float, blend_out: float) -> np.ndarray:
    result = np.ones_like(alpha)
    if blend_in > 1e-9:
        result *= _smoothstep(alpha / blend_in)
    if blend_out > 1e-9:
        result *= _smoothstep((1.0 - alpha) / blend_out)
    return result


@dataclass(frozen=True)
class MotionPrimitive:
    kind: str
    start: float
    end: float
    amount: float = 1.0
    cycles: float = 1.0
    phase: float = 0.0
    direction: int = 1
    axis_mix: Mapping[str, float] = field(default_factory=dict)
    blend_in: float = 0.12
    blend_out: float = 0.12
    params: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        kind = str(self.kind).lower().strip()
        if kind not in PRIMITIVES:
            raise ValueError(f"unknown motion primitive: {self.kind}")
        start = max(0.0, float(self.start))
        end = float(self.end)
        if not np.isfinite(end) or end <= start:
            raise ValueError("motion primitive end must be after start")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "amount", max(0.0, float(self.amount)))
        object.__setattr__(self, "cycles", max(0.05, float(self.cycles)))
        object.__setattr__(self, "phase", float(self.phase))
        object.__setattr__(self, "direction", 1 if int(self.direction) >= 0 else -1)
        object.__setattr__(self, "blend_in", float(np.clip(self.blend_in, 0.0, .49)))
        object.__setattr__(self, "blend_out", float(np.clip(self.blend_out, 0.0, .49)))
        object.__setattr__(self, "axis_mix", {
            axis: float(value) for axis, value in dict(self.axis_mix or {}).items() if axis in AXIS_ORDER
        })
        object.__setattr__(self, "params", {str(k): float(v) for k, v in dict(self.params or {}).items()})

    def to_dict(self):
        return {
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "amount": self.amount,
            "cycles": self.cycles,
            "phase": self.phase,
            "direction": self.direction,
            "axis_mix": dict(self.axis_mix),
            "blend_in": self.blend_in,
            "blend_out": self.blend_out,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


@dataclass(frozen=True)
class MotionProgram:
    primitives: tuple[MotionPrimitive, ...] = ()
    neutral: float = 50.0
    blend: float = 1.0
    sample_hz: float = 20.0
    name: str = "motion-program"

    def __post_init__(self):
        object.__setattr__(self, "primitives", tuple(
            item if isinstance(item, MotionPrimitive) else MotionPrimitive.from_dict(item)
            for item in self.primitives
        ))
        object.__setattr__(self, "neutral", float(np.clip(self.neutral, 0.0, 100.0)))
        object.__setattr__(self, "blend", float(np.clip(self.blend, 0.0, 1.0)))
        object.__setattr__(self, "sample_hz", float(np.clip(self.sample_hz, 4.0, 100.0)))

    @property
    def duration(self) -> float:
        return max((item.end for item in self.primitives), default=0.0)

    def to_dict(self):
        return {
            "version": "1.0",
            "name": self.name,
            "neutral": self.neutral,
            "blend": self.blend,
            "sample_hz": self.sample_hz,
            "primitives": [item.to_dict() for item in self.primitives],
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        return cls(
            primitives=tuple(MotionPrimitive.from_dict(item) for item in payload.get("primitives", ())),
            neutral=float(payload.get("neutral", 50.0)),
            blend=float(payload.get("blend", 1.0)),
            sample_hz=float(payload.get("sample_hz", 20.0)),
            name=str(payload.get("name", "motion-program")),
        )


def _default_mix(kind: str) -> dict[str, float]:
    return {
        "hold": {},
        "drift": {"L1": .60, "L2": .75, "R1": .25, "R2": .25},
        "pulse": {"L0": 1.00, "L1": .22, "R0": .18},
        "wave": {"L0": .45, "L1": .65, "L2": .75, "R0": .40, "R1": .58, "R2": .68},
        "spiral": {"L1": .70, "L2": .70, "R0": .75, "R1": .45, "R2": .45},
        "orbit": {"L1": .72, "L2": .72, "R1": .55, "R2": .55},
        "rock": {"L2": .88, "R1": .76, "R2": .30},
        "sweep": {"L0": .60, "L1": .68, "L2": .36, "R0": .22},
        "twist": {"R0": 1.00, "L0": .16, "R1": .28, "R2": .28},
        "accent": {"L0": 1.00, "R0": .52, "R1": .62, "R2": .42},
        "recoil": {"L0": .88, "L1": .58, "R0": .44, "R2": .30},
    }[kind].copy()


def _primitive_waveform(primitive: MotionPrimitive, alpha: np.ndarray, axis: str) -> np.ndarray:
    phase = 2.0 * pi * (primitive.cycles * alpha * primitive.direction + primitive.phase)
    kind = primitive.kind
    axis_index = AXIS_ORDER.index(axis)
    if kind == "hold":
        return np.zeros_like(alpha)
    if kind == "drift":
        return np.sin(pi * (alpha - .5))
    if kind == "pulse":
        return np.sin(phase)
    if kind == "wave":
        return np.sin(phase - axis_index * pi / 4.8)
    if kind == "spiral":
        if axis in ("L1", "R1"):
            return np.sin(phase)
        if axis in ("L2", "R2"):
            return np.cos(phase)
        return np.sin(phase + pi / 3.0)
    if kind == "orbit":
        if axis in ("L1", "R1"):
            return np.sin(phase)
        if axis in ("L2", "R2"):
            return np.cos(phase)
        return .35 * np.sin(phase * .5)
    if kind == "rock":
        return np.sin(phase + (pi if axis == "R1" else 0.0))
    if kind == "sweep":
        return np.sin(pi * (2.0 * alpha - .5))
    if kind == "twist":
        return np.sin(phase)
    if kind == "accent":
        wave = np.sin(phase)
        return np.sign(wave) * np.power(np.abs(wave), 6.0)
    if kind == "recoil":
        local = np.mod(primitive.cycles * alpha, 1.0)
        rise = np.clip(local / .16, 0.0, 1.0)
        fall = np.exp(-5.5 * np.maximum(0.0, local - .16))
        return (2.0 * rise - 1.0) * fall
    return np.zeros_like(alpha)


def compile_motion_program(
    program: MotionProgram,
    *,
    duration: float | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Compile semantic primitives to canonical six-axis curves."""
    duration = max(float(duration if duration is not None else program.duration), program.duration, 0.05)
    count = max(2, int(np.ceil(duration * program.sample_hz)) + 1)
    times = np.linspace(0.0, duration, count)
    matrix = np.full((count, len(AXIS_ORDER)), float(program.neutral), dtype=np.float64)

    for primitive in program.primitives:
        mask = (times >= primitive.start) & (times <= primitive.end)
        if not np.any(mask):
            continue
        local_times = times[mask]
        alpha = (local_times - primitive.start) / max(primitive.end - primitive.start, 1e-9)
        envelope = _edge_envelope(alpha, primitive.blend_in, primitive.blend_out)
        mix = _default_mix(primitive.kind)
        mix.update(primitive.axis_mix)
        amplitude = 24.0 * primitive.amount * float(primitive.params.get("amplitude", 1.0))
        for column, axis in enumerate(AXIS_ORDER):
            gain = float(mix.get(axis, 0.0))
            if abs(gain) <= 1e-12:
                continue
            wave = _primitive_waveform(primitive, alpha, axis)
            matrix[mask, column] += amplitude * gain * envelope * wave

    matrix = np.clip(matrix, 0.0, 100.0)
    return {
        axis: [(float(at), float(pos)) for at, pos in zip(times, matrix[:, column])]
        for column, axis in enumerate(AXIS_ORDER)
    }


def _sample_plan(plan, axis: str, times: np.ndarray, neutral: float = 50.0) -> np.ndarray:
    rows = sorted((float(t), float(p)) for t, p in plan.get(axis, ()) if np.isfinite(t) and np.isfinite(p))
    if not rows:
        return np.full(times.size, neutral, dtype=np.float64)
    x = np.asarray([row[0] for row in rows], dtype=np.float64)
    y = np.asarray([row[1] for row in rows], dtype=np.float64)
    return np.interp(times, x, y, left=y[0], right=y[-1])


def blend_motion_program(
    base_plan: Mapping[str, Sequence[tuple[float, float]]],
    program: MotionProgram,
    *,
    duration: float | None = None,
    amount: float | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Blend a compiled semantic program into an existing editable base plan."""
    base_duration = max((float(t) for axis in AXIS_ORDER for t, _ in base_plan.get(axis, ())), default=0.0)
    duration = max(float(duration or 0.0), base_duration, program.duration, 0.05)
    overlay = compile_motion_program(program, duration=duration)
    amount = float(np.clip(program.blend if amount is None else amount, 0.0, 1.0))
    times = np.linspace(0.0, duration, max(2, int(np.ceil(duration * program.sample_hz)) + 1))
    result = {}
    for axis in AXIS_ORDER:
        base = _sample_plan(base_plan, axis, times, program.neutral)
        semantic = _sample_plan(overlay, axis, times, program.neutral)
        # Blend displacement from neutral so identity remains exact at amount=0.
        values = base + amount * (semantic - program.neutral)
        result[axis] = [(float(t), float(v)) for t, v in zip(times, np.clip(values, 0.0, 100.0))]
    return result
