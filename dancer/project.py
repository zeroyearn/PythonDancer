"""Portable .pdance projects, autosave, recent projects, and undo history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .multiaxis import AXIS_ORDER
from .workspace import AxisControl, GestureBlock, SectionBlock, TimeRange, WorkspaceState

PROJECT_SCHEMA = 4
APP_DIR = Path.home() / ".pythondancer"
AUTOSAVE_DIR = APP_DIR / "autosave"
RECENT_FILE = APP_DIR / "recent.json"


def _jsonable_plan(plan):
    return {axis: [[float(at), float(pos)] for at, pos in plan.get(axis, ())] for axis in AXIS_ORDER}


def _workspace_from_dict(data: Mapping[str, Any]) -> WorkspaceState:
    ws = WorkspaceState(duration=float(data.get("duration", 0.0)))
    selection = data.get("selection") or {}
    ws.selection = TimeRange(float(selection.get("start", 0.0)), float(selection.get("end", 0.0)))
    ws.sections = [SectionBlock(float(item["start"]), float(item["end"]), str(item["label"])) for item in data.get("sections", [])]
    ws.gestures = [
        GestureBlock(
            float(item["start"]),
            float(item["end"]),
            str(item["gesture"]),
            float(item.get("strength", 1.0)),
            axis_mix=dict(item.get("axis_mix") or {}),
            phase_offset=float(item.get("phase_offset", 0.0)),
            cycles=float(item.get("cycles", 1.0)),
            direction=int(item.get("direction", 1)),
            blend_in=float(item.get("blend_in", 0.12)),
            blend_out=float(item.get("blend_out", 0.12)),
        )
        for item in data.get("gestures", [])
    ]
    axis_data = data.get("axes") or {}
    ws.axes = {
        axis: AxisControl(bool((axis_data.get(axis) or {}).get("muted", False)), bool((axis_data.get(axis) or {}).get("locked", False)))
        for axis in AXIS_ORDER
    }
    solo = data.get("solo_axis")
    ws.solo_axis = solo if solo in AXIS_ORDER else None
    return ws


@dataclass
class ProjectDocument:
    media_path: str = ""
    base_plan: dict[str, list[tuple[float, float]]] = field(default_factory=lambda: {axis: [] for axis in AXIS_ORDER})
    workspace: WorkspaceState = field(default_factory=WorkspaceState)
    analysis: dict[str, Any] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    curve_settings: dict[str, Any] = field(default_factory=dict)
    safety_settings: dict[str, Any] = field(default_factory=dict)
    device: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)
    quality_intelligence: dict[str, Any] = field(default_factory=dict)
    daw: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROJECT_SCHEMA,
            "media_path": self.media_path,
            "base_plan": _jsonable_plan(self.base_plan),
            "workspace": self.workspace.to_dict(),
            "analysis": deepcopy(self.analysis),
            "generation": deepcopy(self.generation),
            "curve_settings": deepcopy(self.curve_settings),
            "safety_settings": deepcopy(self.safety_settings),
            "device": deepcopy(self.device),
            "ui": deepcopy(self.ui),
            "quality_intelligence": deepcopy(self.quality_intelligence),
            "daw": deepcopy(self.daw),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectDocument":
        schema = int(data.get("schema", 0))
        if schema not in (1, 2, 3, PROJECT_SCHEMA):
            raise ValueError(f"unsupported .pdance schema: {schema}")
        plan = {
            axis: [(float(item[0]), float(item[1])) for item in (data.get("base_plan") or {}).get(axis, [])]
            for axis in AXIS_ORDER
        }
        return cls(
            media_path=str(data.get("media_path", "")),
            base_plan=plan,
            workspace=_workspace_from_dict(data.get("workspace") or {}),
            analysis=deepcopy(data.get("analysis") or {}),
            generation=deepcopy(data.get("generation") or {}),
            curve_settings=deepcopy(data.get("curve_settings") or {}),
            safety_settings=deepcopy(data.get("safety_settings") or {}),
            device=deepcopy(data.get("device") or {}),
            ui=deepcopy(data.get("ui") or {}),
            quality_intelligence=deepcopy(data.get("quality_intelligence") or {}),
            daw=deepcopy(data.get("daw") or {}),
            created_at=str(data.get("created_at", "")) or datetime.now(timezone.utc).isoformat(),
            updated_at=str(data.get("updated_at", "")) or datetime.now(timezone.utc).isoformat(),
        )


def _is_autosave_path(path: str | os.PathLike[str]) -> bool:
    target = Path(path).expanduser()
    try:
        if target.resolve(strict=False).parent == AUTOSAVE_DIR.resolve(strict=False):
            return True
    except OSError:
        pass
    return target.name.lower().endswith(".autosave.pdance")


def save_project(path: str | os.PathLike[str], project: ProjectDocument, *, remember: bool = True) -> Path:
    target = Path(path).expanduser()
    if target.suffix.lower() != ".pdance":
        target = target.with_suffix(".pdance")
    target.parent.mkdir(parents=True, exist_ok=True)
    project.updated_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    if remember and not _is_autosave_path(target):
        remember_project(target)
    return target


def load_project(path: str | os.PathLike[str]) -> ProjectDocument:
    target = Path(path).expanduser()
    data = json.loads(target.read_text(encoding="utf-8"))
    project = ProjectDocument.from_dict(data)
    if not _is_autosave_path(target):
        remember_project(target)
    return project


def autosave_path(media_path: str | os.PathLike[str]) -> Path:
    AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
    if media_path:
        source = Path(media_path).expanduser()
        name = source.stem
        canonical = str(source.resolve(strict=False))
        digest = hashlib.sha256(canonical.encode("utf-8", errors="surrogatepass")).hexdigest()[:10]
    else:
        name = "untitled"
        digest = "session"
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)[:68] or "untitled"
    return AUTOSAVE_DIR / f"{safe}-{digest}.autosave.pdance"


def autosave_project(project: ProjectDocument) -> Path:
    return save_project(autosave_path(project.media_path), project, remember=False)


def remember_project(path: str | os.PathLike[str], *, limit: int = 12) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    resolved = str(Path(path).expanduser().resolve())
    if _is_autosave_path(resolved):
        return
    recent = recent_projects()
    recent = [item for item in recent if item != resolved]
    recent.insert(0, resolved)
    RECENT_FILE.write_text(json.dumps(recent[:limit], indent=2), encoding="utf-8")


def recent_projects() -> list[str]:
    try:
        values = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return [
        str(item)
        for item in values
        if isinstance(item, str) and Path(item).exists() and not _is_autosave_path(item)
    ]


class UndoStack:
    """Bounded snapshot history for the editable plan/workspace state."""

    def __init__(self, limit: int = 80):
        self.limit = max(2, int(limit))
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    @staticmethod
    def snapshot(base_plan, workspace: WorkspaceState) -> dict[str, Any]:
        return {"base_plan": _jsonable_plan(base_plan), "workspace": workspace.to_dict()}

    @staticmethod
    def restore(snapshot: Mapping[str, Any]):
        plan = {
            axis: [(float(item[0]), float(item[1])) for item in (snapshot.get("base_plan") or {}).get(axis, [])]
            for axis in AXIS_ORDER
        }
        return plan, _workspace_from_dict(snapshot.get("workspace") or {})

    def push(self, base_plan, workspace: WorkspaceState) -> None:
        snapshot = self.snapshot(base_plan, workspace)
        if self._undo and self._undo[-1] == snapshot:
            return
        self._undo.append(snapshot)
        if len(self._undo) > self.limit:
            del self._undo[0]
        self._redo.clear()

    def undo(self, current_plan, current_workspace: WorkspaceState):
        if not self._undo:
            return None
        self._redo.append(self.snapshot(current_plan, current_workspace))
        return self.restore(self._undo.pop())

    def redo(self, current_plan, current_workspace: WorkspaceState):
        if not self._redo:
            return None
        self._undo.append(self.snapshot(current_plan, current_workspace))
        return self.restore(self._redo.pop())

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
