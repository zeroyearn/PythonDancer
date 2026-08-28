import numpy as np

from dancer.features import _aggregate_to_beats, extract_audio_features, safe_normalize


def test_safe_normalize_constant_and_nonfinite():
    assert np.allclose(safe_normalize([3, 3, 3]), [0, 0, 0])
    normalized = safe_normalize([1, np.nan, 3])
    assert np.isfinite(normalized).all()
    assert np.allclose(normalized, [0, 0, 1])


def test_aggregate_to_beats_has_no_negative_first_slice():
    values = np.arange(10, dtype=float)
    result = _aggregate_to_beats(values, np.array([2, 5, 10]))
    assert np.allclose(result, [0.5, 3.0, 7.0])


def test_extract_audio_features_are_beat_aligned():
    sr = 22050
    duration = 3.0
    t = np.arange(int(sr * duration)) / sr
    y = 0.05 * np.sin(2 * np.pi * 220 * t)
    for second in (0.5, 1.0, 1.5, 2.0, 2.5):
        start = int(second * sr)
        y[start:start + 128] += np.hanning(128)

    data = extract_audio_features(y.astype(np.float32), sr, hop_length=256, frame_length=1024, plp=False)
    n = len(data["beats"])
    assert n > 0
    for key in ("pitch", "energy", "onset", "bass", "mid", "high", "harmonic", "percussive"):
        assert len(data[key]) == n
        assert np.isfinite(data[key]).all()


def test_short_flat_audio_still_produces_finite_features():
    sr = 22050
    y = np.zeros(sr // 4, dtype=np.float32)
    data = extract_audio_features(y, sr, hop_length=256, frame_length=1024, plp=False)
    assert len(data["beats"]) >= 1
    assert np.isfinite(data["energy"]).all()
