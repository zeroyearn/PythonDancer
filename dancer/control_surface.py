"""Optional MIDI, OSC and Ableton-Link style transport/control bridges.

External libraries are optional. Core mapping/state logic remains dependency-free
so source installs and frozen builds can disable control surfaces safely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Thread
import time
from typing import Callable, Mapping

import numpy as np


@dataclass(frozen=True)
class ControlMapping:
    source: str
    control: str
    target: str
    minimum: float = 0.0
    maximum: float = 1.0

    def map_value(self, raw: float, raw_min: float = 0.0, raw_max: float = 127.0) -> float:
        if raw_max <= raw_min:
            return self.minimum
        alpha = float(np.clip((float(raw) - raw_min) / (raw_max - raw_min), 0.0, 1.0))
        return float(self.minimum + alpha * (self.maximum - self.minimum))


DEFAULT_CONTROL_MAPPINGS = (
    ControlMapping("midi", "cc1", "energy", .35, 1.50),
    ControlMapping("midi", "cc2", "stroke_depth", .35, 1.50),
    ControlMapping("midi", "cc3", "rotation_mix", .0, 1.50),
    ControlMapping("midi", "cc4", "complexity", .0, 1.0),
    ControlMapping("midi", "cc5", "gesture_density", .25, 2.0),
    ControlMapping("midi", "cc6", "smoothing", .0, .95),
    ControlMapping("midi", "cc7", "safety_aggressiveness", .0, 1.0),
    ControlMapping("osc", "/pythondancer/energy", "energy", .35, 1.50),
    ControlMapping("osc", "/pythondancer/stroke", "stroke_depth", .35, 1.50),
    ControlMapping("osc", "/pythondancer/rotation", "rotation_mix", .0, 1.50),
    ControlMapping("osc", "/pythondancer/complexity", "complexity", .0, 1.0),
    ControlMapping("osc", "/pythondancer/density", "gesture_density", .25, 2.0),
    ControlMapping("osc", "/pythondancer/smoothing", "smoothing", .0, .95),
    ControlMapping("osc", "/pythondancer/safety", "safety_aggressiveness", .0, 1.0),
    ControlMapping("osc", "/pythondancer/bpm", "bpm", 30.0, 300.0),
)


@dataclass
class ControlState:
    values: dict[str, float] = field(default_factory=dict)
    bpm: float = 120.0
    beat_phase: float = 0.0
    bar: int = 0
    playing: bool = False
    updated_at: float = 0.0

    def update(self, target: str, value: float):
        self.values[str(target)] = float(value)
        self.updated_at = time.monotonic()

    def to_dict(self):
        return {
            "values": dict(self.values),
            "bpm": self.bpm,
            "beat_phase": self.beat_phase,
            "bar": self.bar,
            "playing": self.playing,
            "updated_at": self.updated_at,
        }


class MidiControlBridge:
    def __init__(self, mappings=(), *, input_name: str | None = None, on_change: Callable[[str, float], None] | None = None):
        self.mappings = tuple(mappings) or DEFAULT_CONTROL_MAPPINGS
        self.input_name = input_name
        self.on_change = on_change
        self.state = ControlState()
        self.port = None

    def _mapping(self, control: str):
        return next((item for item in self.mappings if item.source == "midi" and item.control == control), None)

    def process_message(self, message):
        kind = getattr(message, "type", "")
        if kind == "control_change":
            control = f"cc{int(message.control)}"
            mapping = self._mapping(control)
            if mapping:
                value = mapping.map_value(float(message.value))
                self.state.update(mapping.target, value)
                if self.on_change:
                    self.on_change(mapping.target, value)
                return mapping.target, value
        if kind in ("note_on", "note_off"):
            control = f"note{int(message.note)}"
            mapping = self._mapping(control)
            if mapping:
                raw = float(getattr(message, "velocity", 0.0)) if kind == "note_on" else 0.0
                value = mapping.map_value(raw)
                self.state.update(mapping.target, value)
                if self.on_change:
                    self.on_change(mapping.target, value)
                return mapping.target, value
        return None

    def open(self):
        try:
            import mido
        except ImportError as exc:
            raise RuntimeError("MIDI control requires optional dependency 'mido'") from exc
        self.port = mido.open_input(self.input_name, callback=self.process_message)
        return self

    def close(self):
        if self.port is not None:
            try:
                self.port.close()
            finally:
                self.port = None


class OSCControlBridge:
    def __init__(self, mappings=(), *, host="127.0.0.1", port=9000, on_change: Callable[[str, float], None] | None = None):
        self.mappings = tuple(mappings) or DEFAULT_CONTROL_MAPPINGS
        self.host = host
        self.port = int(port)
        self.on_change = on_change
        self.state = ControlState()
        self.server = None
        self.thread: Thread | None = None

    def process(self, address: str, value: float):
        mapping = next((item for item in self.mappings if item.source == "osc" and item.control == address), None)
        if not mapping:
            return None
        mapped = mapping.map_value(float(value), 0.0, 1.0)
        self.state.update(mapping.target, mapped)
        if self.on_change:
            self.on_change(mapping.target, mapped)
        return mapping.target, mapped

    def start(self):
        try:
            from pythonosc.dispatcher import Dispatcher
            from pythonosc.osc_server import ThreadingOSCUDPServer
        except ImportError as exc:
            raise RuntimeError("OSC control requires optional dependency 'python-osc'") from exc
        dispatcher = Dispatcher()
        for mapping in self.mappings:
            if mapping.source != "osc":
                continue
            dispatcher.map(mapping.control, lambda address, *args: self.process(address, float(args[0]) if args else 0.0))
        self.server = ThreadingOSCUDPServer((self.host, self.port), dispatcher)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
            finally:
                self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None


class LinkClock:
    """Thin optional Link clock with a deterministic internal fallback.

    The fallback is useful for tests and for systems where an Ableton Link Python
    binding is unavailable; it preserves the same BPM/phase interface.
    """

    def __init__(self, bpm=120.0):
        self.state = ControlState(bpm=float(bpm), playing=False)
        self._started_at = time.monotonic()
        self._backend = None

    def connect(self):
        backend = None
        for module_name in ("link", "aalink"):
            try:
                backend = __import__(module_name)
                break
            except Exception:
                pass
        self._backend = backend
        return self

    def set_bpm(self, bpm: float):
        self.state.bpm = float(np.clip(bpm, 20.0, 400.0))
        self._started_at = time.monotonic()

    def start(self):
        self.state.playing = True
        self._started_at = time.monotonic()

    def stop(self):
        self.state.playing = False

    def snapshot(self) -> ControlState:
        if not self.state.playing:
            return self.state
        elapsed = time.monotonic() - self._started_at
        beats = elapsed * self.state.bpm / 60.0
        self.state.beat_phase = float(beats % 1.0)
        self.state.bar = int(beats // 4.0)
        self.state.updated_at = time.monotonic()
        return self.state


def mappings_from_dict(payload: Mapping | None):
    payload = payload or {}
    values = tuple(ControlMapping(**item) for item in payload.get("mappings", ()))
    return values or DEFAULT_CONTROL_MAPPINGS
