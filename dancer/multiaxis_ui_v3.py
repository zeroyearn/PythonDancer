"""PythonDancer 2.4 interactive six-axis choreography workstation.

Adds a non-destructive timeline editor, manual section/gesture editing, axis
Solo/Mute/Lock, range regeneration, waveform/beat visualization, and a live 3D
pose preview while reusing the validated 2.3 generation/device implementation.
"""
from __future__ import annotations

from dataclasses import replace
import math
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .choreography import SECTION_GESTURES, SECTION_LABELS
from .multiaxis import AXIS_CHANNELS, AXIS_ORDER, plan_multiaxis
from .multiaxis_ui_v2 import (
    ACCENT,
    BG,
    BORDER,
    CARD,
    GRID,
    MUTED,
    PLOT_BG,
    ROTATION,
    TEXT,
    TRANSLATION,
    MultiAxisWindow as _V2Window,
)
from .workspace import GESTURES, GestureBlock, WorkspaceState, sample_axis, splice_plan

SECTION_COLORS = {
    "intro": "#DBEAFE", "verse": "#E0E7FF", "build": "#FEF3C7",
    "chorus": "#DCFCE7", "drop": "#FCE7F3", "breakdown": "#E2E8F0", "outro": "#F3E8FF",
}
GESTURE_COLORS = {
    "pulse": "#DBEAFE", "sway": "#E0E7FF", "rock": "#E2E8F0", "circle": "#DCFCE7",
    "spiral": "#F3E8FF", "wave": "#CFFAFE", "accent": "#FCE7F3",
}
SECTION_DEFAULT_GESTURE = {
    "intro": "wave", "verse": "sway", "build": "circle", "chorus": "spiral",
    "drop": "accent", "breakdown": "wave", "outro": "wave",
}


class WorkstationTimeline(tk.Canvas):
    """Compact DAW-like editor for selection, section boundaries, and gestures."""

    def __init__(self, master, *, changed=None, section_selected=None, gesture_selected=None):
        super().__init__(master, height=190, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        self.changed = changed
        self.section_selected = section_selected
        self.gesture_selected = gesture_selected
        self.workspace: WorkspaceState | None = None
        self.data = None
        self.drag = None
        self.active_gesture: int | None = None
        self.active_section: int | None = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    @property
    def left(self): return 54.0
    @property
    def right(self): return max(self.left + 1.0, float(self.winfo_width()) - 10.0)

    def set_model(self, workspace: WorkspaceState | None, data) -> None:
        self.workspace, self.data = workspace, data
        self.redraw()

    def _x(self, at: float) -> float:
        duration = max(.001, self.workspace.duration if self.workspace else 1.0)
        return self.left + np.clip(float(at) / duration, 0., 1.) * (self.right - self.left)

    def _time(self, x: float) -> float:
        duration = max(.001, self.workspace.duration if self.workspace else 1.0)
        return float(np.clip((float(x) - self.left) / max(1., self.right - self.left), 0., 1.) * duration)

    def redraw(self) -> None:
        self.delete("all")
        ws = self.workspace
        width = self.right - self.left
        self.create_text(8, 31, text="Wave", anchor="w", fill=MUTED, font=("TkDefaultFont", 8))
        self.create_text(8, 91, text="Section", anchor="w", fill=MUTED, font=("TkDefaultFont", 8))
        self.create_text(8, 139, text="Gesture", anchor="w", fill=MUTED, font=("TkDefaultFont", 8))
        if ws is None:
            self.create_text(self.left + width / 2, 90, text="Generate motion to edit the timeline", fill=MUTED)
            return

        # Waveform envelope and beat grid.
        times = np.asarray((self.data or {}).get("waveform_times", []), dtype=np.float64)
        envelope = np.asarray((self.data or {}).get("waveform_envelope", []), dtype=np.float64)
        if times.size and envelope.size:
            n = min(times.size, envelope.size)
            pts = []
            for at, value in zip(times[:n], envelope[:n]):
                pts.extend((self._x(float(at)), 52.0 - float(value) * 28.0))
            if len(pts) >= 4:
                self.create_line(*pts, fill="#94A3B8", width=1)
        beats = np.asarray((self.data or {}).get("beats", []), dtype=np.float64)
        for i, at in enumerate(beats):
            x = self._x(float(at))
            self.create_line(x, 12, x, 158, fill="#CBD5E1" if i % 4 else "#94A3B8", width=1, dash=(1, 3))

        # Sections.
        for i, block in enumerate(ws.sections):
            x1, x2 = self._x(block.start), self._x(block.end)
            self.create_rectangle(x1, 68, x2, 108, fill=SECTION_COLORS.get(block.label, "#E2E8F0"), outline=ACCENT if i == self.active_section else CARD, width=2 if i == self.active_section else 1, tags=(f"section:{i}",))
            if x2 - x1 > 34:
                self.create_text((x1 + x2) / 2, 88, text=block.label, fill=TEXT, font=("TkDefaultFont", 8, "bold"), tags=(f"section:{i}",))
            if i:
                self.create_line(x1, 64, x1, 112, fill=ACCENT, width=2, tags=(f"boundary:{i}",))

        # Gesture blocks.
        for i, block in enumerate(ws.gestures):
            x1, x2 = self._x(block.start), self._x(block.end)
            selected = i == self.active_gesture
            self.create_rectangle(x1, 119, x2, 157, fill=GESTURE_COLORS.get(block.gesture, "#E2E8F0"), outline=ACCENT if selected else BORDER, width=2 if selected else 1, tags=(f"gesture:{i}",))
            if x2 - x1 > 42:
                self.create_text((x1 + x2) / 2, 138, text=f"{block.gesture} · {block.strength:g}×", fill=TEXT, font=("TkDefaultFont", 8, "bold"), tags=(f"gesture:{i}",))

        # Selection, always on top.
        sel = ws.selection.normalized(ws.duration)
        if sel.duration > .001:
            x1, x2 = self._x(sel.start), self._x(sel.end)
            self.create_rectangle(x1, 10, x2, 162, outline=ACCENT, width=2, dash=(4, 3))
        self.create_line(self.left, 164, self.right, 164, fill=BORDER)
        for fraction in (0., .25, .5, .75, 1.):
            at = ws.duration * fraction
            x = self._x(at)
            self.create_text(x, 176, text=f"{at:.1f}s", fill=MUTED, font=("TkDefaultFont", 7))

    def _hit_boundary(self, x: float, y: float):
        if not self.workspace or not 60 <= y <= 114:
            return None
        for i in range(1, len(self.workspace.sections)):
            if abs(self._x(self.workspace.sections[i].start) - x) <= 7:
                return i
        return None

    def _hit_gesture(self, x: float, y: float):
        if not self.workspace or not 114 <= y <= 162:
            return None
        for i, block in reversed(list(enumerate(self.workspace.gestures))):
            x1, x2 = self._x(block.start), self._x(block.end)
            if x1 - 3 <= x <= x2 + 3:
                edge = "left" if abs(x - x1) <= 7 else "right" if abs(x - x2) <= 7 else "move"
                return i, edge
        return None

    def _hit_section(self, x: float, y: float):
        if not self.workspace or not 64 <= y <= 112:
            return None
        at = self._time(x)
        for i, block in enumerate(self.workspace.sections):
            if block.start <= at <= block.end:
                return i
        return None

    def _press(self, event):
        if not self.workspace:
            return
        boundary = self._hit_boundary(event.x, event.y)
        if boundary is not None:
            self.drag = ("boundary", boundary, self._time(event.x))
            return
        gesture = self._hit_gesture(event.x, event.y)
        if gesture is not None:
            index, mode = gesture
            self.active_gesture = index
            self.active_section = None
            self.drag = (f"gesture-{mode}", index, self._time(event.x))
            if self.gesture_selected: self.gesture_selected(index)
            self.redraw()
            return
        section = self._hit_section(event.x, event.y)
        if section is not None:
            self.active_section = section
            self.active_gesture = None
            if self.section_selected: self.section_selected(section)
            self.redraw()
            return
        at = self._time(event.x)
        self.workspace.set_selection(at, at)
        self.drag = ("selection", None, at)
        self.redraw()

    def _motion(self, event):
        if not self.workspace or not self.drag:
            return
        mode, index, origin = self.drag
        at = self._time(event.x)
        if mode == "selection":
            self.workspace.set_selection(origin, at)
        elif mode == "boundary":
            self.workspace.set_section_boundary(index, at)
        elif mode.startswith("gesture-") and index is not None and 0 <= index < len(self.workspace.gestures):
            block = self.workspace.gestures[index]
            kind = mode.split("-", 1)[1]
            if kind == "left":
                block.start = min(at, block.end - .05)
            elif kind == "right":
                block.end = max(at, block.start + .05)
            else:
                width = block.end - block.start
                delta = at - origin
                start = float(np.clip(block.start + delta, 0., max(0., self.workspace.duration - width)))
                block.start, block.end = start, start + width
                self.drag = (mode, index, at)
        self.redraw()
        if self.changed: self.changed(False)

    def _release(self, _event):
        if self.drag and self.changed: self.changed(True)
        self.drag = None


class MultiAxisWindow(_V2Window):
    """2.4 workstation layered over the stable 2.3 engine/device window."""

    def _build_ui(self):
        self.title("PythonDancer · Choreography Workstation")
        self.geometry("1580x960")
        self.minsize(1240, 800)
        self._configure_style()

        self.device_status_var = tk.StringVar(value="Not connected")
        self.result_summary_var = tk.StringVar(value="No choreography generated")
        self.axis_count_vars = {axis: tk.StringVar(value=f"{axis} · {AXIS_CHANNELS[axis]} · —") for axis in AXIS_ORDER}
        self.workspace: WorkspaceState | None = None
        self.base_plan = None
        self.local_preset_var = tk.StringVar(value=self.preset_var.get())
        self.local_strength_var = tk.DoubleVar(value=self.strength_var.get())
        self.local_gesture_var = tk.DoubleVar(value=self.gesture_strength_var.get())
        self.gesture_var = tk.StringVar(value="sway")
        self.gesture_block_strength_var = tk.DoubleVar(value=1.0)
        self.section_label_var = tk.StringVar(value="verse")
        self.selected_section_index = None
        self.selected_gesture_index = None
        self.solo_var = tk.StringVar(value="All")
        self.axis_mute_vars = {axis: tk.BooleanVar(value=False) for axis in AXIS_ORDER}
        self.axis_lock_vars = {axis: tk.BooleanVar(value=False) for axis in AXIS_ORDER}
        self._last_pose_at = -1.0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        body = ttk.Frame(self, style="App.TFrame", padding=(12, 12, 12, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=305)
        body.columnconfigure(1, weight=1, minsize=600)
        body.columnconfigure(2, minsize=315)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="App.TFrame"); left.grid(row=0, column=0, sticky="nsew", padx=(0, 10)); left.columnconfigure(0, weight=1)
        center = ttk.Frame(body, style="App.TFrame"); center.grid(row=0, column=1, sticky="nsew"); center.columnconfigure(0, weight=1); center.rowconfigure(1, weight=1)
        right = ttk.Frame(body, style="App.TFrame"); right.grid(row=0, column=2, sticky="nsew", padx=(10, 0)); right.columnconfigure(0, weight=1)

        self._build_motion_card(left)
        self._build_intelligence_card(left)
        self._build_axis_card(left)
        self._build_result_header(center)
        self._build_work_tabs(center)
        self._build_regenerate_card(right)
        self._build_device_card(right)
        self._build_export_card(right)

        footer = ttk.Frame(self, style="App.TFrame", padding=(14, 3, 14, 10))
        footer.grid(row=2, column=0, sticky="ew"); footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        self.summary_label = ttk.Label(footer, text="", style="Status.TLabel"); self.summary_label.grid(row=0, column=1, sticky="e")

    def _build_axis_card(self, parent):
        card, body = self._card(parent, "Axis controls", "Solo is preview-only. Mute affects export/device. Lock protects local regeneration.")
        card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Radiobutton(body, text="All axes", variable=self.solo_var, value="All", command=self._axis_controls_changed).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text="Axis", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Label(body, text="Mute", style="Muted.TLabel").grid(row=1, column=1, pady=(8, 2))
        ttk.Label(body, text="Lock", style="Muted.TLabel").grid(row=1, column=2, pady=(8, 2))
        for row, axis in enumerate(AXIS_ORDER, start=2):
            ttk.Radiobutton(body, text=f"{axis} · {AXIS_CHANNELS[axis]}", variable=self.solo_var, value=axis, command=self._axis_controls_changed).grid(row=row, column=0, sticky="w", pady=1)
            ttk.Checkbutton(body, variable=self.axis_mute_vars[axis], command=self._axis_controls_changed).grid(row=row, column=1)
            ttk.Checkbutton(body, variable=self.axis_lock_vars[axis], command=self._axis_controls_changed).grid(row=row, column=2)

    def _build_work_tabs(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.grid(row=1, column=0, sticky="nsew")
        parent.rowconfigure(1, weight=1)

        motion = ttk.Frame(notebook, style="App.TFrame"); motion.columnconfigure(0, weight=1); motion.rowconfigure(0, weight=1)
        notebook.add(motion, text="Motion")
        self._build_preview(motion)
        self._build_timeline(motion)
        # inherited methods grid at rows 1/2, so normalize layout here
        for child in motion.grid_slaves():
            info = child.grid_info()
            if int(info.get("row", 0)) == 1: child.grid_configure(row=0)
            elif int(info.get("row", 0)) == 2: child.grid_configure(row=1)
        motion.rowconfigure(0, weight=1)

        editor = ttk.Frame(notebook, style="Card.TFrame", padding=10); editor.columnconfigure(0, weight=1); editor.rowconfigure(1, weight=1)
        notebook.add(editor, text="Timeline editor")
        ttk.Label(editor, text="Drag empty waveform space to select · drag blue section dividers · drag/resize gesture blocks", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.work_timeline = WorkstationTimeline(editor, changed=self._timeline_edit_changed, section_selected=self._section_selected, gesture_selected=self._gesture_selected)
        self.work_timeline.grid(row=1, column=0, sticky="nsew")
        controls = ttk.Frame(editor, style="Card.TFrame"); controls.grid(row=2, column=0, sticky="ew", pady=(9, 0)); controls.columnconfigure(7, weight=1)
        ttk.Label(controls, text="Gesture", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(controls, textvariable=self.gesture_var, values=GESTURES, state="readonly", width=10).grid(row=0, column=1, padx=(6, 10))
        ttk.Label(controls, text="Strength", style="Muted.TLabel").grid(row=0, column=2)
        ttk.Spinbox(controls, textvariable=self.gesture_block_strength_var, from_=0., to=3., increment=.1, width=5).grid(row=0, column=3, padx=(6, 10))
        ttk.Button(controls, text="Add to selection", command=self._add_gesture, style="Compact.TButton").grid(row=0, column=4, padx=(0, 6))
        ttk.Button(controls, text="Delete gesture", command=self._delete_gesture, style="Compact.TButton").grid(row=0, column=5, padx=(0, 14))
        ttk.Label(controls, text="Section", style="Muted.TLabel").grid(row=0, column=6)
        ttk.Combobox(controls, textvariable=self.section_label_var, values=SECTION_LABELS, state="readonly", width=11).grid(row=0, column=7, sticky="w", padx=(6, 6))
        ttk.Button(controls, text="Apply label", command=self._apply_section_label, style="Compact.TButton").grid(row=0, column=8)

        pose = ttk.Frame(notebook, style="Card.TFrame", padding=8); pose.columnconfigure(0, weight=1); pose.rowconfigure(0, weight=1)
        notebook.add(pose, text="3D Pose")
        self.pose_figure = Figure(figsize=(7, 5), dpi=100, facecolor=CARD)
        self.pose_axes = self.pose_figure.add_subplot(111, projection="3d")
        self.pose_canvas = FigureCanvasTkAgg(self.pose_figure, master=pose)
        self.pose_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._draw_pose(0.0)

    def _build_regenerate_card(self, parent):
        card, body = self._card(parent, "Edit selection", "Select a range in Timeline editor, adjust local character, then replace only that range. Locked axes are preserved.")
        card.grid(row=0, column=0, sticky="ew")
        self._label(body, "Local preset", 0)
        ttk.Combobox(body, textvariable=self.local_preset_var, values=("balanced", "rhythm", "expressive"), state="readonly").grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self._label(body, "Axis strength", 1, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.local_strength_var, from_=0., to=3., increment=.05).grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self._label(body, "Gesture strength", 2, pady=(8, 0))
        ttk.Spinbox(body, textvariable=self.local_gesture_var, from_=0., to=3., increment=.05).grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        self.regenerate_button = ttk.Button(body, text="Regenerate selection", command=self._regenerate_selection, state="disabled", style="Accent.TButton")
        self.regenerate_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.selection_var = tk.StringVar(value="Selection: —")
        ttk.Label(body, textvariable=self.selection_var, style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 0))

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self.base_plan = {axis: list(plan[axis]) for axis in AXIS_ORDER}
        self.workspace = WorkspaceState.from_analysis(analysis, data.get("beats", []), self.duration)
        self.local_preset_var.set(config.preset); self.local_strength_var.set(config.strength); self.local_gesture_var.set(config.gesture_strength)
        for axis in AXIS_ORDER:
            self.axis_mute_vars[axis].set(False); self.axis_lock_vars[axis].set(False)
        self.solo_var.set("All")
        self.regenerate_button.configure(state="normal")
        self.work_timeline.set_model(self.workspace, data)
        self._apply_workspace(redraw=True)

    def _axis_controls_changed(self):
        if not self.workspace or self.base_plan is None: return
        self.workspace.solo_axis = None if self.solo_var.get() == "All" else self.solo_var.get()
        for axis in AXIS_ORDER:
            self.workspace.axes[axis].muted = bool(self.axis_mute_vars[axis].get())
            self.workspace.axes[axis].locked = bool(self.axis_lock_vars[axis].get())
        self._apply_workspace(redraw=True)

    def _selection_label(self):
        if not self.workspace: return "Selection: —"
        sel = self.workspace.selection.normalized(self.workspace.duration)
        return f"Selection: {sel.start:.2f}–{sel.end:.2f}s · {sel.duration:.2f}s"

    def _timeline_edit_changed(self, committed=True):
        if not self.workspace: return
        self.selection_var.set(self._selection_label())
        if committed:
            self._apply_workspace(redraw=True)
        else:
            self._redraw_workspace_preview()

    def _section_selected(self, index):
        self.selected_section_index = index
        if self.workspace and 0 <= index < len(self.workspace.sections):
            self.section_label_var.set(self.workspace.sections[index].label)

    def _gesture_selected(self, index):
        self.selected_gesture_index = index
        if self.workspace and 0 <= index < len(self.workspace.gestures):
            block = self.workspace.gestures[index]
            self.gesture_var.set(block.gesture); self.gesture_block_strength_var.set(block.strength)

    def _add_gesture(self):
        if not self.workspace: return
        sel = self.workspace.selection.normalized(self.workspace.duration)
        if sel.duration < .05:
            messagebox.showwarning("PythonDancer", "Drag a timeline range first."); return
        try:
            block = self.workspace.add_gesture(sel.start, sel.end, self.gesture_var.get(), float(self.gesture_block_strength_var.get()))
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc)); return
        self.selected_gesture_index = self.workspace.gestures.index(block)
        self.work_timeline.active_gesture = self.selected_gesture_index
        self._apply_workspace(redraw=True)

    def _delete_gesture(self):
        if not self.workspace or self.selected_gesture_index is None: return
        if 0 <= self.selected_gesture_index < len(self.workspace.gestures):
            self.workspace.gestures.pop(self.selected_gesture_index)
        self.selected_gesture_index = None; self.work_timeline.active_gesture = None
        self._apply_workspace(redraw=True)

    def _apply_section_label(self):
        if not self.workspace or self.selected_section_index is None:
            messagebox.showwarning("PythonDancer", "Click a section block first."); return
        try: self.workspace.set_section_label(self.selected_section_index, self.section_label_var.get())
        except Exception as exc: messagebox.showerror("PythonDancer", str(exc)); return
        self._apply_workspace(redraw=True)

    def _section_at(self, at: float):
        if not self.workspace: return None
        for block in self.workspace.sections:
            if block.start <= at <= block.end: return block
        return None

    def _regenerate_selection(self):
        if not self.workspace or self.base_plan is None or self.data is None or self.generated_config is None: return
        sel = self.workspace.selection.normalized(self.workspace.duration)
        if sel.duration < .05:
            messagebox.showwarning("PythonDancer", "Drag a timeline range first."); return
        try:
            local_config = replace(self.generated_config, preset=self.local_preset_var.get(), strength=float(self.local_strength_var.get()), gesture_strength=float(self.local_gesture_var.get()))
            candidate = plan_multiaxis(self.data, local_config)
            section = self._section_at((sel.start + sel.end) / 2.)
            if section is not None:
                gesture = SECTION_DEFAULT_GESTURE.get(section.label)
                if gesture:
                    from .workspace import apply_gesture_blocks
                    candidate = apply_gesture_blocks(candidate, [GestureBlock(sel.start, sel.end, gesture, max(.25, float(self.local_gesture_var.get()) * .55))])
            self.base_plan = splice_plan(self.base_plan, candidate, sel.start, sel.end, locked_axes=self.workspace.locked_axes(), blend=min(.35, sel.duration / 3.))
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"Local regeneration failed:\n{exc}"); return
        self.status_var.set(f"Regenerated {sel.start:.2f}–{sel.end:.2f}s; locked axes preserved.")
        self._apply_workspace(redraw=True)

    def _apply_workspace(self, redraw=True):
        if not self.workspace or self.base_plan is None: return
        self.plan = self.workspace.output_plan(self.base_plan)
        self.section_summary_var.set("Structure: " + " | ".join(f"{s.label}:{s.start:.1f}-{s.end:.1f}" for s in self.workspace.sections))
        self.selection_var.set(self._selection_label())
        if redraw:
            self.work_timeline.set_model(self.workspace, self.data)
            self._redraw_workspace_preview()
            self._draw_pose(float(self.timeline_var.get()))

    def _redraw_workspace_preview(self):
        if not self.workspace or self.base_plan is None: return
        preview = self.workspace.preview_plan(self.base_plan)
        for axis in AXIS_ORDER: self.preview_axes[axis].clear()
        self._style_axes()
        for axis in AXIS_ORDER:
            actions = preview[axis]
            if actions:
                t = np.asarray([a for a, _ in actions]); p = np.asarray([v for _, v in actions])
                self.preview_axes[axis].plot(t, p, linewidth=1.15, color=TRANSLATION if axis.startswith("L") else ROTATION)
            if self.workspace.axes[axis].muted:
                self.preview_axes[axis].text(.5, .5, "MUTED", transform=self.preview_axes[axis].transAxes, ha="center", va="center", color=MUTED, fontsize=10, fontweight="bold")
            elif self.workspace.axes[axis].locked:
                self.preview_axes[axis].text(.98, .08, "LOCK", transform=self.preview_axes[axis].transAxes, ha="right", color=MUTED, fontsize=7)
            for section in self.workspace.sections[1:]:
                self.preview_axes[axis].axvline(section.start, color=MUTED, linewidth=.6, alpha=.2)
            sel = self.workspace.selection.normalized(self.workspace.duration)
            if sel.duration > .001: self.preview_axes[axis].axvspan(sel.start, sel.end, color=ACCENT, alpha=.06)
        self.canvas.draw_idle()

    def _pose_values(self, at: float):
        plan = self.plan or self.base_plan or {axis: [] for axis in AXIS_ORDER}
        return {axis: sample_axis(plan.get(axis, ()), at, 50.) for axis in AXIS_ORDER}

    @staticmethod
    def _rotation_matrix(yaw, roll, pitch):
        cy, sy = math.cos(yaw), math.sin(yaw); cr, sr = math.cos(roll), math.sin(roll); cp, sp = math.cos(pitch), math.sin(pitch)
        rz = np.array([[cy,-sy,0],[sy,cy,0],[0,0,1.]])
        rx = np.array([[1.,0,0],[0,cr,-sr],[0,sr,cr]])
        ry = np.array([[cp,0,sp],[0,1.,0],[-sp,0,cp]])
        return rz @ ry @ rx

    def _draw_pose(self, at: float):
        if not hasattr(self, "pose_axes"): return
        values = self._pose_values(float(at))
        norm = {axis: (values[axis] - 50.) / 50. for axis in AXIS_ORDER}
        center = np.array([norm["L2"] * .55, norm["L1"] * .55, .65 + (norm["L0"] + 1.) * .35])
        R = self._rotation_matrix(norm["R0"] * math.radians(28), norm["R1"] * math.radians(22), norm["R2"] * math.radians(22))
        local = np.array([[-.45,-.32,0],[.45,-.32,0],[.45,.32,0],[-.45,.32,0]])
        top = local @ R.T + center
        base = np.array([[-.55,-.4,0],[.55,-.4,0],[.55,.4,0],[-.55,.4,0]])
        ax = self.pose_axes; ax.clear(); ax.set_facecolor(PLOT_BG)
        for poly, color in ((base, "#94A3B8"), (top, ACCENT)):
            closed = np.vstack([poly, poly[0]])
            ax.plot(closed[:,0], closed[:,1], closed[:,2], color=color, linewidth=2)
        for i in range(4): ax.plot([base[i,0], top[i,0]], [base[i,1], top[i,1]], [base[i,2], top[i,2]], color="#CBD5E1", linewidth=1)
        ax.scatter([center[0]], [center[1]], [center[2]], color=ACCENT, s=24)
        ax.set_xlim(-1.2,1.2); ax.set_ylim(-1.2,1.2); ax.set_zlim(0,1.5); ax.set_box_aspect((1,1,.8)); ax.view_init(elev=25, azim=-55)
        ax.set_title(f"Pose @ {at:.2f}s  ·  " + "  ".join(f"{axis} {values[axis]:.0f}" for axis in AXIS_ORDER), fontsize=9, color=TEXT)
        ax.set_xlabel("sway"); ax.set_ylabel("surge"); ax.set_zlabel("stroke")
        ax.tick_params(labelsize=7, colors=MUTED)
        self.pose_canvas.draw_idle()

    def _timeline_release(self, event):
        super()._timeline_release(event)
        self._draw_pose(float(self.timeline_var.get()))

    def _tick_playback(self):
        super()._tick_playback()
        if hasattr(self, "pose_canvas"):
            at = float(self.timeline_var.get())
            if abs(at - self._last_pose_at) >= .18:
                self._last_pose_at = at
                self._draw_pose(at)

    def _export_metadata(self):
        metadata = super()._export_metadata()
        if self.workspace is not None:
            metadata["workspace"] = self.workspace.to_dict()
            metadata["choreography_sections"] = " | ".join(f"{s.label}:{s.start:.2f}-{s.end:.2f}" for s in self.workspace.sections)
            metadata["notes"] = str(metadata.get("notes", "")) + "; editor=workstation-2.4"
        return metadata


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()


if __name__ == "__main__":
    from .util import cli_args
    ux(cli_args().parse_args())
