import json

from dancer.project import ProjectDocument, UndoStack, load_project, save_project
from dancer.workspace import GestureBlock, SectionBlock, WorkspaceState


def test_pdance_round_trip(tmp_path):
    ws = WorkspaceState(duration=12.0)
    ws.sections = [SectionBlock(0, 6, "verse"), SectionBlock(6, 12, "drop")]
    ws.gestures = [GestureBlock(4, 7, "spiral", 1.2, axis_mix={"R0": 1.4}, phase_offset=.25, cycles=2., direction=-1, blend_in=.2, blend_out=.3)]
    ws.axes["R0"].muted = True
    project = ProjectDocument(
        media_path="song.mp3",
        base_plan={
            "L0": [(0, 20), (1, 80)], "L1": [], "L2": [], "R0": [], "R1": [], "R2": []
        },
        workspace=ws,
        curve_settings={"interpolation": "pchip"},
        safety_settings={"profile": "safe"},
    )
    path = save_project(tmp_path / "demo.pdance", project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 2
    restored = load_project(path)
    assert restored.media_path == "song.mp3"
    assert restored.base_plan["L0"] == [(0.0, 20.0), (1.0, 80.0)]
    assert restored.workspace.sections[1].label == "drop"
    gesture = restored.workspace.gestures[0]
    assert gesture.gesture == "spiral"
    assert gesture.axis_mix["R0"] == 1.4
    assert gesture.phase_offset == .25
    assert gesture.cycles == 2.
    assert gesture.direction == -1
    assert restored.workspace.axes["R0"].muted is True
    assert restored.curve_settings["interpolation"] == "pchip"


def test_schema_1_project_still_loads(tmp_path):
    path = tmp_path / "legacy.pdance"
    path.write_text(json.dumps({
        "schema": 1,
        "media_path": "legacy.mp3",
        "base_plan": {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        "workspace": {
            "duration": 5.0,
            "selection": {"start": 0.0, "end": 0.0},
            "sections": [{"start": 0.0, "end": 5.0, "label": "verse"}],
            "gestures": [{"start": 1.0, "end": 2.0, "gesture": "wave", "strength": 1.0}],
            "axes": {},
            "solo_axis": None,
        },
    }), encoding="utf-8")
    restored = load_project(path)
    assert restored.media_path == "legacy.mp3"
    assert restored.workspace.gestures[0].cycles == 1.0
    assert restored.workspace.gestures[0].direction == 1


def test_undo_redo_restores_plan_and_workspace():
    ws = WorkspaceState(duration=5.0)
    plan = {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")}
    plan["L0"] = [(0, 10), (1, 90)]
    history = UndoStack()
    history.push(plan, ws)
    current = {axis: list(values) for axis, values in plan.items()}
    current["L0"][1] = (1, 70)
    ws.axes["R0"].muted = True
    restored = history.undo(current, ws)
    assert restored is not None
    old_plan, old_ws = restored
    assert old_plan["L0"][1][1] == 90.0
    assert old_ws.axes["R0"].muted is False
    redone = history.redo(old_plan, old_ws)
    assert redone is not None
    redo_plan, redo_ws = redone
    assert redo_plan["L0"][1][1] == 70.0
    assert redo_ws.axes["R0"].muted is True
