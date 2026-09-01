"""Unified device digital twin for PythonDancer 2.8.

The twin combines calibration, transport timing, SR6 geometry, optimizer limits,
and mechanical safe-set projection into one portable profile. It never drives
servo PWM directly; output remains TCode/Intiface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping, Sequence

from .calibration import DeviceCalibrationProfile, apply_calibration
from .kinematics import SR6Geometry
from .latency import DeviceTimingProfile, compensate_plan_latency
from .mechanical_safety import MechanicalProjectionConfig, project_plan_to_safe, trajectory_mechanical_risk
from .optimizer import OptimizerConfig, optimize_multiaxis


@dataclass(frozen=True)
class DeviceTwinProfile:
    name: str = "Default SR6"
    device_type: str = "SR6"
    calibration: DeviceCalibrationProfile = field(default_factory=DeviceCalibrationProfile)
    timing: DeviceTimingProfile = field(default_factory=DeviceTimingProfile)
    geometry: SR6Geometry = field(default_factory=SR6Geometry)
    mechanical: MechanicalProjectionConfig = field(default_factory=MechanicalProjectionConfig)
    safe_mode: bool = True
    notes: str = ""

    def optimizer_config(self) -> OptimizerConfig:
        return OptimizerConfig(
            enabled=True,
            neutral=50.0,
            pose_budget=1.65 if self.safe_mode else 1.95,
            velocity_budget=1.95 if self.safe_mode else 2.35,
            iterations=4 if self.safe_mode else 3,
            max_speed={axis: item.max_speed for axis, item in self.calibration.axes.items()},
            max_acceleration={axis: item.max_acceleration for axis, item in self.calibration.axes.items()},
            max_jerk={axis: item.max_jerk for axis, item in self.calibration.axes.items()},
        )

    def canonical_safe_plan(self, plan: Mapping[str, Sequence[tuple[float, float]]]):
        """Project a canonical 0..100 choreography into this device's safe workspace."""
        optimized = optimize_multiaxis(plan, self.optimizer_config())
        projected, first = project_plan_to_safe(optimized, self.geometry, self.mechanical)
        optimized = optimize_multiaxis(projected, self.optimizer_config())
        projected, final = project_plan_to_safe(optimized, self.geometry, self.mechanical)
        return projected, {"first_projection": first, "final_projection": final}

    def output_plan(self, plan: Mapping[str, Sequence[tuple[float, float]]]):
        canonical, diagnostics = self.canonical_safe_plan(plan)
        calibrated = apply_calibration(canonical, self.calibration)
        compensated = compensate_plan_latency(calibrated, self.timing)
        return compensated, diagnostics

    def diagnostics(self, plan: Mapping[str, Sequence[tuple[float, float]]]):
        canonical, passes = self.canonical_safe_plan(plan)
        risk = trajectory_mechanical_risk(canonical, self.geometry, self.mechanical)
        return {
            "name": self.name,
            "device_type": self.device_type,
            "safe_mode": self.safe_mode,
            "timing": self.timing.to_dict(),
            "mechanical": risk,
            "projection": passes,
        }

    def to_dict(self):
        geometry = {
            name: getattr(self.geometry, name)
            for name in self.geometry.__dataclass_fields__
        }
        return {
            "version": "1.0",
            "name": self.name,
            "device_type": self.device_type,
            "safe_mode": bool(self.safe_mode),
            "notes": self.notes,
            "calibration": self.calibration.to_dict(),
            "timing": self.timing.to_dict(),
            "geometry": geometry,
            "mechanical": self.mechanical.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        geometry_payload = dict(payload.get("geometry", {}))
        geometry = SR6Geometry(**{
            key: geometry_payload[key]
            for key in SR6Geometry.__dataclass_fields__
            if key in geometry_payload
        })
        mechanical_payload = dict(payload.get("mechanical", {}))
        mechanical = MechanicalProjectionConfig(**{
            key: mechanical_payload[key]
            for key in MechanicalProjectionConfig.__dataclass_fields__
            if key in mechanical_payload
        })
        return cls(
            name=str(payload.get("name", "Default SR6")),
            device_type=str(payload.get("device_type", "SR6")),
            calibration=DeviceCalibrationProfile.from_dict(payload.get("calibration", {})),
            timing=DeviceTimingProfile.from_dict(payload.get("timing", {})),
            geometry=geometry,
            mechanical=mechanical,
            safe_mode=bool(payload.get("safe_mode", True)),
            notes=str(payload.get("notes", "")),
        )


def load_device_twin(path: str | Path) -> DeviceTwinProfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("device twin must contain a JSON object")
    return DeviceTwinProfile.from_dict(payload)


def save_device_twin(path: str | Path, profile: DeviceTwinProfile) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return target
