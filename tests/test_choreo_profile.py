import numpy as np

from dancer.choreo_profile import synthesize_profiled_choreography
from dancer.style import ChoreographyProfile


def _data():
    beats = np.arange(0.5, 8.5, 0.5)
    n = beats.size
    return {
        "beats": beats,
        "energy": np.linspace(0.2, 0.8, n),
        "onset": np.full(n, 0.2),
        "bass": np.full(n, 0.25),
        "mid": np.linspace(0.7, 0.3, n),
        "high": np.full(n, 0.25),
        "pitch": np.linspace(0.3, 0.7, n),
        "harmonic": np.full(n, 0.5),
        "percussive": np.full(n, 0.25),
    }


def test_stem_features_materially_change_profiled_choreography():
    data = _data()
    action_times = np.arange(0.5, 8.01, 0.25)
    l0 = 50 + 30 * np.sin(np.arange(action_times.size) * np.pi / 2)
    profile = ChoreographyProfile(stem_influence=1.0)
    base, _ = synthesize_profiled_choreography(data, action_times, l0, profile=profile)

    stemmed = dict(data)
    n = len(data["beats"])
    stemmed.update({
        "stem_drums_energy": np.linspace(0.1, 1.0, n),
        "stem_drums_onset": np.asarray(([0.1, 1.0, 0.2, 0.9] * 4)[:n]),
        "stem_bass_energy": np.linspace(1.0, 0.1, n),
        "stem_vocals_energy": np.linspace(0.2, 0.9, n),
        "stem_vocals_pitch": np.linspace(0.9, 0.2, n),
        "stem_other_energy": np.linspace(0.3, 0.8, n),
    })
    enriched, _ = synthesize_profiled_choreography(stemmed, action_times, l0, profile=profile)

    assert not np.allclose(base["L1"], enriched["L1"])
    assert not np.allclose(base["R0"], enriched["R0"])
    assert not np.allclose(base["R2"], enriched["R2"])
    assert all(np.max(np.abs(values)) <= 1.0 + 1e-9 for values in enriched.values())
