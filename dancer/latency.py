"""Device latency measurement and timeline compensation for PythonDancer 2.6."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Mapping, Sequence

import numpy as np

AXES = ("L0", "L1", "L2", "R0", "R1", "R2")


@dataclass(frozen=True)
class DeviceTimingProfile:
    transport: str = "serial"
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    manual_offset_ms: float = 0.0

    def __post_init__(self):
        for field in ("latency_ms", "jitter_ms", "manual_offset_ms"):
            value = float(getattr(self, field))
            if not np.isfinite(value):
                raise ValueError(f"{field} must be finite")
            object.__setattr__(self, field, value)

    @property
    def command_lead_ms(self) -> float:
        return max(0.0, self.latency_ms + self.manual_offset_ms)

    def to_dict(self) -> dict[str, object]:
        return {
            "transport": self.transport,
            "latency_ms": float(self.latency_ms),
            "jitter_ms": float(self.jitter_ms),
            "manual_offset_ms": float(self.manual_offset_ms),
            "command_lead_ms": float(self.command_lead_ms),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "DeviceTimingProfile":
        return cls(
            transport=str(payload.get("transport", "serial")),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            jitter_ms=float(payload.get("jitter_ms", 0.0)),
            manual_offset_ms=float(payload.get("manual_offset_ms", 0.0)),
        )


def compensate_plan_latency(
    plan: Mapping[str, Sequence[tuple[float, float]]],
    timing: DeviceTimingProfile | None,
) -> dict[str, list[tuple[float, float]]]:
    lead = 0.0 if timing is None else timing.command_lead_ms / 1000.0
    result: dict[str, list[tuple[float, float]]] = {}
    for axis in AXES:
        rows = []
        for at, pos in plan.get(axis, ()):
            shifted = max(0.0, float(at) - lead)
            rows.append((shifted, float(pos)))
        # If early keyframes collapse to t=0, the latest desired pose wins.
        dedup: dict[float, float] = {}
        for at, pos in sorted(rows):
            dedup[float(at)] = float(pos)
        result[axis] = [(at, dedup[at]) for at in sorted(dedup)]
    return result


def measure_query_latency(device, *, command: str = "D1", samples: int = 5) -> DeviceTimingProfile:
    """Estimate serial request/response latency using a harmless identify query."""
    count = max(1, int(samples))
    values = []
    for _ in range(count):
        start = monotonic()
        device.query(command)
        values.append((monotonic() - start) * 1000.0)
    array = np.asarray(values, dtype=np.float64)
    # One-way scheduling delay is approximated as half RTT. Manual offset stays
    # available for devices whose mechanical response dominates transport RTT.
    return DeviceTimingProfile(
        transport="serial",
        latency_ms=float(np.median(array) * .5),
        jitter_ms=float(np.std(array)),
    )
