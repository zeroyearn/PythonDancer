"""Optional live audio capture and low-latency TCode sink for PythonDancer 2.8."""
from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Callable

from .live import LiveChoreographyEngine, StreamingAudioFeatures
from .tcode import SerialTCodeDevice, encode_axis


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
    """Capture mono audio and emit fixed-size numpy blocks through a queue."""

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
    """Persistent serial sink for one predictive pose at a time."""

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
        for axis in ("L0", "L1", "L2", "R0", "R1", "R2"):
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
    """Background live audio -> features -> planner -> optional hardware sink."""

    def __init__(
        self,
        source: SoundDeviceLiveSource,
        engine: LiveChoreographyEngine,
        *,
        sink: TCodeLiveSink | None = None,
        on_motion: Callable | None = None,
        pose_transform: Callable | None = None,
        bpm: float = 120.0,
    ):
        self.source = source
        self.engine = engine
        self.sink = sink
        self.on_motion = on_motion
        self.pose_transform = pose_transform
        self.bpm = float(bpm)
        self.stop_event = Event()
        self.worker: Thread | None = None
        self.extractor = StreamingAudioFeatures(source.samplerate)
        self._phase_anchor = monotonic()

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.source.start()
        if self.sink is not None:
            self.sink.open()

        def work():
            try:
                while not self.stop_event.is_set():
                    try:
                        timestamp, block = self.source.read(.15)
                    except Empty:
                        continue
                    period = 60.0 / max(1e-6, self.bpm)
                    phase = ((timestamp - self._phase_anchor) / period) % 1.0
                    frame = self.extractor.analyze(
                        block,
                        timestamp=timestamp,
                        bpm=self.bpm,
                        beat_phase=phase,
                        confidence=.55,
                    )
                    motion = self.engine.process(frame)
                    output_pose = dict(motion.pose)
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

    def stop(self):
        self.stop_event.set()
