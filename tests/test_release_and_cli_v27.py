from argparse import Namespace
from pathlib import Path
import sys

import pytest

from dancer.cli_v27 import _validate_args
from dancer.improvement import ImprovementConfig


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_score": float("nan")},
        {"minimum_improvement": float("nan")},
        {"minimum_improvement": float("inf")},
        {"blend_seconds": float("nan")},
        {"blend_seconds": float("inf")},
    ],
)
def test_improvement_config_rejects_non_finite_thresholds(kwargs):
    with pytest.raises(ValueError):
        ImprovementConfig(**kwargs)


def test_windows_desktop_entry_defaults_to_multiaxis(monkeypatch):
    import ui_entry

    calls = []
    monkeypatch.setattr(sys, "argv", ["PythonDancer.exe"])
    monkeypatch.setattr(ui_entry, "main", lambda: calls.append(tuple(sys.argv)) or 0)
    assert ui_entry.desktop_main() == 0
    assert calls == [("PythonDancer.exe", "--multiaxis")]


def test_windows_desktop_entry_preserves_explicit_arguments(monkeypatch):
    import ui_entry

    calls = []
    monkeypatch.setattr(sys, "argv", ["PythonDancer.exe", "--cli", "song.mp3"])
    monkeypatch.setattr(ui_entry, "main", lambda: calls.append(tuple(sys.argv)) or 0)
    assert ui_entry.desktop_main() == 0
    assert calls == [("PythonDancer.exe", "--cli", "song.mp3")]


def test_release_workflow_is_explicit_and_targets_27():
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'default: "v2.7.0"' in text
    assert 'else TAG="v2.7.0"' in text
    assert 'branches:' not in text
    assert 'tags: ["v*"]' in text
    assert "PythonDancer 2.7.0 — Quality Intelligence" in text


def test_windows_bundle_is_gui_only_and_freezes_plan_window():
    text = Path("qt.spec").read_text(encoding="utf-8")
    assert "console=False" in text
    assert '"dancer.plan_window"' in text
