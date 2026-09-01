from dancer.candidates import CandidateResult
from dancer.comparison import best_section_merge, merge_candidate_sections
from dancer.mechanical_safety import MechanicalProjectionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig
from dancer.quality import QualityReport


def _candidate(name, l0_mid, r0_mid):
    plan = {
        axis: [(0.0, 50.0), (1.0, 50.0), (2.0, 50.0)]
        for axis in AXIS_ORDER
    }
    plan["L0"] = [(0.0, 50.0), (1.0, float(l0_mid)), (2.0, 50.0)]
    plan["R0"] = [(0.0, 50.0), (1.0, float(r0_mid)), (2.0, 50.0)]
    config = MultiAxisConfig(mechanical=MechanicalProjectionConfig(enabled=False))
    return CandidateResult(name, config, plan, QualityReport(50.0, {}))


def _current_plan():
    plan = {axis: [(0.0, 50.0), (1.0, 50.0), (2.0, 50.0)] for axis in AXIS_ORDER}
    plan["L0"] = [(0.0, 50.0), (1.0, 42.0), (2.0, 50.0)]
    plan["R0"] = [(0.0, 50.0), (1.0, 44.0), (2.0, 50.0)]
    return plan


def test_merge_candidate_sections_preserves_locked_axes_from_current_plan():
    base = _candidate("base", 20.0, 30.0)
    alternate = _candidate("alternate", 90.0, 95.0)
    current = _current_plan()
    merged = merge_candidate_sections(
        [base, alternate],
        [{"start": 0.0, "end": 2.0, "label": "drop"}],
        {0: 1},
        base_plan=current,
        locked_axes=("L0", "R0"),
        blend=0.0,
    )
    assert merged["L0"] == current["L0"]
    assert merged["R0"] == current["R0"]
    assert merged["L0"] != base.plan["L0"]


def test_merge_candidate_sections_still_replaces_unlocked_axes():
    base = _candidate("base", 20.0, 30.0)
    alternate = _candidate("alternate", 90.0, 95.0)
    alternate_plan = {axis: list(rows) for axis, rows in alternate.plan.items()}
    alternate_plan["L1"] = [(0.0, 10.0), (1.0, 80.0), (2.0, 10.0)]
    alternate = CandidateResult(alternate.name, alternate.config, alternate_plan, alternate.quality)
    merged = merge_candidate_sections(
        [base, alternate],
        [{"start": 0.0, "end": 2.0, "label": "drop"}],
        {0: 1},
        base_plan=_current_plan(),
        locked_axes=("L0", "R0"),
        blend=0.0,
    )
    assert merged["L1"] == alternate.plan["L1"]


def test_best_section_scoring_uses_current_locked_curves(monkeypatch):
    base = _candidate("base", 20.0, 30.0)
    alternate = _candidate("alternate", 90.0, 95.0)
    current = _current_plan()
    scored_l0 = []

    def fake_score(plan, *_args, **_kwargs):
        scored_l0.append(list(plan["L0"]))
        return QualityReport(float(plan["L1"][1][1]), {})

    monkeypatch.setattr("dancer.comparison.score_plan", fake_score)
    merged, _choices, _scores = best_section_merge(
        [base, alternate],
        [{"start": 0.0, "end": 2.0, "label": "drop"}],
        base_plan=current,
        locked_axes=("L0", "R0"),
        blend=0.0,
    )
    assert len(scored_l0) == 2
    assert all(rows == current["L0"] for rows in scored_l0)
    assert merged["L0"] == current["L0"]
