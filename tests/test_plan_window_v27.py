import pytest

from dancer.multiaxis import AXIS_ORDER
from dancer.plan_window import sample_actions, slice_plan


def test_slice_plan_inserts_interpolated_window_boundaries():
    plan = {axis: [] for axis in AXIS_ORDER}
    plan["L0"] = [(0.0, 0.0), (10.0, 100.0)]
    sliced = slice_plan(plan, 4.0, 6.0, rebase=True)
    assert sliced["L0"] == pytest.approx([(0.0, 40.0), (2.0, 60.0)])
    assert sliced["L1"] == []


def test_slice_plan_keeps_interior_keyframes_and_original_interpolation():
    actions = [(0.0, 10.0), (5.0, 90.0), (10.0, 30.0)]
    plan = {axis: (actions if axis == "R0" else []) for axis in AXIS_ORDER}
    sliced = slice_plan(plan, 2.0, 8.0, rebase=False)
    assert [at for at, _ in sliced["R0"]] == [2.0, 5.0, 8.0]
    assert sliced["R0"][0][1] == pytest.approx(sample_actions(actions, 2.0))
    assert sliced["R0"][-1][1] == pytest.approx(sample_actions(actions, 8.0))


def test_slice_plan_supports_reversed_bounds_without_losing_motion():
    plan = {axis: [] for axis in AXIS_ORDER}
    plan["L1"] = [(0.0, 20.0), (10.0, 80.0)]
    sliced = slice_plan(plan, 8.0, 2.0, rebase=True)
    assert sliced["L1"][0] == pytest.approx((0.0, 32.0))
    assert sliced["L1"][-1] == pytest.approx((6.0, 68.0))
