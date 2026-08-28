import numpy as np

from dancer.libfun import create_actions
from dancer.motion import MotionConfig, apply_constraints, plan_motion


def sample_data():
    return {
        "beats": np.array([0.5, 1.0, 1.5, 2.0]),
        "tempo": 120.0,
        "energy": np.array([0.2, 0.8, 0.4, 1.0]),
        "pitch": np.array([1.0, 1.2, 1.1, 1.4]),
        "onset": np.array([0.1, 1.0, 0.3, 0.9]),
        "bass": np.array([0.2, 1.0, 0.4, 0.8]),
        "high": np.array([0.1, 0.5, 0.2, 0.7]),
        "harmonic": np.array([0.4, 0.6, 0.5, 0.7]),
        "percussive": np.array([0.1, 1.0, 0.2, 0.9]),
    }


def test_adaptive_motion_is_monotonic_and_in_range():
    actions = plan_motion(sample_data(), MotionConfig(subdivision=2, max_speed=0, max_acceleration=0))
    assert len(actions) == 4 * 4
    times = np.array([a[0] for a in actions])
    positions = np.array([a[1] for a in actions])
    assert np.all(np.diff(times) > 0)
    assert np.all((positions >= 0) & (positions <= 100))


def test_constraints_cap_speed():
    actions = apply_constraints([(0.0, 0), (0.1, 100), (0.2, 0)], max_speed=100, max_acceleration=0, min_interval=0)
    for previous, current in zip(actions, actions[1:]):
        speed = abs(current[1] - previous[1]) / (current[0] - previous[0])
        assert speed <= 100.000001


def test_legacy_planner_still_available():
    actions = create_actions(sample_data(), planner="legacy", energy_multiplier=1, pitch_range=100)
    assert actions
    assert all(0 <= pos <= 100 for _, pos in actions)


def test_constant_features_do_not_create_nan():
    data = {
        "beats": np.array([0.5, 1.0, 1.5]),
        "energy": np.ones(3),
        "pitch": np.ones(3),
    }
    actions = create_actions(data)
    assert actions
    assert np.isfinite(np.asarray(actions)).all()
