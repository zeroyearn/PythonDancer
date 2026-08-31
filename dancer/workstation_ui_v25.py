"""PythonDancer 2.5 editing and safety workstation UI."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread
from time import sleep
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .editing import (
    CurveSettings,
    INTERPOLATIONS,
    delete_keyframes,
    flatten_range,
    insert_keyframe,
    move_keyframe,
    nearest_beat,
    quantize_actions,
    resample_curve,
    smooth_range,
    transform_range,
)
from .motion import MotionConfig
from .multiaxis import AXIS_CHANNELS, AXIS_ORDER, MultiAxisConfig
from .multiaxis_ui_v2 import ACCENT, BORDER, CARD, MUTED, PLOT_BG, TEXT
from .outputs import DEFAULT_INTIFACE_ADDRESS, discover_intiface_devices_sync, play_plan_intiface_sync
from .project import ProjectDocument, UndoStack, autosave_project, load_project, save_project
from .safety import (
    AxisLink,
    SafetySettings,
    SMART_LIMIT_PRESETS,
    add_auto_home,
    apply_axis_links,
    apply_smart_limits,
    fill_motion_gaps,
    motion_heatmap,
    risk_heatmap,
)
from .tcode import SerialTCodeDevice, TCodePlaybackController, encode_axis
from .workspace import copy_plan
from .workspace_constraints import constrain_workspace_plan
from .workstation_ui import MultiAxisWindow as _V24Window


class MultiAxisWindow(_V24Window):
    def _build_ui(self):
        # 2.5 state must exist before the inherited builders call our overrides.
        self.curve_axis_var = tk.StringVar(value="L0")
        self.curve_method_var = tk.StringVar(value="linear")
        self.curve_snap_var = tk.BooleanVar(value=True)
        self.curve_quantize_var = tk.StringVar(value="nearest")
        self.curve_scale_var = tk.DoubleVar(value=1.0)
        self.curve_offset_var = tk.DoubleVar(value=0.0)
        self.curve_settings = {axis: CurveSettings() for axis in AXIS_ORDER}
        self.selected_keyframe: int | None = None
        self._dragging_keyframe = False

        self.smart_limit_var = tk.BooleanVar(value=True)
        self.smart_profile_var = tk.StringVar(value="balanced")
        self.gap_fill_var = tk.StringVar(value="none")
        self.gap_threshold_var = tk.DoubleVar(value=1.75)
        self.soft_start_var = tk.IntVar(value=750)
        self.auto_home_var = tk.BooleanVar(value=True)
        self.home_ms_var = tk.IntVar(value=700)
        self.link_source_var = tk.StringVar(value="L2")
        self.link_target_var = tk.StringVar(value="R1")
        self.link_gain_var = tk.DoubleVar(value=-0.35)
        self.link_delay_var = tk.DoubleVar(value=0.0)
        self.link_summary_var = tk.StringVar(value="No axis links")
        self.safety_settings = SafetySettings(gap_fill="none")

        self.history = UndoStack(limit=100)
        self.project_path: Path | None = None
        self.project_dirty = False
        self._timeline_drag_checkpointed = False

        self.intiface_address_var = tk.StringVar(value=DEFAULT_INTIFACE_ADDRESS)
        self.intiface_device_var = tk.StringVar(value="")
        self.intiface_status_var = tk.StringVar(value="Not connected")
        self.intiface_devices = []
        self.intiface_worker: Thread | None = None
        self.intiface_stop = Event()

        super()._build_ui()
        self.title("PythonDancer 2.5 · Editing & Safety Workstation")
        self._build_app_menu()

    # ---------- layout additions ----------
    def _build_app_menu(self):
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open project…", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Save project", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="Save project as…", command=self.save_project_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Autosave now", command=self.autosave_now)
        menu.add_cascade(label="File", menu=file_menu)
        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        menu.add_cascade(label="Edit", menu=edit_menu)
        self.configure(menu=menu)
        self.bind_all("<Control-o>", lambda _e: self.open_project())
        self.bind_all("<Control-s>", lambda _e: self.save_project())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_project_as())
        self.bind_all("<Control-z>", lambda _e: self.undo())
        self.bind_all("<Control-y>", lambda _e: self.redo())

    def _new_child(self, parent, before):
        created = [child for child in parent.winfo_children() if child not in before]
        return created[-1] if created else None

    def _build_axis_card(self, parent):
        super()._build_axis_card(parent)
        card, body = self._card(parent, "Safety & motion shaping", "Smart limits constrain coupled poses. Gap fill and axis links are applied before the final physical constraint pass.")
        card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(body, text="Smart cross-axis limits", variable=self.smart_limit_var, command=self._safety_changed).grid(row=0, column=0, columnspan=2, sticky="w")
        self._label(body, "Envelope", 1, pady=(8, 0))
        ttk.Combobox(body, textvariable=self.smart_profile_var, values=tuple(SMART_LIMIT_PRESETS), state="readonly", width=11).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._label(body, "Gap filling", 2, pady=(8, 0))
        ttk.Combobox(body, textvariable=self.gap_fill_var, values=("none", "ambient", "beat", "repeat"), state="readonly", width=11).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self._label(body, "Gap threshold", 3, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.gap_threshold_var, from_=.5, to=10., increment=.25, width=7).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Button(body, text="Apply shaping", command=self._safety_changed, style="Compact.TButton").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        ttk.Label(body, text="Axis link", style="Metric.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 4))
        row = ttk.Frame(body, style="Card.TFrame"); row.grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Combobox(row, textvariable=self.link_source_var, values=AXIS_ORDER, state="readonly", width=5).grid(row=0, column=0)
        ttk.Label(row, text="→", style="Muted.TLabel").grid(row=0, column=1, padx=4)
        ttk.Combobox(row, textvariable=self.link_target_var, values=AXIS_ORDER, state="readonly", width=5).grid(row=0, column=2)
        ttk.Spinbox(row, textvariable=self.link_gain_var, from_=-2., to=2., increment=.05, width=6).grid(row=0, column=3, padx=(7, 0))
        ttk.Button(row, text="Add", command=self._add_axis_link, style="Compact.TButton").grid(row=0, column=4, padx=(6, 0))
        ttk.Label(body, textvariable=self.link_summary_var, style="Muted.TLabel", wraplength=270).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(body, text="Remove last link", command=self._remove_axis_link, style="Compact.TButton").grid(row=8, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_device_card(self, parent):
        before = list(parent.winfo_children())
        super()._build_device_card(parent)
        card = self._new_child(parent, before)
        if card is not None:
            card.grid_configure(row=1, pady=(10, 0))

    def _build_export_card(self, parent):
        before = list(parent.winfo_children())
        super()._build_export_card(parent)
        export_card = self._new_child(parent, before)
        if export_card is not None:
            export_card.grid_configure(row=2, pady=(10, 0))

        project, body = self._card(parent, "5 · Project", "Save the entire editable session as a portable .pdance file. Autosave is written after committed edits.")
        project.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(body, text="Save .pdance", command=self.save_project, style="Soft.TButton").grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(body, text="Open .pdance…", command=self.open_project, style="Soft.TButton").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        history = ttk.Frame(body, style="Card.TFrame"); history.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0)); history.columnconfigure((0, 1), weight=1)
        ttk.Button(history, text="↶ Undo", command=self.undo, style="Compact.TButton").grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(history, text="↷ Redo", command=self.redo, style="Compact.TButton").grid(row=0, column=1, sticky="ew", padx=(3, 0))

        intiface, ibody = self._card(parent, "6 · Intiface / Buttplug", "Connect to Intiface Central over WebSocket. Position uses L0; vibration follows six-axis motion intensity; rotation follows R0.")
        intiface.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._label(ibody, "Server", 0)
        ttk.Entry(ibody, textvariable=self.intiface_address_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._label(ibody, "Device", 1, pady=(8, 0))
        self.intiface_combo = ttk.Combobox(ibody, textvariable=self.intiface_device_var, state="readonly")
        self.intiface_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        row = ttk.Frame(ibody, style="Card.TFrame"); row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(9, 0)); row.columnconfigure((0, 1), weight=1)
        ttk.Button(row, text="Scan", command=self.scan_intiface, style="Compact.TButton").grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(row, text="Play", command=self.play_intiface, style="Accent.TButton").grid(row=0, column=1, sticky="ew", padx=(3, 0))
        ttk.Button(ibody, text="Stop Intiface", command=self.stop_intiface, style="Danger.TButton").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(ibody, textvariable=self.intiface_status_var, style="Muted.TLabel", wraplength=270).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]

        curve = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        curve.columnconfigure(0, weight=1); curve.rowconfigure(0, weight=1)
        notebook.add(curve, text="Curve editor")
        self.curve_figure = Figure(figsize=(8, 5), dpi=100, facecolor=CARD)
        self.curve_axes = self.curve_figure.add_subplot(111)
        self.curve_canvas = FigureCanvasTkAgg(self.curve_figure, master=curve)
        self.curve_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        controls = ttk.Frame(curve, style="Card.TFrame"); controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(controls, text="Axis", style="Muted.TLabel").grid(row=0, column=0)
        ttk.Combobox(controls, textvariable=self.curve_axis_var, values=AXIS_ORDER, state="readonly", width=6).grid(row=0, column=1, padx=(4, 8))
        ttk.Label(controls, text="Interpolation", style="Muted.TLabel").grid(row=0, column=2)
        interp = ttk.Combobox(controls, textvariable=self.curve_method_var, values=INTERPOLATIONS, state="readonly", width=10)
        interp.grid(row=0, column=3, padx=(4, 8)); interp.bind("<<ComboboxSelected>>", lambda _e: self._interpolation_changed())
        ttk.Checkbutton(controls, text="Snap to beat", variable=self.curve_snap_var).grid(row=0, column=4, padx=(0, 8))
        ttk.Combobox(controls, textvariable=self.curve_quantize_var, values=("nearest", "floor", "ceil"), state="readonly", width=8).grid(row=0, column=5)
        ttk.Button(controls, text="Quantize", command=self._quantize_curve, style="Compact.TButton").grid(row=0, column=6, padx=(6, 0))
        ttk.Button(controls, text="Smooth", command=self._smooth_curve, style="Compact.TButton").grid(row=1, column=0, pady=(7, 0))
        ttk.Button(controls, text="Flatten", command=self._flatten_curve, style="Compact.TButton").grid(row=1, column=1, pady=(7, 0), padx=(4, 8))
        ttk.Label(controls, text="Scale", style="Muted.TLabel").grid(row=1, column=2, pady=(7, 0))
        ttk.Spinbox(controls, textvariable=self.curve_scale_var, from_=0., to=3., increment=.05, width=6).grid(row=1, column=3, pady=(7, 0), padx=(4, 8))
        ttk.Label(controls, text="Offset", style="Muted.TLabel").grid(row=1, column=4, pady=(7, 0))
        ttk.Spinbox(controls, textvariable=self.curve_offset_var, from_=-50., to=50., increment=1., width=6).grid(row=1, column=5, pady=(7, 0))
        ttk.Button(controls, text="Apply", command=self._transform_curve, style="Compact.TButton").grid(row=1, column=6, pady=(7, 0), padx=(6, 0))
        ttk.Button(controls, text="Delete selected keyframe", command=self._delete_keyframe, style="Compact.TButton").grid(row=2, column=0, columnspan=7, sticky="ew", pady=(7, 0))
        ttk.Label(curve, text="Double-click to add · drag a point to move · edits affect final funscript/TCode output", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.curve_axis_var.trace_add("write", lambda *_: self._curve_axis_changed())
        self.curve_canvas.mpl_connect("button_press_event", self._curve_press)
        self.curve_canvas.mpl_connect("motion_notify_event", self._curve_motion)
        self.curve_canvas.mpl_connect("button_release_event", self._curve_release)

        diagnostics = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        diagnostics.columnconfigure(0, weight=1); diagnostics.rowconfigure(0, weight=1)
        notebook.add(diagnostics, text="Diagnostics")
        self.diagnostic_figure = Figure(figsize=(8, 5), dpi=100, facecolor=CARD)
        self.diagnostic_axes = [self.diagnostic_figure.add_subplot(7, 1, i + 1) for i in range(7)]
        self.diagnostic_canvas = FigureCanvasTkAgg(self.diagnostic_figure, master=diagnostics)
        self.diagnostic_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.diagnostic_summary_var = tk.StringVar(value="Generate or open a project to view motion/risk diagnostics.")
        ttk.Label(diagnostics, textvariable=self.diagnostic_summary_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self._redraw_curve_editor()
        self._redraw_diagnostics()

    # ---------- history / project ----------
    def _checkpoint(self):
        if self.workspace is not None and self.base_plan is not None:
            self.history.push(self.base_plan, self.workspace)

    def _mark_changed(self):
        self.project_dirty = True
        self.autosave_now(silent=True)

    def undo(self):
        if self.workspace is None or self.base_plan is None:
            return
        restored = self.history.undo(self.base_plan, self.workspace)
        if restored is None:
            self.status_var.set("Nothing to undo")
            return
        self.base_plan, self.workspace = restored
        self._sync_axis_controls_from_workspace()
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.status_var.set("Undo")

    def redo(self):
        if self.workspace is None or self.base_plan is None:
            return
        restored = self.history.redo(self.base_plan, self.workspace)
        if restored is None:
            self.status_var.set("Nothing to redo")
            return
        self.base_plan, self.workspace = restored
        self._sync_axis_controls_from_workspace()
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.status_var.set("Redo")

    def _sync_axis_controls_from_workspace(self):
        if not self.workspace:
            return
        self.solo_var.set(self.workspace.solo_axis or "All")
        for axis in AXIS_ORDER:
            self.axis_mute_vars[axis].set(self.workspace.axes[axis].muted)
            self.axis_lock_vars[axis].set(self.workspace.axes[axis].locked)

    @staticmethod
    def _jsonify(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            return {str(k): MultiAxisWindow._jsonify(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [MultiAxisWindow._jsonify(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _restore_arrays(value):
        if isinstance(value, dict):
            return {k: MultiAxisWindow._restore_arrays(v) for k, v in value.items()}
        if isinstance(value, list):
            if value and all(isinstance(item, (int, float)) for item in value):
                return np.asarray(value, dtype=np.float64)
            return [MultiAxisWindow._restore_arrays(v) for v in value]
        return value

    def _project_document(self):
        if self.workspace is None or self.base_plan is None:
            raise RuntimeError("Generate or open a choreography first")
        generation = asdict(self.generated_config) if self.generated_config is not None else {}
        if generation.get("profile") is not None:
            generation["profile"] = self._jsonify(generation["profile"])
        return ProjectDocument(
            media_path=str(self.source_path or self.path_var.get().strip()),
            base_plan=copy_plan(self.base_plan),
            workspace=self.workspace,
            analysis=self._jsonify(self.data or {}),
            generation=self._jsonify(generation),
            curve_settings={axis: self.curve_settings[axis].to_dict() for axis in AXIS_ORDER},
            safety_settings=self.safety_settings.to_dict(),
            device={"intiface_address": self.intiface_address_var.get(), "serial_port": self.port_var.get(), "baud": self.baud_var.get()},
            ui={"timeline": float(self.timeline_var.get())},
        )

    def save_project(self):
        if self.workspace is None:
            messagebox.showwarning("PythonDancer", "Generate or open a choreography first.")
            return
        if self.project_path is None:
            return self.save_project_as()
        try:
            save_project(self.project_path, self._project_document())
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"Project save failed:\n{exc}")
            return
        self.project_dirty = False
        self.status_var.set(f"Saved project: {self.project_path.name}")

    def save_project_as(self):
        if self.workspace is None:
            messagebox.showwarning("PythonDancer", "Generate or open a choreography first.")
            return
        initial = (Path(self.source_path).stem if self.source_path else "project") + ".pdance"
        selected = filedialog.asksaveasfilename(title="Save PythonDancer project", defaultextension=".pdance", initialfile=initial, filetypes=[("PythonDancer project", "*.pdance")])
        if not selected:
            return
        self.project_path = Path(selected)
        self.save_project()

    def autosave_now(self, silent=False):
        if self.workspace is None or self.base_plan is None:
            return
        try:
            path = autosave_project(self._project_document())
        except Exception as exc:
            if not silent:
                messagebox.showerror("PythonDancer", f"Autosave failed:\n{exc}")
            return
        if not silent:
            self.status_var.set(f"Autosaved: {path.name}")

    def open_project(self):
        selected = filedialog.askopenfilename(title="Open PythonDancer project", filetypes=[("PythonDancer project", "*.pdance"), ("All files", "*.*")])
        if not selected:
            return
        try:
            project = load_project(selected)
            self._load_project_document(project)
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"Project open failed:\n{exc}")
            return
        self.project_path = Path(selected)
        self.project_dirty = False
        self.status_var.set(f"Opened project: {self.project_path.name}")

    def _load_project_document(self, project: ProjectDocument):
        self.source_path = Path(project.media_path) if project.media_path else None
        self.path_var.set(project.media_path)
        self.base_plan = copy_plan(project.base_plan)
        self.workspace = project.workspace
        self.duration = float(project.workspace.duration)
        self.data = self._restore_arrays(project.analysis)
        generation = dict(project.generation or {})
        motion_data = generation.pop("motion", {}) or {}
        generation.pop("profile", None)
        allowed = {key for key in MultiAxisConfig.__dataclass_fields__ if key != "motion"}
        kwargs = {key: value for key, value in generation.items() if key in allowed}
        motion_allowed = MotionConfig.__dataclass_fields__
        motion = MotionConfig(**{key: value for key, value in motion_data.items() if key in motion_allowed})
        self.generated_config = MultiAxisConfig(motion=motion, **kwargs)
        for axis in AXIS_ORDER:
            settings = (project.curve_settings or {}).get(axis, {})
            try:
                self.curve_settings[axis] = CurveSettings(**settings)
            except Exception:
                self.curve_settings[axis] = CurveSettings()
        safe = project.safety_settings or {}
        links = [AxisLink(**item) for item in safe.get("links", [])]
        self.safety_settings = SafetySettings(
            smart_limits=bool(safe.get("smart_limits", True)), profile=str(safe.get("profile", "balanced")),
            soft_start_ms=int(safe.get("soft_start_ms", 750)), auto_home=bool(safe.get("auto_home", True)),
            home_ms=int(safe.get("home_ms", 700)), gap_fill=str(safe.get("gap_fill", "none")),
            gap_threshold=float(safe.get("gap_threshold", 1.75)), links=links,
        )
        self._sync_safety_vars()
        self._sync_axis_controls_from_workspace()
        self.timeline_scale.configure(to=max(0.01, self.duration))
        self.timeline_var.set(float((project.ui or {}).get("timeline", 0.0)))
        self.export_button.configure(state="normal"); self.tcode_export_button.configure(state="normal"); self.play_button.configure(state="normal")
        self.regenerate_button.configure(state="normal")
        self.work_timeline.set_model(self.workspace, self.data)
        self._apply_workspace(redraw=True)

    # ---------- curve editing ----------
    def _curve_axis_changed(self):
        settings = self.curve_settings[self.curve_axis_var.get()]
        self.curve_method_var.set(settings.interpolation)
        self.curve_snap_var.set(settings.snap_to_beat)
        self.curve_quantize_var.set(settings.quantize_mode)
        self.selected_keyframe = None
        self._redraw_curve_editor()

    def _curve_selection(self):
        if self.workspace is None:
            return 0.0, float("inf")
        selection = self.workspace.selection.normalized(self.workspace.duration)
        if selection.duration <= .001:
            return 0.0, self.workspace.duration
        return selection.start, selection.end

    def _interpolation_changed(self):
        axis = self.curve_axis_var.get()
        try:
            self.curve_settings[axis] = CurveSettings(self.curve_method_var.get(), bool(self.curve_snap_var.get()), self.curve_quantize_var.get())
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self._checkpoint(); self._apply_workspace(redraw=True); self._mark_changed()

    def _quantize_curve(self):
        if self.base_plan is None or self.data is None:
            return
        axis = self.curve_axis_var.get(); self._checkpoint()
        start, end = self._curve_selection()
        self.base_plan[axis] = quantize_actions(self.base_plan[axis], self.data.get("beats", []), mode=self.curve_quantize_var.get(), start=start, end=end)
        self._apply_workspace(redraw=True); self._mark_changed()

    def _smooth_curve(self):
        if self.base_plan is None: return
        axis = self.curve_axis_var.get(); start, end = self._curve_selection(); self._checkpoint()
        self.base_plan[axis] = smooth_range(self.base_plan[axis], start, end, window=5)
        self._apply_workspace(redraw=True); self._mark_changed()

    def _flatten_curve(self):
        if self.base_plan is None: return
        axis = self.curve_axis_var.get(); start, end = self._curve_selection(); self._checkpoint()
        self.base_plan[axis] = flatten_range(self.base_plan[axis], start, end)
        self._apply_workspace(redraw=True); self._mark_changed()

    def _transform_curve(self):
        if self.base_plan is None: return
        axis = self.curve_axis_var.get(); start, end = self._curve_selection(); self._checkpoint()
        self.base_plan[axis] = transform_range(self.base_plan[axis], start, end, scale=float(self.curve_scale_var.get()), offset=float(self.curve_offset_var.get()))
        self._apply_workspace(redraw=True); self._mark_changed()

    def _delete_keyframe(self):
        if self.base_plan is None or self.selected_keyframe is None: return
        axis = self.curve_axis_var.get(); self._checkpoint()
        self.base_plan[axis] = delete_keyframes(self.base_plan[axis], [self.selected_keyframe])
        self.selected_keyframe = None
        self._apply_workspace(redraw=True); self._mark_changed()

    def _curve_press(self, event):
        if self.base_plan is None or event.inaxes is not self.curve_axes or event.xdata is None or event.ydata is None:
            return
        axis = self.curve_axis_var.get(); actions = self.base_plan[axis]
        at = float(max(0.0, event.xdata)); pos = float(np.clip(event.ydata, 0.0, 100.0))
        if event.dblclick:
            self._checkpoint()
            if self.curve_snap_var.get() and self.data is not None:
                at = nearest_beat(at, self.data.get("beats", []), self.curve_quantize_var.get())
            self.base_plan[axis] = insert_keyframe(actions, at, pos)
            self.selected_keyframe = min(range(len(self.base_plan[axis])), key=lambda i: abs(self.base_plan[axis][i][0] - at))
            self._apply_workspace(redraw=True); self._mark_changed(); return
        if not actions:
            return
        duration = max(self.duration, 1.0)
        distances = [((p_at - at) / duration) ** 2 + ((p_pos - pos) / 100.0) ** 2 for p_at, p_pos in actions]
        index = int(np.argmin(distances))
        if distances[index] <= .0025:
            self._checkpoint(); self.selected_keyframe = index; self._dragging_keyframe = True; self._redraw_curve_editor()

    def _curve_motion(self, event):
        if not self._dragging_keyframe or self.base_plan is None or self.selected_keyframe is None or event.inaxes is not self.curve_axes or event.xdata is None or event.ydata is None:
            return
        axis = self.curve_axis_var.get(); at = float(max(0.0, event.xdata)); pos = float(np.clip(event.ydata, 0.0, 100.0))
        if self.curve_snap_var.get() and self.data is not None:
            at = nearest_beat(at, self.data.get("beats", []), self.curve_quantize_var.get())
        self.base_plan[axis] = move_keyframe(self.base_plan[axis], self.selected_keyframe, at, pos)
        self.selected_keyframe = min(range(len(self.base_plan[axis])), key=lambda i: abs(self.base_plan[axis][i][0] - at))
        self._apply_workspace(redraw=False); self._redraw_curve_editor()

    def _curve_release(self, _event):
        if self._dragging_keyframe:
            self._dragging_keyframe = False; self._apply_workspace(redraw=True); self._mark_changed()

    def _curve_plan(self, plan):
        result = copy_plan(plan)
        for axis in AXIS_ORDER:
            settings = self.curve_settings[axis]
            actions = result[axis]
            if settings.interpolation == "linear" or len(actions) < 2:
                continue
            start, end = actions[0][0], actions[-1][0]
            count = max(2, int(np.ceil((end - start) * 20.0)) + 1)
            sample = np.linspace(start, end, count)
            result[axis] = resample_curve(actions, sample, settings.interpolation)
        return result

    def _redraw_curve_editor(self):
        if not hasattr(self, "curve_axes"):
            return
        ax = self.curve_axes; ax.clear(); ax.set_facecolor(PLOT_BG); ax.set_ylim(0, 100); ax.grid(color=BORDER, linewidth=.6)
        axis = self.curve_axis_var.get(); ax.set_title(f"{axis} · {AXIS_CHANNELS[axis]} keyframes", loc="left", fontsize=10, fontweight="bold", color=TEXT)
        actions = self.base_plan.get(axis, []) if self.base_plan else []
        if actions:
            times = np.asarray([at for at, _ in actions]); values = np.asarray([pos for _, pos in actions])
            ax.plot(times, values, linewidth=1, color=ACCENT, alpha=.45)
            ax.scatter(times, values, s=22, color=ACCENT)
            if self.selected_keyframe is not None and self.selected_keyframe < len(actions):
                at, pos = actions[self.selected_keyframe]; ax.scatter([at], [pos], s=80, facecolors="none", edgecolors="#DC2626", linewidths=1.5)
        if self.workspace is not None:
            selection = self.workspace.selection.normalized(self.workspace.duration)
            if selection.duration > .001: ax.axvspan(selection.start, selection.end, color=ACCENT, alpha=.06)
        ax.tick_params(labelsize=8, colors=MUTED); self.curve_figure.tight_layout(); self.curve_canvas.draw_idle()

    # ---------- safety / diagnostics ----------
    def _sync_safety_vars(self):
        s = self.safety_settings
        self.smart_limit_var.set(s.smart_limits); self.smart_profile_var.set(s.profile); self.gap_fill_var.set(s.gap_fill); self.gap_threshold_var.set(s.gap_threshold)
        self.soft_start_var.set(s.soft_start_ms); self.auto_home_var.set(s.auto_home); self.home_ms_var.set(s.home_ms); self._update_link_summary()

    def _safety_changed(self):
        try:
            self.safety_settings.smart_limits = bool(self.smart_limit_var.get())
            self.safety_settings.profile = self.smart_profile_var.get()
            self.safety_settings.gap_fill = self.gap_fill_var.get()
            self.safety_settings.gap_threshold = float(self.gap_threshold_var.get())
            self.safety_settings.__post_init__()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self._apply_workspace(redraw=True); self._mark_changed()

    def _add_axis_link(self):
        try:
            link = AxisLink(self.link_source_var.get(), self.link_target_var.get(), float(self.link_gain_var.get()), float(self.link_delay_var.get()))
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self.safety_settings.links.append(link); self._update_link_summary(); self._apply_workspace(redraw=True); self._mark_changed()

    def _remove_axis_link(self):
        if self.safety_settings.links:
            self.safety_settings.links.pop(); self._update_link_summary(); self._apply_workspace(redraw=True); self._mark_changed()

    def _update_link_summary(self):
        if not self.safety_settings.links:
            self.link_summary_var.set("No axis links"); return
        self.link_summary_var.set(" · ".join(f"{x.source}→{x.target} {x.gain:+.2f}" for x in self.safety_settings.links[-3:]))

    def _apply_workspace(self, redraw=True):
        if not self.workspace or self.base_plan is None:
            return
        plan = self.workspace.output_plan(self.base_plan)
        plan = self._curve_plan(plan)
        if self.safety_settings.links:
            plan = apply_axis_links(plan, self.safety_settings.links)
        if self.safety_settings.gap_fill != "none":
            plan = fill_motion_gaps(plan, (self.data or {}).get("beats", []), mode=self.safety_settings.gap_fill, threshold=self.safety_settings.gap_threshold)
        if self.safety_settings.smart_limits:
            plan = apply_smart_limits(plan, self.safety_settings.profile)
        # Mute is authoritative even if a link or gap filler generated that axis.
        for axis in AXIS_ORDER:
            if self.workspace.axes[axis].muted:
                plan[axis] = []
        self.plan = constrain_workspace_plan(plan, self.generated_config)
        self.section_summary_var.set("Structure: " + " | ".join(f"{section.label}:{section.start:.1f}-{section.end:.1f}" for section in self.workspace.sections))
        self.selection_var.set(self._selection_label())
        for axis in AXIS_ORDER:
            self.axis_count_vars[axis].set(f"{axis} · {AXIS_CHANNELS[axis]} · {len(self.plan.get(axis, ()))}")
        if redraw:
            self.work_timeline.set_model(self.workspace, self.data)
            self._redraw_workspace_preview(); self._draw_pose(float(self.timeline_var.get())); self._redraw_curve_editor(); self._redraw_diagnostics()

    def _redraw_diagnostics(self):
        if not hasattr(self, "diagnostic_axes"):
            return
        for ax in self.diagnostic_axes: ax.clear(); ax.set_facecolor(PLOT_BG)
        if not self.plan:
            self.diagnostic_canvas.draw_idle(); return
        bins = 90; motion = motion_heatmap(self.plan, duration=self.duration, bins=bins); risk = risk_heatmap(self.plan, duration=self.duration, bins=bins)
        labels = list(AXIS_ORDER) + ["RISK"]
        for i, label in enumerate(labels):
            values = risk if label == "RISK" else motion[label]
            ax = self.diagnostic_axes[i]
            ax.imshow(values.reshape(1, -1), aspect="auto", interpolation="nearest", extent=[0, max(self.duration, .01), 0, 1], cmap="inferno" if label == "RISK" else "Blues", vmin=0, vmax=1)
            ax.set_yticks([]); ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize=8, color=TEXT); ax.tick_params(axis="x", labelsize=7, colors=MUTED)
            if i < 6: ax.tick_params(axis="x", labelbottom=False)
        peak = float(np.max(risk)) if risk.size else 0.0
        high = int(np.sum(risk >= .85))
        self.diagnostic_summary_var.set(f"Peak risk {peak:.2f} · {high}/{bins} bins above 0.85 · smart envelope {self.safety_settings.profile if self.safety_settings.smart_limits else 'off'}")
        self.diagnostic_figure.tight_layout(h_pad=.15); self.diagnostic_canvas.draw_idle()

    # ---------- inherited edit hooks with history/autosave ----------
    def _axis_controls_changed(self):
        self._checkpoint(); super()._axis_controls_changed(); self._mark_changed()

    def _timeline_edit_changed(self, committed=True):
        if not committed and not self._timeline_drag_checkpointed:
            self._checkpoint(); self._timeline_drag_checkpointed = True
        super()._timeline_edit_changed(committed)
        if committed:
            self._timeline_drag_checkpointed = False; self._mark_changed()

    def _add_gesture(self):
        self._checkpoint(); super()._add_gesture(); self._mark_changed()

    def _delete_gesture(self):
        self._checkpoint(); super()._delete_gesture(); self._mark_changed()

    def _apply_section_label(self):
        self._checkpoint(); super()._apply_section_label(); self._mark_changed()

    def _regenerate_selection(self):
        self._checkpoint(); super()._regenerate_selection(); self._mark_changed()

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self.project_path = None; self.project_dirty = True; self.history = UndoStack(limit=100)
        self.curve_settings = {axis: CurveSettings() for axis in AXIS_ORDER}; self.selected_keyframe = None
        self.safety_settings = SafetySettings(gap_fill="none"); self._sync_safety_vars(); self._apply_workspace(redraw=True); self.autosave_now(silent=True)

    # ---------- device safety / Intiface ----------
    def _device_plan(self):
        plan = super()._device_plan()
        if self.safety_settings.auto_home and plan:
            plan = {axis: list(actions) for axis, actions in add_auto_home(plan, home_ms=int(self.home_ms_var.get())).items() if actions}
        return plan

    def play_device(self):
        # The validated 2.4 controller already performs a smooth synchronization
        # on seek. 2.5 raises that ramp to the configured Soft Start envelope.
        original = int(self.args.seek_ramp_ms)
        self.args.seek_ramp_ms = max(original, int(self.soft_start_var.get()))
        try:
            super().play_device()
        finally:
            self.args.seek_ramp_ms = original

    def scan_intiface(self):
        if self.intiface_worker and self.intiface_worker.is_alive(): return
        self.intiface_status_var.set("Scanning Intiface Central…")
        address = self.intiface_address_var.get().strip() or DEFAULT_INTIFACE_ADDRESS
        def work():
            try: devices = discover_intiface_devices_sync(address, 2.5)
            except Exception as exc: self.after(0, lambda: self.intiface_status_var.set(f"Scan failed: {exc}")); return
            def done():
                self.intiface_devices = devices
                values = [f"{item.index} · {item.name}" for item in devices]
                self.intiface_combo.configure(values=values)
                if values: self.intiface_device_var.set(values[0]); self.intiface_status_var.set(f"Found {len(values)} device(s)")
                else: self.intiface_status_var.set("No devices found")
            self.after(0, done)
        self.intiface_worker = Thread(target=work, daemon=True); self.intiface_worker.start()

    def play_intiface(self):
        if not self.plan or (self.intiface_worker and self.intiface_worker.is_alive()): return
        address = self.intiface_address_var.get().strip() or DEFAULT_INTIFACE_ADDRESS
        selected = self.intiface_device_var.get().strip(); index = None
        if selected:
            try: index = int(selected.split("·", 1)[0].strip())
            except ValueError: pass
        self.intiface_stop.clear(); plan = self._device_plan(); start_at = float(self.timeline_var.get()); speed = float(self.play_speed_var.get())
        self.intiface_status_var.set("Playing…")
        def work():
            try: play_plan_intiface_sync(plan, address=address, device_index=index, speed=speed, stop_event=self.intiface_stop, start_at=start_at)
            except Exception as exc: self.after(0, lambda: self.intiface_status_var.set(f"Playback failed: {exc}")); return
            self.after(0, lambda: self.intiface_status_var.set("Ready"))
        self.intiface_worker = Thread(target=work, daemon=True); self.intiface_worker.start()

    def stop_intiface(self):
        self.intiface_stop.set(); self.intiface_status_var.set("Stopping…")


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
