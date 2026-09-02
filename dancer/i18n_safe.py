"""Safety wrapper for GUI localization.

Only human-readable StringVars are translated. Motion/control StringVars such
as preset, mode, axis, direction, file paths and serial settings stay in their
stable internal English/token form.
"""
from __future__ import annotations

from .i18n import I18nController, LANG_ZH


_DISPLAY_NAMES = {
    "status_var", "device_status_var", "intiface_status_var", "result_summary_var",
    "section_summary_var", "style_summary_var", "selection_var", "link_summary_var",
    "timeline_label_var", "intent_summary_var", "reference_library_var",
    "timing_summary_var", "calibration_summary_var", "effective_intent_summary_var",
    "cluster_summary_var", "sr6_summary_var", "sr6_pose_status_var",
}

_DYNAMIC_ZH = (
    ("SR6 diagnostics", "SR6 机械诊断"),
    ("SR6 pose", "SR6 姿态"),
    ("default firmware geometry", "默认固件几何参数"),
    ("loaded geometry", "已加载几何参数"),
    ("unreachable", "不可达"),
    ("Reachable", "可达"),
    ("Unreachable", "不可达"),
    ("max servo", "最大舵机角"),
    ("samples", "采样点"),
    ("not evaluated", "尚未评估"),
    ("reference bundle(s)", "个参考脚本包"),
    ("reference bundle", "参考脚本包"),
    ("audio-driven", "音频驱动"),
    ("manual = current inferred values", "手动值 = 当前推断值"),
    ("blend", "混合"),
    ("intensity", "强度"),
    ("aggression", "冲击性"),
    ("flow", "流动性"),
    ("complexity", "复杂度"),
    ("symmetry", "对称性"),
    ("rotation bias", "旋转偏好"),
    ("translation bias", "平移偏好"),
    ("accent density", "重音密度"),
    ("Generation Quality", "生成质量"),
    ("quality", "质量"),
)


def _display_name(name: str) -> bool:
    return (
        name in _DISPLAY_NAMES
        or name.endswith("_summary_var")
        or name.endswith("_status_var")
        or name.endswith("_label_var")
        or name in {"axis_count_vars"}
    )


class SafeI18nController(I18nController):
    def tr(self, text: object) -> str:
        result = super().tr(text)
        if self.language == LANG_ZH:
            for source, target in _DYNAMIC_ZH:
                result = result.replace(source, target)
        return result

    def bind_object(self, obj) -> None:
        import tkinter as tk
        seen: set[int] = set()

        def visit(value):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
            if isinstance(value, tk.StringVar):
                self._vars[identity] = value
                try:
                    current = str(value.get())
                except Exception:
                    return
                self._var_raw.setdefault(identity, current)
                self._var_rendered.setdefault(identity, current)
                return
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item)

        for name, value in getattr(obj, "__dict__", {}).items():
            if _display_name(str(name)):
                visit(value)
