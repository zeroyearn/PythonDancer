"""Final PythonDancer 2.4 workstation entry window.

This thin layer keeps the interactive editor in ``multiaxis_ui_v3`` focused on
UI behavior and guarantees that every edited plan is re-constrained before it
is previewed, exported, or streamed to hardware.
"""
from __future__ import annotations

import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 - registers 3D projection for frozen builds

from .multiaxis import AXIS_CHANNELS, AXIS_ORDER
from .multiaxis_ui_v2 import ACCENT, MUTED, ROTATION, TRANSLATION
from .multiaxis_ui_v3 import MultiAxisWindow as _EditorWindow
from .workspace_constraints import constrain_workspace_plan


class MultiAxisWindow(_EditorWindow):
    def _apply_workspace(self, redraw=True):
        if not self.workspace or self.base_plan is None:
            return
        raw = self.workspace.output_plan(self.base_plan)
        self.plan = constrain_workspace_plan(raw, self.generated_config)
        self.section_summary_var.set(
            "Structure: " + " | ".join(
                f"{section.label}:{section.start:.1f}-{section.end:.1f}"
                for section in self.workspace.sections
            )
        )
        self.selection_var.set(self._selection_label())
        for axis in AXIS_ORDER:
            self.axis_count_vars[axis].set(
                f"{axis} · {AXIS_CHANNELS[axis]} · {len(self.plan.get(axis, ())) }"
            )
        if redraw:
            self.work_timeline.set_model(self.workspace, self.data)
            self._redraw_workspace_preview()
            self._draw_pose(float(self.timeline_var.get()))

    def _redraw_workspace_preview(self):
        if not self.workspace or self.base_plan is None:
            return
        # Preview the exact constrained output. Solo then acts only as a visual
        # filter and never mutates ``self.plan`` used by export/device playback.
        preview = {axis: list(self.plan.get(axis, ())) for axis in AXIS_ORDER}
        if self.workspace.solo_axis is not None:
            preview = {
                axis: actions if axis == self.workspace.solo_axis else []
                for axis, actions in preview.items()
            }

        for axis in AXIS_ORDER:
            self.preview_axes[axis].clear()
        self._style_axes()
        for axis in AXIS_ORDER:
            actions = preview[axis]
            if actions:
                times = np.asarray([at for at, _ in actions], dtype=np.float64)
                positions = np.asarray([pos for _, pos in actions], dtype=np.float64)
                self.preview_axes[axis].plot(
                    times,
                    positions,
                    linewidth=1.15,
                    color=TRANSLATION if axis.startswith("L") else ROTATION,
                )
            if self.workspace.axes[axis].muted:
                self.preview_axes[axis].text(
                    .5, .5, "MUTED",
                    transform=self.preview_axes[axis].transAxes,
                    ha="center", va="center", color=MUTED, fontsize=10, fontweight="bold",
                )
            elif self.workspace.axes[axis].locked:
                self.preview_axes[axis].text(
                    .98, .08, "LOCK",
                    transform=self.preview_axes[axis].transAxes,
                    ha="right", color=MUTED, fontsize=7,
                )
            for section in self.workspace.sections[1:]:
                self.preview_axes[axis].axvline(section.start, color=MUTED, linewidth=.6, alpha=.2)
            selection = self.workspace.selection.normalized(self.workspace.duration)
            if selection.duration > .001:
                self.preview_axes[axis].axvspan(selection.start, selection.end, color=ACCENT, alpha=.06)
        self.canvas.draw_idle()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
