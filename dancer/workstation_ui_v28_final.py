"""Release-quality runtime integration for the PythonDancer 2.8 DAW."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Thread
from tkinter import messagebox, ttk

from .automation import AutomationSet, StyleMorphTimeline
from .candidate_composer import CandidateComposition
from .daw_transform import apply_daw_transform
from .device_twin import DeviceTwinProfile
from .generation_limits import optimizer_from_calibration
from .improvement import ImprovementConfig, auto_improve
from .workspace import copy_plan
from .workspace_constraints import constrain_workspace_plan
from .workstation_ui_v27_hotfix import _effective_output_snapshot
from .workstation_ui_v28 import MultiAxisWindow as _DAWWindow, _DAWHistory


class MultiAxisWindow(_DAWWindow):
    def _build_ui(self):
        import tkinter as tk
        self.twin_safe_var = tk.BooleanVar(value=True)
        self._loading_daw_project = False
        super()._build_ui()
        self.twin_safe_var.set(bool(self.device_twin.safe_mode))
        self._bind_twin_safe_checkbox()

    def _bind_twin_safe_checkbox(self):
        stack = [self]
        while stack:
            parent = stack.pop()
            for child in parent.winfo_children():
                stack.append(child)
                if isinstance(child, ttk.Checkbutton):
                    try:
                        if str(child.cget("text")) in ("Safe mode", "安全模式"):
                            child.configure(variable=self.twin_safe_var, command=self._toggle_twin_safe_mode)
                            return
                    except Exception:
                        pass

    # ---------- device twin ----------
    def _toggle_twin_safe_mode(self):
        self.device_twin = replace(self.device_twin, safe_mode=bool(self.twin_safe_var.get()))
        self.apply_device_twin(record=True)

    def apply_device_twin(self, *, record=True):
        record = bool(record) and not self._loading_daw_project
        if record:
            self._checkpoint()
        twin = self.device_twin
        self.twin_safe_var.set(bool(twin.safe_mode))
        self.sr6_geometry = twin.geometry
        self.calibration_profile = twin.calibration
        self.latency_ms_var.set(twin.timing.latency_ms)
        self.manual_offset_var.set(twin.timing.manual_offset_ms)
        self.mechanical_projection_var.set(twin.mechanical.enabled)
        self.mechanical_max_risk_var.set(twin.mechanical.max_risk)
        self.servo_limit_var.set(twin.mechanical.servo_limit_deg)
        self.singularity_sensitivity_var.set(twin.mechanical.sensitivity_limit_deg_per_unit)
        if self.generated_config is not None:
            self.generated_config = replace(
                self.generated_config,
                optimizer=optimizer_from_calibration(self.generated_config.optimizer, twin.calibration),
                mechanical=twin.mechanical,
                geometry=twin.geometry,
            )
        if self.workspace is not None and self.base_plan is not None:
            self._apply_workspace(redraw=True)
        if record:
            self._mark_changed()
            self.score_current()
        self.twin_summary_var.set(
            f"Device Twin · {twin.name} · {twin.device_type} · "
            f"safe {'on' if twin.safe_mode else 'off'} · latency {twin.timing.command_lead_ms:.1f} ms"
        )

    # ---------- DAW-aware Auto Improvement ----------
    def run_auto_improvement(self):
        if (
            not self.base_plan
            or self.data is None
            or self.generated_config is None
            or not self.workspace
            or (self.quality_worker and self.quality_worker.is_alive())
        ):
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before Auto Improvement.")
            return
        if self._live_running():
            messagebox.showwarning("PythonDancer", "Stop Live Choreography before Auto Improvement.")
            return
        try:
            improve = ImprovementConfig(
                max_iterations=int(self.improve_iterations_var.get()),
                target_score=float(self.improve_target_var.get()),
                minimum_improvement=float(self.improve_min_gain_var.get()),
                candidates=max(2, min(8, int(self.quality_candidate_count_var.get()))),
            )
            generation = self._v27_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return

        self.improvement_summary_var.set("Auto Improvement: scoring DAW effective output…")
        data = self.data
        base = copy_plan(self.base_plan)
        locked = tuple(self.workspace.locked_axes())
        sections = deepcopy(self._sections_payload())
        geometry = self.sr6_geometry
        workspace = deepcopy(self.workspace)
        curves = deepcopy(self.curve_settings)
        safety = deepcopy(self.safety_settings)
        automation = deepcopy(self.automation)
        styles = deepcopy(self.style_morph)
        context = self._motion_state_fingerprint()

        def score_transform(plan, scoring_config):
            output = _effective_output_snapshot(
                plan,
                scoring_config,
                base_plan=base,
                workspace=workspace,
                curve_settings=curves,
                safety_settings=safety,
                data=data,
            )
            output = apply_daw_transform(output, automation, styles)
            return constrain_workspace_plan(output, scoring_config)

        def work():
            try:
                result = auto_improve(
                    data,
                    base,
                    generation,
                    config=improve,
                    geometry=geometry,
                    sections=sections,
                    locked_axes=locked,
                    score_transform=score_transform,
                )
                self.after(0, lambda: self._improvement_done_guarded(context, result))
            except Exception as exc:
                self.after(0, lambda e=exc: self._quality_failed(e))

        self.quality_worker = Thread(target=work, daemon=True)
        self.quality_worker.start()

    # ---------- transport mutual exclusion ----------
    def _live_running(self):
        return bool(self.live_session and self.live_session.worker and self.live_session.worker.is_alive())

    def generate(self):
        if self._live_running():
            messagebox.showwarning("PythonDancer", "Stop Live Choreography before generating a track.")
            return
        return super().generate()

    def open_project(self):
        if self._live_running():
            messagebox.showwarning("PythonDancer", "Stop Live Choreography before opening another project.")
            return
        return super().open_project()

    def play_device(self):
        if self._live_running():
            messagebox.showwarning("PythonDancer", "Stop Live Choreography before starting timeline TCode playback.")
            return
        return super().play_device()

    def play_intiface(self):
        if self._live_running():
            messagebox.showwarning("PythonDancer", "Stop Live Choreography before starting Intiface playback.")
            return
        return super().play_intiface()

    def start_live(self):
        if (self.device_worker and self.device_worker.is_alive()) or (self.intiface_worker and self.intiface_worker.is_alive()):
            messagebox.showwarning("PythonDancer", "Stop timeline device playback before starting Live Choreography.")
            return
        return super().start_live()

    # ---------- persistence/history ----------
    def _load_project_document(self, project):
        self._loading_daw_project = True
        try:
            super()._load_project_document(project)
        finally:
            self._loading_daw_project = False
        self.history = _DAWHistory(limit=100)
        self.twin_safe_var.set(bool(self.device_twin.safe_mode))
        self._bind_twin_safe_checkbox()
        # A loaded project is a clean baseline, not a user edit.
        self.project_dirty = False

    def _restore_snapshot(self, snapshot):
        super()._restore_snapshot(snapshot)
        self.twin_safe_var.set(bool(self.device_twin.safe_mode))
        self._bind_twin_safe_checkbox()

    def _on_close(self):
        self.stop_live()
        return super()._on_close()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
