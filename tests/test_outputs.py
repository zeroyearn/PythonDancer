from dancer.outputs import DEFAULT_INTIFACE_ADDRESS, intiface_frames


def test_intiface_frames_map_l0_motion_and_r0_rotation():
    plan = {
        "L0": [(0, 0), (1, 100), (2, 50)],
        "L1": [], "L2": [],
        "R0": [(0, 50), (1, 100), (2, 50)],
        "R1": [], "R2": [],
    }
    frames = intiface_frames(plan)
    assert DEFAULT_INTIFACE_ADDRESS.endswith(":12345")
    assert len(frames) == 3
    assert frames[0][2] == 0.0
    assert frames[1][2] == 1.0
    assert frames[1][4] == 1.0
    assert all(0 <= frame[3] <= 1 for frame in frames)
