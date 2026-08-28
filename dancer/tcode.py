"""TCode v0.3 encoding, scheduled script export, and serial playback.

PythonDancer plans motion in normalized 0..100 space. TCode v0.3 accepts
axis magnitudes as decimal digits representing 0.0..0.9999... and supports an
``I<milliseconds>`` extension for ramping to the target over a time interval.

For multi-axis playback we send all axes for a target frame in one newline-
terminated command so the device starts them together.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Iterable, Mapping, Sequence

import numpy as np

TCODE_AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
DEFAULT_BAUD = 115200
MAX_INTERVAL_MS = 9_999_999


@dataclass(frozen=True)
class TCodeEvent:
    """One host-scheduled TCode line.

    ``send_at`` is host playback time in seconds. ``target_at`` is when the
    device should reach the encoded target. The command contains ``I`` ramps.
    """

    send_at: float
    target_at: float
    interval_ms: int
    command: str


def position_to_tcode(position: float, *, digits: int = 4) -> int:
    """Map PythonDancer 0..100 position to a TCode integer magnitude."""
    if not 1 <= int(digits) <= 7:
        raise ValueError("digits must be between 1 and 7")
    if not np.isfinite(position):
        raise ValueError("position must be finite")
    maximum = 10 ** int(digits) - 1
    normalized = float(np.clip(position, 0.0, 100.0)) / 100.0
    return int(round(normalized * maximum))


def encode_axis(axis: str, position: float, *, interval_ms: int | None = None, digits: int = 4) -> str:
    """Encode one TCode axis command."""
    axis = str(axis).upper()
    if len(axis) != 2 or axis[0] not in "LRVA" or not axis[1].isdigit():
        raise ValueError(f"invalid TCode axis: {axis!r}")
    value = position_to_tcode(position, digits=digits)
    command = f"{axis}{value:0{digits}d}"
    if interval_ms is not None and int(interval_ms) > 0:
        interval = min(MAX_INTERVAL_MS, max(1, int(round(interval_ms))))
        command += f"I{interval}"
    return command


def _clean_actions(actions: Iterable[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    rows = sorted(
        (float(at), float(pos))
        for at, pos in actions
        if np.isfinite(at) and np.isfinite(pos)
    )
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
    return np.interp(
        target_times,
        times,
        positions,
        left=float(positions[0]),
        right=float(positions[-1]),
    )


def build_tcode_events(
    plan: Mapping[str, Iterable[tuple[float, float]]],
    *,
    axes: Sequence[str] | None = None,
    digits: int = 4,
) -> list[TCodeEvent]:
    """Build ramp-ahead events from a single- or multi-axis motion plan."""
    selected = tuple(str(axis).upper() for axis in (axes or TCODE_AXES) if str(axis).upper() in plan)
    if not selected:
        return []

    if "L0" in plan:
        target_times, _ = _clean_actions(plan["L0"])
    else:
        merged: set[float] = set()
        for axis in selected:
            times, _ = _clean_actions(plan[axis])
            merged.update(float(value) for value in times)
        target_times = np.asarray(sorted(merged), dtype=np.float64)

    if target_times.size == 0:
        return []

    sampled = {axis: _sample_axis(plan[axis], target_times) for axis in selected}
    events: list[TCodeEvent] = []

    previous_target = 0.0
    for index, target_at in enumerate(target_times):
        target_at = max(0.0, float(target_at))
        send_at = 0.0 if index == 0 else previous_target
        interval_ms = max(0, int(round((target_at - send_at) * 1000.0)))
        commands = [
            encode_axis(
                axis,
                float(sampled[axis][index]),
                interval_ms=interval_ms if interval_ms > 0 else None,
                digits=digits,
            )
            for axis in selected
        ]
        events.append(
            TCodeEvent(
                send_at=send_at,
                target_at=target_at,
                interval_ms=interval_ms,
                command=" ".join(commands),
            )
        )
        previous_target = target_at

    return events


def default_tcode_path(base_path: str | Path) -> Path:
    path = Path(base_path)
    text = str(path)
    if text.lower().endswith(".funscript"):
        text = text[: -len(".funscript")]
        return Path(text + ".tcode")
    if path.suffix.lower() == ".csv":
        return path.with_suffix(".tcode")
    return Path(text + ".tcode")


def export_tcode_script(
    path: str | Path,
    events: Sequence[TCodeEvent],
    *,
    source: str | None = None,
) -> Path:
    """Write a PythonDancer scheduled TCode text script."""
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
    """Load a PythonDancer scheduled ``.tcode`` text script."""
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
    """Return ``(device, description)`` pairs discovered by pyserial."""
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("Serial support requires pyserial (pip install pyserial)") from exc
    return [(item.device, item.description or "") for item in list_ports.comports()]


class SerialTCodeDevice:
    """Small newline-framed TCode serial transport."""

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
        self.serial = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            timeout=self.timeout,
            write_timeout=max(1.0, self.timeout),
        )
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
        return {
            "firmware": self.query("D0"),
            "tcode": self.query("D1"),
            "axes": self.query("D2"),
        }


def play_tcode_events(
    events: Sequence[TCodeEvent],
    device: SerialTCodeDevice,
    *,
    speed: float = 1.0,
    stop_on_interrupt: bool = True,
    stop_event=None,
) -> None:
    """Play scheduled events in real time over an open serial device."""
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
