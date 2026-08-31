import json

import numpy as np

from dancer.motion import MotionConfig
from dancer.multiaxis import MultiAxisConfig, plan_multiaxis
from dancer.style import ChoreographyProfile, learn_profile_from_bundle, load_profile, save_profile


def _write_script(path, values):
    payload = {"actions": [{"at": int(i * 100), "pos": float(value)} for i, value in enumerate(values)]}
    path.write_text(json.dumps(payload), encoding="utf8")


def _song_data():
    beats = np.arange(0.5, 16.5, 0.5)
    n = beats.size
    x = np.linspace(0.0, 1.0, n)
    return {
        "at": float(beats[-1]),
        "tempo": 120.0,
        "beats": beats,
        "energy": 0.3 + 0.7 * np.sin(x * np.pi) ** 2,
        "onset": np.clip(0.2 + 0.8 * (np.arange(n) % 4 == 0), 0, 1),
        "bass": np.clip(0.2 + 0.8 * x, 0, 1),
        "mid": np.clip(0.8 - 0.5 * x, 0, 1),
        "high": np.clip(0.2 + 0.6 * np.sin(np.arange(n) * 0.8) ** 2, 0, 1),
        "pitch": np.clip(0.5 + 0.35 * np.sin(np.arange(n) * 0.25), 0, 1),
        "harmonic": np.clip(0.45 + 0.35 * np.sin(np.arange(n) * 0.17), 0, 1),
        "percussive": np.clip(0.25 + 0.7 * (np.arange(n) % 2 == 0), 0, 1),
    }


def test_profile_json_round_trip(tmp_path):
    profile = ChoreographyProfile(
        name="custom",
        axis_scale={"R0": 1.6},
        gesture_gain={"spiral": 1.4},
        coupling_gain={"sway_roll": 1.2},
        reactive_mix=0.25,
        smoothing=0.3,
        stem_influence=1.5,
    )
    path = save_profile(tmp_path / "profile.json", profile)
    loaded = load_profile(path)
    assert loaded.name == "custom"
    assert loaded.axis_multiplier("R0") == 1.6
    assert loaded.gesture_multiplier("spiral") == 1.4
    assert loaded.coupling_multiplier("sway_roll") == 1.2
    assert loaded.stem_influence == 1.5


def test_reference_bundle_learning_extracts_axis_and_coupling_style(tmp_path):
    base = tmp_path / "reference"
    t = np.linspace(0, 4 * np.pi, 100)
    l0 = 50 + 35 * np.sin(t)
    l1 = 50 + 12 * np.sin(t * 0.5)
    l2 = 50 + 28 * np.sin(t * 0.25)
    r0 = 50 + 38 * np.sin(t + 0.4)
    r1 = 50 - 24 * np.sin(t * 0.25)
    r2 = 50 - 14 * np.sin(t * 0.5)
    suffixes = {"": l0, ".surge": l1, ".sway": l2, ".twist": r0, ".roll": r1, ".pitch": r2}
    for suffix, values in suffixes.items():
        _write_script(tmp_path / f"reference{suffix}.funscript", values)

    learned = learn_profile_from_bundle(base)
    assert learned.axis_multiplier("R0") > learned.axis_multiplier("L1")
    assert learned.coupling_multiplier("sway_roll") > 1.0
    assert learned.coupling_multiplier("surge_pitch") > 1.0
    assert learned.metadata["present_axes"] == ["L0", "L1", "L2", "R0", "R1", "R2"]


def test_profile_materially_changes_generated_motion():
    data = _song_data()
    motion = MotionConfig(subdivision=1, max_speed=0, max_acceleration=0, min_interval=0)
    normal = plan_multiaxis(data, MultiAxisConfig(motion=motion, preset="balanced"))
    profile = ChoreographyProfile(axis_scale={"R0": 0.25, "L2": 1.8}, gesture_gain={"sway": 1.8}, coupling_gain={"sway_roll": 1.6})
    styled = plan_multiaxis(data, MultiAxisConfig(motion=motion, preset="balanced", profile=profile))

    normal_r0 = np.asarray([p for _, p in normal["R0"]])
    styled_r0 = np.asarray([p for _, p in styled["R0"]])
    normal_l2 = np.asarray([p for _, p in normal["L2"]])
    styled_l2 = np.asarray([p for _, p in styled["L2"]])
    assert np.std(styled_r0 - 50) < np.std(normal_r0 - 50)
    assert np.std(styled_l2 - 50) > np.std(normal_l2 - 50)
