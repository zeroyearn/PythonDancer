"""Audio feature extraction for PythonDancer.

The public output is intentionally dictionary based so older callers that expect
``data["beats"]``, ``data["pitch"]`` and ``data["energy"]`` keep working.
"""
from __future__ import annotations

from typing import Iterable

import librosa
import numpy as np

EPSILON = 1e-9


def safe_normalize(values: Iterable[float]) -> np.ndarray:
    """Normalize finite values to 0..1 without producing NaN/inf."""
    data = np.asarray(values, dtype=np.float64)
    if data.size == 0:
        return np.asarray([], dtype=np.float64)
    finite = np.isfinite(data)
    if not finite.any():
        return np.zeros_like(data, dtype=np.float64)
    clean = data.copy()
    finite_values = clean[finite]
    minimum = float(np.min(finite_values))
    maximum = float(np.max(finite_values))
    clean[~finite] = minimum
    span = maximum - minimum
    if span <= EPSILON:
        return np.zeros_like(clean, dtype=np.float64)
    return np.clip((clean - minimum) / span, 0.0, 1.0)


def _weighted_pitch(y: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr, hop_length=hop_length, center=True)
    numerator = np.sum(pitches * magnitudes, axis=0)
    denominator = np.sum(magnitudes, axis=0)
    weighted = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator, dtype=np.float64),
        where=denominator > EPSILON,
    )
    return np.log10(np.maximum(weighted, 0.01))


def _band_energy(magnitude: np.ndarray, frequencies: np.ndarray, low_hz: float, high_hz: float | None) -> np.ndarray:
    mask = frequencies >= low_hz
    if high_hz is not None:
        mask &= frequencies < high_hz
    if not np.any(mask):
        return np.zeros(magnitude.shape[1], dtype=np.float64)
    return np.sqrt(np.mean(np.square(magnitude[mask]), axis=0))


def _aggregate_to_beats(values: np.ndarray, beat_frames: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    beat_frames = np.asarray(beat_frames, dtype=np.int64).reshape(-1)
    if beat_frames.size == 0:
        return np.asarray([], dtype=np.float64)
    if values.size == 0:
        return np.zeros(beat_frames.size, dtype=np.float64)
    beat_frames = np.clip(beat_frames, 1, values.size)
    beat_frames = np.maximum.accumulate(beat_frames)
    boundaries = np.concatenate(([0], beat_frames))
    result = np.zeros(beat_frames.size, dtype=np.float64)
    for i in range(beat_frames.size):
        start = int(boundaries[i])
        end = int(boundaries[i + 1])
        if end <= start:
            idx = min(max(end - 1, 0), values.size - 1)
            result[i] = values[idx]
        else:
            segment = values[start:end]
            finite = segment[np.isfinite(segment)]
            result[i] = float(np.mean(finite)) if finite.size else 0.0
    return result


def _fallback_beat_frames(onset: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    frames = librosa.onset.onset_detect(
        onset_envelope=onset,
        sr=sr,
        hop_length=hop_length,
        units="frames",
        backtrack=False,
    )
    frames = np.asarray(frames, dtype=np.int64).reshape(-1)
    if frames.size:
        return frames
    frame_count = max(1, onset.size)
    step = max(1, int(round(sr / hop_length)))
    frames = np.arange(step, frame_count + 1, step, dtype=np.int64)
    if frames.size == 0:
        frames = np.asarray([frame_count], dtype=np.int64)
    return frames


def waveform_preview(samples: np.ndarray, sr: int, *, points: int = 1200) -> tuple[np.ndarray, np.ndarray]:
    """Return a small peak envelope suitable for the interactive timeline.

    This deliberately stores only a display envelope, not the decoded audio, so
    normal analysis results remain compact enough for project/session metadata.
    """
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    if values.size == 0 or sr <= 0:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    count = max(16, min(int(points), values.size))
    edges = np.linspace(0, values.size, count + 1, dtype=np.int64)
    envelope = np.zeros(count, dtype=np.float64)
    for i in range(count):
        segment = values[edges[i]:edges[i + 1]]
        if segment.size:
            envelope[i] = float(np.max(np.abs(segment)))
    peak = float(np.max(envelope)) if envelope.size else 0.0
    if peak > EPSILON:
        envelope /= peak
    duration = values.size / float(sr)
    times = np.linspace(0.0, duration, count, endpoint=False, dtype=np.float64)
    return times, np.clip(envelope, 0.0, 1.0)


def extract_audio_features(
    y: np.ndarray,
    sr: int,
    *,
    hop_length: int = 512,
    frame_length: int = 2048,
    plp: bool = True,
) -> dict[str, np.ndarray | float]:
    """Extract beat-aligned rhythmic/spectral features plus a UI waveform envelope."""
    samples = np.asarray(y, dtype=np.float32).reshape(-1)
    if samples.size == 0 or sr <= 0:
        raise ValueError("Input contains no decodable audio samples")
    if not np.isfinite(samples).any():
        raise ValueError("Input audio contains no finite samples")
    samples = np.nan_to_num(samples, copy=False)

    preview_times, preview_envelope = waveform_preview(samples, sr)
    onset = librosa.onset.onset_strength(y=samples, sr=sr, hop_length=hop_length)
    beat_envelope = onset
    if plp and onset.size:
        beat_envelope = librosa.beat.plp(onset_envelope=onset, sr=sr, hop_length=hop_length)

    tempo, beat_frames = librosa.beat.beat_track(
        y=samples,
        sr=sr,
        onset_envelope=beat_envelope,
        hop_length=hop_length,
        trim=False,
        units="frames",
    )
    beat_frames = np.asarray(beat_frames, dtype=np.int64).reshape(-1)
    if beat_frames.size < 2:
        beat_frames = _fallback_beat_frames(onset, sr, hop_length)

    rms = librosa.feature.rms(y=samples, frame_length=frame_length, hop_length=hop_length, center=True)[0]
    pitch = _weighted_pitch(samples, sr, hop_length)
    stft = np.abs(librosa.stft(samples, n_fft=frame_length, hop_length=hop_length))
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=frame_length)
    bass = _band_energy(stft, frequencies, 20.0, 180.0)
    mid = _band_energy(stft, frequencies, 180.0, 2000.0)
    high = _band_energy(stft, frequencies, 2000.0, None)

    harmonic, percussive = librosa.effects.hpss(samples)
    harmonic_rms = librosa.feature.rms(y=harmonic, frame_length=frame_length, hop_length=hop_length, center=True)[0]
    percussive_rms = librosa.feature.rms(y=percussive, frame_length=frame_length, hop_length=hop_length, center=True)[0]

    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
    tempo_value = float(np.asarray(tempo, dtype=np.float64).reshape(-1)[0]) if np.size(tempo) else 0.0

    return {
        "at": float(librosa.get_duration(y=samples, sr=sr)),
        "sr": float(sr),
        "tempo": tempo_value,
        "beats": np.asarray(beats, dtype=np.float64),
        "pitch": _aggregate_to_beats(pitch, beat_frames),
        "energy": _aggregate_to_beats(rms, beat_frames),
        "onset": _aggregate_to_beats(onset, beat_frames),
        "bass": _aggregate_to_beats(bass, beat_frames),
        "mid": _aggregate_to_beats(mid, beat_frames),
        "high": _aggregate_to_beats(high, beat_frames),
        "harmonic": _aggregate_to_beats(harmonic_rms, beat_frames),
        "percussive": _aggregate_to_beats(percussive_rms, beat_frames),
        "waveform_times": preview_times,
        "waveform_envelope": preview_envelope,
    }
