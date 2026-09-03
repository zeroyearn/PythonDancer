import json

import dancer.project as project_mod
from dancer.project import ProjectDocument, UndoStack, autosave_project, load_project, recent_projects, save_project
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
        quality_intelligence={"report": {"overall": 91.2}, "candidate_a": "Balanced"},
        daw={"automation": {"version": "1.0"}, "live": {"bpm": 128.0}},
        intelligence={"version": "3.0", "copilot_instruction": "drop 加一个 wave"},
    )
    path = save_project(tmp_path / "demo.pdance", project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 5
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
    assert restored.quality_intelligence["report"]["overall"] == 91.2
    assert restored.daw["live"]["bpm"] == 128.0
    assert restored.intelligence["copilot_instruction"] == "drop 加一个 wave"


def test_autosaves_do_not_enter_recents_and_same_stem_does_not_collide(tmp_path, monkeypatch):
    app = tmp_path / "app"
    monkeypatch.setattr(project_mod, "APP_DIR", app)
    monkeypatch.setattr(project_mod, "AUTOSAVE_DIR", app / "autosave")
    monkeypatch.setattr(project_mod, "RECENT_FILE", app / "recent.json")

    first = ProjectDocument(media_path=str(tmp_path / "A" / "song.mp3"))
    second = ProjectDocument(media_path=str(tmp_path / "B" / "song.mp3"))
    first_path = autosave_project(first)
    second_path = autosave_project(second)

    assert first_path != second_path
    assert first_path.name.startswith("song-")
    assert second_path.name.startswith("song-")
    assert recent_projects() == []


def test_recent_projects_filters_legacy_autosave_entries(tmp_path, monkeypatch):
    app = tmp_path / "app"
    autosaves = app / "autosave"
    autosaves.mkdir(parents=True)
    monkeypatch.setattr(project_mod, "APP_DIR", app)
    monkeypatch.setattr(project_mod, "AUTOSAVE_DIR", autosaves)
    monkeypatch.setattr(project_mod, "RECENT_FILE", app / "recent.json")

    normal = tmp_path / "real.pdance"
    normal.write_text("{}", encoding="utf-8")
    legacy_auto = autosaves / "song.autosave.pdance"
    legacy_auto.write_text("{}", encoding="utf-8")
    project_mod.RECENT_FILE.write_text(json.dumps([str(legacy_auto), str(normal)]), encoding="utf-8")

    assert recent_projects() == [str(normal)]


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
    assert restored.daw == {}
    assert restored.intelligence == {}


def test_schema_2_project_still_loads(tmp_path):
    path = tmp_path / "v26.pdance"
    path.write_text(json.dumps({
        "schema": 2,
        "media_path": "v26.mp3",
        "base_plan": {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        "workspace": {"duration": 0, "selection": {}, "sections": [], "gestures": [], "axes": {}, "solo_axis": None},
        "generation": {"version": "2.6"},
    }), encoding="utf-8")
    restored = load_project(path)
    assert restored.media_path == "v26.mp3"
    assert restored.generation["version"] == "2.6"
    assert restored.quality_intelligence == {}
    assert restored.daw == {}
    assert restored.intelligence == {}


def test_schema_3_project_still_loads_with_empty_daw(tmp_path):
    path = tmp_path / "v27.pdance"
    path.write_text(json.dumps({
        "schema": 3,
        "media_path": "v27.mp3",
        "base_plan": {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        "workspace": {"duration": 0, "selection": {}, "sections": [], "gestures": [], "axes": {}, "solo_axis": None},
        "quality_intelligence": {"report": {"overall": 88.0}},
    }), encoding="utf-8")
    restored = load_project(path)
    assert restored.media_path == "v27.mp3"
    assert restored.quality_intelligence["report"]["overall"] == 88.0
    assert restored.daw == {}
    assert restored.intelligence == {}


def test_schema_4_project_still_loads_with_empty_intelligence(tmp_path):
    path = tmp_path / "v28.pdance"
    path.write_text(json.dumps({
        "schema": 4,
        "media_path": "v28.mp3",
        "base_plan": {axis: [] for axis in ("L0", "L1", "L2", "R0", "R1", "R2")},
        "workspace": {"duration": 0, "selection": {}, "sections": [], "gestures": [], "axes": {}, "solo_axis": None},
        "daw": {"live": {"bpm": 126.0}},
    }), encoding="utf-8")
    restored = load_project(path)
    assert restored.daw["live"]["bpm"] == 126.0
    assert restored.intelligence == {}


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
