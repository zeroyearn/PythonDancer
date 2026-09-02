"""PythonDancer 2.6 generation-quality workstation UI.

Adds visible controls for Motion Intent, independent axis clocks, cross-axis
optimization, advanced gesture blocks, timing compensation and device
calibration on top of the validated 2.5 editing/safety workstation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Thread
from time import sleep
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .calibration import (
    DeviceCalibrationProfile,
    apply_calibration,
    calibration_test_plan,
    load_calibration_profile,
)
from .independent_planner import IndependentAxisConfig
from .intent import INTENT_FIELDS, infer_motion_intent
from .latency import DeviceTimingProfile, compensate_plan_latency, measure_query_latency
from .libfun import autoval, load_audio_data
from .multiaxis import AXIS_ORDER, MultiAxisConfig, analyze_multiaxis, plan_multiaxis
from .optimizer import OptimizerConfig, optimizer_diagnostics
from .reference_library import cluster_profiles, learn_profile_from_bundles
from .stems import enrich_with_stems
from .style import learn_profile_from_bundle, load_profile
from .tcode import SerialTCodeDevice, TCodePlaybackController, encode_plan_frame
from .workspace import GestureBlock, sample_axis
from .workstation_ui_v25_final import MultiAxisWindow as _V25Window
from .outputs import DEFAULT_INTIFACE_ADDRESS, play_plan_intiface_sync


class MultiAxisWindow(_V25Window):
    def _build_ui(self):
        # Generation-quality state must exist before inherited builders dispatch
        # to this class's card/tab overrides.
        self.independent_axes_var = tk.BooleanVar(value=bool(getattr(self.args, "independent_axes", True)))
        self.axis_density_var = tk.DoubleVar(value=float(getattr(self.args, "axis_density", 1.0)))
        self.axis_threshold_var = tk.DoubleVar(value=float(getattr(self.args, "axis_accent_threshold", .62)))
        self.motion_optimizer_var = tk.BooleanVar(value=bool(getattr(self.args, "motion_optimizer", True)))
        self.pose_budget_var = tk.DoubleVar(value=float(getattr(self.args, "pose_budget", 1.85)))
        self.velocity_budget_var = tk.DoubleVar(value=float(getattr(self.args, "velocity_budget", 2.25)))
        self.optimizer_iterations_var = tk.IntVar(value=int(getattr(self.args, "optimizer_iterations", 3)))
        self.intent_summary_var = tk.StringVar(value="Motion Intent: generate a track to analyze")
        self.intent_value_vars = {field: tk.StringVar(value="—") for field in INTENT_FIELDS}
        self.reference_library_paths: list[str] = list(getattr(self.args, "reference_library", None) or [])
        self.reference_library_var = tk.StringVar(value=self._reference_library_label())

        self.gesture_cycles_var = tk.DoubleVar(value=1.0)
        self.gesture_phase_var = tk.DoubleVar(value=0.0)
        self.gesture_direction_var = tk.StringVar(value="forward")
        self.gesture_blend_in_var = tk.DoubleVar(value=.12)
        self.gesture_blend_out_var = tk.DoubleVar(value=.12)
        self.gesture_axis_mix_vars = {axis: tk.DoubleVar(value=1.0) for axis in AXIS_ORDER}

        self.latency_ms_var = tk.DoubleVar(value=float(getattr(self.args, "latency_ms", 0.0)))
        self.manual_offset_var = tk.DoubleVar(value=float(getattr(self.args, "manual_offset_ms", 0.0)))
        self.measure_latency_var = tk.BooleanVar(value=bool(getattr(self.args, "measure_latency", False)))
        self.calibration_path_var = tk.StringVar(value=str(getattr(self.args, "calibration_profile", "") or ""))
        self.calibration_profile: DeviceCalibrationProfile | None = None
        self.timing_summary_var = tk.StringVar(value="Timing: no compensation")
        self.calibration_summary_var = tk.StringVar(value="Calibration: normalized 0–100")

        super()._build_ui()
        self.title("PythonDancer 2.6 · Generation Quality Workstation")
        if self.calibration_path_var.get().strip():
            self.after(10, lambda: self._load_calibration(self.calibration_path_var.get().strip(), silent=True))

    def _reference_library_label(self):
        if not getattr(self, "reference_library_paths", None):
            return "No reference library"
        return f"{len(self.reference_library_paths)} reference bundle(s)"

    # ---------- visible generation quality ----------
    def _build_axis_card(self, parent):
        super()._build_axis_card(parent)
        card, body = self._card(
            parent,
            "Generation Quality",
            "Independent stem-driven clocks feed a continuous Motion Intent layer before the 6D pose / velocity / jerk optimizer.",
        )
        card.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(body, text="Independent secondary-axis timelines", variable=self.independent_axes_var).grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(body, "Axis density", 1, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.axis_density_var, from_=.25, to=4., increment=.05, width=7).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._label(body, "Accent threshold", 2, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.axis_threshold_var, from_=0., to=1., increment=.02, width=7).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Checkbutton(body, text="6D pose / velocity / jerk optimizer", variable=self.motion_optimizer_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._label(body, "Pose budget", 4, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.pose_budget_var, from_=.3, to=4., increment=.05, width=7).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._label(body, "Velocity budget", 5, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.velocity_budget_var, from_=.3, to=5., increment=.05, width=7).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._label(body, "Optimizer passes", 6, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.optimizer_iterations_var, from_=1, to=8, increment=1, width=7).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(body, textvariable=self.intent_summary_var, style="Muted.TLabel", wraplength=270).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_intelligence_card(self, parent):
        super()._build_intelligence_card(parent)
        # Append multi-reference controls under the existing intelligence card
        # instead of creating another large sidebar block.
        cards = [child for child in parent.winfo_children() if int(child.grid_info().get("row", -1)) == 1]
        if not cards:
            return
        card = cards[-1]
        body_frames = [child for child in card.winfo_children() if isinstance(child, ttk.Frame)]
        if not body_frames:
            return
        body = body_frames[-1]
        row = ttk.Frame(body, style="Card.TFrame")
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, textvariable=self.reference_library_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(row, text="Reference library…", command=self.browse_reference_library, style="Compact.TButton").grid(row=0, column=1, padx=(6, 0))

    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        quality = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        quality.columnconfigure(0, weight=1)
        notebook.add(quality, text="Intent / Gesture")

        intent = ttk.LabelFrame(quality, text="Motion Intent", padding=10)
        intent.grid(row=0, column=0, sticky="ew")
        for index, field in enumerate(INTENT_FIELDS):
            row, col = divmod(index, 4)
            box = ttk.Frame(intent, style="Card.TFrame")
            box.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 12, 0), pady=(0 if row == 0 else 7, 0))
            ttk.Label(box, text=field.replace("_", " "), style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(box, textvariable=self.intent_value_vars[field], style="Metric.TLabel").grid(row=1, column=0, sticky="w")

        gesture = ttk.LabelFrame(quality, text="Selected / next gesture block", padding=10)
        gesture.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for col in range(6):
            gesture.columnconfigure(col, weight=1)
        ttk.Label(gesture, text="Cycles", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(gesture, textvariable=self.gesture_cycles_var, from_=.25, to=16., increment=.25, width=7).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(gesture, text="Phase", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Spinbox(gesture, textvariable=self.gesture_phase_var, from_=0., to=.99, increment=.05, width=7).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Label(gesture, text="Direction", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Combobox(gesture, textvariable=self.gesture_direction_var, values=("forward", "reverse"), state="readonly", width=8).grid(row=1, column=2, sticky="ew", padx=6)
        ttk.Label(gesture, text="Blend in", style="Muted.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Spinbox(gesture, textvariable=self.gesture_blend_in_var, from_=0., to=.5, increment=.02, width=7).grid(row=1, column=3, sticky="ew", padx=6)
        ttk.Label(gesture, text="Blend out", style="Muted.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(gesture, textvariable=self.gesture_blend_out_var, from_=0., to=.5, increment=.02, width=7).grid(row=1, column=4, sticky="ew", padx=6)
        ttk.Button(gesture, text="Apply selected", command=self._apply_advanced_gesture, style="Compact.TButton").grid(row=1, column=5, sticky="ew", padx=(6, 0))

        mixes = ttk.Frame(gesture, style="Card.TFrame")
        mixes.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        for col, axis in enumerate(AXIS_ORDER):
            mixes.columnconfigure(col, weight=1)
            ttk.Label(mixes, text=axis, style="Muted.TLabel").grid(row=0, column=col)
            ttk.Spinbox(mixes, textvariable=self.gesture_axis_mix_vars[axis], from_=-3., to=3., increment=.1, width=6).grid(row=1, column=col, sticky="ew", padx=(0 if col == 0 else 3, 0))

    def _build_export_card(self, parent):
        super()._build_export_card(parent)
        card, body = self._card(
            parent,
            "8 · Timing & calibration",
            "Live output can compensate transport/device latency and map normalized choreography into a saved device-safe envelope.",
        )
        card.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self._label(body, "Latency", 0)
        ttk.Spinbox(body, textvariable=self.latency_ms_var, from_=0., to=1000., increment=1., width=8).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(body, text="ms", style="Muted.TLabel").grid(row=0, column=2, padx=(4, 0))
        self._label(body, "Manual offset", 1, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.manual_offset_var, from_=-500., to=500., increment=1., width=8).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(body, text="ms", style="Muted.TLabel").grid(row=1, column=2, padx=(4, 0), pady=(8, 0))
        ttk.Checkbutton(body, text="Measure serial RTT before play", variable=self.measure_latency_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(body, textvariable=self.timing_summary_var, style="Muted.TLabel", wraplength=270).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        row = ttk.Frame(body, style="Card.TFrame"); row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(9, 0)); row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.calibration_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Load…", command=self.browse_calibration, style="Compact.TButton").grid(row=0, column=1, padx=(6, 0))
        ttk.Label(body, textvariable=self.calibration_summary_var, style="Muted.TLabel", wraplength=270).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(body, text="Safe axis test", command=self.run_calibration_test, style="Soft.TButton").grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    # ---------- profiles / generation ----------
    def browse_reference_library(self):
        paths = filedialog.askopenfilenames(title="Select reference L0 funscripts", filetypes=[("Funscript", "*.funscript"), ("All files", "*.*")])
        if not paths:
            return
        self.reference_library_paths = list(paths)
        self.reference_library_var.set(self._reference_library_label())
        self.reference_bundle_var.set("")
        self.profile_path_var.set("")

    def _quality_config(self):
        independent = IndependentAxisConfig(
            enabled=bool(self.independent_axes_var.get()),
            min_interval=max(float(self.args.min_interval), .02),
            density=float(self.axis_density_var.get()),
            accent_threshold=float(self.axis_threshold_var.get()),
        )
        optimizer = OptimizerConfig(
            enabled=bool(self.motion_optimizer_var.get()),
            pose_budget=float(self.pose_budget_var.get()),
            velocity_budget=float(self.velocity_budget_var.get()),
            iterations=int(self.optimizer_iterations_var.get()),
        )
        return independent, optimizer

    def generate(self):
        if self.worker and self.worker.is_alive():
            return
        raw_path = self.path_var.get().strip()
        if not raw_path:
            messagebox.showwarning("PythonDancer", "Choose a media file first.")
            return
        source = Path(raw_path)
        if not source.exists():
            messagebox.showerror("PythonDancer", f"File does not exist:\n{source}")
            return
        try:
            strength = float(self.strength_var.get()); gesture_strength = float(self.gesture_strength_var.get())
            beats_per_bar = int(self.beats_per_bar_var.get()); bars_per_phrase = int(self.bars_per_phrase_var.get()); section_bars = int(self.section_bars_var.get())
            independent, optimizer = self._quality_config()
            if strength < 0 or gesture_strength < 0 or min(beats_per_bar, bars_per_phrase, section_bars) <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("PythonDancer", "Generation Quality parameters are invalid.")
            return

        profile_path = self.profile_path_var.get().strip(); reference_bundle = self.reference_bundle_var.get().strip()
        source_count = int(bool(profile_path)) + int(bool(reference_bundle)) + int(bool(self.reference_library_paths))
        if source_count > 1:
            messagebox.showerror("PythonDancer", "Choose one style source: Profile, Reference bundle, or Reference library.")
            return
        preset = self.preset_var.get(); mode = self.mode_var.get(); subdivision = int(self.subdivision_var.get()); automap = bool(self.automap_var.get())
        stem_mode = self.stem_mode_var.get(); stem_dir = self.stem_dir_var.get().strip() or None
        if stem_dir and stem_mode == "off": stem_mode = "auto"
        self.source_path = source
        self.status_var.set("Analyzing stems, Motion Intent, independent axis clocks, and 6D optimization…")
        for button in (self.generate_button, self.export_button, self.tcode_export_button, self.play_button, self.save_profile_button): button.configure(state="disabled")

        def work():
            try:
                if self.reference_library_paths:
                    style_profile = learn_profile_from_bundles(self.reference_library_paths, name=self.args.profile_name or "GUI reference library")
                elif reference_bundle:
                    style_profile = learn_profile_from_bundle(reference_bundle, name=self.args.profile_name)
                elif profile_path:
                    style_profile = load_profile(profile_path)
                else:
                    style_profile = None
                data = load_audio_data(source, plp=not self.args.no_plp)
                if stem_mode != "off":
                    data = enrich_with_stems(data, source, mode=stem_mode, stem_dir=stem_dir, cache_dir=self.args.stem_cache, model=self.args.demucs_model)
                pitch = float(self.args.pitch); energy = float(self.args.energy)
                if automap:
                    pitch, energy = autoval(data, tpi=self.args.auto_pitch, target_speed=self.args.auto_speed, v2above=self.args.auto_per / 100., opt=self.args.auto_mod - 1, planner="adaptive")
                config = MultiAxisConfig(
                    motion=self._motion_config(pitch, energy, subdivision), preset=preset, strength=strength, mode=mode,
                    gesture_strength=gesture_strength, beats_per_bar=beats_per_bar, bars_per_phrase=bars_per_phrase, section_bars=section_bars,
                    profile=style_profile, independent=independent, optimizer=optimizer,
                )
                analysis = analyze_multiaxis(data, config)
                plan = plan_multiaxis(data, config)
                if not plan["L0"]: raise ValueError("No actions could be generated from this input")
                self.after(0, lambda: self._generation_done(data, plan, analysis, config, pitch, energy))
            except Exception as exc:
                self.after(0, lambda e=exc: self._generation_failed(e))
        self.worker = Thread(target=work, daemon=True); self.worker.start()

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        intent = infer_motion_intent(data, analysis)
        for field, value in intent.global_intent.to_dict().items(): self.intent_value_vars[field].set(f"{value:.2f}")
        diag = optimizer_diagnostics(plan)
        self.intent_summary_var.set(
            f"Intent: I {intent.global_intent.intensity:.2f} · Agg {intent.global_intent.aggression:.2f} · Flow {intent.global_intent.flow:.2f} · "
            f"6D load {diag['peak_pose_load']:.2f}"
        )
        self.result_summary_var.set(
            f"2.6 quality · {'independent axes' if config.independent.enabled else 'shared timeline'} · "
            f"optimizer {'on' if config.optimizer.enabled else 'off'} · {sum(len(plan[a]) for a in AXIS_ORDER)} keyframes"
        )

    # ---------- advanced gesture timeline ----------
    def _advanced_gesture_kwargs(self):
        return {
            "axis_mix": {axis: float(var.get()) for axis, var in self.gesture_axis_mix_vars.items()},
            "phase_offset": float(self.gesture_phase_var.get()),
            "cycles": float(self.gesture_cycles_var.get()),
            "direction": -1 if self.gesture_direction_var.get() == "reverse" else 1,
            "blend_in": float(self.gesture_blend_in_var.get()),
            "blend_out": float(self.gesture_blend_out_var.get()),
        }

    def _gesture_selected(self, index):
        super()._gesture_selected(index)
        if self.workspace and 0 <= index < len(self.workspace.gestures):
            block = self.workspace.gestures[index]
            self.gesture_cycles_var.set(block.cycles); self.gesture_phase_var.set(block.phase_offset)
            self.gesture_direction_var.set("reverse" if block.direction < 0 else "forward")
            self.gesture_blend_in_var.set(block.blend_in); self.gesture_blend_out_var.set(block.blend_out)
            for axis in AXIS_ORDER: self.gesture_axis_mix_vars[axis].set(block.axis_multiplier(axis))

    def _add_gesture(self):
        if not self.workspace: return
        sel = self.workspace.selection.normalized(self.workspace.duration)
        if sel.duration < .05:
            messagebox.showwarning("PythonDancer", "Drag a timeline range first."); return
        self._checkpoint()
        try:
            block = self.workspace.add_gesture(sel.start, sel.end, self.gesture_var.get(), float(self.gesture_block_strength_var.get()), **self._advanced_gesture_kwargs())
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self.selected_gesture_index = self.workspace.gestures.index(block); self.work_timeline.active_gesture = self.selected_gesture_index
        self._apply_workspace(redraw=True); self._mark_changed()

    def _apply_advanced_gesture(self):
        if not self.workspace or self.selected_gesture_index is None or not (0 <= self.selected_gesture_index < len(self.workspace.gestures)):
            messagebox.showwarning("PythonDancer", "Select a gesture block first."); return
        self._checkpoint()
        block = self.workspace.gestures[self.selected_gesture_index]
        try:
            block.strength = float(self.gesture_block_strength_var.get()); block.gesture = self.gesture_var.get()
            for key, value in self._advanced_gesture_kwargs().items(): setattr(block, key, value)
            block.__post_init__()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self._apply_workspace(redraw=True); self._mark_changed()

    # ---------- project compatibility ----------
    def _load_project_document(self, project):
        original_generation = deepcopy(project.generation or {})
        generation = deepcopy(original_generation)
        independent_data = generation.pop("independent", {}) or {}
        optimizer_data = generation.pop("optimizer", {}) or {}
        project.generation = generation
        try:
            super()._load_project_document(project)
        finally:
            project.generation = original_generation
        if self.generated_config is not None:
            independent = IndependentAxisConfig(**{key: value for key, value in independent_data.items() if key in IndependentAxisConfig.__dataclass_fields__}) if independent_data else IndependentAxisConfig()
            optimizer = OptimizerConfig(**{key: value for key, value in optimizer_data.items() if key in OptimizerConfig.__dataclass_fields__}) if optimizer_data else OptimizerConfig()
            self.generated_config = replace(self.generated_config, independent=independent, optimizer=optimizer)
            self.independent_axes_var.set(independent.enabled); self.axis_density_var.set(independent.density); self.axis_threshold_var.set(independent.accent_threshold)
            self.motion_optimizer_var.set(optimizer.enabled); self.pose_budget_var.set(optimizer.pose_budget); self.velocity_budget_var.set(optimizer.velocity_budget); self.optimizer_iterations_var.set(optimizer.iterations)
        device = project.device or {}
        self.latency_ms_var.set(float(device.get("latency_ms", 0.0))); self.manual_offset_var.set(float(device.get("manual_offset_ms", 0.0)))
        calibration_path = str(device.get("calibration_profile", "") or "")
        self.calibration_path_var.set(calibration_path)
        if calibration_path: self._load_calibration(calibration_path, silent=True)

    def _project_document(self):
        project = super()._project_document()
        project.device.update({
            "latency_ms": float(self.latency_ms_var.get()),
            "manual_offset_ms": float(self.manual_offset_var.get()),
            "measure_latency": bool(self.measure_latency_var.get()),
            "calibration_profile": self.calibration_path_var.get().strip(),
        })
        project.ui["reference_library"] = list(self.reference_library_paths)
        return project

    # ---------- calibration / latency ----------
    def browse_calibration(self):
        path = filedialog.askopenfilename(title="Open device calibration profile", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path: self._load_calibration(path)

    def _load_calibration(self, path: str, *, silent=False):
        try:
            profile = load_calibration_profile(path)
        except Exception as exc:
            if not silent: messagebox.showerror("PythonDancer", f"Calibration load failed:\n{exc}")
            return False
        self.calibration_profile = profile; self.calibration_path_var.set(path)
        self.calibration_summary_var.set(f"Calibration: {profile.name} · latency {profile.latency_ms:.1f} ms")
        return True

    def _timing_profile(self, measured_ms: float = 0.0, jitter_ms: float = 0.0, transport="serial"):
        calibration_latency = self.calibration_profile.latency_ms if self.calibration_profile else 0.0
        timing = DeviceTimingProfile(
            transport=transport,
            latency_ms=float(self.latency_ms_var.get()) + float(calibration_latency) + float(measured_ms),
            jitter_ms=float(jitter_ms), manual_offset_ms=float(self.manual_offset_var.get()),
        )
        self.timing_summary_var.set(f"Timing: lead {timing.command_lead_ms:.1f} ms · jitter {timing.jitter_ms:.1f} ms")
        return timing

    def _live_plan(self, transport="serial", measured_ms=0.0, jitter_ms=0.0):
        plan = self._device_plan()
        plan = apply_calibration(plan, self.calibration_profile)
        return compensate_plan_latency(plan, self._timing_profile(measured_ms, jitter_ms, transport=transport))

    def _pose_values(self, at: float):
        values = {axis: sample_axis((self.plan or self.base_plan or {}).get(axis, ()), at, 50.) for axis in AXIS_ORDER}
        if self.calibration_profile:
            values = {axis: self.calibration_profile.axes[axis].map_normalized(value) for axis, value in values.items()}
        return values

    def play_device(self):
        if not self.plan or (self.device_worker and self.device_worker.is_alive()): return
        if not self._sync_transport_safety(record=False): return
        try: port, baud, speed = self._serial_settings()
        except Exception as exc: messagebox.showwarning("PythonDancer", str(exc)); return
        timeout=float(self.args.serial_timeout); start_at=float(np.clip(self.timeline_var.get(),0.,self.duration)); use_ranges=bool(self.device_ranges_var.get())
        soft_start_ms=int(self.safety_settings.soft_start_ms); seek_ramp_ms=max(int(self.args.seek_ramp_ms),soft_start_ms)
        self.play_button.configure(state="disabled"); self.pause_button.configure(state="normal"); self.resume_button.configure(state="normal"); self.stop_button.configure(state="normal")
        self.device_status_var.set(f"Opening {port}…")
        def work():
            try:
                with SerialTCodeDevice(port, baud=baud, timeout=timeout) as device:
                    self.active_device=device; profile=device.profile(); self.device_profile=profile
                    measured_ms=jitter=0.
                    if self.measure_latency_var.get():
                        timing_measure=measure_query_latency(device); measured_ms=timing_measure.latency_ms; jitter=timing_measure.jitter_ms
                    device_plan=self._live_plan("serial", measured_ms, jitter)
                    controller_profile=profile if use_ranges else None
                    if soft_start_ms>0 and start_at<=1e-9:
                        device.stop(); command=encode_plan_frame(device_plan,0.,profile=controller_profile,interval_ms=soft_start_ms)
                        if command: device.send(command); sleep(soft_start_ms/1000.)
                    controller=TCodePlaybackController(device_plan,device,speed=speed,profile=profile,use_device_ranges=use_ranges,seek_ramp_ms=seek_ramp_ms)
                    self.active_controller=controller; controller.play(start_at=start_at); device.stop()
                self.after(0,self._device_done)
            except Exception as exc: self.after(0,lambda e=exc:self._device_failed(e))
            finally: self.active_controller=None; self.active_device=None
        self.device_worker=Thread(target=work,daemon=True); self.device_worker.start()

    def play_intiface(self):
        if not self.plan or (self.intiface_worker and self.intiface_worker.is_alive()): return
        if not self._sync_transport_safety(record=False): return
        address=self.intiface_address_var.get().strip() or DEFAULT_INTIFACE_ADDRESS; selected=self.intiface_device_var.get().strip(); index=None
        if selected:
            try: index=int(selected.split("·",1)[0].strip())
            except ValueError: pass
        self.intiface_stop.clear(); plan=self._live_plan("intiface"); start_at=float(self.timeline_var.get()); speed=float(self.play_speed_var.get()); soft_start_ms=int(self.safety_settings.soft_start_ms)
        self.intiface_status_var.set("Playing…")
        def work():
            try: play_plan_intiface_sync(plan,address=address,device_index=index,speed=speed,stop_event=self.intiface_stop,start_at=start_at,soft_start_ms=soft_start_ms)
            except Exception as exc: self.after(0,lambda e=exc:self.intiface_status_var.set(f"Playback failed: {e}")); return
            self.after(0,lambda:self.intiface_status_var.set("Ready"))
        self.intiface_worker=Thread(target=work,daemon=True); self.intiface_worker.start()

    def run_calibration_test(self):
        if self.device_worker and self.device_worker.is_alive(): return
        if self.calibration_profile is None:
            self.calibration_profile = DeviceCalibrationProfile(name="Safe default")
            self.calibration_summary_var.set("Calibration: Safe default · 5% verification excursion")
        try: port, baud, speed = self._serial_settings()
        except Exception as exc: messagebox.showwarning("PythonDancer", str(exc)); return
        plan=calibration_test_plan(self.calibration_profile,excursion=5.); timeout=float(self.args.serial_timeout)
        if not messagebox.askokcancel("PythonDancer", "Run a slow one-axis-at-a-time ±5% verification sequence? Keep access to STOP/emergency power."): return
        def work():
            try:
                with SerialTCodeDevice(port,baud=baud,timeout=timeout) as device:
                    self.active_device=device; profile=device.profile(); controller=TCodePlaybackController(plan,device,speed=min(speed,1.),profile=profile,use_device_ranges=bool(self.device_ranges_var.get()),seek_ramp_ms=max(350,int(self.args.seek_ramp_ms)))
                    self.active_controller=controller; controller.play(); device.stop()
                self.after(0,lambda:self.status_var.set("Safe calibration verification complete."))
            except Exception as exc: self.after(0,lambda e=exc:self._device_failed(e))
            finally: self.active_controller=None; self.active_device=None
        self.device_worker=Thread(target=work,daemon=True); self.device_worker.start()

    def _export_metadata(self):
        metadata=super()._export_metadata()
        if self.generated_config and self.data is not None:
            intent=infer_motion_intent(self.data,self.analysis)
            choreography=dict(metadata.get("choreography") or {})
            choreography.update({
                "intent": intent.to_dict(),
                "independent_axes": {"enabled":self.generated_config.independent.enabled,"density":self.generated_config.independent.density,"accent_threshold":self.generated_config.independent.accent_threshold},
                "optimizer": self.generated_config.optimizer.to_dict(),
            })
            metadata["choreography"]=choreography
            metadata["device_timing"]={"latency_ms":float(self.latency_ms_var.get()),"manual_offset_ms":float(self.manual_offset_var.get())}
            if self.calibration_profile: metadata["device_calibration"]=self.calibration_profile.to_dict()
            metadata["notes"]=str(metadata.get("notes",""))+"; generation=2.6-independent-intent-optimizer"
        return metadata


def ux(args):
    app=MultiAxisWindow(args); app.mainloop()
