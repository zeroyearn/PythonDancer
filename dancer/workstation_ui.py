"""Final PythonDancer 2.4 workstation entry window.

This thin layer keeps the interactive editor in ``multiaxis_ui_v3`` focused on
UI behavior and guarantees that every edited plan is re-constrained before it
is previewed, exported, or streamed to hardware.
"""
from __future__ import annotations

from threading import Thread
from tkinter import filedialog, messagebox

import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 - registers 3D projection for frozen builds

from .multiaxis import AXIS_CHANNELS, AXIS_ORDER
from .multiaxis_ui_v2 import ACCENT, MUTED, ROTATION, TRANSLATION
from .multiaxis_ui_v3 import MultiAxisWindow as _EditorWindow
from .tcode import SerialTCodeDevice, TCodePlaybackController, build_tcode_events, default_tcode_path, export_tcode_script
from .workspace_constraints import constrain_workspace_plan


class MultiAxisWindow(_EditorWindow):
    def _apply_workspace(self, redraw=True):
        if not self.workspace or self.base_plan is None:
            return
        self.plan = constrain_workspace_plan(self.workspace.output_plan(self.base_plan), self.generated_config)
        self.section_summary_var.set("Structure: " + " | ".join(
            f"{section.label}:{section.start:.1f}-{section.end:.1f}" for section in self.workspace.sections
        ))
        self.selection_var.set(self._selection_label())
        for axis in AXIS_ORDER:
            self.axis_count_vars[axis].set(f"{axis} · {AXIS_CHANNELS[axis]} · {len(self.plan.get(axis, ()))}")
        if redraw:
            self.work_timeline.set_model(self.workspace, self.data)
            self._redraw_workspace_preview()
            self._draw_pose(float(self.timeline_var.get()))

    def _redraw_workspace_preview(self):
        if not self.workspace or self.base_plan is None:
            return
        preview = {axis: list(self.plan.get(axis, ())) for axis in AXIS_ORDER}
        if self.workspace.solo_axis is not None:
            preview = {axis: actions if axis == self.workspace.solo_axis else [] for axis, actions in preview.items()}
        for axis in AXIS_ORDER:
            self.preview_axes[axis].clear()
        self._style_axes()
        for axis in AXIS_ORDER:
            actions = preview[axis]
            if actions:
                times = np.asarray([at for at, _ in actions], dtype=np.float64)
                positions = np.asarray([pos for _, pos in actions], dtype=np.float64)
                self.preview_axes[axis].plot(times, positions, linewidth=1.15, color=TRANSLATION if axis.startswith("L") else ROTATION)
            if self.workspace.axes[axis].muted:
                self.preview_axes[axis].text(.5, .5, "MUTED", transform=self.preview_axes[axis].transAxes, ha="center", va="center", color=MUTED, fontsize=10, fontweight="bold")
            elif self.workspace.axes[axis].locked:
                self.preview_axes[axis].text(.98, .08, "LOCK", transform=self.preview_axes[axis].transAxes, ha="right", color=MUTED, fontsize=7)
            for section in self.workspace.sections[1:]:
                self.preview_axes[axis].axvline(section.start, color=MUTED, linewidth=.6, alpha=.2)
            selection = self.workspace.selection.normalized(self.workspace.duration)
            if selection.duration > .001:
                self.preview_axes[axis].axvspan(selection.start, selection.end, color=ACCENT, alpha=.06)
        self.canvas.draw_idle()

    def _device_plan(self):
        return {axis: list(self.plan.get(axis, ())) for axis in AXIS_ORDER if self.plan.get(axis)}

    def export_tcode(self):
        if not self.plan or not self.source_path:
            return
        device_plan = self._device_plan()
        if not device_plan:
            messagebox.showwarning("PythonDancer", "All axes are muted; there is no TCode motion to export.")
            return
        selected = filedialog.asksaveasfilename(title="Export scheduled TCode script", defaultextension=".tcode", initialfile=default_tcode_path(self.source_path).name, filetypes=[("TCode script", "*.tcode"), ("All files", "*.*")])
        if not selected:
            return
        try:
            profile = self.device_profile if self.device_ranges_var.get() else None
            events = build_tcode_events(device_plan, profile=profile)
            path = export_tcode_script(selected, events, source=str(self.source_path))
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"TCode export failed:\n{exc}")
            return
        mapping = "D2 mapped" if profile and profile.axes else "full range"
        self.status_var.set(f"Exported {len(events)} scheduled TCode frames to {path.name} ({mapping})")

    def play_device(self):
        if not self.plan or (self.device_worker and self.device_worker.is_alive()):
            return
        device_plan = self._device_plan()
        if not device_plan:
            messagebox.showwarning("PythonDancer", "All axes are muted; there is no device motion to play.")
            return
        try:
            port, baud, speed = self._serial_settings()
        except Exception as exc:
            messagebox.showwarning("PythonDancer", str(exc))
            return
        timeout = float(self.args.serial_timeout)
        start_at = float(np.clip(self.timeline_var.get(), 0.0, self.duration))
        use_ranges = bool(self.device_ranges_var.get())
        seek_ramp_ms = int(self.args.seek_ramp_ms)
        self.play_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.device_status_var.set(f"Opening {port}…")
        self.status_var.set(f"Opening {port} @ {baud}...")

        def work():
            try:
                with SerialTCodeDevice(port, baud=baud, timeout=timeout) as device:
                    self.active_device = device
                    profile = device.profile()
                    self.device_profile = profile
                    controller = TCodePlaybackController(device_plan, device, speed=speed, profile=profile, use_device_ranges=use_ranges, seek_ramp_ms=seek_ramp_ms)
                    self.active_controller = controller
                    summary = self._profile_summary(profile)
                    self.after(0, lambda: self.status_var.set(f"Playing on {port} at {speed:g}x — {summary}"))
                    controller.play(start_at=start_at)
                self.after(0, self._device_done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._device_failed(e))
            finally:
                self.active_controller = None
                self.active_device = None

        self.device_worker = Thread(target=work, daemon=True)
        self.device_worker.start()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
