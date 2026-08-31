import numpy as np

from dancer.safety import (
    AxisLink,
    add_auto_home,
    add_soft_start,
    apply_axis_links,
    apply_smart_limits,
    fill_motion_gaps,
    motion_heatmap,
    risk_heatmap,
)


def sample_plan():
    return {
        "L0": [(0, 50), (1, 95), (2, 5), (3, 50)],
        "L1": [(0, 50), (1, 90), (2, 10), (3, 50)],
        "L2": [(0, 50), (1, 90), (2, 10), (3, 50)],
        "R0": [(0, 50), (1, 95), (2, 5), (3, 50)],
        "R1": [(0, 50), (1, 90), (2, 10), (3, 50)],
        "R2": [(0, 50), (1, 90), (2, 10), (3, 50)],
    }


def test_heatmaps_have_expected_shape_and_range():
    plan = sample_plan()
    heat = motion_heatmap(plan, bins=16)
    assert set(heat) == set(plan)
    assert all(values.shape == (16,) for values in heat.values())
    assert all(np.all((0 <= values) & (values <= 1)) for values in heat.values())
    risk = risk_heatmap(plan, bins=16)
    assert risk.shape == (16,)
    assert np.max(risk) > 0


def test_smart_limits_reduce_cross_axis_extremes():
    plan = sample_plan()
    safe = apply_smart_limits(plan, "safe")
    assert abs(safe["R0"][1][1] - 50) < abs(plan["R0"][1][1] - 50)
    assert abs(safe["R2"][1][1] - 50) < abs(plan["R2"][1][1] - 50)
    assert abs(safe["R1"][1][1] - 50) < abs(plan["R1"][1][1] - 50)


def test_safe_profile_reduces_simultaneous_high_velocity_steps_more_than_open():
    rapid = {
        axis: [(0.0, 50.0), (0.05, 100.0), (0.10, 0.0), (0.15, 50.0)]
        for axis in ("L0", "L1", "L2", "R0", "R1", "R2")
    }
    safe = apply_smart_limits(rapid, "safe")
    open_plan = apply_smart_limits(rapid, "open")
    safe_step = sum(abs(safe[axis][1][1] - 50.0) for axis in rapid)
    open_step = sum(abs(open_plan[axis][1][1] - 50.0) for axis in rapid)
    assert safe_step < open_step


def test_axis_link_generates_target_from_source():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L2"] = [(0, 20), (1, 80), (2, 20)]
    linked = apply_axis_links(plan, [AxisLink("L2", "R1", gain=-.5, only_if_empty=True)])
    assert linked["R1"]
    assert linked["R1"][0][1] > 50
    assert linked["R1"][1][1] < 50


def test_velocity_axis_link_and_delay_are_applied():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L1"] = [(0.0, 20), (0.5, 80), (1.0, 20)]
    linked = apply_axis_links(
        plan,
        [AxisLink("L1", "R2", gain=.6, delay_ms=100, smoothing=.4, mode="velocity", only_if_empty=True)],
    )
    assert linked["R2"]
    assert linked["R2"][0][0] == 0.1
    assert all(0 <= pos <= 100 for _, pos in linked["R2"])


def test_gap_fill_inserts_motion_and_soft_home_wraps_plan():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L0"] = [(0, 40), (5, 60)]
    filled = fill_motion_gaps(plan, [1, 2, 3, 4], mode="beat", threshold=1.5)
    assert len(filled["L0"]) == 6
    started = add_soft_start(filled, 1.0, duration_ms=500)
    assert started["L0"][0][1] == 50.0
    homed = add_auto_home(started, home_ms=500)
    assert homed["L0"][-1][1] == 50.0


def test_soft_start_at_zero_creates_real_ramp_instead_of_duplicate_timestamp():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L0"] = [(0.0, 80), (1.0, 20)]
    started = add_soft_start(plan, 0.0, duration_ms=500)
    assert started["L0"][0] == (0.0, 50.0)
    assert started["L0"][1] == (0.5, 80.0)
    assert started["L0"][-1][0] == 1.5
