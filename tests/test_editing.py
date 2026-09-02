import numpy as np

from dancer.editing import (
    CurveSettings,
    delete_keyframes,
    flatten_range,
    insert_keyframe,
    move_keyframe,
    nearest_beat,
    quantize_actions,
    resample_curve,
    smooth_range,
    transform_range,
)


def test_keyframe_insert_move_delete_and_transform():
    actions = [(0.0, 20.0), (1.0, 80.0)]
    actions = insert_keyframe(actions, .5, 50)
    assert actions == [(0.0, 20.0), (.5, 50.0), (1.0, 80.0)]
    actions = move_keyframe(actions, 1, .6, 60)
    assert actions[1] == (.6, 60.0)
    actions = transform_range(actions, 0.5, 1.0, scale=.5, offset=5)
    assert actions[1][1] == 60.0
    assert actions[2][1] == 70.0
    actions = delete_keyframes(actions, [1])
    assert len(actions) == 2


def test_quantize_and_nearest_modes():
    beats = [0.0, .5, 1.0, 1.5]
    assert nearest_beat(.74, beats) == .5
    assert nearest_beat(.74, beats, "ceil") == 1.0
    assert nearest_beat(.74, beats, "floor") == .5
    actions = quantize_actions([(.48, 10), (1.08, 90)], beats)
    assert [at for at, _ in actions] == [.5, 1.0]


def test_interpolation_methods_are_bounded_and_distinct():
    actions = [(0.0, 10), (1.0, 90), (2.0, 20), (3.0, 70)]
    sample = np.linspace(0, 3, 25)
    outputs = {}
    for method in ("linear", "smoothstep", "pchip", "makima"):
        values = resample_curve(actions, sample, method)
        assert len(values) == len(sample)
        assert all(0 <= pos <= 100 for _, pos in values)
        outputs[method] = np.asarray([pos for _, pos in values])
    assert not np.allclose(outputs["linear"], outputs["smoothstep"])
    assert not np.allclose(outputs["linear"], outputs["pchip"])


def test_flatten_and_smooth_range():
    actions = [(0, 10), (1, 80), (2, 20), (3, 90), (4, 30)]
    flat = flatten_range(actions, 1, 3, 50)
    assert [pos for at, pos in flat if 1 <= at <= 3] == [50.0, 50.0, 50.0]
    smooth = smooth_range(actions, 1, 3, window=3)
    assert smooth[0] == (0.0, 10.0)
    assert smooth[-1] == (4.0, 30.0)
    CurveSettings(interpolation="makima", snap_to_beat=True)
