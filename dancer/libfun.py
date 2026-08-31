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

VERSION = "2.0.0"
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
                "ffmpeg", "-v", "error", "-i", str(audio_file),
                "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", "48000", "pipe:1",
            ])
            y = np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False)
            sr = 48000
        except Exception as exc:
            raise ValueError(f"Unable to decode audio from {audio_file}") from exc
        if y.size == 0:
            raise ValueError(f"Input contains no audio stream: {audio_file}")

    return extract_audio_features(
        y,
        int(sr),
        hop_length=hop_length,
        frame_length=frame_length,
        plp=plp,
    )


def normalize(data):
    return safe_normalize(data)


def default_peak(pos, at, last_pos, last_at):
    return [(at, min(max(0.0, float(pos)), 100.0))]


def int_at(pos, at, last_pos, last_at, limit):
    before_ratio = abs(last_pos - limit)
    after_ratio = abs(pos - limit)
    denominator = after_ratio + before_ratio
    if denominator <= 1e-9:
        return float(at)
    return (before_ratio * at + after_ratio * last_at) / denominator


def create_peak_bounce(pos, at, last_pos, last_at):
    actions = []
    action = lambda p, t: actions.append(default_peak(p, t, 0, 0)[0])

    if last_pos < 0:
        action(0, int_at(pos, at, last_pos, last_at, 0))
    elif last_pos > 100:
        action(100, int_at(pos, at, last_pos, last_at, 100))

    if pos > 100:
        action(100, int_at(pos, at, last_pos, last_at, 100))
        action(200 - pos, at)
    elif pos < 0:
        action(0, int_at(pos, at, last_pos, last_at, 0))
        action(-pos, at)
    else:
        action(pos, at)
    return actions


def create_peak_fold(pos, at, last_pos, last_at):
    actions = []
    action = lambda p, t: actions.append(default_peak(p, t, 0, 0)[0])
    int_att = (last_at + at) / 2
    travel = abs(last_pos - pos) / 2
    if last_pos < 0:
        action(last_pos + travel, int_att)
    elif last_pos > 100:
        action(last_pos - travel, int_att)

    if pos < 0:
        action(last_pos - travel, int_att)
        action(last_pos, at)
    elif pos > 100:
        action(last_pos + travel, int_att)
        action(last_pos, at)
    else:
        action(pos, at)
    return actions


peaks = [default_peak, create_peak_bounce, create_peak_fold]


def create_actions_barrier(data, start_time=0, overflow=0):
    last_at = float(start_time)
    last_pos = 50.0
    actions = []
    for unoffset_pos, at, offset in zip(data["energy_to_pos"], data["beats"], data["offsets"]):
        at = float(at)
        intermediate_at = (at + last_at) / 2
        pos = float(unoffset_pos + offset)
        actions += peaks[int(overflow)](pos, intermediate_at, last_pos, last_at)
        last_at = intermediate_at
        last_pos = pos

        pos = float((unoffset_pos * -1) + offset)
        actions += peaks[int(overflow)](pos, at, last_pos, last_at)
        last_at = at
        last_pos = pos
    return actions


def _legacy_create_actions(data, energy_multiplier=1, pitch_range=100, overflow=0, amplitude_centering=0, center_offset=0):
    processed_data = data.copy()
    normalized_pitch = safe_normalize(processed_data.get("pitch", []))
    normalized_energy = safe_normalize(processed_data.get("energy", []))
    length = min(len(normalized_energy), len(np.asarray(processed_data.get("beats", []))))
    if length == 0:
        return []

    pitch_bias = (100 - pitch_range) / 2
    processed_data["beats"] = np.asarray(processed_data["beats"])[:length]
    processed_data["offsets"] = (
        normalized_pitch[:length] * pitch_range
        + pitch_bias
        + amplitude_centering * normalized_energy[:length]
        + center_offset
    )
    processed_data["energy_to_pos"] = normalized_energy[:length] * energy_multiplier * 50
    return create_actions_barrier(processed_data, overflow=overflow)


def create_actions(
    data,
    energy_multiplier=1,
    pitch_range=100,
    overflow=0,
    amplitude_centering=0,
    center_offset=0,
    *,
    planner="adaptive",
    subdivision=0,
    max_speed=400,
    max_acceleration=2400,
    min_interval=0.02,
):
    if planner == "legacy":
        return _legacy_create_actions(
            data,
            energy_multiplier=energy_multiplier,
            pitch_range=pitch_range,
            overflow=overflow,
            amplitude_centering=amplitude_centering,
            center_offset=center_offset,
        )
    if planner != "adaptive":
        raise ValueError("planner must be 'adaptive' or 'legacy'")

    config = MotionConfig(
        energy_multiplier=float(energy_multiplier),
        pitch_range=float(pitch_range),
        overflow=int(overflow),
        amplitude_centering=float(amplitude_centering),
        center_offset=float(center_offset),
        subdivision=int(subdivision),
        max_speed=float(max_speed),
        max_acceleration=float(max_acceleration),
        min_interval=float(min_interval),
    )
    return plan_motion(data, config)


def _speed(A, B, smax=400.0):
    dt = float(B[0]) - float(A[0])
    if dt <= 1e-9:
        return 0.0
    value = abs(float(B[1]) - float(A[1])) / dt
    return value / smax if smax > 0 else value


def speed(A, B, **kwargs):
    return max(min(_speed(A, B, **kwargs), 1.0), 0.0)


def _average_position(actions):
    if not actions:
        return 50.0
    return float(np.mean([position for _, position in actions]))


def _raw_speeds(actions):
    if len(actions) < 2:
        return np.asarray([], dtype=np.float64)
    return np.asarray([
        _speed(actions[i], actions[i + 1], smax=1.0)
        for i in range(len(actions) - 1)
    ], dtype=np.float64)


def autoval(data, tpi=50, target_speed=250, v2above=0.65, opt=1, *, planner="adaptive"):
    if len(np.asarray(data.get("beats", []))) == 0:
        return 100.0, 1.0
    target_position = float(np.clip(tpi, 0, 100))

    def position_error(pitch_range):
        actions = create_actions(
            data,
            energy_multiplier=0.0,
            pitch_range=pitch_range,
            max_speed=0,
            max_acceleration=0,
            planner=planner,
        )
        return abs(_average_position(actions) - target_position)

    pitch_result = minimize_scalar(position_error, bounds=(-200.0, 200.0), method="bounded")
    pitch_range = float(pitch_result.x) if pitch_result.success else 100.0

    def energy_error(energy):
        actions = create_actions(
            data,
            energy_multiplier=energy,
            pitch_range=pitch_range,
            max_speed=0,
            max_acceleration=0,
            planner=planner,
        )
        speeds = _raw_speeds(actions)
        if speeds.size == 0:
            return float(target_speed)
        if opt == 0:
            return abs(float(np.mean(speeds)) - target_speed)
        if opt == 1:
            percentage = float(np.mean(speeds > target_speed))
            return abs(percentage - float(np.clip(v2above, 0.0, 1.0)))
        if opt == 2:
            result = np.asarray([abs(actions[i][1] - actions[i + 1][1]) / 100.0 for i in range(len(actions) - 1)])
            return abs(float(np.mean(result)) - float(np.clip(v2above, 0.0, 1.0)))
        raise ValueError("opt must be 0, 1, or 2")

    energy_result = minimize_scalar(energy_error, bounds=(0.0, 10.0), method="bounded")
    energy = float(energy_result.x) if energy_result.success else 1.0
    return pitch_range, energy


def render_heatmap(
    data,
    energy,
    pitch,
    oor,
    amplitude_centering=0,
    center_offset=0,
    w=4096,
    h=128,
    *,
    planner="adaptive",
    subdivision=0,
    max_speed=400,
    max_acceleration=2400,
    min_interval=0.02,
):
    result = create_actions(
        data,
        energy_multiplier=energy,
        pitch_range=pitch,
        overflow=oor,
        amplitude_centering=amplitude_centering,
        center_offset=center_offset,
        planner=planner,
        subdivision=subdivision,
        max_speed=max_speed,
        max_acceleration=max_acceleration,
        min_interval=min_interval,
    )
    speeds = np.asarray([speed(result[i], result[i + 1]) for i in range(max(0, len(result) - 1))])
    if speeds.size == 0:
        speeds = np.zeros(1, dtype=np.float64)
    gradient = np.vstack([speeds] * max(1, int(h)))

    dpi = mpl.rcParams["figure.dpi"]
    width = max(1, int(w))
    height = max(1, int(h))
    fig = Figure(figsize=(width / dpi, height / dpi), tight_layout=True)
    plot = fig.add_subplot(111)
    plot.imshow(gradient, cmap=HEATMAP, interpolation="lanczos", aspect="auto")
    plot.axis("off")
    return fig


def dump_csv(f, data):
    for at, pos in data:
        f.write(f"{int(round(float(at) * 1000))},{round(float(pos))}\n")


def dump_funscript(f, data, metadata=None):
    actions = [
        {"at": int(round(float(at) * 1000)), "pos": int(round(float(pos)))}
        for at, pos in data
        if np.isfinite(at) and np.isfinite(pos)
    ]
    actions.sort(key=lambda action: action["at"])
    duration = actions[-1]["at"] if actions else 0
    meta = {
        "creator": "PythonDancer 2",
        "description": "Generated from audio features",
        "duration": duration,
        "license": "None",
        "notes": "",
        "performers": [],
        "script_url": "",
        "tags": [],
        "title": "",
        "type": "basic",
        "video_url": "",
    }
    if metadata:
        meta.update(metadata)
    return dump(
        {
            "actions": actions,
            "inverted": False,
            "metadata": meta,
            "range": 100,
            "version": "1.0",
        },
        f,
        indent=2,
    )
