"""Portable JSON profiles for SR6 firmware-model geometry diagnostics."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Mapping

from .kinematics import SR6Geometry


def geometry_to_dict(geometry: SR6Geometry) -> dict[str, object]:
    return {"version": "1.0", "geometry": asdict(geometry)}


def geometry_from_dict(payload: Mapping) -> SR6Geometry:
    values = payload.get("geometry", payload)
    if not isinstance(values, Mapping):
        raise ValueError("SR6 geometry profile must contain a geometry object")
    allowed = SR6Geometry.__dataclass_fields__
    return SR6Geometry(**{key: float(value) for key, value in values.items() if key in allowed})


def load_geometry_profile(path: str | Path) -> SR6Geometry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SR6 geometry profile must contain a JSON object")
    return geometry_from_dict(payload)


def save_geometry_profile(path: str | Path, geometry: SR6Geometry) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(geometry_to_dict(geometry), indent=2), encoding="utf-8")
    return target
