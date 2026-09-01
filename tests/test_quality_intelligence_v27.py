import numpy as np

from dancer.candidates import generate_candidates
from dancer.cli_v27 import add_cli_arguments
from dancer.i18n import LANG_ZH, translate_text
from dancer.i18n_v27 import install_v27_translations
from dancer.improvement import ImprovementConfig, auto_improve
from dancer.intent import INTENT_FIELDS, IntentEnvelope, MotionIntent
from dancer.mechanical_safety import MechanicalProjectionConfig, mechanical_risk_at_pose, project_plan_to_safe, project_pose_to_safe
from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig, plan_multiaxis
from dancer.quality import METRICS, score_plan
from dancer.section_intent import SectionIntentOverride, apply_section_intent_overrides
from dancer.util import cli_args


def sample_data():
    beats = np.arange(0.0, 4.5, 0.5, dtype=np.float64)
    n = beats.size
    x = np.linspace(0.0, 1.0, n)
    return {
        "at": 4.5,
        "tempo": 120.0,
        "beats": beats,
        "energy": .25 + .7 * np.sin(x * np.pi) ** 2,
        "onset": np.asarray([.9, .2, .85, .25, 1., .3, .9, .2, .8]),
        "bass": np.linspace(.15, 1., n),
        "mid": np.linspace(.9, .2, n),
        "high": np.asarray([.2, .8, .3, .9, .4, .85, .3, .75, .2]),
        "pitch": np.asarray([1.8, 2., 2.1, 1.95, 2.3, 2.2, 2.4, 2.1, 2.25]),
        "harmonic": np.linspace(.25, .95, n),
        "percussive": np.asarray([.9, .25, .8, .3, 1., .3, .85, .2, .75]),
        "stem_bass_energy": np.linspace(.1, 1., n),
        "stem_drums_hihat": np.asarray([.2, .8, .3, .9, .4, .85, .3, .75, .2]),
        "stem_drums_snare": np.asarray([.15, .95, .2, .9, .25, 1., .2, .85, .2]),
        "stem_drums_onset": np.asarray([.9, .2, .85, .25, 1., .3, .9, .2, .8]),
        "stem_vocals_energy": np.linspace(.2, .9, n),
        "stem_vocals_pitch_motion": np.asarray([.1, .4, .2, .7, .3, .9, .4, .8, .2]),
    }


def simple_config():
    return MultiAxisConfig(
        motion=MotionConfig(subdivision=1, max_speed=400.0, max_acceleration=2400.0),
        mechanical=MechanicalProjectionConfig(enabled=False),
    )


def test_quality_report_is_bounded_and_complete():
    plan = plan_multiaxis(sample_data(), simple_config())
    report = score_plan(plan, sample_data(), compute_windows=False)
    assert 0.0 <= report.overall <= 100.0
    assert set(report.metrics) == set(METRICS)
    assert all(0.0 <= value <= 100.0 for value in report.metrics.values())
    assert report.mechanical["samples"] > 0


def test_section_intent_override_only_changes_selected_range():
    beats = tuple(float(v) for v in range(10))
    base = MotionIntent(**{field: .2 for field in INTENT_FIELDS})
    envelope = IntentEnvelope(beats, {field: tuple(.2 for _ in beats) for field in INTENT_FIELDS}, base)
    target = MotionIntent(**{field: (.9 if field == "intensity" else .2) for field in INTENT_FIELDS})
    result = apply_section_intent_overrides(envelope, [SectionIntentOverride(3.0, 6.0, target, 1.0, "drop", .2)])
    values = np.asarray(result.fields["intensity"])
    assert values[1] == .2
    assert values[4] > .85
    assert values[8] == .2


def test_mechanical_projection_reduces_extreme_pose_risk():
    config = MechanicalProjectionConfig(max_risk=.45, servo_limit_deg=88.0)
    neutral = {axis: 50.0 for axis in AXIS_ORDER}
    extreme = {"L0": 100.0, "L1": 100.0, "L2": 0.0, "R0": 100.0, "R1": 100.0, "R2": 0.0}
    neutral_risk = mechanical_risk_at_pose(neutral, config=config)
    initial = mechanical_risk_at_pose(extreme, config=config)
    projected, final, changed = project_pose_to_safe(extreme, config=config)
    assert neutral_risk.reachable
    assert final.risk <= initial.risk + 1e-9
    assert all(0.0 <= projected[axis] <= 100.0 for axis in AXIS_ORDER)
    if changed:
        assert final.reachable
        assert final.risk <= config.max_risk + 1e-6


def test_plan_projection_preserves_axes_and_bounds():
    plan = {axis: [(0.0, 50.0), (1.0, 95.0), (2.0, 50.0)] for axis in AXIS_ORDER}
    projected, diagnostics = project_plan_to_safe(plan, config=MechanicalProjectionConfig(max_risk=.55))
    assert tuple(projected) == AXIS_ORDER
    for axis in AXIS_ORDER:
        assert len(projected[axis]) == len(plan[axis])
        assert all(0.0 <= pos <= 100.0 for _, pos in projected[axis])
    assert diagnostics["samples"] > 0


def test_candidate_generation_is_ranked_and_distinct():
    results = generate_candidates(sample_data(), simple_config(), count=3)
    assert len(results) == 3
    scores = [item.quality.overall for item in results]
    assert scores == sorted(scores, reverse=True)
    assert len({item.name for item in results}) == 3
    assert len({item.config.preset for item in results} | {round(item.config.independent.density, 3) for item in results}) >= 2


def test_auto_improvement_never_accepts_lower_score():
    data = sample_data()
    config = simple_config()
    plan = plan_multiaxis(data, config)
    before = score_plan(plan, data).overall
    result = auto_improve(data, plan, config, config=ImprovementConfig(max_iterations=1, candidates=2, minimum_improvement=0.0))
    assert result.quality.overall + 1e-9 >= before
    assert all(step.after + 1e-9 >= step.before for step in result.history)


def test_cli_exposes_quality_intelligence_flags():
    parser = add_cli_arguments(cli_args())
    args = parser.parse_args([
        "song.mp3", "--multiaxis", "--quality-score", "--quality-candidates", "4",
        "--auto-improve", "--merge-best-sections", "--mechanical-max-risk", ".7",
    ])
    assert args.quality_score is True
    assert args.quality_candidates == 4
    assert args.auto_improve is True
    assert args.merge_best_sections is True
    assert args.mechanical_max_risk == .7


def test_v27_chinese_translation_does_not_translate_engine_tokens():
    install_v27_translations()
    assert translate_text("Quality Intelligence", LANG_ZH) == "质量智能"
    assert translate_text("Motion Quality", LANG_ZH) == "动作质量"
    assert translate_text("balanced", LANG_ZH) == "balanced"
    assert translate_text("L0", LANG_ZH) == "L0"


def test_release_entry_modules_import():
    import dancer.cli_v27  # noqa: F401
    import dancer.workstation_ui_v27  # noqa: F401
    import dancer.workstation_ui_v27_release  # noqa: F401
