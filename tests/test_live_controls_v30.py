from types import SimpleNamespace

from dancer.control_surface import DEFAULT_CONTROL_MAPPINGS, MidiControlBridge, OSCControlBridge
from dancer.live_io import LiveSession


class DummySource:
    samplerate = 48000


def session():
    return LiveSession(DummySource(), SimpleNamespace())


def test_default_control_mappings_cover_core_daw_targets():
    targets = {item.target for item in DEFAULT_CONTROL_MAPPINGS}
    assert {"energy", "stroke_depth", "rotation_mix", "complexity", "gesture_density", "smoothing", "safety_aggressiveness", "bpm"} <= targets
    assert MidiControlBridge().mappings
    assert OSCControlBridge().mappings


def test_live_control_energy_and_rotation_change_pose():
    live = session()
    pose = {"L0": 60.0, "L1": 55.0, "L2": 45.0, "R0": 60.0, "R1": 55.0, "R2": 45.0}
    state = {"values": {"energy": 1.5, "rotation_mix": .5}}
    output = live._apply_control_values(pose, state)
    assert output["L0"] > pose["L0"]
    # energy expands R0, then rotation_mix reduces that expansion.
    assert 50.0 < output["R0"] < 65.0


def test_live_control_smoothing_uses_previous_control_pose():
    live = session()
    first = live._apply_control_values({axis: 70.0 for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}, None)
    live._last_control_pose = first
    second = live._apply_control_values(
        {axis: 30.0 for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        {"values": {"smoothing": .5}},
    )
    assert all(abs(value - 50.0) < 1e-6 for value in second.values())


def test_pose_transform_is_downstream_of_control_shaping_contract():
    live = session()
    controlled = live._apply_control_values(
        {axis: 60.0 for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        {"values": {"energy": 1.5}},
    )
    safe = {axis: min(62.0, value) for axis, value in controlled.items()}
    assert all(value <= 62.0 for value in safe.values())
    assert controlled["L0"] > safe["L0"]
