"""Safety wrapper for GUI localization.

Only human-readable StringVars are translated.  Motion/control StringVars such
as preset, mode, axis, direction, file paths and serial settings stay in their
stable internal English/token form.
"""
from __future__ import annotations

from .i18n import I18nController


_DISPLAY_NAMES = {
    "status_var", "device_status_var", "intiface_status_var", "result_summary_var",
    "section_summary_var", "style_summary_var", "selection_var", "link_summary_var",
    "timeline_label_var", "intent_summary_var", "reference_library_var",
    "timing_summary_var", "calibration_summary_var", "effective_intent_summary_var",
    "cluster_summary_var", "sr6_summary_var", "sr6_pose_status_var",
}


def _display_name(name: str) -> bool:
    return (
        name in _DISPLAY_NAMES
        or name.endswith("_summary_var")
        or name.endswith("_status_var")
        or name.endswith("_label_var")
        or name in {"axis_count_vars"}
    )


class SafeI18nController(I18nController):
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
