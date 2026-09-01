from argparse import Namespace
from pathlib import Path

import pytest

from dancer.cli_v27 import _validate_args


def _args(**overrides):
    values = {
        "quality_candidates": 4,
        "mechanical_max_risk": .82,
        "improve_iterations": 4,
        "improve_target": 90.0,
        "improve_min_gain": .35,
        "servo_limit_deg": 88.0,
        "singularity_sensitivity": 2.5,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_candidates", 0),
        ("quality_candidates", 9),
        ("mechanical_max_risk", float("nan")),
        ("mechanical_max_risk", 1.1),
        ("improve_iterations", 0),
        ("improve_target", float("inf")),
        ("improve_target", 101.0),
        ("improve_min_gain", -0.1),
        ("servo_limit_deg", 0.0),
        ("servo_limit_deg", float("nan")),
        ("singularity_sensitivity", 0.0),
        ("singularity_sensitivity", float("inf")),
    ],
)
def test_quality_cli_rejects_invalid_numeric_inputs(field, value):
    assert _validate_args(_args(**{field: value})) is not None


def test_quality_cli_accepts_valid_boundary_values():
    assert _validate_args(_args(quality_candidates=1, mechanical_max_risk=0.0, improve_target=0.0, improve_min_gain=0.0)) is None
    assert _validate_args(_args(quality_candidates=8, mechanical_max_risk=1.0, improve_target=100.0)) is None


def test_release_workflow_is_explicit_and_targets_27():
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'default: "v2.7.0"' in text
    assert 'else TAG="v2.7.0"' in text
    assert 'branches:' not in text
    assert 'tags: ["v*"]' in text
    assert "PythonDancer 2.7.0 — Quality Intelligence" in text
