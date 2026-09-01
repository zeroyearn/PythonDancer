"""Release entry layer for the PythonDancer 2.7 bilingual workstation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Event, Thread
from tkinter import messagebox, ttk

import numpy as np

from .candidates import CandidateResult, candidate_config_from_dict
from .comparison import best_section_merge, compare_plans
from .i18n_v27 import install_v27_translations
from .intent import INTENT_FIELDS
from .multiaxis import AXIS_ORDER
from .quality import score_plan
from .tcode import SerialTCodeDevice, TCodePlaybackController, encode_plan_frame
from .workstation_ui_v25_final import _FullHistory
from .workstation_ui_v27 import MultiAxisWindow as _QualityWindow


class _QualityHistory(_FullHistory):
    """2.7 history extends motion snapshots with generation/Intent state."""

    @staticmethod
    def capture(window):
        snapshot = _FullHistory.capture(window)
        snapshot["generated_config"] = deepcopy(getattr(window, "generated_config", None))
        snapshot["section_intent_overrides"] = deepcopy(getattr(window, "section_intent_overrides", {}))
        snapshot["improvement_history"] = deepcopy(getattr(window, "improvement_history", []))
        return snapshot


class MultiAxisWindow(_QualityWindow):
    def _build_ui(self):
        self.serial_prestart_cancel = Event()
        install_v27_translations()
        super()._build_ui()
        self.history = _QualityHistory(limit=100)
        self.title("PythonDancer 2.7 · Quality Intelligence Workstation")
        self.candidate_a_combo.bind("<<ComboboxSelected>>", self._candidate_selection_changed)
        self.candidate_b_combo.bind("<<ComboboxSelected>>", self._candidate_selection_changed)
        self._install_mechanical_apply_button()
        if self.i18n is not None:
            self.i18n.bind_object(self)
            self.i18n.refresh(force=True)
        self._refresh_quality_i18n()

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self.history = _QualityHistory(limit=100)

    def _install_mechanical_apply_button(self):
        stack = [self]
        target = None
        while stack:
            parent = stack.pop()
            for child in parent.winfo_children():
                stack.append(child)
                if isinstance(child, ttk.LabelFrame):
                    try:
                        text = str(child.cget("text"))
                    except Exception:
                        text = ""
                    if text in ("Mechanical projection / singularity", "机械投影 / 奇异性"):
                        target = child
                        break
            if target is not None:
                break
        if target is not None:
            ttk.Button(
                target,
                text="Apply mechanical policy",
                command=self.apply_mechanical_policy,
                style="Compact.TButton",
            ).grid(row=1, column=0, columnspan=8, sticky="ew", pady=(8, 0))

    def _busy_message(self, purpose: str) -> bool:
        main_busy = bool(self.worker and self.worker.is_alive())
        quality_busy = bool(self.quality_worker and self.quality_worker.is_alive())
        if main_busy or quality_busy:
            messagebox.showwarning(
                "PythonDancer",
                f"Finish the current generation/Quality Intelligence task before {purpose}.",
            )
            return True
        return False

    def generate(self):
        if self.quality_worker and self.quality_worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current Quality Intelligence task before generating a new track.")
            return
        if (self.device_worker and self.device_worker.is_alive()) or (self.intiface_worker and self.intiface_worker.is_alive()):
            messagebox.showwarning("PythonDancer", "Stop device playback before generating another track.")
            return
        return super().generate()

    def generate_quality_candidates(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before generating candidates.")
            return
        return super().generate_quality_candidates()

    def run_auto_improvement(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before Auto Improvement.")
            return
        return super().run_auto_improvement()

    def regenerate_intent_section(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before regenerating a section.")
            return
        return super().regenerate_intent_section()

    def open_project(self):
        if self._busy_message("opening another project"):
            return
        if (self.device_worker and self.device_worker.is_alive()) or (self.intiface_worker and self.intiface_worker.is_alive()):
            messagebox.showwarning("PythonDancer", "Stop device playback before opening another project.")
            return
        return super().open_project()

    def _timeline_edit_changed(self, committed=True):
        super()._timeline_edit_changed(committed=committed)
        if committed:
            self._refresh_section_intent_combo()
            self._sync_section_intent_ranges()
            if self.quality_report is not None:
                self.score_current()

    def _apply_section_label(self):
        super()._apply_section_label()
        self._refresh_section_intent_combo()
        self._sync_section_intent_ranges()

    def apply_section_intent(self):
        self._checkpoint()
        return super().apply_section_intent()

    def clear_section_intent(self):
        self._checkpoint()
        return super().clear_section_intent()

    def _sync_generation_controls(self, config):
        if config is None:
            return
        self.generated_config = config
        self.preset_var.set(config.preset)
        self.strength_var.set(float(config.strength))
        self.gesture_strength_var.set(float(config.gesture_strength))
        self.independent_axes_var.set(bool(config.independent.enabled))
        self.axis_density_var.set(float(config.independent.density))
        self.axis_threshold_var.set(float(config.independent.accent_threshold))
        self.motion_optimizer_var.set(bool(config.optimizer.enabled))
        self.pose_budget_var.set(float(config.optimizer.pose_budget))
        self.velocity_budget_var.set(float(config.optimizer.velocity_budget))
        self.optimizer_iterations_var.set(int(config.optimizer.iterations))
        self.intent_override_amount_var.set(float(config.independent.intent_override_amount))
        for field in INTENT_FIELDS:
            if field in config.independent.intent_override:
                self.manual_intent_vars[field].set(float(config.independent.intent_override[field]))
        mechanical = config.mechanical
        self.mechanical_projection_var.set(bool(mechanical.enabled))
        self.mechanical_max_risk_var.set(float(mechanical.max_risk))
        self.servo_limit_var.set(float(mechanical.servo_limit_deg))
        self.singularity_sensitivity_var.set(float(mechanical.sensitivity_limit_deg_per_unit))

    def _restore_snapshot(self, snapshot):
        super()._restore_snapshot(snapshot)
        config = deepcopy(snapshot.get("generated_config"))
        if config is not None:
            self._sync_generation_controls(config)
        self.section_intent_overrides = deepcopy(snapshot.get("section_intent_overrides", {}))
        self.improvement_history = deepcopy(snapshot.get("improvement_history", []))
        self._refresh_section_intent_combo()
        self._sync_section_intent_ranges()
        self._apply_workspace(redraw=True)
        self.score_current()
        if self.quality_candidates:
            self._refresh_candidate_scores(mark_changed=False)

    def _adopt_candidate_config(self, config):
        """Keep the visible controls and subsequent regeneration on the same candidate character."""
        config = replace(config, mechanical=self._mechanical_config(), geometry=self.sr6_geometry)
        self._sync_generation_controls(config)

    def _effective_candidate_plan(self, candidate):
        plan = {axis: list(candidate.plan.get(axis, ())) for axis in AXIS_ORDER}
        if self.workspace is not None and self.base_plan is not None:
            for axis in self.workspace.locked_axes():
                plan[axis] = list(self.base_plan.get(axis, ()))
        return plan

    def _rescore_candidate_list(self, candidates):
        if self.data is None:
            return list(candidates)
        mechanical = self._mechanical_config()
        sections = self._sections_payload()
        rescored = []
        for candidate in candidates:
            effective = self._effective_candidate_plan(candidate)
            quality = score_plan(
                effective,
                self.data,
                sections=sections,
                geometry=self.sr6_geometry,
                mechanical_config=mechanical,
            )
            config = replace(candidate.config, mechanical=mechanical, geometry=self.sr6_geometry)
            rescored.append(CandidateResult(candidate.name, config, candidate.plan, quality))
        rescored.sort(key=lambda item: (-item.quality.overall, item.name))
        return rescored

    def _refresh_candidate_scores(self, *, mark_changed=False):
        if not self.quality_candidates:
            return
        selected_a = self.candidate_a_var.get()
        selected_b = self.candidate_b_var.get()
        self.quality_candidates = self._rescore_candidate_list(self.quality_candidates)
        self._populate_candidate_tree()
        names = [item.name for item in self.quality_candidates]
        self.candidate_a_combo["values"] = names
        self.candidate_b_combo["values"] = names
        if names:
            self.candidate_a_var.set(selected_a if selected_a in names else names[0])
            self.candidate_b_var.set(selected_b if selected_b in names else names[min(1, len(names) - 1)])
            self.compare_ab()
        if mark_changed:
            self._mark_changed()

    def _candidates_done(self, results):
        super()._candidates_done(self._rescore_candidate_list(results))
        self._mark_changed()

    def _candidate_selection_changed(self, _event=None):
        self.compare_ab()
        self._mark_changed()

    def _candidate_tree_selected(self, event=None):
        super()._candidate_tree_selected(event)
        if self.quality_candidates:
            self._mark_changed()

    def _axis_controls_changed(self):
        before = self.workspace.locked_axes() if self.workspace else ()
        super()._axis_controls_changed()
        after = self.workspace.locked_axes() if self.workspace else ()
        if before != after and self.quality_candidates:
            self._refresh_candidate_scores(mark_changed=True)

    def compare_ab(self):
        a = self._candidate_by_name(self.candidate_a_var.get())
        b = self._candidate_by_name(self.candidate_b_var.get())
        if not a or not b:
            return
        report = compare_plans(
            self._effective_candidate_plan(a),
            self._effective_candidate_plan(b),
            self.data,
            geometry=self.sr6_geometry,
            mechanical_config=self._mechanical_config(),
        )
        strongest = max(report.metric_delta, key=lambda key: abs(report.metric_delta[key])) if report.metric_delta else ""
        from .workstation_ui_v27 import _METRIC_LABELS
        self.comparison_summary_var.set(
            f"A/B · B−A {report.score_delta:+.1f} · {_METRIC_LABELS.get(strongest, strongest)} {report.metric_delta.get(strongest, 0):+.1f}"
        )

    def preview_candidate(self, which):
        candidate = self._candidate_by_name(self.candidate_a_var.get() if which == "A" else self.candidate_b_var.get())
        if not candidate:
            return
        self.preview_candidate_plan = self._effective_candidate_plan(candidate)
        self.preview_candidate_name = candidate.name
        self._render_candidate_preview(self.preview_candidate_plan)
        self.status_var.set(f"Preview only · {candidate.name} · locked axes preserved · output remains unchanged")

    def use_candidate(self, which):
        candidate = self._candidate_by_name(self.candidate_a_var.get() if which == "A" else self.candidate_b_var.get())
        if candidate is None or not self.workspace:
            return
        self._checkpoint()
        self._adopt_candidate_config(candidate.config)
        self.base_plan = self._effective_candidate_plan(candidate)
        self.preview_candidate_plan = None
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.score_current()
        self.status_var.set(f"Applied candidate: {candidate.name} · locked axes preserved")

    def apply_mechanical_policy(self):
        try:
            mechanical = self._mechanical_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return
        self._checkpoint()
        if self.generated_config is not None:
            self.generated_config = replace(self.generated_config, mechanical=mechanical, geometry=self.sr6_geometry)
        self.score_current()
        self._refresh_candidate_scores(mark_changed=False)
        self._mark_changed()
        self.status_var.set("Mechanical policy applied · current plan and candidates rescored")

    def merge_best_sections(self):
        if len(self.quality_candidates) < 2 or not self.workspace:
            messagebox.showwarning("PythonDancer", "Generate at least two candidates first.")
            return
        try:
            merged, choices, scores = best_section_merge(
                self.quality_candidates,
                self.workspace.sections,
                self.data,
                geometry=self.sr6_geometry,
                mechanical_config=self._mechanical_config(),
                base_plan=self.base_plan,
                locked_axes=self.workspace.locked_axes(),
            )
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return
        self._checkpoint()
        self.base_plan = merged
        self.preview_candidate_plan = None
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.score_current()
        summary = []
        for index, section in enumerate(self.workspace.sections):
            selected = choices.get(index, 0)
            summary.append(f"{section.label}:{self.quality_candidates[selected].name}")
        self.comparison_summary_var.set("Best sections · " + " | ".join(summary))
        self.status_var.set("Merged highest-scoring candidate per section · current mechanical policy · locked axes preserved")

    def stop_device(self):
        self.serial_prestart_cancel.set()
        return super().stop_device()

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
        self.serial_prestart_cancel.clear()
        self.play_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.device_status_var.set(f"Opening {port}…")
        self.status_var.set(f"Opening {port} @ {baud}...")

        def work():
            try:
                cancelled = False
                with SerialTCodeDevice(port, baud=baud, timeout=timeout) as device:
                    self.active_device = device
                    profile = device.profile()
                    self.device_profile = profile
                    controller_profile = profile if use_ranges else None
                    cancelled = self.serial_prestart_cancel.is_set()
                    if not cancelled and soft_start_ms > 0 and start_at <= 1e-9:
                        device.stop()
                        command = encode_plan_frame(
                            device_plan,
                            0.0,
                            profile=controller_profile,
                            interval_ms=soft_start_ms,
                        )
                        if command and not self.serial_prestart_cancel.is_set():
                            device.send(command)
                            cancelled = self.serial_prestart_cancel.wait(soft_start_ms / 1000.0)
                    if self.serial_prestart_cancel.is_set():
                        cancelled = True
                    if not cancelled:
                        controller = TCodePlaybackController(
                            device_plan,
                            device,
                            speed=speed,
                            profile=profile,
                            use_device_ranges=use_ranges,
                            seek_ramp_ms=seek_ramp_ms,
                        )
                        self.active_controller = controller
                        if self.serial_prestart_cancel.is_set():
                            controller.stop()
                            cancelled = True
                        if not cancelled:
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

    def _load_project_document(self, project):
        super()._load_project_document(project)
        state = project.quality_intelligence or {}
        raw_candidates = list(state.get("candidates", []) or [])
        self.history = _QualityHistory(limit=100)
        if self.generated_config is None or not raw_candidates:
            return

        # Schema-3 files written before candidate config persistence still load:
        # their top-level preset/strength/gesture fields are used as a fallback.
        try:
            base = self._v27_config(self.generated_config)
        except Exception:
            base = self.generated_config
        restored = []
        for item in raw_candidates:
            quality = self._report_from_dict(item.get("quality"))
            if quality is None:
                continue
            plan = {
                axis: [(float(row[0]), float(row[1])) for row in (item.get("plan") or {}).get(axis, [])]
                for axis in AXIS_ORDER
            }
            config_payload = item.get("config") or {
                "preset": item.get("preset", base.preset),
                "strength": item.get("strength", base.strength),
                "gesture_strength": item.get("gesture_strength", base.gesture_strength),
            }
            try:
                candidate_config = candidate_config_from_dict(base, config_payload)
            except Exception:
                candidate_config = base
            restored.append(CandidateResult(str(item.get("name", "Candidate")), candidate_config, plan, quality))

        if not restored:
            return
        self.quality_candidates = self._rescore_candidate_list(restored)
        self._populate_candidate_tree()
        names = [item.name for item in self.quality_candidates]
        self.candidate_a_combo["values"] = names
        self.candidate_b_combo["values"] = names
        selected_a = state.get("candidate_a")
        selected_b = state.get("candidate_b")
        self.candidate_a_var.set(selected_a if selected_a in names else names[0])
        self.candidate_b_var.set(selected_b if selected_b in names else names[min(1, len(names) - 1)])
        self.compare_ab()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()