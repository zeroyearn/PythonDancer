from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig
from dancer.workspace_constraints import constrain_workspace_plan


def test_manual_edits_are_reconstrained_before_output():
    plan = {axis: [(0.0, 50.0), (0.1, 100.0), (0.2, 0.0)] for axis in AXIS_ORDER}
    config = MultiAxisConfig(
        motion=MotionConfig(max_speed=100.0, max_acceleration=0.0, min_interval=0.0)
    )
    safe = constrain_workspace_plan(plan, config)

    # L0 is capped at 100 normalized units/sec -> max 10 points per 100 ms.
    assert safe["L0"][1][1] == 60.0
    assert safe["L0"][2][1] == 50.0

    # Secondary axes use their own conservative limits rather than L0's limit.
    assert safe["L1"][1][1] == 68.0
    assert safe["R0"][1][1] == 80.0


def test_muted_axes_remain_empty_after_constraint_pass():
    plan = {axis: [(0.0, 50.0), (1.0, 55.0)] for axis in AXIS_ORDER}
    plan["R2"] = []
    safe = constrain_workspace_plan(plan, MultiAxisConfig())
    assert safe["R2"] == []
    assert safe["L0"]
