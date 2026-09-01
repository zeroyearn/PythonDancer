from dancer.candidates import CandidateResult
from dancer.comparison import merge_candidate_sections
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


def test_merge_candidate_sections_preserves_locked_axes():
    base = _candidate("base", 20.0, 30.0)
    alternate = _candidate("alternate", 90.0, 95.0)
    merged = merge_candidate_sections(
        [base, alternate],
        [{"start": 0.0, "end": 2.0, "label": "drop"}],
        {0: 1},
        locked_axes=("L0", "R0"),
        blend=0.0,
    )
    assert merged["L0"] == base.plan["L0"]
    assert merged["R0"] == base.plan["R0"]


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
        locked_axes=("L0", "R0"),
        blend=0.0,
    )
    assert merged["L1"] == alternate.plan["L1"]
