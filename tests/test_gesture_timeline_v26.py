from dancer.workspace import GestureBlock, WorkspaceState, apply_gesture_blocks


def base_plan():
    times = [0., .25, .5, .75, 1.]
    return {axis: [(at, 50.) for at in times] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}


def test_axis_mix_can_target_one_axis():
    block = GestureBlock(0., 1., "sway", axis_mix={"L2": 1., "R1": 0., "L0": 0., "L1": 0., "R0": 0., "R2": 0.})
    result = apply_gesture_blocks(base_plan(), [block])
    assert any(abs(pos - 50.) > 1e-6 for _, pos in result["L2"])
    assert all(abs(pos - 50.) < 1e-9 for _, pos in result["R1"])


def test_gesture_phase_cycles_direction_and_blends_serialize():
    workspace = WorkspaceState(duration=4.)
    block = workspace.add_gesture(
        1., 3., "spiral", 1.2,
        axis_mix={"R0": 1.4}, phase_offset=.25, cycles=2., direction=-1, blend_in=.2, blend_out=.3,
    )
    payload = workspace.to_dict()["gestures"][0]
    assert payload["phase_offset"] == .25
    assert payload["cycles"] == 2.
    assert payload["direction"] == -1
    assert payload["axis_mix"]["R0"] == 1.4
    assert block.blend_out == .3
