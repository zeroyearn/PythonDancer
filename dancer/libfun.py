"""Backward-compatible public API for PythonDancer's analysis and motion engine."""
from __future__ import annotations

from json import dump
from pathlib import Path
import subprocess

import matplotlib as mpl
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from scipy.optimize import minimize_scalar

from .features import extract_audio_features, safe_normalize
from .motion import MotionConfig, plan_motion

VERSION = "2.4.0"
HEATMAP = LinearSegmentedColormap.from_list(
    "intensity", ["white", "green", "orange", "red"], N=256
)


def load_audio_data(audio_file: str | Path, hop_length: int = 512, frame_length: int = 2048, plp: bool = True):
    import librosa

    try:
        y, sr = librosa.load(str(audio_file), sr=None, mono=True)
    except Exception:
        try:
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-i", str(audio_file), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"
            ])
            y = np.frombuffer(raw, dtype=np.float32)
            sr = 48000
        except Exception as exc:
            raise ValueError(f"Unable to decode audio from {audio_file}") from exc
    return extract_audio_features(y, int(sr), hop_length=hop_length, frame_length=frame_length, plp=plp)


def normalize(data):
    """Backward-compatible normalization helper."""
    return safe_normalize(data)


def _speed(actions):
    """Return normalized-units/second between action points without division by zero."""
    if len(actions) < 2:
        return np.asarray([], dtype=np.float64)
    t = np.asarray([item[0] for item in actions], dtype=np.float64)
    p = np.asarray([item[1] for item in actions], dtype=np.float64)
    dt = np.diff(t)
    dp = np.diff(p)
    return np.divide(dp, dt, out=np.zeros_like(dp), where=np.abs(dt) > 1e-12)


def plan_actions(data, *, planner="adaptive", energy=1.0, pitch=100.0, overflow=0, amplitude_centering=0.0, center_offset=0.0, subdivision=0, max_speed=400.0, max_acceleration=2400.0, min_interval=0.02):
    if planner == "adaptive":
        return plan_motion(
            data,
            MotionConfig(
                energy_multiplier=float(energy),
                pitch_range=float(pitch),
                overflow=int(overflow),
                amplitude_centering=float(amplitude_centering),
                center_offset=float(center_offset),
                subdivision=int(subdivision),
                max_speed=float(max_speed),
                max_acceleration=float(max_acceleration),
                min_interval=float(min_interval),
            ),
        )
    if planner != "legacy":
        raise ValueError("planner must be 'adaptive' or 'legacy'")

    # Legacy compatibility: map beat-aligned pitch/energy directly to extrema.
    beats = np.asarray(data.get("beats", []), dtype=np.float64)
    p = safe_normalize(data.get("pitch", []))
    e = safe_normalize(data.get("energy", []))
    n = min(len(beats), len(p), len(e))
    if n == 0:
        return []
    actions = []
    direction = 1.0
    for i in range(n):
        center = 50.0 + (float(p[i]) - 0.5) * float(pitch) + float(center_offset)
        amp = float(e[i]) * float(energy) * 50.0
        value = center + direction * amp
        if int(overflow) == 1:
            value %= 200.0
            if value > 100.0:
                value = 200.0 - value
        else:
            value = np.clip(value, 0.0, 100.0)
        actions.append((float(beats[i]), float(value)))
        direction *= -1.0
    return actions


def autoval(data, tpi=100, target_speed=300, v2above=.4, opt=1, planner="adaptive"):
    """Estimate pitch range and energy multiplier for a target action speed.

    Keeps the original public signature while avoiding NaN/zero-division and
    using the selected motion planner for the objective.
    """
    pitch_values = safe_normalize(data.get("pitch", []))
    if pitch_values.size:
        p_hi = float(np.quantile(pitch_values, max(0.5, min(0.999, 1.0 - float(v2above)))))
        pitch = max(10.0, min(100.0, float(tpi) * (0.65 + 0.35 * p_hi)))
    else:
        pitch = max(10.0, min(100.0, float(tpi)))

    def objective(multiplier):
        actions = plan_actions(data, planner=planner, pitch=pitch, energy=float(multiplier))
        speeds = np.abs(_speed(actions))
        if speeds.size == 0:
            return abs(float(target_speed))
        if int(opt) == 0:
            measured = float(np.mean(speeds))
        elif int(opt) == 2:
            measured = float(np.quantile(speeds, .85))
        else:
            measured = float(np.median(speeds))
        return abs(measured - float(target_speed))

    result = minimize_scalar(objective, bounds=(0.1, 4.0), method="bounded")
    energy = float(result.x) if result.success else 1.0
    return pitch, energy


def process(audio_file, pitch, energy, overflow=0, amplitude_centering=0, center_offset=0, *, planner="adaptive", subdivision=0, max_speed=400.0, max_acceleration=2400.0, min_interval=0.02, plp=True):
    data = load_audio_data(audio_file, plp=plp)
    actions = plan_actions(
        data,
        planner=planner,
        pitch=pitch,
        energy=energy,
        overflow=overflow,
        amplitude_centering=amplitude_centering,
        center_offset=center_offset,
        subdivision=subdivision,
        max_speed=max_speed,
        max_acceleration=max_acceleration,
        min_interval=min_interval,
    )
    return data, actions


def heatmap(actions, filename):
    """Render a compact speed/intensity heatmap for generated actions."""
    actions = list(actions)
    if len(actions) < 2:
        raise ValueError("at least two actions are required to build a heatmap")
    times = np.asarray([item[0] for item in actions], dtype=np.float64)
    speeds = np.abs(_speed(actions))
    normalized = safe_normalize(speeds)
    fig = Figure(figsize=(10, 1.4), dpi=120)
    ax = fig.add_subplot(111)
    ax.imshow(normalized[np.newaxis, :], aspect="auto", cmap=HEATMAP, extent=(times[0], times[-1], 0, 1), interpolation="nearest")
    ax.set_yticks([])
    ax.set_xlabel("Time (s)")
    fig.tight_layout()
    fig.savefig(str(filename))
    return filename


def write_funscript(path, actions, *, metadata=None):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "inverted": False,
        "range": 90,
        "actions": [{"at": int(round(float(at) * 1000.0)), "pos": int(round(float(pos)))} for at, pos in actions],
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    with output.open("w", encoding="utf8") as handle:
        dump(payload, handle, indent=2)
    return output
