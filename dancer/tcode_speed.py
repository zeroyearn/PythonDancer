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
from time import monotonic, sleep
import re

import numpy as np

from .tcode import TCodePlaybackController, build_tcode_events

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
    """TCode controller that scales musical interpolation intervals by speed.

    STOP is sticky for the lifetime of a controller. This matters during a GUI
    Soft Start: a stop request that lands immediately before ``play()`` must not
    be cleared by the playback entry point and accidentally restart hardware.
    Create a new controller for a new playback session.
    """

    def __init__(self, plan, device, *, speed: float = 1.0, **kwargs):
        self.raw_device = device
        self.interval_device = _IntervalScaledDevice(device, speed)
        super().__init__(plan, self.interval_device, speed=speed, **kwargs)

    def _sync_position(self, position: float) -> None:
        # Seek synchronization and Soft Start use real safety milliseconds and
        # must not become shorter at >1x playback or longer at <1x playback.
        with self.interval_device.unscaled():
            super()._sync_position(position)

    def play(self, *, start_at: float = 0.0) -> None:
        offset = float(np.clip(float(start_at), 0.0, self.duration))
        with self._condition:
            self._position = offset
            if self._stop_requested:
                self._state = "stopped"
                self._base_real = None
                self.device.stop()
                return
            self._seek_requested = None
            self._paused = False
            self._state = "playing"
        if offset > 0:
            self.device.stop()
            self._sync_position(offset)

        while True:
            events = build_tcode_events(self.plan, start_at=offset, profile=self.profile)
            index = 0
            with self._condition:
                self._base_real = monotonic() - offset / self.speed
                self._state = "paused" if self._paused else "playing"
            restart = False
            restart_sync = False

            while index < len(events):
                with self._condition:
                    if self._stop_requested:
                        if self._base_real is not None and self._state == "playing":
                            self._position = float(np.clip((monotonic() - self._base_real) * self.speed, 0.0, self.duration))
                        self._state = "stopped"
                        self._base_real = None
                        self.device.stop()
                        return
                    if self._seek_requested is not None:
                        offset = self._seek_requested
                        self._seek_requested = None
                        self._position = offset
                        self.device.stop()
                        restart = True
                        restart_sync = True
                        break
                    if self._paused:
                        self._condition.wait(timeout=0.05)
                        continue
                    if self._state == "paused":
                        offset = self._position
                        restart = True
                        restart_sync = True
                        self._state = "playing"
                        break

                event = events[index]
                deadline = self._base_real + event.send_at / self.speed
                while True:
                    with self._condition:
                        if self._stop_requested:
                            restart = True
                            restart_sync = False
                            break
                        if self._seek_requested is not None:
                            restart = True
                            restart_sync = True
                            break
                        if self._paused:
                            restart = True
                            restart_sync = False
                            break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                    sleep(min(remaining, 0.02))
                if restart:
                    break
                self.device.send(event.command)
                with self._condition:
                    self._position = min(event.send_at, self.duration)
                index += 1

            if restart:
                with self._condition:
                    if self._stop_requested:
                        continue
                    if self._seek_requested is not None:
                        offset = self._seek_requested
                        self._seek_requested = None
                        self._position = offset
                        restart_sync = True
                    else:
                        offset = self._position
                    paused = self._paused
                self.device.stop()
                if restart_sync and (not paused or self._seek_requested is None):
                    self._sync_position(offset)
                continue

            if events:
                final_target = events[-1].target_at
                target_deadline = self._base_real + final_target / self.speed
                while monotonic() < target_deadline:
                    with self._condition:
                        if self._stop_requested:
                            restart = True
                            restart_sync = False
                            break
                        if self._seek_requested is not None:
                            restart = True
                            restart_sync = True
                            break
                        if self._paused:
                            restart = True
                            restart_sync = False
                            break
                    sleep(min(0.02, max(0.0, target_deadline - monotonic())))
                if restart:
                    offset = self.position
                    self.device.stop()
                    if restart_sync:
                        self._sync_position(offset)
                    continue

            with self._condition:
                self._position = self.duration
                self._state = "finished"
                self._base_real = None
            return