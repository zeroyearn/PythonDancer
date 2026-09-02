import inspect
from types import SimpleNamespace

import pytest

from dancer.automation import AutomationSet, StyleKeyframe, StyleMorphTimeline
from dancer.candidate_composer import CandidateComposition, auto_assign_by_section_scores, compose_candidates
from dancer.daw_transform import apply_daw_transform
from dancer.device_twin import DeviceTwinProfile
from dancer.intent import MotionIntent
from dancer.live import LiveChoreographyConfig, LiveChoreographyEngine, LiveFeatureFrame, PredictiveBeatScheduler
from dancer.live_io import LiveSession


AXES = ("L0", "L1", "L2", "R0", "R1", "R2")


def simple_plan():
    return {
        "L0": [(0.0, 20.0), (1.0, 80.0), (2.0, 20.0)],
        "L1": [(0.0, 50.0), (2.0, 65.0)],
        "L2": [],
        "R0": [(0.0, 45.0), (1.0, 70.0), (2.0, 45.0)],
        "R1": [],
        "R2": [],
    }


def test_default_daw_transform_is_strict_identity():
    plan = simple_plan()
    assert apply_daw_transform(plan, AutomationSet(), StyleMorphTimeline()) == plan


def test_automation_lane_changes_motion_and_quantizes_to_beats():
    plan = simple_plan()
    automation = AutomationSet()
    lane = automation.lanes["energy"]
    lane.set_point(.47, .4)
    lane.set_point(1.51, 1.4)
    lane.quantize([0.0, .5, 1.0, 1.5, 2.0])
    assert [point.time for point in lane.points] == [.5, 1.5]
    transformed = apply_daw_transform(plan, automation, StyleMorphTimeline())
    assert transformed["L0"] != plan["L0"]
    assert transformed["L2"] == []


def test_style_morph_interpolates_intent_and_changes_output():
    smooth = MotionIntent(intensity=.4, aggression=.1, flow=.9, complexity=.3, symmetry=.8, rotation_bias=.4, translation_bias=.5, accent_density=.2)
    aggressive = MotionIntent(intensity=.95, aggression=.95, flow=.2, complexity=.8, symmetry=.3, rotation_bias=.7, translation_bias=.9, accent_density=.95)
    styles = StyleMorphTimeline([
        StyleKeyframe(0.0, "Smooth", smooth, .8),
        StyleKeyframe(2.0, "Aggressive", aggressive, 1.2),
    ])
    intent, strength, name = styles.sample(1.0)
    assert .4 < intent.intensity < .95
    assert .8 < strength < 1.2
    assert name in {"Smooth", "Aggressive"}
    assert apply_daw_transform(simple_plan(), AutomationSet(), styles) != simple_plan()


def test_candidate_composer_uses_raw_plans_and_preserves_locked_axis():
    base = simple_plan()
    candidate_a = SimpleNamespace(name="A", plan=simple_plan())
    candidate_b_plan = simple_plan()
    candidate_b_plan["L0"] = [(0.0, 90.0), (1.0, 10.0), (2.0, 90.0)]
    candidate_b_plan["R0"] = [(0.0, 10.0), (1.0, 90.0), (2.0, 10.0)]
    candidate_b = SimpleNamespace(name="B", plan=candidate_b_plan)
    sections = [SimpleNamespace(start=0.0, end=1.0, label="verse"), SimpleNamespace(start=1.0, end=2.0, label="drop")]
    composition = CandidateComposition({1: "B"}, blend_seconds=.0)
    merged, choices = compose_candidates([candidate_a, candidate_b], sections, composition, base_plan=base, locked_axes=("L0",))
    assert choices == {1: "B"}
    assert merged["L0"] == base["L0"]
    assert merged["R0"] != base["R0"]


def test_candidate_composer_auto_assign_uses_exact_section_scorer():
    candidate_a = SimpleNamespace(name="A", quality=SimpleNamespace(overall=99.0, weak_ranges=()))
    candidate_b = SimpleNamespace(name="B", quality=SimpleNamespace(overall=10.0, weak_ranges=()))
    sections = [
        SimpleNamespace(start=0.0, end=1.0, label="verse"),
        SimpleNamespace(start=1.0, end=2.0, label="drop"),
    ]
    exact = {
        ("A", 0): 94.0,
        ("B", 0): 72.0,
        ("A", 1): 38.0,
        ("B", 1): 91.0,
    }

    composition = auto_assign_by_section_scores(
        [candidate_a, candidate_b],
        sections,
        score_section=lambda candidate, _start, _end, index: exact[(candidate.name, index)],
    )

    # Overall score would choose A for both sections. Exact section scoring must
    # independently choose B for the drop.
    assert composition.assignments == {0: "A", 1: "B"}


def test_auto_improvement_stale_context_includes_daw_state():
    from dancer.workstation_ui_v27_async import MultiAxisWindow as AsyncWindow
    from dancer.workstation_ui_v28 import MultiAxisWindow as DAWWindow

    fingerprint_source = inspect.getsource(AsyncWindow._motion_state_fingerprint)
    daw_context_source = inspect.getsource(DAWWindow._candidate_context)
    assert "self._candidate_context()" in fingerprint_source
    assert "self.automation.to_dict()" in daw_context_source
    assert "self.style_morph.to_dict()" in daw_context_source


def test_device_twin_round_trip_and_safe_pose():
    twin = DeviceTwinProfile(name="Lab SR6")
    restored = DeviceTwinProfile.from_dict(twin.to_dict())
    assert restored.name == "Lab SR6"
    pose, risk, changed = restored.safe_pose({axis: 50.0 for axis in AXES})
    assert all(0.0 <= pose[axis] <= 100.0 for axis in AXES)
    assert risk.reachable is True
    assert isinstance(changed, bool)
    output, diagnostics = restored.output_plan(simple_plan())
    assert set(output) == set(AXES)
    assert "final_projection" in diagnostics


def test_predictive_live_scheduler_and_engine_are_bounded():
    scheduler = PredictiveBeatScheduler(prediction_horizon_ms=420.0, latency_ms=35.0)
    frame = LiveFeatureFrame(10.0, bpm=120.0, beat_phase=.25, beat_confidence=.9, energy=.8, onset=.7, bass=.8, mid=.5, high=.6, vocals=.4)
    scheduler.update(frame)
    target, command = scheduler.command_target(10.0)
    assert target >= 10.0
    assert command <= target

    engine = LiveChoreographyEngine(LiveChoreographyConfig(prediction_horizon_ms=420.0, latency_ms=35.0))
    motion = engine.process(frame)
    assert motion.gesture in {"pulse", "rock", "wave", "spiral", "accent"}
    assert all(0.0 <= value <= 100.0 for value in motion.pose.values())
    assert motion.prediction_ms >= 0.0


def test_live_session_cleans_source_when_sink_open_fails():
    class FakeSource:
        samplerate = 48000
        started = False
        stopped = False
        def start(self):
            self.started = True
        def stop(self):
            self.stopped = True

    class FailingSink:
        def open(self):
            raise RuntimeError("no serial")
        def stop(self):
            pass

    source = FakeSource()
    session = LiveSession(source, LiveChoreographyEngine(), sink=FailingSink())
    with pytest.raises(RuntimeError, match="no serial"):
        session.start()
    assert source.started is True
    assert source.stopped is True


def test_2_8_release_modules_import():
    import dancer.cli_v28  # noqa: F401
    import dancer.workstation_ui_v28  # noqa: F401
    import dancer.workstation_ui_v28_final  # noqa: F401
