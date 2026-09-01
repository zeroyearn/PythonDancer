"""PythonDancer 2.6 release CLI integration."""
from __future__ import annotations

from dataclasses import replace

from . import cli_v26, cli_v26_final
from .calibration import load_calibration_profile
from .generation_limits import optimizer_from_calibration
from .kinematics import trajectory_kinematics_diagnostics


def cmd(args):
    base_multi = cli_v26._multi_config
    base_export = cli_v26.legacy.export_funscript_bundle
    base_plan = cli_v26.legacy.plan_multiaxis

    def multi_config(inner_args, motion, profile=None):
        config = base_multi(inner_args, motion, profile)
        calibration_path = getattr(inner_args, "calibration_profile", None)
        if calibration_path:
            calibration = load_calibration_profile(calibration_path)
            config = replace(config, optimizer=optimizer_from_calibration(config.optimizer, calibration))
        return config

    def plan_multiaxis(data, config):
        plan = base_plan(data, config)
        if plan.get("L0"):
            diagnostics = trajectory_kinematics_diagnostics(plan)
            print(
                "SR6 diagnostics: "
                f"unreachable={diagnostics['unreachable_ratio'] * 100.0:.1f}% "
                f"max_servo={diagnostics['max_abs_servo_angle_deg']:.1f}deg "
                f"samples={diagnostics['samples']}"
            )
        return plan

    def export_bundle(base_path, plan, *, metadata=None, manifest=True):
        payload = dict(metadata or {})
        payload["sr6_kinematics"] = trajectory_kinematics_diagnostics(plan)
        return base_export(base_path, plan, metadata=payload, manifest=manifest)

    cli_v26._multi_config = multi_config
    cli_v26.legacy.plan_multiaxis = plan_multiaxis
    cli_v26.legacy.export_funscript_bundle = export_bundle
    try:
        return cli_v26_final.cmd(args)
    finally:
        cli_v26._multi_config = base_multi
        cli_v26.legacy.plan_multiaxis = base_plan
        cli_v26.legacy.export_funscript_bundle = base_export
