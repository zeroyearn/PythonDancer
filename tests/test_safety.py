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


def test_axis_link_generates_target_from_source():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L2"] = [(0, 20), (1, 80), (2, 20)]
    linked = apply_axis_links(plan, [AxisLink("L2", "R1", gain=-.5, only_if_empty=True)])
    assert linked["R1"]
    assert linked["R1"][0][1] > 50
    assert linked["R1"][1][1] < 50


def test_gap_fill_inserts_motion_and_soft_home_wraps_plan():
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L0"] = [(0, 40), (5, 60)]
    filled = fill_motion_gaps(plan, [1, 2, 3, 4], mode="beat", threshold=1.5)
    assert len(filled["L0"]) == 6
    started = add_soft_start(filled, 1.0, duration_ms=500)
    assert started["L0"][0][1] == 50.0
    homed = add_auto_home(started, home_ms=500)
    assert homed["L0"][-1][1] == 50.0
