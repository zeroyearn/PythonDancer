"""Optional stem separation and beat-aligned stem feature enrichment.

Demucs is deliberately optional. PythonDancer remains lightweight by default:
users may provide an existing stem directory, let PythonDancer invoke an
installed Demucs package, or keep stem analysis disabled.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
from typing import Mapping

import numpy as np

STEM_NAMES = ("drums", "bass", "vocals", "other")


def demucs_available() -> bool:
    return find_spec("demucs") is not None


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
    if not demucs_available():
        raise RuntimeError("Demucs is not installed. Install it separately or pass --stem_dir with existing stems.")

    cache = Path(cache_dir)
    expected = cache / model / source.stem
    existing = find_stem_files(expected)
    if len(existing) == len(STEM_NAMES) and not force:
        return existing

    cache.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        str(model),
        "-o",
        str(cache),
        str(source),
    ]
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
        elif stem == "vocals":
            pitch = _weighted_pitch(y, sr, hop_length)
            output["stem_vocals_pitch"] = _aggregate_to_beats(pitch, sr, hop_length, beats)
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
      auto     - use supplied stems, otherwise Demucs only when installed;
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
    result["stem_analysis"] = {
        "status": "ready",
        "source": source_kind or "provided",
        "model": model if source_kind == "demucs" else None,
        "files": {stem: str(path) for stem, path in files.items()},
        "features": sorted(features),
    }
    return result
