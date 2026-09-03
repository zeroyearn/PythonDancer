"""Portable Motion Pack container for reusable grammar, style and device assets."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping
import zipfile


@dataclass(frozen=True)
class MotionPackManifest:
    name: str
    version: str = "1.0"
    author: str = ""
    description: str = ""
    license: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "license": self.license,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            name=str(payload.get("name", "motion-pack")),
            version=str(payload.get("version", "1.0")),
            author=str(payload.get("author", "")),
            description=str(payload.get("description", "")),
            license=str(payload.get("license", "")),
            tags=tuple(str(item) for item in payload.get("tags", ())),
        )


@dataclass
class MotionPack:
    manifest: MotionPackManifest
    motion_programs: dict[str, Mapping] = field(default_factory=dict)
    style_morphs: dict[str, Mapping] = field(default_factory=dict)
    automation_presets: dict[str, Mapping] = field(default_factory=dict)
    device_twins: dict[str, Mapping] = field(default_factory=dict)
    preference_profiles: dict[str, Mapping] = field(default_factory=dict)
    plugin_config: dict[str, Mapping] = field(default_factory=dict)

    def to_dict(self):
        return {
            "format": "pythondancer-motion-pack",
            "manifest": self.manifest.to_dict(),
            "motion_programs": self.motion_programs,
            "style_morphs": self.style_morphs,
            "automation_presets": self.automation_presets,
            "device_twins": self.device_twins,
            "preference_profiles": self.preference_profiles,
            "plugin_config": self.plugin_config,
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        if payload.get("format") not in (None, "pythondancer-motion-pack"):
            raise ValueError("unsupported motion pack format")
        return cls(
            MotionPackManifest.from_dict(payload.get("manifest") or {}),
            motion_programs=dict(payload.get("motion_programs") or {}),
            style_morphs=dict(payload.get("style_morphs") or {}),
            automation_presets=dict(payload.get("automation_presets") or {}),
            device_twins=dict(payload.get("device_twins") or {}),
            preference_profiles=dict(payload.get("preference_profiles") or {}),
            plugin_config=dict(payload.get("plugin_config") or {}),
        )

    def asset(self, kind: str, name: str):
        collection = getattr(self, kind)
        if name not in collection:
            raise KeyError(f"motion pack asset not found: {kind}/{name}")
        return collection[name]


def save_motion_pack(path: str | Path, pack: MotionPack) -> Path:
    target = Path(path).expanduser()
    if target.suffix.lower() not in (".pdmotion", ".zip"):
        target = target.with_suffix(".pdmotion")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pack.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.json", payload)
    return target


def load_motion_pack(path: str | Path) -> MotionPack:
    target = Path(path).expanduser()
    with zipfile.ZipFile(target, "r") as archive:
        if "pack.json" not in archive.namelist():
            raise ValueError("motion pack is missing pack.json")
        payload = json.loads(archive.read("pack.json").decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("motion pack manifest must contain a JSON object")
    return MotionPack.from_dict(payload)
