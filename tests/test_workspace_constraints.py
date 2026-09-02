from dancer.mechanical_safety import MechanicalProjectionConfig, trajectory_mechanical_risk
from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig
from dancer.optimizer import OptimizerConfig
from dancer.workspace_constraints import constrain_workspace_plan


def test_manual_edits_are_reconstrained_before_output():
    plan = {axis: [(0.0, 50.0), (0.1, 100.0), (0.2, 0.0)] for axis in AXIS_ORDER}
    config = MultiAxisConfig(
        motion=MotionConfig(max_speed=100.0, max_acceleration=0.0, min_interval=0.0),
        optimizer=OptimizerConfig(enabled=False),
        mechanical=MechanicalProjectionConfig(enabled=False),
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


def test_manual_edits_are_reprojected_into_mechanical_safe_set():
    plan = {
        "L0": [(0.0, 50.0), (1.0, 100.0), (2.0, 50.0)],
        "L1": [(0.0, 50.0), (1.0, 100.0), (2.0, 50.0)],
        "L2": [(0.0, 50.0), (1.0, 0.0), (2.0, 50.0)],
        "R0": [(0.0, 50.0), (1.0, 100.0), (2.0, 50.0)],
        "R1": [(0.0, 50.0), (1.0, 100.0), (2.0, 50.0)],
        "R2": [(0.0, 50.0), (1.0, 0.0), (2.0, 50.0)],
    }
    mechanical = MechanicalProjectionConfig(
        enabled=True,
        max_risk=0.45,
        servo_limit_deg=50.0,
    )
    config = MultiAxisConfig(
        motion=MotionConfig(min_interval=0.0),
        optimizer=OptimizerConfig(enabled=False),
        mechanical=mechanical,
    )

    safe = constrain_workspace_plan(plan, config)
    diagnostics = trajectory_mechanical_risk(safe, config.geometry, mechanical)

    assert diagnostics["unsafe_ratio"] == 0.0
    assert diagnostics["min_servo_margin_deg"] >= 0.0
    assert safe != plan
