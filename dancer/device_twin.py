"""Unified device digital twin for PythonDancer 3.0.

The twin combines calibration, transport timing, SR6 geometry, optimizer limits,
mechanical safe-set projection, dynamic load estimation and optional
hardware-in-the-loop feedback into one portable profile. It never drives servo
PWM directly; output remains TCode/Intiface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .calibration import DeviceCalibrationProfile
from .device_feedback import DeviceDynamicsProfile, FeedbackCalibration, simulate_dynamic_load
from .kinematics import AXES, SR6Geometry
from .latency import DeviceTimingProfile, compensate_plan_latency
from .mechanical_safety import MechanicalProjectionConfig, project_plan_to_safe, project_pose_to_safe, trajectory_mechanical_risk
from .optimizer import OptimizerConfig, optimize_multiaxis


def _apply_feedback_latency(plan, latency_ms: float):
    offset = max(0.0, float(latency_ms)) / 1000.0
    if offset <= 1e-9:
        return {axis: [(float(t), float(p)) for t, p in plan.get(axis, ())] for axis in AXES}
    return {
        axis: [(max(0.0, float(t) - offset), float(p)) for t, p in plan.get(axis, ())]
        for axis in AXES
    }


@dataclass(frozen=True)
class DeviceTwinProfile:
    name: str = "Default SR6"
    device_type: str = "SR6"
    calibration: DeviceCalibrationProfile = field(default_factory=DeviceCalibrationProfile)
    timing: DeviceTimingProfile = field(default_factory=DeviceTimingProfile)
    geometry: SR6Geometry = field(default_factory=SR6Geometry)
    mechanical: MechanicalProjectionConfig = field(default_factory=MechanicalProjectionConfig)
    dynamics: DeviceDynamicsProfile = field(default_factory=DeviceDynamicsProfile)
    feedback: FeedbackCalibration = field(default_factory=FeedbackCalibration)
    safe_mode: bool = True
    notes: str = ""

    def optimizer_config(self) -> OptimizerConfig:
        derate = float(np.clip(self.dynamics.velocity_derate, .25, 1.25))
        if self.safe_mode:
            derate = min(derate, 1.0)
        return OptimizerConfig(
            enabled=True,
            neutral=50.0,
            pose_budget=1.65 if self.safe_mode else 1.95,
            velocity_budget=(1.95 if self.safe_mode else 2.35) * derate,
            iterations=4 if self.safe_mode else 3,
            max_speed={axis: item.max_speed * derate for axis, item in self.calibration.axes.items()},
            max_acceleration={axis: item.max_acceleration * derate for axis, item in self.calibration.axes.items()},
            max_jerk={axis: item.max_jerk * derate for axis, item in self.calibration.axes.items()},
        )

    def safe_pose(self, pose: Mapping[str, float], *, calibrate: bool = False):
        canonical, risk, changed = project_pose_to_safe(pose, self.geometry, self.mechanical)
        if calibrate:
            mapped = {}
            for axis in AXES:
                command = self.feedback.correct_command(axis, float(canonical.get(axis, 50.0)))
                mapped[axis] = self.calibration.axes[axis].map_normalized(command)
            return mapped, risk, changed
        return canonical, risk, changed

    def canonical_safe_plan(self, plan: Mapping[str, Sequence[tuple[float, float]]]):
        """Project a canonical 0..100 choreography into this device's safe workspace."""
        optimized = optimize_multiaxis(plan, self.optimizer_config())
        projected, first = project_plan_to_safe(optimized, self.geometry, self.mechanical)
        optimized = optimize_multiaxis(projected, self.optimizer_config())
        projected, final = project_plan_to_safe(optimized, self.geometry, self.mechanical)
        return projected, {"first_projection": first, "final_projection": final}

    def output_plan(self, plan: Mapping[str, Sequence[tuple[float, float]]]):
        canonical, diagnostics = self.canonical_safe_plan(plan)
        calibrated = {}
        for axis in AXES:
            calibration = self.calibration.axes[axis]
            calibrated[axis] = [
                (float(at), calibration.map_normalized(self.feedback.correct_command(axis, float(pos))))
                for at, pos in canonical.get(axis, ())
            ]
        compensated = compensate_plan_latency(calibrated, self.timing)
        compensated = _apply_feedback_latency(compensated, self.feedback.latency_ms if self.feedback.enabled else 0.0)
        diagnostics["feedback"] = self.feedback.to_dict()
        diagnostics["dynamic_load"] = simulate_dynamic_load(canonical, self.dynamics).to_dict()
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
            "dynamics": self.dynamics.to_dict(),
            "dynamic_load": simulate_dynamic_load(canonical, self.dynamics).to_dict(),
            "feedback": self.feedback.to_dict(),
        }

    def to_dict(self):
        geometry = {
            name: getattr(self.geometry, name)
            for name in self.geometry.__dataclass_fields__
        }
        return {
            "version": "2.0",
            "name": self.name,
            "device_type": self.device_type,
            "safe_mode": bool(self.safe_mode),
            "notes": self.notes,
            "calibration": self.calibration.to_dict(),
            "timing": self.timing.to_dict(),
            "geometry": geometry,
            "mechanical": self.mechanical.to_dict(),
            "dynamics": self.dynamics.to_dict(),
            "feedback": self.feedback.to_dict(),
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
            dynamics=DeviceDynamicsProfile.from_dict(payload.get("dynamics")),
            feedback=FeedbackCalibration.from_dict(payload.get("feedback")),
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
