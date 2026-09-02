import numpy as np

from dancer.calibration import AxisCalibration, DeviceCalibrationProfile, apply_calibration, calibration_test_plan
from dancer.independent_planner import IndependentAxisConfig, axis_event_times
from dancer.intent import infer_motion_intent
from dancer.latency import DeviceTimingProfile, compensate_plan_latency
from dancer.multiaxis import MultiAxisConfig, plan_multiaxis
from dancer.optimizer import OptimizerConfig, optimize_multiaxis, optimizer_diagnostics
from dancer.reference_library import blend_profiles, cluster_profiles
from dancer.style import ChoreographyProfile


def feature_data(count=24):
    beats = np.arange(count, dtype=float) * .5
    phase = np.linspace(0., 2. * np.pi, count)
    return {
        "beats": beats,
        "energy": np.clip(.5 + .4 * np.sin(phase), 0., 1.),
        "onset": np.clip(.5 + .5 * np.sin(phase * 2.), 0., 1.),
        "bass": np.clip(.5 + .45 * np.cos(phase), 0., 1.),
        "mid": np.clip(.5 + .2 * np.sin(phase * .5), 0., 1.),
        "high": np.clip(.5 + .45 * np.sin(phase * 3.), 0., 1.),
        "pitch": np.linspace(.2, .8, count),
        "harmonic": np.clip(.6 + .3 * np.cos(phase * .5), 0., 1.),
        "percussive": np.clip(.5 + .5 * np.sin(phase * 2.), 0., 1.),
        "stem_drums_energy": np.clip(.5 + .5 * np.sin(phase * 2.), 0., 1.),
        "stem_drums_onset": np.clip(.5 + .5 * np.sin(phase * 2.), 0., 1.),
        "stem_drums_snare": np.asarray([(i % 4) == 2 for i in range(count)], dtype=float),
        "stem_drums_hihat": np.asarray([(i % 2) == 1 for i in range(count)], dtype=float),
        "stem_bass_energy": np.clip(.5 + .45 * np.cos(phase), 0., 1.),
        "stem_vocals_energy": np.clip(.5 + .35 * np.cos(phase * .5), 0., 1.),
        "stem_vocals_pitch": np.linspace(.2, .8, count),
        "stem_vocals_pitch_motion": np.r_[0., np.abs(np.diff(np.linspace(.2, .8, count)))],
        "stem_other_energy": np.full(count, .4),
    }


def test_motion_intent_is_bounded_and_sampleable():
    data = feature_data()
    envelope = infer_motion_intent(data)
    assert set(envelope.global_intent.to_dict()) == {
        "intensity", "aggression", "flow", "complexity", "symmetry", "rotation_bias", "translation_bias", "accent_density"
    }
    assert all(0. <= value <= 1. for value in envelope.global_intent.to_dict().values())
    sampled = envelope.sample([0., 1., 2.])
    assert sampled["intensity"].shape == (3,)


def test_axis_event_times_are_independent():
    data = feature_data()
    cfg = IndependentAxisConfig(density=1.0, accent_threshold=.5)
    l2 = axis_event_times(data, "L2", 10., config=cfg)
    r0 = axis_event_times(data, "R0", 10., config=cfg)
    assert len(l2) != len(r0) or not np.array_equal(l2, r0)
    assert l2[0] == 0.
    assert r0[-1] == 10.


def test_multiaxis_default_uses_distinct_secondary_timelines():
    data = feature_data(32)
    plan = plan_multiaxis(data, MultiAxisConfig())
    assert all(plan[axis] for axis in ("L0", "L1", "L2", "R0", "R1", "R2"))
    timelines = {axis: tuple(round(at, 4) for at, _ in plan[axis]) for axis in plan}
    assert len({timelines[axis] for axis in ("L1", "L2", "R0", "R1", "R2")}) > 1


def test_optimizer_reduces_pose_load_and_bounds_positions():
    plan = {axis: [(0., 50.), (1., 100.), (2., 0.)] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    before = optimizer_diagnostics(plan)
    optimized = optimize_multiaxis(plan, OptimizerConfig(pose_budget=1.2, velocity_budget=1.2, iterations=2))
    after = optimizer_diagnostics(optimized)
    assert after["peak_pose_load"] <= before["peak_pose_load"] + 1e-9
    assert all(0. <= pos <= 100. for actions in optimized.values() for _, pos in actions)


def test_profile_blending_and_clustering_are_deterministic():
    a = ChoreographyProfile(name="a", axis_scale={"R0": .6}, gesture_gain={"wave": 1.5})
    b = ChoreographyProfile(name="b", axis_scale={"R0": 1.8}, gesture_gain={"pulse": 1.6})
    blended = blend_profiles([a, b], [1., 3.], name="mix")
    assert blended.name == "mix"
    assert abs(blended.axis_multiplier("R0") - 1.5) < 1e-9
    clusters = cluster_profiles([a, b], clusters=2)
    assert len(clusters) == 2
    assert sorted(len(cluster.member_indices) for cluster in clusters) == [1, 1]


def test_latency_compensation_shifts_but_never_goes_negative():
    plan = {"L0": [(0.02, 40.), (.2, 60.)]}
    shifted = compensate_plan_latency(plan, DeviceTimingProfile(latency_ms=50.))
    assert shifted["L0"][0][0] == 0.
    assert abs(shifted["L0"][-1][0] - .15) < 1e-9


def test_calibration_profile_maps_and_test_sequence_is_conservative():
    profile = DeviceCalibrationProfile(axes={"L0": AxisCalibration(minimum=10., maximum=90., neutral=50., inverted=True)})
    mapped = apply_calibration({"L0": [(0., 0.), (1., 100.)]}, profile)
    assert mapped["L0"] == [(0.0, 90.0), (1.0, 10.0)]
    sequence = calibration_test_plan(profile, excursion=5.)
    assert all(sequence[axis] for axis in sequence)
    assert all(profile.axes[axis].minimum <= pos <= profile.axes[axis].maximum for axis in sequence for _, pos in sequence[axis])
