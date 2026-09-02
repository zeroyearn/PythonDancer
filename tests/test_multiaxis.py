import json

import numpy as np

from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig, bundle_paths, export_funscript_bundle, plan_multiaxis


def sample_data():
    beats = np.arange(0.5, 4.5, 0.5, dtype=np.float64)
    n = beats.size
    x = np.linspace(0.0, 1.0, n)
    return {
        "at": 4.5,
        "tempo": 120.0,
        "beats": beats,
        "energy": 0.2 + 0.8 * np.sin(x * np.pi) ** 2,
        "onset": np.asarray([0.2, 0.8, 0.3, 1.0, 0.4, 0.9, 0.3, 0.7]),
        "bass": np.linspace(0.1, 1.0, n),
        "mid": np.linspace(1.0, 0.2, n),
        "high": np.asarray([0.2, 0.3, 0.8, 0.4, 0.9, 0.5, 0.7, 0.3]),
        "pitch": np.asarray([1.9, 2.0, 2.2, 2.1, 2.4, 2.3, 2.5, 2.2]),
        "harmonic": np.linspace(0.3, 0.9, n),
        "percussive": np.asarray([0.3, 1.0, 0.4, 0.9, 0.5, 0.8, 0.6, 1.0]),
    }


def _sample(actions, grid):
    times = np.asarray([at for at, _ in actions], dtype=float)
    values = np.asarray([pos for _, pos in actions], dtype=float)
    return np.interp(grid, times, values, left=values[0], right=values[-1])


def test_plan_multiaxis_has_six_distinct_bounded_axes():
    plan = plan_multiaxis(
        sample_data(),
        MultiAxisConfig(
            motion=MotionConfig(energy_multiplier=1.2, pitch_range=80.0, subdivision=2, max_speed=400.0, max_acceleration=2400.0),
            preset="balanced",
        ),
    )
    assert tuple(plan) == AXIS_ORDER
    assert all(plan[axis] for axis in AXIS_ORDER)
    for axis in AXIS_ORDER:
        times = [at for at, _ in plan[axis]]
        positions = np.asarray([pos for _, pos in plan[axis]])
        assert times == sorted(times)
        assert np.all(np.isfinite(positions))
        assert np.all((positions >= 0.0) & (positions <= 100.0))
    duration = max(plan[axis][-1][0] for axis in AXIS_ORDER if plan[axis])
    grid = np.linspace(0.0, duration, 64)
    l1 = _sample(plan["L1"], grid)
    l2 = _sample(plan["L2"], grid)
    r0 = _sample(plan["R0"], grid)
    assert not np.allclose(l1, l2)
    assert not np.allclose(l1, r0)


def test_zero_axis_strength_centers_secondary_axes():
    plan = plan_multiaxis(sample_data(), MultiAxisConfig(motion=MotionConfig(subdivision=1), strength=0.0))
    for axis in AXIS_ORDER[1:]:
        assert all(abs(pos - 50.0) < 1e-9 for _, pos in plan[axis])


def test_standard_bundle_paths_and_export(tmp_path):
    paths = bundle_paths(tmp_path / "scene.funscript")
    assert paths["L0"].name == "scene.funscript"
    assert paths["L1"].name == "scene.surge.funscript"
    assert paths["L2"].name == "scene.sway.funscript"
    assert paths["R0"].name == "scene.twist.funscript"
    assert paths["R1"].name == "scene.roll.funscript"
    assert paths["R2"].name == "scene.pitch.funscript"

    plan = plan_multiaxis(sample_data(), MultiAxisConfig(motion=MotionConfig(subdivision=1)))
    metadata = {"choreography_sections": "intro:0-8", "notes": "mode=choreography"}
    written = export_funscript_bundle(tmp_path / "scene.funscript", plan, metadata=metadata)

    for axis in AXIS_ORDER:
        assert written[axis].exists()
        payload = json.loads(written[axis].read_text(encoding="utf8"))
        assert payload["metadata"]["axis"] == axis
        assert payload["metadata"]["choreography_sections"] == "intro:0-8"
        assert payload["actions"]

    manifest = json.loads(written["manifest"].read_text(encoding="utf8"))
    assert set(manifest["axes"]) == set(AXIS_ORDER)
    assert manifest["version"] == "1.5"
    assert manifest["metadata"]["choreography_sections"] == "intro:0-8"
