"""Optional non-TCode outputs for PythonDancer.

Intiface support is deliberately optional for source installs. Desktop release
builds install the ``intiface`` extra so Intiface Central works out of the box.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Mapping, Sequence

import numpy as np

from .workspace import sample_axis

DEFAULT_INTIFACE_ADDRESS = "ws://127.0.0.1:12345"


class IntifaceUnavailable(RuntimeError):
    pass


def _imports():
    try:
        from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
    except ImportError as exc:
        raise IntifaceUnavailable(
            "Intiface output requires the optional 'buttplug' package. "
            "Install python-dancer[intiface]."
        ) from exc
    return ButtplugClient, DeviceOutputCommand, OutputType


@dataclass
class IntifaceDeviceInfo:
    index: int
    name: str
    position: bool
    vibrate: bool
    rotate: bool

    def to_dict(self):
        return {
            "index": int(self.index),
            "name": self.name,
            "position": bool(self.position),
            "vibrate": bool(self.vibrate),
            "rotate": bool(self.rotate),
        }


async def discover_intiface_devices(address: str = DEFAULT_INTIFACE_ADDRESS, scan_seconds: float = 3.0):
    ButtplugClient, _, OutputType = _imports()
    client = ButtplugClient("PythonDancer")
    await client.connect(address)
    try:
        await client.start_scanning()
        await asyncio.sleep(max(0.1, float(scan_seconds)))
        await client.stop_scanning()
        infos = []
        for index, device in client.devices.items():
            infos.append(IntifaceDeviceInfo(
                int(index),
                str(device.name),
                bool(device.has_output(OutputType.POSITION_WITH_DURATION)),
                bool(device.has_output(OutputType.VIBRATE)),
                bool(device.has_output(OutputType.ROTATE)),
            ))
        return infos
    finally:
        await client.disconnect()


def discover_intiface_devices_sync(address: str = DEFAULT_INTIFACE_ADDRESS, scan_seconds: float = 3.0):
    return asyncio.run(discover_intiface_devices(address, scan_seconds))


def _timeline(plan: Mapping[str, Sequence[tuple[float, float]]]):
    preferred = plan.get("L0") or ()
    if preferred:
        return [float(at) for at, _ in preferred]
    return sorted({float(at) for actions in plan.values() for at, _ in actions})


def intiface_frames(plan: Mapping[str, Sequence[tuple[float, float]]]):
    """Create generic position/intensity frames independent of Buttplug."""
    times = _timeline(plan)
    frames = []
    previous = None
    for i, at in enumerate(times):
        next_at = times[i + 1] if i + 1 < len(times) else at + .1
        duration_ms = max(20, int(round((next_at - at) * 1000.0)))
        position = float(np.clip(sample_axis(plan.get("L0", ()), at, 50.0) / 100.0, 0.0, 1.0))
        if previous is None:
            intensity = 0.0
        else:
            dt = max(at - previous[0], 1e-6)
            deltas = [
                abs(sample_axis(plan.get(axis, ()), at, 50.0) - sample_axis(plan.get(axis, ()), previous[0], 50.0))
                for axis in plan
            ]
            intensity = float(np.clip(max(deltas, default=0.0) / dt / 180.0, 0.0, 1.0))
        rotation = float(np.clip(abs(sample_axis(plan.get("R0", ()), at, 50.0) - 50.0) / 50.0, 0.0, 1.0))
        frames.append((at, duration_ms, position, intensity, rotation))
        previous = (at, position)
    return frames


async def play_plan_intiface(
    plan,
    *,
    address: str = DEFAULT_INTIFACE_ADDRESS,
    device_index: int | None = None,
    speed: float = 1.0,
    stop_event=None,
    start_at: float = 0.0,
    soft_start_ms: int = 0,
):
    """Play the effective plan through one Intiface/Buttplug device.

    POSITION_WITH_DURATION receives L0. VIBRATE receives normalized six-axis
    motion intensity. ROTATE receives normalized R0 excursion. When supported,
    ``soft_start_ms`` first moves the position actuator to the selected start
    pose while vibration/rotation remain off.
    """
    if speed <= 0:
        raise ValueError("speed must be positive")
    if soft_start_ms < 0:
        raise ValueError("soft_start_ms must be non-negative")
    ButtplugClient, DeviceOutputCommand, OutputType = _imports()
    client = ButtplugClient("PythonDancer")
    await client.connect(address)
    device = None
    try:
        if not client.devices:
            await client.start_scanning()
            await asyncio.sleep(2.0)
            await client.stop_scanning()
        if not client.devices:
            raise RuntimeError("No Intiface devices found")
        if device_index is None:
            device = next(iter(client.devices.values()))
        else:
            device = client.devices.get(int(device_index))
            if device is None:
                raise RuntimeError(f"Intiface device {device_index} not found")

        frames = [frame for frame in intiface_frames(plan) if frame[0] >= float(start_at)]
        if not frames:
            return

        if soft_start_ms > 0:
            _, _, start_position, _, _ = frames[0]
            if device.has_output(OutputType.POSITION_WITH_DURATION):
                await device.run_output(
                    DeviceOutputCommand(
                        OutputType.POSITION_WITH_DURATION,
                        start_position,
                        duration=max(20, int(soft_start_ms)),
                    )
                )
            if device.has_output(OutputType.VIBRATE):
                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))
            if device.has_output(OutputType.ROTATE):
                await device.run_output(DeviceOutputCommand(OutputType.ROTATE, 0.0))
            await asyncio.sleep(soft_start_ms / 1000.0)

        base = time.monotonic() - float(start_at) / speed
        for at, duration_ms, position, intensity, rotation in frames:
            if stop_event is not None and stop_event.is_set():
                break
            target = base + at / speed
            while True:
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                if stop_event is not None and stop_event.is_set():
                    break
                await asyncio.sleep(min(remaining, .03))
            if stop_event is not None and stop_event.is_set():
                break
            if device.has_output(OutputType.POSITION_WITH_DURATION):
                await device.run_output(
                    DeviceOutputCommand(
                        OutputType.POSITION_WITH_DURATION,
                        position,
                        duration=max(20, int(duration_ms / speed)),
                    )
                )
            if device.has_output(OutputType.VIBRATE):
                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))
            if device.has_output(OutputType.ROTATE):
                await device.run_output(DeviceOutputCommand(OutputType.ROTATE, rotation))
        await device.stop()
    finally:
        if device is not None:
            try:
                await device.stop()
            except Exception:
                pass
        await client.disconnect()


def play_plan_intiface_sync(plan, **kwargs):
    return asyncio.run(play_plan_intiface(plan, **kwargs))
