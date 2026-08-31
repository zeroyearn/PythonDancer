"""Keyframe and curve editing primitives for PythonDancer 2.5.

The GUI intentionally delegates all destructive-looking operations to this
module so edits are deterministic, testable, and reusable by future quality
optimizers or plugin APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.interpolate import Akima1DInterpolator, PchipInterpolator

INTERPOLATIONS = ("linear", "smoothstep", "pchip", "makima")


def _clean_actions(actions: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    clean: list[tuple[float, float]] = []
    for at, pos in actions:
        at = float(at)
        pos = float(np.clip(pos, 0.0, 100.0))
        if not np.isfinite(at) or not np.isfinite(pos):
            continue
        clean.append((at, pos))
    clean.sort(key=lambda item: item[0])
    deduped: list[tuple[float, float]] = []
    for item in clean:
        if deduped and abs(item[0] - deduped[-1][0]) < 1e-9:
            deduped[-1] = item
        else:
            deduped.append(item)
    return deduped


def nearest_beat(at: float, beats: Sequence[float], mode: str = "nearest") -> float:
    values = np.asarray(beats, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float(at)
    at = float(at)
    if mode == "nearest":
        return float(values[int(np.argmin(np.abs(values - at)))])
    if mode == "floor":
        eligible = values[values <= at]
        return float(eligible[-1] if eligible.size else values[0])
    if mode == "ceil":
        eligible = values[values >= at]
        return float(eligible[0] if eligible.size else values[-1])
    raise ValueError(f"unknown quantize mode: {mode}")


def quantize_actions(
    actions: Sequence[tuple[float, float]],
    beats: Sequence[float],
    *,
    mode: str = "nearest",
    start: float | None = None,
    end: float | None = None,
) -> list[tuple[float, float]]:
    result = []
    lo = -np.inf if start is None else float(start)
    hi = np.inf if end is None else float(end)
    for at, pos in _clean_actions(actions):
        snapped = nearest_beat(at, beats, mode) if lo <= at <= hi else at
        result.append((snapped, pos))
    return _clean_actions(result)


def insert_keyframe(actions: Sequence[tuple[float, float]], at: float, pos: float) -> list[tuple[float, float]]:
    return _clean_actions([*_clean_actions(actions), (float(at), float(pos))])


def move_keyframe(actions: Sequence[tuple[float, float]], index: int, at: float, pos: float) -> list[tuple[float, float]]:
    result = _clean_actions(actions)
    if index < 0 or index >= len(result):
        raise IndexError("keyframe index out of range")
    result.pop(index)
    result.append((float(at), float(pos)))
    return _clean_actions(result)


def delete_keyframes(actions: Sequence[tuple[float, float]], indices: Iterable[int]) -> list[tuple[float, float]]:
    remove = set(int(i) for i in indices)
    return [item for i, item in enumerate(_clean_actions(actions)) if i not in remove]


def transform_range(
    actions: Sequence[tuple[float, float]],
    start: float,
    end: float,
    *,
    scale: float = 1.0,
    offset: float = 0.0,
    center: float = 50.0,
) -> list[tuple[float, float]]:
    lo, hi = sorted((float(start), float(end)))
    out = []
    for at, pos in _clean_actions(actions):
        if lo <= at <= hi:
            pos = center + (pos - center) * float(scale) + float(offset)
        out.append((at, float(np.clip(pos, 0.0, 100.0))))
    return out


def flatten_range(actions: Sequence[tuple[float, float]], start: float, end: float, value: float | None = None) -> list[tuple[float, float]]:
    clean = _clean_actions(actions)
    lo, hi = sorted((float(start), float(end)))
    selected = [pos for at, pos in clean if lo <= at <= hi]
    if not selected:
        return clean
    target = float(np.median(selected) if value is None else value)
    return [(at, float(np.clip(target if lo <= at <= hi else pos, 0.0, 100.0))) for at, pos in clean]


def smooth_range(actions: Sequence[tuple[float, float]], start: float, end: float, window: int = 5) -> list[tuple[float, float]]:
    clean = _clean_actions(actions)
    if len(clean) < 3:
        return clean
    lo, hi = sorted((float(start), float(end)))
    values = np.asarray([pos for _, pos in clean], dtype=np.float64)
    window = max(3, int(window) | 1)
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    kernel = np.ones(window, dtype=np.float64) / window
    smoothed = np.convolve(padded, kernel, mode="valid")
    out = []
    for i, (at, pos) in enumerate(clean):
        out.append((at, float(np.clip(smoothed[i] if lo <= at <= hi else pos, 0.0, 100.0))))
    return out


def _smoothstep_interpolate(times: np.ndarray, values: np.ndarray, sample_times: np.ndarray) -> np.ndarray:
    result = np.empty_like(sample_times, dtype=np.float64)
    for i, at in enumerate(sample_times):
        if at <= times[0]:
            result[i] = values[0]
            continue
        if at >= times[-1]:
            result[i] = values[-1]
            continue
        right = int(np.searchsorted(times, at, side="right"))
        left = right - 1
        dt = max(times[right] - times[left], 1e-12)
        alpha = float(np.clip((at - times[left]) / dt, 0.0, 1.0))
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
        result[i] = values[left] * (1.0 - alpha) + values[right] * alpha
    return result


def resample_curve(
    actions: Sequence[tuple[float, float]],
    sample_times: Sequence[float],
    method: str = "linear",
) -> list[tuple[float, float]]:
    clean = _clean_actions(actions)
    sample = np.asarray(sample_times, dtype=np.float64).reshape(-1)
    sample = sample[np.isfinite(sample)]
    if sample.size == 0 or not clean:
        return []
    times = np.asarray([at for at, _ in clean], dtype=np.float64)
    values = np.asarray([pos for _, pos in clean], dtype=np.float64)
    if len(clean) == 1:
        output = np.full_like(sample, values[0], dtype=np.float64)
    elif method == "linear":
        output = np.interp(sample, times, values, left=values[0], right=values[-1])
    elif method == "smoothstep":
        output = _smoothstep_interpolate(times, values, sample)
    elif method == "pchip":
        output = PchipInterpolator(times, values, extrapolate=True)(sample)
    elif method == "makima":
        try:
            output = Akima1DInterpolator(times, values, method="makima", extrapolate=True)(sample)
        except TypeError:  # SciPy builds predating the method keyword.
            output = Akima1DInterpolator(times, values, extrapolate=True)(sample)
        output = np.where(np.isfinite(output), output, np.interp(sample, times, values))
    else:
        raise ValueError(f"unknown interpolation: {method}")
    output = np.clip(np.asarray(output, dtype=np.float64), 0.0, 100.0)
    return list(zip(sample.tolist(), output.tolist()))


@dataclass
class CurveSettings:
    interpolation: str = "linear"
    snap_to_beat: bool = True
    quantize_mode: str = "nearest"

    def __post_init__(self):
        if self.interpolation not in INTERPOLATIONS:
            raise ValueError(f"unsupported interpolation: {self.interpolation}")
        if self.quantize_mode not in ("nearest", "floor", "ceil"):
            raise ValueError(f"unsupported quantize mode: {self.quantize_mode}")

    def to_dict(self) -> dict[str, object]:
        return {
            "interpolation": self.interpolation,
            "snap_to_beat": bool(self.snap_to_beat),
            "quantize_mode": self.quantize_mode,
        }
