"""Final PythonDancer 2.5 workstation layer.

Completes transport safety, full Axis Link controls, and full-session Undo/Redo
on top of the 2.5 editing UI without duplicating generation or diagnostics.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Thread
from time import sleep
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from .editing import CurveSettings
from .multiaxis import AXIS_ORDER
from .outputs import DEFAULT_INTIFACE_ADDRESS, play_plan_intiface_sync
from .safety import AxisLink, SafetySettings
from .style import ChoreographyProfile
from .tcode import SerialTCodeDevice, TCodePlaybackController, encode_plan_frame
from .workspace import copy_plan
from .workstation_ui_v25 import MultiAxisWindow as _EditingSafetyWindow


class _FullHistory:
    """Bounded snapshots of all user-editable motion state."""

    def __init__(self, limit: int = 100):
        self.limit = max(2, int(limit))
        self.undo_items = []
        self.redo_items = []

    @staticmethod
    def capture(window):
        return {
            "base_plan": copy_plan(window.base_plan),
            "workspace": deepcopy(window.workspace),
            "curve_settings": deepcopy(window.curve_settings),
            "safety_settings": deepcopy(window.safety_settings),
        }

    def push(self, window):
        if window.base_plan is None or window.workspace is None:
            return
        snapshot = self.capture(window)
        if self.undo_items and self.undo_items[-1] == snapshot:
            return
        self.undo_items.append(snapshot)
        if len(self.undo_items) > self.limit:
            del self.undo_items[0]
        self.redo_items.clear()

    def undo(self, window):
        if not self.undo_items:
            return None
        self.redo_items.append(self.capture(window))
        return self.undo_items.pop()

    def redo(self, window):
        if not self.redo_items:
            return None
        self.undo_items.append(self.capture(window))
        return self.redo_items.pop()


class MultiAxisWindow(_EditingSafetyWindow):
    def _build_ui(self):
        # These variables are needed while the inherited UI is constructing the
        # Safety & motion shaping card and calling our _build_axis_card override.
        self.link_smoothing_var = tk.DoubleVar(value=.2)
        self.link_mode_var = tk.StringVar(value="position")
        self.link_only_empty_var = tk.BooleanVar(value=False)
        super()._build_ui()
        self.history = _FullHistory(limit=100)

    def _build_axis_card(self, parent):
        super()._build_axis_card(parent)
        cards = [child for child in parent.winfo_children() if int(child.grid_info().get("row", -1)) == 3]
        if not cards:
            return
        card = cards[-1]
        frames = [child for child in card.winfo_children() if isinstance(child, ttk.Frame)]
        if not frames:
            return
        body = frames[-1]
        self._label(body, "Link delay", 9, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.link_delay_var, from_=-2000, to=2000, increment=10, width=7).grid(
            row=9, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        self._label(body, "Link smoothing", 10, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.link_smoothing_var, from_=0, to=1, increment=.05, width=7).grid(
            row=10, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        self._label(body, "Link mode", 11, pady=(8, 0))
        ttk.Combobox(body, textvariable=self.link_mode_var, values=("position", "velocity"), state="readonly", width=9).grid(
            row=11, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        ttk.Checkbutton(body, text="Only generate when target is empty", variable=self.link_only_empty_var).grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

    def _build_export_card(self, parent):
        super()._build_export_card(parent)
        card, body = self._card(
            parent,
            "7 · Playback safety",
            "Soft Start enters the selected start pose before playback. Auto Home returns naturally completed motion to neutral.",
        )
        card.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self._label(body, "Soft start", 0)
        ttk.Spinbox(body, textvariable=self.soft_start_var, from_=0, to=5000, increment=50, width=8).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        ttk.Label(body, text="ms", style="Muted.TLabel").grid(row=0, column=2, padx=(4, 0))
        ttk.Checkbutton(body, text="Auto Home after natural finish", variable=self.auto_home_var, command=self._transport_safety_changed).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        self._label(body, "Home ramp", 2, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.home_ms_var, from_=50, to=5000, increment=50, width=8).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        ttk.Label(body, text="ms", style="Muted.TLabel").grid(row=2, column=2, padx=(4, 0), pady=(8, 0))
        ttk.Button(body, text="Apply safety timing", command=self._transport_safety_changed, style="Compact.TButton").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(9, 0)
        )

    # ---------- complete undo/redo ----------
    def _checkpoint(self):
        if hasattr(self, "history"):
            self.history.push(self)

    def _restore_snapshot(self, snapshot):
        self.base_plan = copy_plan(snapshot["base_plan"])
        self.workspace = deepcopy(snapshot["workspace"])
        self.curve_settings = deepcopy(snapshot["curve_settings"])
        self.safety_settings = deepcopy(snapshot["safety_settings"])
        self._sync_axis_controls_from_workspace()
        self._sync_safety_vars()
        axis = self.curve_axis_var.get()
        settings = self.curve_settings.get(axis, CurveSettings())
        self.curve_method_var.set(settings.interpolation)
        self.curve_snap_var.set(settings.snap_to_beat)
        self.curve_quantize_var.set(settings.quantize_mode)
        self._apply_workspace(redraw=True)

    def undo(self):
        if self.workspace is None or self.base_plan is None:
            return
        snapshot = self.history.undo(self)
        if snapshot is None:
            self.status_var.set("Nothing to undo")
            return
        self._restore_snapshot(snapshot)
        self._mark_changed()
        self.status_var.set("Undo")

    def redo(self):
        if self.workspace is None or self.base_plan is None:
            return
        snapshot = self.history.redo(self)
        if snapshot is None:
            self.status_var.set("Nothing to redo")
            return
        self._restore_snapshot(snapshot)
        self._mark_changed()
        self.status_var.set("Redo")

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self.history = _FullHistory(limit=100)

    # ---------- complete safety editing ----------
    def _safety_changed(self):
        self._checkpoint()
        super()._safety_changed()

    def _add_axis_link(self):
        if self.workspace is None or self.base_plan is None:
            return
        self._checkpoint()
        try:
            link = AxisLink(
                self.link_source_var.get(),
                self.link_target_var.get(),
                gain=float(self.link_gain_var.get()),
                delay_ms=float(self.link_delay_var.get()),
                smoothing=float(self.link_smoothing_var.get()),
                mode=self.link_mode_var.get(),
                only_if_empty=bool(self.link_only_empty_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return
        self.safety_settings.links.append(link)
        self._update_link_summary()
        self._apply_workspace(redraw=True)
        self._mark_changed()

    def _remove_axis_link(self):
        if not self.safety_settings.links:
            return
        self._checkpoint()
        self.safety_settings.links.pop()
        self._update_link_summary()
        self._apply_workspace(redraw=True)
        self._mark_changed()

    # ---------- project restoration ----------
    def _load_project_document(self, project):
        profile_payload = (project.generation or {}).get("profile")
        super()._load_project_document(project)
        if profile_payload and self.generated_config is not None:
            try:
                profile = ChoreographyProfile.from_dict(profile_payload)
                self.generated_config = replace(self.generated_config, profile=profile)
            except Exception:
                pass
        device = project.device or {}
        if device.get("intiface_address"):
            self.intiface_address_var.set(str(device["intiface_address"]))
        if device.get("serial_port"):
            self.port_var.set(str(device["serial_port"]))
        if device.get("baud"):
            try:
                self.baud_var.set(int(device["baud"]))
            except (TypeError, ValueError):
                pass
        if self.safety_settings.links:
            latest = self.safety_settings.links[-1]
            self.link_delay_var.set(latest.delay_ms)
            self.link_smoothing_var.set(latest.smoothing)
            self.link_mode_var.set(latest.mode)
            self.link_only_empty_var.set(latest.only_if_empty)
        self.history = _FullHistory(limit=100)
        self._apply_workspace(redraw=True)

    # ---------- transport safety ----------
    def _sync_transport_safety(self, *, record: bool):
        if record:
            self._checkpoint()
        try:
            soft_start = int(self.soft_start_var.get())
            home_ms = int(self.home_ms_var.get())
            if soft_start < 0 or home_ms < 50:
                raise ValueError("Soft Start must be >= 0 ms and Home ramp must be >= 50 ms")
            self.safety_settings.soft_start_ms = soft_start
            self.safety_settings.auto_home = bool(self.auto_home_var.get())
            self.safety_settings.home_ms = home_ms
            self.safety_settings.__post_init__()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return False
        if record:
            self._mark_changed()
            self.status_var.set(
                f"Playback safety: soft start {soft_start} ms · auto home {'on' if self.safety_settings.auto_home else 'off'}"
            )
        return True

    def _transport_safety_changed(self):
        self._sync_transport_safety(record=True)

    def play_device(self):
        if not self.plan or (self.device_worker and self.device_worker.is_alive()):
            return
        if not self._sync_transport_safety(record=False):
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
        soft_start_ms = int(self.safety_settings.soft_start_ms)
        seek_ramp_ms = max(int(self.args.seek_ramp_ms), soft_start_ms)
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
                    controller_profile = profile if use_ranges else None
                    if soft_start_ms > 0 and start_at <= 1e-9:
                        device.stop()
                        command = encode_plan_frame(
                            device_plan,
                            0.0,
                            profile=controller_profile,
                            interval_ms=soft_start_ms,
                        )
                        if command:
                            device.send(command)
                            sleep(soft_start_ms / 1000.0)
                    controller = TCodePlaybackController(
                        device_plan,
                        device,
                        speed=speed,
                        profile=profile,
                        use_device_ranges=use_ranges,
                        seek_ramp_ms=seek_ramp_ms,
                    )
                    self.active_controller = controller
                    summary = self._profile_summary(profile)
                    self.after(0, lambda: self.status_var.set(
                        f"Playing on {port} at {speed:g}x — {summary} · soft start {soft_start_ms} ms"
                    ))
                    controller.play(start_at=start_at)
                    device.stop()
                self.after(0, self._device_done)
            except Exception as exc:
                try:
                    if self.active_device is not None:
                        self.active_device.stop()
                except Exception:
                    pass
                self.after(0, lambda e=exc: self._device_failed(e))
            finally:
                self.active_controller = None
                self.active_device = None

        self.device_worker = Thread(target=work, daemon=True)
        self.device_worker.start()

    def play_intiface(self):
        if not self.plan or (self.intiface_worker and self.intiface_worker.is_alive()):
            return
        if not self._sync_transport_safety(record=False):
            return
        address = self.intiface_address_var.get().strip() or DEFAULT_INTIFACE_ADDRESS
        selected = self.intiface_device_var.get().strip()
        index = None
        if selected:
            try:
                index = int(selected.split("·", 1)[0].strip())
            except ValueError:
                pass
        self.intiface_stop.clear()
        plan = self._device_plan()
        start_at = float(self.timeline_var.get())
        speed = float(self.play_speed_var.get())
        soft_start_ms = int(self.safety_settings.soft_start_ms)
        self.intiface_status_var.set("Playing…")

        def work():
            try:
                play_plan_intiface_sync(
                    plan,
                    address=address,
                    device_index=index,
                    speed=speed,
                    stop_event=self.intiface_stop,
                    start_at=start_at,
                    soft_start_ms=soft_start_ms,
                )
            except Exception as exc:
                self.after(0, lambda: self.intiface_status_var.set(f"Playback failed: {exc}"))
                return
            self.after(0, lambda: self.intiface_status_var.set("Ready"))

        self.intiface_worker = Thread(target=work, daemon=True)
        self.intiface_worker.start()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
