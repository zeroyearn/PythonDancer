"""Low-latency predictive live choreography engine for PythonDancer 2.8."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Mapping

import numpy as np

from .intent import MotionIntent

AXES = ("L0", "L1", "L2", "R0", "R1", "R2")


@dataclass(frozen=True)
class LiveFeatureFrame:
    timestamp: float
    bpm: float = 120.0
    beat_phase: float = 0.0
    beat_confidence: float = 0.0
    energy: float = 0.0
    onset: float = 0.0
    bass: float = 0.0
    mid: float = 0.0
    high: float = 0.0
    vocals: float = 0.0

    def __post_init__(self):
        if not np.isfinite(self.timestamp):
            raise ValueError("live timestamp must be finite")
        object.__setattr__(self, "bpm", float(np.clip(self.bpm if np.isfinite(self.bpm) else 120.0, 30.0, 300.0)))
        object.__setattr__(self, "beat_phase", float(self.beat_phase % 1.0 if np.isfinite(self.beat_phase) else 0.0))
        object.__setattr__(self, "beat_confidence", float(np.clip(self.beat_confidence, 0.0, 1.0)))
        for name in ("energy", "onset", "bass", "mid", "high", "vocals"):
            value = float(getattr(self, name))
            object.__setattr__(self, name, float(np.clip(value if np.isfinite(value) else 0.0, 0.0, 1.0)))


@dataclass(frozen=True)
class LiveMotionFrame:
    target_time: float
    pose: Mapping[str, float]
    intent: MotionIntent
    gesture: str
    bpm: float
    beat_confidence: float
    prediction_ms: float

    def to_dict(self):
        return {
            "target_time": float(self.target_time),
            "pose": {axis: float(self.pose.get(axis, 50.0)) for axis in AXES},
            "intent": self.intent.to_dict(),
            "gesture": self.gesture,
            "bpm": float(self.bpm),
            "beat_confidence": float(self.beat_confidence),
            "prediction_ms": float(self.prediction_ms),
        }


@dataclass
class PredictiveBeatScheduler:
    prediction_horizon_ms: float = 420.0
    latency_ms: float = 0.0
    smoothing: float = .18
    bpm: float = 120.0
    phase: float = 0.0
    confidence: float = 0.0
    last_timestamp: float | None = None

    def update(self, frame: LiveFeatureFrame):
        alpha = float(np.clip(self.smoothing, 0.0, 1.0))
        if self.last_timestamp is None:
            self.bpm = frame.bpm
            self.phase = frame.beat_phase
            self.confidence = frame.beat_confidence
        else:
            self.bpm = (1.0 - alpha) * self.bpm + alpha * frame.bpm
            # Circular phase blend around the shortest direction.
            delta = ((frame.beat_phase - self.phase + .5) % 1.0) - .5
            self.phase = (self.phase + alpha * delta) % 1.0
            self.confidence = (1.0 - alpha) * self.confidence + alpha * frame.beat_confidence
        self.last_timestamp = frame.timestamp

    @property
    def beat_period(self) -> float:
        return 60.0 / max(1e-6, self.bpm)

    def next_beat_time(self, now: float | None = None) -> float:
        now = float(time.monotonic() if now is None else now)
        reference = now if self.last_timestamp is None else float(self.last_timestamp)
        elapsed = max(0.0, now - reference)
        phase_now = (self.phase + elapsed / self.beat_period) % 1.0
        wait = (1.0 - phase_now) * self.beat_period
        if wait < 1e-5:
            wait = self.beat_period
        return now + wait

    def command_target(self, now: float | None = None) -> tuple[float, float]:
        now = float(time.monotonic() if now is None else now)
        next_beat = self.next_beat_time(now)
        horizon = max(0.0, self.prediction_horizon_ms) / 1000.0
        lead = max(0.0, self.latency_ms) / 1000.0
        target = max(now, min(next_beat, now + horizon))
        command_time = max(now, target - lead)
        return target, command_time


@dataclass
class LiveChoreographyConfig:
    prediction_horizon_ms: float = 420.0
    latency_ms: float = 0.0
    strength: float = 1.0
    rotation_mix: float = 1.0
    smoothing: float = .28
    max_step: Mapping[str, float] = field(default_factory=lambda: {
        "L0": 22.0, "L1": 10.0, "L2": 11.0, "R0": 16.0, "R1": 12.0, "R2": 11.0,
    })


class LiveChoreographyEngine:
    """Convert streaming musical features into predictive six-axis poses.

    The planner is deliberately deterministic and bounded. Device-specific
    projection should still be applied by DeviceTwinProfile before output.
    """

    def __init__(self, config: LiveChoreographyConfig | None = None):
        self.config = config or LiveChoreographyConfig()
        self.scheduler = PredictiveBeatScheduler(
            prediction_horizon_ms=self.config.prediction_horizon_ms,
            latency_ms=self.config.latency_ms,
        )
        self.pose = {axis: 50.0 for axis in AXES}
        self._beat_index = 0

    def _intent(self, frame: LiveFeatureFrame) -> MotionIntent:
        return MotionIntent(
            intensity=.45 * frame.energy + .30 * frame.bass + .25 * frame.onset,
            aggression=.52 * frame.onset + .28 * frame.high + .20 * frame.bass,
            flow=.45 * frame.vocals + .30 * frame.mid + .25 * (1.0 - frame.onset),
            complexity=.34 * frame.high + .34 * frame.onset + .32 * frame.mid,
            symmetry=.55 * (1.0 - frame.onset) + .45 * frame.mid,
            rotation_bias=.44 * frame.vocals + .34 * frame.high + .22 * frame.mid,
            translation_bias=.48 * frame.bass + .32 * frame.energy + .20 * (1.0 - frame.high),
            accent_density=.62 * frame.onset + .38 * frame.high,
        )

    def _gesture(self, intent: MotionIntent) -> str:
        if intent.aggression > .72 and intent.accent_density > .65:
            return "accent"
        if intent.rotation_bias > .67 and intent.flow > .55:
            return "spiral"
        if intent.flow > .68:
            return "wave"
        if intent.translation_bias > .66:
            return "rock"
        return "pulse"

    def _desired_pose(self, frame: LiveFeatureFrame, intent: MotionIntent) -> dict[str, float]:
        phase = 2.0 * math.pi * frame.beat_phase
        beat = math.sin(phase)
        quadrature = math.cos(phase)
        strength = max(0.0, float(self.config.strength))
        rotation = max(0.0, float(self.config.rotation_mix))
        accent = frame.onset * (1.0 if beat >= 0 else -1.0)
        return {
            "L0": 50.0 + strength * (30.0 * beat * (.35 + .65 * intent.intensity) + 10.0 * accent),
            "L1": 50.0 + strength * 17.0 * quadrature * (.25 + .75 * frame.bass),
            "L2": 50.0 + strength * 18.0 * beat * (.25 + .75 * frame.high),
            "R0": 50.0 + strength * rotation * 28.0 * quadrature * (.25 + .75 * intent.rotation_bias),
            "R1": 50.0 - strength * rotation * 20.0 * beat * (.25 + .75 * frame.onset),
            "R2": 50.0 + strength * rotation * 18.0 * quadrature * (.25 + .75 * frame.vocals),
        }

    def process(self, frame: LiveFeatureFrame) -> LiveMotionFrame:
        self.scheduler.update(frame)
        intent = self._intent(frame)
        desired = self._desired_pose(frame, intent)
        smoothing = float(np.clip(self.config.smoothing, 0.0, .95))
        for axis in AXES:
            current = float(self.pose[axis])
            target = float(np.clip(desired[axis], 0.0, 100.0))
            blended = smoothing * current + (1.0 - smoothing) * target
            max_step = max(.1, float(self.config.max_step.get(axis, 12.0)))
            self.pose[axis] = float(np.clip(current + np.clip(blended - current, -max_step, max_step), 0.0, 100.0))
        target_time, _ = self.scheduler.command_target(frame.timestamp)
        prediction_ms = max(0.0, (target_time - frame.timestamp) * 1000.0)
        return LiveMotionFrame(
            target_time=target_time,
            pose=dict(self.pose),
            intent=intent,
            gesture=self._gesture(intent),
            bpm=self.scheduler.bpm,
            beat_confidence=self.scheduler.confidence,
            prediction_ms=prediction_ms,
        )


class StreamingAudioFeatures:
    """Small dependency-free audio feature extractor for optional live capture."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = int(sample_rate)
        self._energy_ema = 1e-4

    def analyze(self, samples, *, timestamp: float | None = None, bpm: float = 120.0, beat_phase: float = 0.0, confidence: float = .5):
        array = np.asarray(samples, dtype=np.float64).reshape(-1)
        if array.size == 0:
            array = np.zeros(64, dtype=np.float64)
        rms = float(np.sqrt(np.mean(array * array)))
        self._energy_ema = .92 * self._energy_ema + .08 * max(rms, 1e-6)
        energy = float(np.clip(rms / max(self._energy_ema * 2.2, 1e-6), 0.0, 1.0))
        window = np.hanning(array.size)
        spectrum = np.abs(np.fft.rfft(array * window))
        freqs = np.fft.rfftfreq(array.size, 1.0 / self.sample_rate)

        def band(low, high):
            mask = (freqs >= low) & (freqs < high)
            if not np.any(mask):
                return 0.0
            return float(np.mean(spectrum[mask]))

        bass_raw = band(30, 180)
        mid_raw = band(180, 2400)
        high_raw = band(2400, 9000)
        total = max(bass_raw + mid_raw + high_raw, 1e-9)
        onset = float(np.clip((rms - self._energy_ema) / max(self._energy_ema, 1e-6) * 1.8, 0.0, 1.0))
        return LiveFeatureFrame(
            timestamp=float(time.monotonic() if timestamp is None else timestamp),
            bpm=bpm,
            beat_phase=beat_phase,
            beat_confidence=confidence,
            energy=energy,
            onset=onset,
            bass=float(np.clip(bass_raw / total * 2.2, 0.0, 1.0)),
            mid=float(np.clip(mid_raw / total * 2.0, 0.0, 1.0)),
            high=float(np.clip(high_raw / total * 2.4, 0.0, 1.0)),
            vocals=float(np.clip(mid_raw / total * 1.6, 0.0, 1.0)),
        )
