import json

from dancer.calibration import AxisCalibration, DeviceCalibrationProfile
from dancer.generation_limits import optimizer_from_calibration
from dancer.geometry_profile import load_geometry_profile, save_geometry_profile
from dancer.i18n import LANG_EN, LANG_ZH, translate_text
from dancer.i18n_safe import _display_name
from dancer.kinematics import SR6Geometry, solve_sr6_pose, trajectory_kinematics_diagnostics
from dancer.optimizer import OptimizerConfig


AXES = ("L0", "L1", "L2", "R0", "R1", "R2")


def test_chinese_translation_keeps_engine_tokens_separate():
    assert translate_text("Generation Quality", LANG_ZH) == "生成质量"
    assert translate_text("Timing: no compensation", LANG_ZH) == "时序：未启用补偿"
    assert translate_text("Generation Quality", LANG_EN) == "Generation Quality"
    assert _display_name("status_var") is True
    assert _display_name("axis_count_vars") is True
    assert _display_name("preset_var") is False
    assert _display_name("gesture_direction_var") is False


def test_calibration_dynamic_limits_feed_optimizer():
    profile = DeviceCalibrationProfile(
        axes={
            "L0": AxisCalibration(max_speed=123.0, max_acceleration=456.0, max_jerk=789.0),
            "R0": AxisCalibration(max_speed=222.0, max_acceleration=333.0, max_jerk=444.0),
        }
    )
    calibrated = optimizer_from_calibration(OptimizerConfig(), profile)
    assert calibrated.max_speed["L0"] == 123.0
    assert calibrated.max_acceleration["L0"] == 456.0
    assert calibrated.max_jerk["L0"] == 789.0
    assert calibrated.max_speed["R0"] == 222.0
    # Unspecified axes are normalized by DeviceCalibrationProfile defaults.
    assert calibrated.max_speed["L1"] > 0


def test_sr6_neutral_pose_and_trajectory_are_reachable():
    pose = {axis: 50.0 for axis in AXES}
    solution = solve_sr6_pose(pose)
    assert solution.reachable is True
    assert set(solution.servo_angles_rad) == {
        "lower_left", "upper_left", "left_pitch", "right_pitch", "upper_right", "lower_right"
    }
    plan = {axis: [(0.0, 50.0), (1.0, 50.0)] for axis in AXES}
    diagnostics = trajectory_kinematics_diagnostics(plan)
    assert diagnostics["samples"] == 2
    assert diagnostics["unreachable"] == 0
    assert diagnostics["unreachable_ratio"] == 0.0


def test_sr6_geometry_profile_round_trip(tmp_path):
    geometry = SR6Geometry(receiver_x_hundredths_mm=17000.0, main_y_hundredths_mm=1600.0)
    path = save_geometry_profile(tmp_path / "sr6-geometry.json", geometry)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "1.0"
    restored = load_geometry_profile(path)
    assert restored.receiver_x_hundredths_mm == 17000.0
    assert restored.main_y_hundredths_mm == 1600.0


def test_release_entry_modules_import_without_starting_gui():
    import dancer.cli_v26_release as cli_release
    import dancer.workstation_ui_v26_release as gui_release

    assert callable(cli_release.cmd)
    assert callable(gui_release.ux)
