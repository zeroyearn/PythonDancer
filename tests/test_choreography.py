import numpy as np

from dancer.choreography import ChoreographyAnalysis, SectionSpan, detect_sections, musical_phase, synthesize_choreography_signals
from dancer.motion import MotionConfig
from dancer.multiaxis import AXIS_ORDER, MultiAxisConfig, analyze_multiaxis, plan_multiaxis


def _song_data(beats=64):
    times = np.arange(1, beats + 1, dtype=np.float64) * 0.5
    energy = np.concatenate([
        np.linspace(0.05, 0.15, 16),
        np.linspace(0.35, 0.48, 16),
        np.linspace(0.42, 0.78, 16),
        np.linspace(0.82, 1.00, 16),
    ])[:beats]
    onset = np.concatenate([
        np.full(16, 0.10),
        np.full(16, 0.42),
        np.linspace(0.35, 0.82, 16),
        np.full(16, 0.92),
    ])[:beats]
    bass = np.clip(energy * 0.92 + 0.04, 0, 1)
    mid = np.clip(0.35 + energy * 0.55, 0, 1)
    high = np.clip(onset * 0.82 + 0.05, 0, 1)
    pitch = np.clip(0.5 + 0.32 * np.sin(np.arange(beats) * 0.31), 0, 1)
    harmonic = np.clip(0.55 + 0.28 * np.sin(np.arange(beats) * 0.17), 0, 1)
    percussive = np.clip(onset * 0.95, 0, 1)
    return {
        "at": float(times[-1]),
        "tempo": 120.0,
        "beats": times,
        "energy": energy,
        "onset": onset,
        "bass": bass,
        "mid": mid,
        "high": high,
        "pitch": pitch,
        "harmonic": harmonic,
        "percussive": percussive,
    }


def _sample_actions(actions, grid):
    times = np.asarray([at for at, _ in actions], dtype=np.float64)
    values = np.asarray([position for _, position in actions], dtype=np.float64)
    return np.interp(grid, times, values, left=values[0], right=values[-1])


def test_musical_phase_tracks_real_beat_bar_and_phrase_coordinates():
    beats = np.asarray([0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    phase = musical_phase(beats, [0.5, 0.75, 1.0, 2.5], beats_per_bar=4, bars_per_phrase=2)
    assert np.allclose(phase["beat_position"][:3], [0.0, 0.5, 1.0])
    assert np.allclose(phase["beat_phase"][:3], [0.0, 0.5, 0.0])
    assert phase["bar_phase"][3] == 0.0
    assert np.all((phase["phrase_phase"] >= 0) & (phase["phrase_phase"] < 1))


def test_section_detection_is_phrase_aligned_and_dynamic():
    data = _song_data()
    analysis = detect_sections(data, beats_per_bar=4, bars_per_phrase=4, section_bars=4)
    assert len(analysis.sections) == 4
    assert analysis.sections[0].label == "intro"
    assert all(section.start_beat % 16 == 0 for section in analysis.sections)
    assert all(section.label in {"intro", "verse", "build", "chorus", "drop", "breakdown", "outro"} for section in analysis.sections)
    assert len(set(analysis.labels())) >= 2
    assert any(section.label in {"build", "chorus", "drop"} for section in analysis.sections[2:])


def test_analysis_summary_merges_adjacent_labels_and_serializes_metrics():
    analysis = ChoreographyAnalysis(
        (
            SectionSpan(0, 16, "verse", 0.3, 0.4, 0.1),
            SectionSpan(16, 32, "verse", 0.4, 0.5, 0.2),
            SectionSpan(32, 48, "drop", 0.9, 0.95, 0.8),
        ),
        beats_per_bar=4,
        bars_per_phrase=4,
        section_bars=4,
    )
    assert analysis.summary() == "verse:0-32 | drop:32-48"
    payload = analysis.to_dict()
    assert payload["summary"] == analysis.summary()
    assert payload["sections"][2]["label"] == "drop"
    assert payload["sections"][2]["activity"] == 0.95


def test_gesture_choreography_is_bounded_distinct_and_not_reactive_clone():
    data = _song_data()
    action_times = np.arange(0.5, 32.01, 0.25)
    l0 = 50.0 + 35.0 * np.sin(np.arange(action_times.size) * np.pi / 2.0)
    signals, analysis = synthesize_choreography_signals(data, action_times, l0, preset="expressive", gesture_strength=1.0)
    reactive_heavy, _ = synthesize_choreography_signals(data, action_times, l0, preset="expressive", gesture_strength=0.0)
    assert analysis.sections
    assert set(signals) == {"L1", "L2", "R0", "R1", "R2"}
    for values in signals.values():
        assert values.shape == action_times.shape
        assert np.isfinite(values).all()
        assert np.max(np.abs(values)) <= 1.0 + 1e-9
    assert not np.allclose(signals["L1"], signals["L2"])
    assert not np.allclose(signals["L2"], signals["R1"])
    assert not np.allclose(signals["R0"], reactive_heavy["R0"])


def test_multiaxis_defaults_to_choreography_but_reactive_mode_remains_available():
    data = _song_data()
    motion = MotionConfig(subdivision=1, max_speed=0, max_acceleration=0, min_interval=0.0)
    choreo_config = MultiAxisConfig(motion=motion, preset="balanced")
    reactive_config = MultiAxisConfig(motion=motion, preset="balanced", mode="reactive")
    assert choreo_config.mode == "choreography"
    assert analyze_multiaxis(data, choreo_config).sections
    choreo = plan_multiaxis(data, choreo_config)
    reactive = plan_multiaxis(data, reactive_config)
    assert set(choreo) == set(AXIS_ORDER)
    assert all(choreo[axis] for axis in AXIS_ORDER)
    assert all(reactive[axis] for axis in AXIS_ORDER)

    # 2.6 choreography intentionally gives secondary axes independent musical
    # clocks, while reactive mode keeps the shared L0 clock. Compare motion on
    # a common preview grid instead of assuming equal keyframe counts.
    duration = max(choreo["R0"][-1][0], reactive["R0"][-1][0])
    grid = np.linspace(0.0, duration, 128)
    assert not np.allclose(
        _sample_actions(choreo["R0"], grid),
        _sample_actions(reactive["R0"], grid),
    )
