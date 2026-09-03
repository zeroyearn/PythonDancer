"""Optional live audio capture and low-latency TCode sink for PythonDancer 3.0."""
from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Callable

import numpy as np

from .live import LiveChoreographyEngine, StreamingAudioFeatures
from .tcode import SerialTCodeDevice, encode_axis


AXES = ("L0", "L1", "L2", "R0", "R1", "R2")
ROTATION_AXES = {"R0", "R1", "R2"}
SECONDARY_AXES = {"L1", "L2", "R1", "R2"}


def list_audio_devices():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("live audio capture requires python-dancer[live]") from exc
    devices = sd.query_devices()
    return [
        {
            "index": index,
            "name": str(item.get("name", f"Device {index}")),
            "inputs": int(item.get("max_input_channels", 0)),
            "outputs": int(item.get("max_output_channels", 0)),
            "default_samplerate": float(item.get("default_samplerate", 0.0)),
        }
        for index, item in enumerate(devices)
    ]


class SoundDeviceLiveSource:
    def __init__(self, *, device=None, samplerate: int = 48000, blocksize: int = 1024):
        self.device = device
        self.samplerate = int(samplerate)
        self.blocksize = int(blocksize)
        self.queue: Queue = Queue(maxsize=12)
        self.stream = None

    def start(self):
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("live audio capture requires python-dancer[live]") from exc

        def callback(indata, frames, time_info, status):
            block = indata[:, 0].copy()
            try:
                self.queue.put_nowait((monotonic(), block))
            except Exception:
                try:
                    self.queue.get_nowait()
                except Empty:
                    pass
                try:
                    self.queue.put_nowait((monotonic(), block))
                except Exception:
                    pass

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self.stream.start()
        return self

    def read(self, timeout: float = .25):
        return self.queue.get(timeout=timeout)

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
            self.stream = None


class TCodeLiveSink:
    def __init__(self, port: str, *, baud: int = 115200, timeout: float = .25, interval_ms: int = 80):
        self.port = port
        self.baud = int(baud)
        self.timeout = float(timeout)
        self.interval_ms = max(20, int(interval_ms))
        self.device = None
        self.profile = None

    def open(self):
        self.device = SerialTCodeDevice(self.port, baud=self.baud, timeout=self.timeout)
        self.device.open()
        try:
            self.profile = self.device.profile()
        except Exception:
            self.profile = None
        return self

    def send_pose(self, pose, *, interval_ms: int | None = None):
        if self.device is None:
            raise RuntimeError("live TCode sink is not open")
        duration = self.interval_ms if interval_ms is None else max(20, int(interval_ms))
        commands = []
        for axis in AXES:
            axis_range = None
            if self.profile is not None and self.profile.axes:
                if axis not in self.profile.axes:
                    continue
                axis_range = self.profile.axes.get(axis)
            commands.append(encode_axis(axis, float(pose.get(axis, 50.0)), interval_ms=duration, axis_range=axis_range))
        if commands:
            self.device.send(" ".join(commands))

    def stop(self):
        if self.device is not None:
            try:
                self.device.stop()
            finally:
                self.device.close()
                self.device = None


class LiveSession:
    """Background live audio -> planner -> control surfaces -> safety -> sink.

    ``control_state`` may return an object/dict with BPM/beat phase and optional
    live controls such as energy, stroke_depth, rotation_mix, complexity,
    gesture_density, smoothing and safety_aggressiveness. Control shaping always
    happens before ``pose_transform`` so Device Twin safe-pose projection remains
    authoritative for hardware output.
    """

    def __init__(
        self,
        source: SoundDeviceLiveSource,
        engine: LiveChoreographyEngine,
        *,
        sink: TCodeLiveSink | None = None,
        on_motion: Callable | None = None,
        pose_transform: Callable | None = None,
        bpm: float = 120.0,
        control_state: Callable | None = None,
    ):
        self.source = source
        self.engine = engine
        self.sink = sink
        self.on_motion = on_motion
        self.pose_transform = pose_transform
        self.bpm = float(bpm)
        self.control_state = control_state
        self.stop_event = Event()
        self.worker: Thread | None = None
        self.extractor = StreamingAudioFeatures(source.samplerate)
        self._phase_anchor = monotonic()
        self._last_control_pose = None

    def _control_snapshot(self):
        if self.control_state is None:
            return None
        try:
            return self.control_state()
        except Exception:
            return None

    @staticmethod
    def _state_value(state, name, default=None):
        if state is None:
            return default
        if isinstance(state, dict):
            values = state.get("values") or {}
            return values.get(name, state.get(name, default))
        values = getattr(state, "values", {}) or {}
        return values.get(name, getattr(state, name, default))

    def _transport(self, timestamp: float, state=None):
        bpm = self.bpm
        phase = None
        if state is not None:
            bpm = float(self._state_value(state, "bpm", bpm))
            phase = self._state_value(state, "beat_phase", None)
            if bpm > 1e-6:
                self.bpm = bpm
        period = 60.0 / max(1e-6, self.bpm)
        if phase is None:
            phase = ((timestamp - self._phase_anchor) / period) % 1.0
        return self.bpm, float(phase) % 1.0

    def _apply_control_values(self, pose, state):
        if state is None:
            return dict(pose)
        output = {axis: float(pose.get(axis, 50.0)) for axis in AXES}
        energy = self._state_value(state, "energy", None)
        stroke = self._state_value(state, "stroke_depth", None)
        rotation = self._state_value(state, "rotation_mix", None)
        complexity = self._state_value(state, "complexity", None)
        density = self._state_value(state, "gesture_density", None)
        safety = self._state_value(state, "safety_aggressiveness", None)

        for axis in AXES:
            scale = 1.0
            if energy is not None:
                scale *= float(np.clip(energy, 0.0, 1.75))
            if axis == "L0" and stroke is not None:
                scale *= float(np.clip(stroke, 0.0, 1.75))
            if axis in ROTATION_AXES and rotation is not None:
                scale *= float(np.clip(rotation, 0.0, 1.75))
            if axis in SECONDARY_AXES and complexity is not None:
                scale *= .70 + .60 * float(np.clip(complexity, 0.0, 1.0))
            if axis in SECONDARY_AXES and density is not None:
                scale *= .60 + .40 * float(np.clip(density, 0.0, 2.0))
            if safety is not None:
                scale *= .70 + .30 * float(np.clip(safety, 0.0, 1.0))
            output[axis] = float(np.clip(50.0 + (output[axis] - 50.0) * scale, 0.0, 100.0))

        smoothing = self._state_value(state, "smoothing", None)
        if smoothing is not None and self._last_control_pose is not None:
            amount = float(np.clip(smoothing, 0.0, .95))
            for axis in AXES:
                output[axis] = float(self._last_control_pose[axis] * amount + output[axis] * (1.0 - amount))
        self._last_control_pose = dict(output)
        return output

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.stop_event.clear()
        self._last_control_pose = None
        source_started = False
        sink_opened = False
        try:
            self.source.start()
            source_started = True
            if self.sink is not None:
                self.sink.open()
                sink_opened = True
        except Exception:
            if sink_opened and self.sink is not None:
                try:
                    self.sink.stop()
                except Exception:
                    pass
            if source_started:
                try:
                    self.source.stop()
                except Exception:
                    pass
            raise

        def work():
            try:
                while not self.stop_event.is_set():
                    try:
                        timestamp, block = self.source.read(.15)
                    except Empty:
                        continue
                    control = self._control_snapshot()
                    bpm, phase = self._transport(timestamp, control)
                    frame = self.extractor.analyze(
                        block,
                        timestamp=timestamp,
                        bpm=bpm,
                        beat_phase=phase,
                        confidence=.72 if control is not None else .55,
                    )
                    motion = self.engine.process(frame)
                    output_pose = self._apply_control_values(motion.pose, control)
                    if self.pose_transform is not None:
                        output_pose = dict(self.pose_transform(output_pose))
                    if self.sink is not None:
                        self.sink.send_pose(output_pose, interval_ms=max(20, int(motion.prediction_ms)))
                    if self.on_motion is not None:
                        self.on_motion(frame, motion, output_pose)
            finally:
                try:
                    if self.sink is not None:
                        self.sink.stop()
                finally:
                    self.source.stop()

        self.worker = Thread(target=work, daemon=True)
        self.worker.start()
        return self

    def stop(self):
        self.stop_event.set()
