"""TCode v0.3 encoding, D2 device profiles, and controllable serial playback."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Condition
from time import monotonic, sleep
from typing import Iterable, Mapping, Sequence

import numpy as np

TCODE_AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
DEFAULT_BAUD = 115200
MAX_INTERVAL_MS = 9_999_999


@dataclass(frozen=True)
class TCodeEvent:
    send_at: float
    target_at: float
    interval_ms: int
    command: str


@dataclass(frozen=True)
class AxisRange:
    axis: str
    minimum: int
    maximum: int
    name: str = ""

    def map_position(self, position: float) -> int:
        if not np.isfinite(position):
            raise ValueError("position must be finite")
        normalized = float(np.clip(position, 0.0, 100.0)) / 100.0
        return int(round(self.minimum + normalized * (self.maximum - self.minimum)))


@dataclass(frozen=True)
class DeviceProfile:
    firmware: tuple[str, ...] = ()
    tcode: tuple[str, ...] = ()
    axes: Mapping[str, AxisRange] | None = None

    def __post_init__(self):
        object.__setattr__(self, "axes", dict(self.axes or {}))

    def active_motion_axes(self, plan: Mapping[str, object]) -> tuple[str, ...]:
        return tuple(axis for axis in TCODE_AXES if axis in plan and (not self.axes or axis in self.axes))


def parse_d2_axis_line(line: str) -> AxisRange | None:
    """Parse D2 rows such as ``L0 0 9999 Up``."""
    parts = str(line).strip().split(maxsplit=3)
    if len(parts) < 3:
        return None
    axis = parts[0].upper()
    if len(axis) != 2 or axis[0] not in "LRVA" or not axis[1].isdigit():
        return None
    try:
        minimum = int(parts[1])
        maximum = int(parts[2])
    except ValueError:
        return None
    if not (0 <= minimum <= 9999 and 0 <= maximum <= 9999):
        return None
    return AxisRange(axis=axis, minimum=minimum, maximum=maximum, name=parts[3] if len(parts) > 3 else "")


def parse_d2_axes(lines: Iterable[str]) -> dict[str, AxisRange]:
    result: dict[str, AxisRange] = {}
    for line in lines:
        item = parse_d2_axis_line(line)
        if item is not None:
            result[item.axis] = item
    return result


def position_to_tcode(position: float, *, digits: int = 4, axis_range: AxisRange | tuple[int, int] | None = None) -> int:
    """Map normalized 0..100 into the full TCode range or a D2 preference range."""
    if not 1 <= int(digits) <= 7:
        raise ValueError("digits must be between 1 and 7")
    if not np.isfinite(position):
        raise ValueError("position must be finite")
    maximum = 10 ** int(digits) - 1
    if axis_range is None:
        low, high = 0, maximum
    elif isinstance(axis_range, AxisRange):
        low, high = axis_range.minimum, axis_range.maximum
    else:
        low, high = map(int, axis_range)
    low = int(np.clip(low, 0, maximum))
    high = int(np.clip(high, 0, maximum))
    normalized = float(np.clip(position, 0.0, 100.0)) / 100.0
    return int(round(low + normalized * (high - low)))


def encode_axis(axis: str, position: float, *, interval_ms: int | None = None, digits: int = 4, axis_range: AxisRange | tuple[int, int] | None = None) -> str:
    axis = str(axis).upper()
    if len(axis) != 2 or axis[0] not in "LRVA" or not axis[1].isdigit():
        raise ValueError(f"invalid TCode axis: {axis!r}")
    value = position_to_tcode(position, digits=digits, axis_range=axis_range)
    command = f"{axis}{value:0{digits}d}"
    if interval_ms is not None and int(interval_ms) > 0:
        interval = min(MAX_INTERVAL_MS, max(1, int(round(interval_ms))))
        command += f"I{interval}"
    return command


def _clean_actions(actions: Iterable[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    rows = sorted((float(at), float(pos)) for at, pos in actions if np.isfinite(at) and np.isfinite(pos))
    if not rows:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    deduplicated: dict[float, float] = {}
    for at, pos in rows:
        deduplicated[max(0.0, at)] = float(np.clip(pos, 0.0, 100.0))
    times = np.asarray(sorted(deduplicated), dtype=np.float64)
    positions = np.asarray([deduplicated[t] for t in times], dtype=np.float64)
    return times, positions


def _sample_axis(actions: Iterable[tuple[float, float]], target_times: np.ndarray) -> np.ndarray:
    times, positions = _clean_actions(actions)
    if target_times.size == 0:
        return np.asarray([], dtype=np.float64)
    if times.size == 0:
        return np.full(target_times.size, 50.0, dtype=np.float64)
    if times.size == 1:
        return np.full(target_times.size, float(positions[0]), dtype=np.float64)
    return np.interp(target_times, times, positions, left=float(positions[0]), right=float(positions[-1]))


def plan_duration(plan: Mapping[str, Iterable[tuple[float, float]]]) -> float:
    duration = 0.0
    for actions in plan.values():
        times, _ = _clean_actions(actions)
        if times.size:
            duration = max(duration, float(times[-1]))
    return duration


def sample_plan(plan: Mapping[str, Iterable[tuple[float, float]]], at: float, *, axes: Sequence[str] | None = None) -> dict[str, float]:
    selected = tuple(str(axis).upper() for axis in (axes or TCODE_AXES) if str(axis).upper() in plan)
    target = np.asarray([max(0.0, float(at))], dtype=np.float64)
    return {axis: float(_sample_axis(plan[axis], target)[0]) for axis in selected}


def _resolve_axes(plan: Mapping[str, Iterable[tuple[float, float]]], axes: Sequence[str] | None, profile: DeviceProfile | None) -> tuple[str, ...]:
    selected = tuple(str(axis).upper() for axis in (axes or TCODE_AXES) if str(axis).upper() in plan)
    if profile is not None and profile.axes:
        selected = tuple(axis for axis in selected if axis in profile.axes)
    return selected


def encode_plan_frame(plan: Mapping[str, Iterable[tuple[float, float]]], at: float, *, axes: Sequence[str] | None = None, profile: DeviceProfile | None = None, interval_ms: int | None = None, digits: int = 4) -> str:
    selected = _resolve_axes(plan, axes, profile)
    positions = sample_plan(plan, at, axes=selected)
    return " ".join(
        encode_axis(
            axis,
            positions[axis],
            interval_ms=interval_ms,
            digits=digits,
            axis_range=profile.axes.get(axis) if profile and profile.axes else None,
        )
        for axis in selected
    )


def build_tcode_events(plan: Mapping[str, Iterable[tuple[float, float]]], *, axes: Sequence[str] | None = None, digits: int = 4, start_at: float = 0.0, profile: DeviceProfile | None = None) -> list[TCodeEvent]:
    """Build ramp-ahead events starting from an arbitrary timeline position."""
    selected = _resolve_axes(plan, axes, profile)
    if not selected:
        return []
    start_at = max(0.0, float(start_at))
    if "L0" in plan:
        target_times, _ = _clean_actions(plan["L0"])
    else:
        merged: set[float] = set()
        for axis in selected:
            times, _ = _clean_actions(plan[axis])
            merged.update(float(value) for value in times)
        target_times = np.asarray(sorted(merged), dtype=np.float64)
    target_times = target_times[target_times >= start_at - 1e-9]
    if target_times.size == 0:
        return []
    sampled = {axis: _sample_axis(plan[axis], target_times) for axis in selected}
    events: list[TCodeEvent] = []
    previous_target = start_at
    for index, target_at in enumerate(target_times):
        target_at = max(start_at, float(target_at))
        send_at = start_at if index == 0 else previous_target
        interval_ms = max(0, int(round((target_at - send_at) * 1000.0)))
        commands = [
            encode_axis(
                axis,
                float(sampled[axis][index]),
                interval_ms=interval_ms if interval_ms > 0 else None,
                digits=digits,
                axis_range=profile.axes.get(axis) if profile and profile.axes else None,
            )
            for axis in selected
        ]
        events.append(TCodeEvent(send_at=send_at, target_at=target_at, interval_ms=interval_ms, command=" ".join(commands)))
        previous_target = target_at
    return events


def default_tcode_path(base_path: str | Path) -> Path:
    path = Path(base_path)
    text = str(path)
    if text.lower().endswith(".funscript"):
        return Path(text[: -len(".funscript")] + ".tcode")
    if path.suffix.lower() == ".csv":
        return path.with_suffix(".tcode")
    return Path(text + ".tcode")


def export_tcode_script(path: str | Path, events: Sequence[TCodeEvent], *, source: str | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf8", newline="\n") as handle:
        handle.write("# PythonDancer TCode v0.3 scheduled script\n")
        handle.write("# format: send_at_ms<TAB>newline-terminated-device-command\n")
        if source:
            handle.write(f"# source: {source}\n")
        for event in events:
            handle.write(f"{int(round(event.send_at * 1000.0))}\t{event.command}\n")
    return output


def load_tcode_script(path: str | Path) -> list[TCodeEvent]:
    events: list[TCodeEvent] = []
    for raw in Path(path).read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            timestamp, command = line.split(None, 1)
        except ValueError as exc:
            raise ValueError(f"invalid TCode script line: {raw!r}") from exc
        send_at = int(timestamp) / 1000.0
        events.append(TCodeEvent(send_at=send_at, target_at=send_at, interval_ms=0, command=command.strip()))
    return events


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("Serial support requires pyserial (pip install pyserial)") from exc
    return [(item.device, item.description or "") for item in list_ports.comports()]


class SerialTCodeDevice:
    def __init__(self, port: str, *, baud: int = DEFAULT_BAUD, timeout: float = 0.25):
        self.port = str(port)
        self.baud = int(baud)
        self.timeout = float(timeout)
        self.serial = None

    def open(self) -> "SerialTCodeDevice":
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Serial support requires pyserial (pip install pyserial)") from exc
        self.serial = serial.Serial(port=self.port, baudrate=self.baud, timeout=self.timeout, write_timeout=max(1.0, self.timeout))
        return self

    @property
    def is_open(self) -> bool:
        return bool(self.serial is not None and self.serial.is_open)

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()

    def __enter__(self) -> "SerialTCodeDevice":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def send(self, command: str) -> None:
        if not self.is_open:
            raise RuntimeError("serial device is not open")
        payload = command.rstrip("\r\n") + "\n"
        self.serial.write(payload.encode("ascii"))
        self.serial.flush()

    def stop(self) -> None:
        if self.is_open:
            self.send("DSTOP")

    def query(self, command: str, *, max_lines: int = 8) -> list[str]:
        if not self.is_open:
            raise RuntimeError("serial device is not open")
        self.serial.reset_input_buffer()
        self.send(command)
        lines: list[str] = []
        deadline = monotonic() + max(0.05, self.timeout)
        while monotonic() < deadline and len(lines) < max_lines:
            raw = self.serial.readline()
            if not raw:
                break
            text = raw.decode("utf8", errors="replace").strip()
            if text:
                lines.append(text)
        return lines

    def identify(self) -> dict[str, list[str]]:
        return {"firmware": self.query("D0"), "tcode": self.query("D1"), "axes": self.query("D2", max_lines=40)}

    def profile(self) -> DeviceProfile:
        identity = self.identify()
        return DeviceProfile(firmware=tuple(identity["firmware"]), tcode=tuple(identity["tcode"]), axes=parse_d2_axes(identity["axes"]))


class TCodePlaybackController:
    """Thread-safe real-time controller with pause, resume, seek, and D2 range mapping."""

    def __init__(self, plan: Mapping[str, Iterable[tuple[float, float]]], device: SerialTCodeDevice, *, speed: float = 1.0, profile: DeviceProfile | None = None, use_device_ranges: bool = True, seek_ramp_ms: int = 120):
        if not np.isfinite(speed) or speed <= 0:
            raise ValueError("playback speed must be a positive finite number")
        self.plan = plan
        self.device = device
        self.speed = float(speed)
        self.profile = profile if use_device_ranges else None
        self.seek_ramp_ms = max(0, int(seek_ramp_ms))
        self.duration = plan_duration(plan)
        self._condition = Condition()
        self._state = "idle"
        self._position = 0.0
        self._base_real: float | None = None
        self._paused = False
        self._stop_requested = False
        self._seek_requested: float | None = None

    @property
    def state(self) -> str:
        with self._condition:
            return self._state

    @property
    def position(self) -> float:
        with self._condition:
            if self._state == "playing" and self._base_real is not None:
                current = (monotonic() - self._base_real) * self.speed
                return float(np.clip(current, 0.0, self.duration))
            return self._position

    def pause(self) -> None:
        with self._condition:
            if self._state == "playing":
                if self._base_real is not None:
                    self._position = float(np.clip((monotonic() - self._base_real) * self.speed, 0.0, self.duration))
                self._paused = True
                self._state = "paused"
                self.device.stop()
                self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            if self._state == "paused":
                self._paused = False
                self._condition.notify_all()

    def seek(self, seconds: float) -> None:
        target = float(np.clip(float(seconds), 0.0, self.duration))
        with self._condition:
            self._seek_requested = target
            self._position = target
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
        self.device.stop()

    def _sync_position(self, position: float) -> None:
        if self.duration <= 0:
            return
        command = encode_plan_frame(self.plan, position, profile=self.profile, interval_ms=self.seek_ramp_ms if self.seek_ramp_ms > 0 else None)
        if command:
            self.device.send(command)
            if self.seek_ramp_ms > 0:
                sleep(self.seek_ramp_ms / 1000.0)

    def play(self, *, start_at: float = 0.0) -> None:
        offset = float(np.clip(float(start_at), 0.0, self.duration))
        with self._condition:
            self._position = offset
            self._stop_requested = False
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
                        break
                    if self._paused:
                        self._condition.wait(timeout=0.05)
                        continue
                    if self._state == "paused":
                        offset = self._position
                        restart = True
                        self._state = "playing"
                        break

                event = events[index]
                deadline = self._base_real + event.send_at / self.speed
                while True:
                    with self._condition:
                        if self._stop_requested or self._seek_requested is not None or self._paused:
                            restart = True
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
                    else:
                        offset = self._position
                self.device.stop()
                self._sync_position(offset)
                continue

            if events:
                final_target = events[-1].target_at
                target_deadline = self._base_real + final_target / self.speed
                while monotonic() < target_deadline:
                    with self._condition:
                        if self._stop_requested or self._seek_requested is not None or self._paused:
                            restart = True
                            break
                    sleep(min(0.02, max(0.0, target_deadline - monotonic())))
                if restart:
                    offset = self.position
                    self.device.stop()
                    self._sync_position(offset)
                    continue

            with self._condition:
                self._position = self.duration
                self._state = "finished"
                self._base_real = None
            return


def play_tcode_events(events: Sequence[TCodeEvent], device: SerialTCodeDevice, *, speed: float = 1.0, stop_on_interrupt: bool = True, stop_event=None) -> None:
    """Backward-compatible stateless playback helper."""
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError("playback speed must be a positive finite number")
    if not events:
        return
    start = monotonic()
    try:
        for event in events:
            if stop_event is not None and stop_event.is_set():
                device.stop()
                return
            deadline = start + max(0.0, float(event.send_at)) / float(speed)
            while True:
                if stop_event is not None and stop_event.is_set():
                    device.stop()
                    return
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                sleep(min(remaining, 0.02))
            device.send(event.command)
    except KeyboardInterrupt:
        if stop_on_interrupt:
            device.stop()
        raise