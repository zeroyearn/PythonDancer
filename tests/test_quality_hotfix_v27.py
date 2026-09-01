import numpy as np

from dancer.candidates import generate_candidates
from dancer.mechanical_safety import MechanicalProjectionConfig
from dancer.motion import MotionConfig
from dancer.multiaxis import MultiAxisConfig
from dancer.quality import _slice_sections


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


def test_candidate_ranking_skips_weak_window_recursion():
    config = MultiAxisConfig(
        motion=MotionConfig(subdivision=1, max_speed=400.0, max_acceleration=2400.0),
        mechanical=MechanicalProjectionConfig(enabled=False),
    )
    results = generate_candidates(_data(), config, count=2)
    assert len(results) == 2
    assert all(candidate.quality.weak_ranges == () for candidate in results)


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


def test_final_hotfix_module_imports():
    import dancer.workstation_ui_v27_hotfix  # noqa: F401
