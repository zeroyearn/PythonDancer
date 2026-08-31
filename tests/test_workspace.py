import numpy as np

from dancer.choreography import ChoreographyAnalysis, SectionSpan
from dancer.features import waveform_preview
from dancer.multiaxis import AXIS_ORDER
from dancer.workspace import GestureBlock, WorkspaceState, apply_gesture_blocks, splice_plan


def sample_plan(scale=1.0):
    times = np.linspace(0.0, 4.0, 17)
    return {
        axis: [(float(t), float(50.0 + scale * (i + 1) * np.sin(t * np.pi / 2.0))) for t in times]
        for i, axis in enumerate(AXIS_ORDER)
    }


def test_waveform_preview_is_compact_and_normalized():
    sr = 1000
    t = np.arange(5000) / sr
    y = 0.5 * np.sin(2 * np.pi * 7 * t)
    times, envelope = waveform_preview(y, sr, points=100)
    assert len(times) == len(envelope) == 100
    assert times[0] == 0.0
    assert times[-1] < 5.0
    assert np.all((envelope >= 0.0) & (envelope <= 1.0))
    assert np.max(envelope) == 1.0


def test_gesture_overlay_changes_motion_but_keeps_bounds():
    plan = sample_plan()
    changed = apply_gesture_blocks(plan, [GestureBlock(0.5, 3.5, "spiral", 1.2)])
    assert changed["R0"] != plan["R0"]
    for axis in AXIS_ORDER:
        assert all(0.0 <= pos <= 100.0 for _, pos in changed[axis])


def test_solo_is_preview_only_but_mute_affects_output():
    ws = WorkspaceState(duration=4.0)
    plan = sample_plan()
    ws.solo_axis = "R0"
    output = ws.output_plan(plan)
    preview = ws.preview_plan(plan)
    assert all(output[axis] for axis in AXIS_ORDER)
    assert preview["R0"]
    assert all(not preview[axis] for axis in AXIS_ORDER if axis != "R0")

    ws.axes["L2"].muted = True
    output = ws.output_plan(plan)
    assert output["L2"] == []
    assert output["R0"]


def test_locked_axis_survives_local_splice():
    current = sample_plan(scale=0.5)
    replacement = sample_plan(scale=2.0)
    result = splice_plan(current, replacement, 1.0, 3.0, locked_axes=("R0",), blend=0.25)
    assert result["R0"] == current["R0"]
    assert result["L1"] != current["L1"]
    before = [item for item in result["L1"] if item[0] < 1.0]
    after = [item for item in result["L1"] if item[0] > 3.0]
    assert before == [item for item in current["L1"] if item[0] < 1.0]
    assert after == [item for item in current["L1"] if item[0] > 3.0]


def test_sections_convert_to_continuous_time_blocks_and_boundary_moves():
    analysis = ChoreographyAnalysis(
        sections=(
            SectionSpan(0, 4, "intro", 0.2, 0.2, 0.1),
            SectionSpan(4, 8, "verse", 0.5, 0.5, 0.2),
        ),
        beats_per_bar=4,
        bars_per_phrase=4,
        section_bars=1,
    )
    beats = np.arange(0.0, 4.0, 0.5)
    ws = WorkspaceState.from_analysis(analysis, beats, 4.0)
    assert ws.sections[0].start == 0.0
    assert ws.sections[-1].end == 4.0
    ws.set_section_boundary(1, 1.75)
    assert ws.sections[0].end == ws.sections[1].start == 1.75
    ws.set_section_label(1, "drop")
    assert ws.sections[1].label == "drop"


def test_workspace_serialization_contains_editor_state():
    ws = WorkspaceState(duration=4.0)
    ws.set_selection(1.0, 2.0)
    ws.add_gesture(1.0, 2.0, "pulse", 1.3)
    ws.axes["R2"].locked = True
    payload = ws.to_dict()
    assert payload["selection"] == {"start": 1.0, "end": 2.0}
    assert payload["gestures"][0]["gesture"] == "pulse"
    assert payload["axes"]["R2"]["locked"] is True
