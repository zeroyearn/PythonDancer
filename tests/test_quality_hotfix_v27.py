import numpy as np
import pytest

from dancer.candidates import generate_candidates
from dancer.editing import CurveSettings
from dancer.improvement import ImprovementConfig, auto_improve
from dancer.mechanical_safety import MechanicalProjectionConfig
from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig
from dancer.quality import _slice_sections, score_plan
from dancer.safety import SafetySettings
from dancer.workspace import WorkspaceState
from dancer.workstation_ui_v27_hotfix import _effective_output_snapshot


def _data():
    beats = np.arange(0.0, 8.5, 0.5, dtype=np.float64)
    n = beats.size
    return {
        "at": 8.5,
        "tempo": 120.0,
        "beats": beats,
        "energy": np.linspace(.2, .9, n),
        "onset": np.resize(np.asarray([.9, .2, .8, .3]), n),
        "bass": np.linspace(.1, 1.0, n),
        "mid": np.linspace(.8, .2, n),
        "high": np.resize(np.asarray([.2, .8, .3, .9]), n),
        "pitch": np.linspace(1.8, 2.4, n),
        "harmonic": np.linspace(.25, .95, n),
        "percussive": np.resize(np.asarray([.9, .25, .8, .3]), n),
    }


def _config():
    return MultiAxisConfig(
        motion=MotionConfig(
            subdivision=1,
            max_speed=400.0,
            max_acceleration=2400.0,
            min_interval=0.0,
        ),
        mechanical=MechanicalProjectionConfig(enabled=False),
    )


def test_candidate_ranking_skips_weak_window_recursion():
    results = generate_candidates(_data(), _config(), count=2)
    assert len(results) == 2
    assert all(candidate.quality.weak_ranges == () for candidate in results)


def test_candidate_score_transform_changes_score_not_stored_raw_plan():
    baseline = generate_candidates(_data(), _config(), count=1)[0]

    def neutral_output(_plan, _candidate_config):
        return {
            axis: [(0.0, 50.0), (8.0, 50.0)]
            for axis in AXIS_ORDER
        }

    transformed = generate_candidates(
        _data(),
        _config(),
        count=1,
        score_transform=neutral_output,
    )[0]

    # CandidateResult.plan stays the non-destructive raw base plan even when
    # ranking is performed against a shaped/effective output.
    assert transformed.plan == baseline.plan
    assert transformed.quality.metrics["axis_diversity"] == pytest.approx(0.0)
    assert transformed.quality.overall != pytest.approx(baseline.quality.overall)


def test_auto_improvement_scores_effective_output_but_returns_raw_plan():
    raw = {
        axis: [
            (0.0, 15.0 + index * 4.0),
            (4.0, 88.0 - index * 3.0),
            (8.0, 25.0 + index * 5.0),
        ]
        for index, axis in enumerate(AXIS_ORDER)
    }

    def neutral_output(_plan, _generation_config):
        return {
            axis: [(0.0, 50.0), (8.0, 50.0)]
            for axis in AXIS_ORDER
        }

    result = auto_improve(
        _data(),
        raw,
        _config(),
        config=ImprovementConfig(max_iterations=1, target_score=0.0, candidates=2),
        score_transform=neutral_output,
    )
    raw_report = score_plan(raw, _data(), compute_windows=False)

    # Optimization must keep the editable raw plan, while its reported quality
    # describes the effective/shaped output that the user would actually use.
    assert result.plan == raw
    assert result.quality.metrics["axis_diversity"] == pytest.approx(0.0)
    assert raw_report.metrics["axis_diversity"] > 0.0


def test_effective_output_snapshot_respects_locked_base_and_mute():
    raw = {axis: [] for axis in AXIS_ORDER}
    raw["L0"] = [(0.0, 90.0), (1.0, 10.0)]
    raw["R0"] = [(0.0, 20.0), (1.0, 80.0)]

    base = {axis: [] for axis in AXIS_ORDER}
    base["L0"] = [(0.0, 20.0), (1.0, 80.0)]
    base["R0"] = [(0.0, 40.0), (1.0, 60.0)]

    workspace = WorkspaceState(duration=1.0)
    workspace.axes["L0"].locked = True
    workspace.axes["R0"].muted = True
    curves = {axis: CurveSettings() for axis in AXIS_ORDER}
    safety = SafetySettings(smart_limits=False, gap_fill="none")

    effective = _effective_output_snapshot(
        raw,
        _config(),
        base_plan=base,
        workspace=workspace,
        curve_settings=curves,
        safety_settings=safety,
        data={"beats": np.asarray([0.0, 0.5, 1.0])},
    )

    assert effective["R0"] == []
    assert effective["L0"][0] == pytest.approx((0.0, 20.0))
    assert effective["L0"][-1] == pytest.approx((1.0, 80.0))


def test_weak_window_sections_are_clipped_and_rebased():
    sections = [
        {"start": 0.0, "end": 3.0, "label": "verse"},
        {"start": 3.0, "end": 7.0, "label": "chorus"},
        {"start": 7.0, "end": 10.0, "label": "outro"},
    ]
    local = _slice_sections(sections, 2.0, 8.0)
    assert local == [
        {"start": 0.0, "end": 1.0, "label": "verse"},
        {"start": 1.0, "end": 5.0, "label": "chorus"},
        {"start": 5.0, "end": 6.0, "label": "outro"},
    ]


def test_final_release_layers_import():
    import dancer.workstation_ui_v27_hotfix  # noqa: F401
    import dancer.workstation_ui_v27_async  # noqa: F401
