"""Helpers for extracting time windows without changing the represented motion."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from .kinematics import AXES


def _clean(actions: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    dedup: dict[float, float] = {}
    for at, pos in actions:
        at = float(at); pos = float(pos)
        if np.isfinite(at) and np.isfinite(pos):
            dedup[max(0.0, at)] = float(np.clip(pos, 0.0, 100.0))
    return sorted(dedup.items())


def sample_actions(actions: Sequence[tuple[float, float]], at: float, default: float = 50.0) -> float:
    rows = _clean(actions)
    if not rows:
        return float(default)
    if len(rows) == 1:
        return float(rows[0][1])
    times = np.asarray([row[0] for row in rows], dtype=np.float64)
    values = np.asarray([row[1] for row in rows], dtype=np.float64)
    return float(np.interp(float(at), times, values, left=values[0], right=values[-1]))


def slice_plan(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    start: float,
    end: float,
    *,
    rebase: bool = True,
) -> dict[str, list[tuple[float, float]]]:
    """Extract a plan window while preserving the full-plan interpolation.

    Every non-empty axis gets explicit values at ``start`` and ``end`` plus its
    original interior keyframes. This is important for independent axis clocks:
    merely filtering keyframes can turn a moving sparse axis into an empty,
    neutral axis during section/weak-window scoring.
    """
    start = float(start); end = float(end)
    if not np.isfinite(start) or not np.isfinite(end):
        raise ValueError("window bounds must be finite")
    if end < start:
        start, end = end, start
    start = max(0.0, start); end = max(start, end)

    result: dict[str, list[tuple[float, float]]] = {}
    for axis in AXES:
        rows = _clean(plan.get(axis, ()))
        if not rows:
            result[axis] = []
            continue
        window: dict[float, float] = {
            start: sample_actions(rows, start),
            end: sample_actions(rows, end),
        }
        for at, pos in rows:
            if start < at < end:
                window[at] = pos
        ordered = sorted(window.items())
        if rebase:
            ordered = [(float(at - start), float(pos)) for at, pos in ordered]
        result[axis] = ordered
    return result
