"""Playback-speed aware TCode controller for PythonDancer 2.5.

The 2.4 controller already scales host-side send deadlines by ``speed``. TCode
``I<ms>`` interpolation durations must be scaled by the same factor during
normal playback, otherwise 2x playback sends targets twice as fast while the
device still spends the original duration moving to each target.

Seek/Soft-Start synchronization ramps are safety timings, not musical timings,
so this wrapper deliberately leaves commands sent by ``_sync_position``
unscaled.
"""
from __future__ import annotations

from contextlib import contextmanager
import re

from .tcode import TCodePlaybackController

_INTERVAL_RE = re.compile(r"I(\d+)")


def scale_tcode_intervals(command: str, speed: float) -> str:
    speed = float(speed)
    if speed <= 0:
        raise ValueError("speed must be positive")
    if abs(speed - 1.0) < 1e-12:
        return str(command)

    def replace(match):
        value = int(match.group(1))
        if value <= 0:
            return match.group(0)
        scaled = max(1, int(round(value / speed)))
        return f"I{scaled}"

    return _INTERVAL_RE.sub(replace, str(command))


class _IntervalScaledDevice:
    def __init__(self, device, speed: float):
        self.device = device
        self.speed = float(speed)
        self.scale_enabled = True

    def send(self, command: str) -> None:
        if self.scale_enabled:
            command = scale_tcode_intervals(command, self.speed)
        self.device.send(command)

    def stop(self) -> None:
        self.device.stop()

    @contextmanager
    def unscaled(self):
        previous = self.scale_enabled
        self.scale_enabled = False
        try:
            yield
        finally:
            self.scale_enabled = previous


class SpeedAwareTCodePlaybackController(TCodePlaybackController):
    """TCode controller that scales musical interpolation intervals by speed."""

    def __init__(self, plan, device, *, speed: float = 1.0, **kwargs):
        self.raw_device = device
        self.interval_device = _IntervalScaledDevice(device, speed)
        super().__init__(plan, self.interval_device, speed=speed, **kwargs)

    def _sync_position(self, position: float) -> None:
        # Seek synchronization and Soft Start use real safety milliseconds and
        # must not become shorter at >1x playback or longer at <1x playback.
        with self.interval_device.unscaled():
            super()._sync_position(position)
