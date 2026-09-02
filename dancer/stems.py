"""Optional stem separation and beat-aligned source features.

Demucs remains optional. PythonDancer can consume an existing four-stem folder,
invoke an installed Demucs backend, or fall back to mixed-audio features. 2.6
adds rhythm-band proxies (kick/snare/hi-hat), bass onset, vocal pitch motion and
other-stem spectral motion so different axes can use different event clocks.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

import numpy as np

STEM_NAMES = ("drums", "bass", "vocals", "other")


def _demucs_prefix() -> list[str] | None:
    executable = shutil.which("demucs")
    if executable:
        return [executable]
    if not getattr(sys, "frozen", False) and find_spec("demucs") is not None:
        return [sys.executable, "-m", "demucs.separate"]
    return None


def demucs_available() -> bool:
    return _demucs_prefix() is not None


def find_stem_files(root: str | Path) -> dict[str, Path]:
    root = Path(root)
    if not root.exists():
        return {}
    result: dict[str, Path] = {}
    for stem in STEM_NAMES:
        direct = [root / f"{stem}.wav", root / f"{stem}.flac", root / f"{stem}.mp3"]
        found = next((path for path in direct if path.exists()), None)
        if found is None:
            matches = []
            for suffix in ("wav", "flac", "mp3"):
                matches.extend(root.rglob(f"{stem}.{suffix}"))
            found = sorted(matches, key=lambda item: (len(item.parts), str(item)))[0] if matches else None
        if found is not None:
            result[stem] = found
    return result


def separate_with_demucs(
    source: str | Path,
    *,
    cache_dir: str | Path = ".dancer_stems",
    model: str = "htdemucs",
    force: bool = False,
) -> dict[str, Path]:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    prefix = _demucs_prefix()
    if prefix is None:
        raise RuntimeError("Demucs is not available. Install it separately or pass --stem_dir with existing stems.")

    cache = Path(cache_dir)
    expected = cache / model / source.stem
    existing = find_stem_files(expected)
    if len(existing) == len(STEM_NAMES) and not force:
        return existing

    cache.mkdir(parents=True, exist_ok=True)
    command = prefix + ["-n", str(model), "-o", str(cache), str(source)]
    subprocess.run(command, check=True)
    found = find_stem_files(expected)
    if len(found) < len(STEM_NAMES):
        missing = ", ".join(stem for stem in STEM_NAMES if stem not in found)
        raise RuntimeError(f"Demucs completed but required stems were not found: {missing}")
    return found


def _aggregate_to_beats(values: np.ndarray, sr: int, hop_length: int, beat_times: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    beat_times = np.asarray(beat_times, dtype=np.float64).reshape(-1)
    if beat_times.size == 0:
        return np.asarray([], dtype=np.float64)
    if values.size == 0:
        return np.zeros(beat_times.size, dtype=np.float64)
    frame_times = np.arange(values.size, dtype=np.float64) * float(hop_length) / float(sr)
    boundaries = np.searchsorted(frame_times, beat_times, side="right")
    boundaries = np.clip(boundaries, 1, values.size)
    result = np.zeros(beat_times.size, dtype=np.float64)
    start = 0
    for index, end in enumerate(boundaries):
        end = max(start + 1, int(end))
        segment = values[start:min(end, values.size)]
        finite = segment[np.isfinite(segment)]
        result[index] = float(np.mean(finite)) if finite.size else 0.0
        start = min(end, values.size - 1)
    return result


def _weighted_pitch(y: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    import librosa

    pitches, magnitudes = librosa.piptrack(y=y, sr=sr, hop_length=hop_length)
    numerator = np.sum(pitches * magnitudes, axis=0)
    denominator = np.sum(magnitudes, axis=0)
    weighted = np.divide(numerator, denominator, out=np.zeros_like(numerator, dtype=np.float64), where=denominator > 1e-9)
    return np.log10(np.maximum(weighted, 0.01))


def _spectral_band_envelope(y: np.ndarray, sr: int, hop_length: int, low: float, high: float | None) -> np.ndarray:
    import librosa

    spectrum = np.abs(librosa.stft(y=y, hop_length=hop_length))
    frequencies = librosa.fft_frequencies(sr=sr)
    mask = frequencies >= float(low)
    if high is not None:
        mask &= frequencies < float(high)
    if not np.any(mask):
        return np.zeros(spectrum.shape[1], dtype=np.float64)
    return np.mean(spectrum[mask], axis=0)


def _confidence(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = values[np.isfinite(values)]
    if finite.size < 3:
        return 0.0
    spread = float(np.std(finite))
    magnitude = float(np.mean(np.abs(finite)))
    return float(np.clip(spread / max(magnitude, 1e-8), 0.0, 1.0))


def extract_stem_features(stem_files: Mapping[str, str | Path], beat_times, *, hop_length: int = 512) -> dict[str, np.ndarray]:
    """Extract compact beat-aligned features from separated source stems."""
    import librosa

    beats = np.asarray(beat_times, dtype=np.float64).reshape(-1)
    output: dict[str, np.ndarray] = {}
    for stem in STEM_NAMES:
        path = stem_files.get(stem)
        if path is None:
            continue
        y, sr = librosa.load(str(path), sr=None, mono=True)
        y = np.nan_to_num(np.asarray(y, dtype=np.float32).reshape(-1), copy=False)
        if y.size == 0 or sr <= 0:
            continue
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        output[f"stem_{stem}_energy"] = _aggregate_to_beats(rms, sr, hop_length, beats)

        if stem == "drums":
            onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
            output["stem_drums_onset"] = _aggregate_to_beats(onset, sr, hop_length, beats)
            output["stem_drums_kick"] = _aggregate_to_beats(_spectral_band_envelope(y, sr, hop_length, 25., 180.), sr, hop_length, beats)
            output["stem_drums_snare"] = _aggregate_to_beats(_spectral_band_envelope(y, sr, hop_length, 180., 3500.), sr, hop_length, beats)
            output["stem_drums_hihat"] = _aggregate_to_beats(_spectral_band_envelope(y, sr, hop_length, 5000., None), sr, hop_length, beats)
        elif stem == "bass":
            onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
            output["stem_bass_onset"] = _aggregate_to_beats(onset, sr, hop_length, beats)
            output["stem_bass_low"] = _aggregate_to_beats(_spectral_band_envelope(y, sr, hop_length, 25., 220.), sr, hop_length, beats)
        elif stem == "vocals":
            pitch = _weighted_pitch(y, sr, hop_length)
            beat_pitch = _aggregate_to_beats(pitch, sr, hop_length, beats)
            output["stem_vocals_pitch"] = beat_pitch
            movement = np.zeros_like(beat_pitch)
            if beat_pitch.size > 1:
                movement[1:] = np.abs(np.diff(beat_pitch))
            output["stem_vocals_pitch_motion"] = movement
        elif stem == "other":
            centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]
            output["stem_other_centroid"] = _aggregate_to_beats(centroid, sr, hop_length, beats)
    return output


def enrich_with_stems(
    data: Mapping,
    source: str | Path,
    *,
    mode: str = "off",
    stem_dir: str | Path | None = None,
    cache_dir: str | Path = ".dancer_stems",
    model: str = "htdemucs",
) -> dict:
    """Return a feature dictionary enriched with optional stem features.

    mode:
      off      - never inspect stems;
      auto     - use supplied stems, otherwise Demucs only when available;
      required - fail when four stems cannot be obtained.
    """
    if mode not in ("off", "auto", "required"):
        raise ValueError("stem mode must be off, auto, or required")
    result = dict(data)
    if mode == "off":
        result["stem_analysis"] = {"status": "off"}
        return result

    files = find_stem_files(stem_dir) if stem_dir else {}
    source_kind = "provided" if files else ""
    if len(files) < len(STEM_NAMES) and demucs_available():
        try:
            files = separate_with_demucs(source, cache_dir=cache_dir, model=model)
            source_kind = "demucs"
        except Exception as exc:
            if mode == "required":
                raise
            result["stem_analysis"] = {"status": "failed", "error": str(exc)}
            return result

    if len(files) < len(STEM_NAMES):
        missing = [stem for stem in STEM_NAMES if stem not in files]
        if mode == "required":
            raise RuntimeError("stem analysis required but missing: " + ", ".join(missing))
        result["stem_analysis"] = {"status": "unavailable", "missing": missing}
        return result

    features = extract_stem_features(files, result.get("beats", []))
    result.update(features)
    confidence = {name: _confidence(values) for name, values in features.items()}
    result["stem_analysis"] = {
        "status": "ready",
        "source": source_kind or "provided",
        "model": model if source_kind == "demucs" else None,
        "files": {stem: str(path) for stem, path in files.items()},
        "features": sorted(features),
        "confidence": confidence,
        "mean_confidence": float(np.mean(list(confidence.values()))) if confidence else 0.0,
    }
    return result
