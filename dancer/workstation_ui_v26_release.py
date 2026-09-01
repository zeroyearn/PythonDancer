"""PythonDancer 2.6 release workstation.

Final integration layer: bilingual Chinese/English GUI, calibration-aware
optimizer limits, portable SR6 geometry profiles and firmware-model mechanical
reachability diagnostics in the 3D workstation/export metadata.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .generation_limits import optimizer_from_calibration
from .geometry_profile import load_geometry_profile
from .i18n import LANG_EN, LANG_ZH, detect_language
from .i18n_safe import SafeI18nController
from .kinematics import SR6Geometry, solve_sr6_pose, trajectory_kinematics_diagnostics
from .workstation_ui_v26_final import MultiAxisWindow as _V26FinalWindow


class MultiAxisWindow(_V26FinalWindow):
    def _build_ui(self):
        self.sr6_geometry = SR6Geometry()
        self.sr6_geometry_path_var = tk.StringVar(value="")
        self.sr6_summary_var = tk.StringVar(value="SR6 diagnostics: default firmware geometry")
        self.sr6_pose_status_var = tk.StringVar(value="SR6 pose: not evaluated")
        self.language_var = tk.StringVar(value=detect_language())
        self.i18n = None
        super()._build_ui()
        self.title("PythonDancer 2.6 · Generation Quality Workstation")
        self.i18n = SafeI18nController(self, self.language_var.get())
        self._install_language_menu()
        self.i18n.bind_object(self)
        self.i18n.refresh(force=True)
        self.after(180, self._i18n_tick)

    # ---------- bilingual UI ----------
    def _install_language_menu(self):
        menu_name = self.cget("menu")
        menu = self.nametowidget(menu_name) if menu_name else tk.Menu(self)
        if not menu_name:
            self.configure(menu=menu)
        language_menu = tk.Menu(menu, tearoff=False)
        language_menu.add_radiobutton(label="简体中文", value=LANG_ZH, variable=self.language_var, command=self._language_changed)
        language_menu.add_radiobutton(label="English", value=LANG_EN, variable=self.language_var, command=self._language_changed)
        menu.add_cascade(label="Language", menu=language_menu)

    def _language_changed(self):
        if self.i18n is not None:
            self.i18n.set_language(self.language_var.get())
            self._draw_pose(float(self.timeline_var.get()))

    def _i18n_tick(self):
        try:
            if self.i18n is not None:
                self.i18n.refresh()
            self.after(220, self._i18n_tick)
        except tk.TclError:
            return

    def _tr(self, text: str) -> str:
        return self.i18n.tr(text) if self.i18n is not None else text

    # ---------- SR6 UI ----------
    def _build_export_card(self, parent):
        super()._build_export_card(parent)
        card, body = self._card(
            parent,
            "SR6 mechanical diagnostics",
            "Firmware-model linkage solving is diagnostic only; real servo control remains inside the TCode device firmware.",
        )
        card.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        self._label(body, "SR6 geometry", 0)
        row = ttk.Frame(body, style="Card.TFrame")
        row.grid(row=0, column=1, sticky="ew", padx=(8, 0)); row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.sr6_geometry_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Load geometry…", command=self.browse_sr6_geometry, style="Compact.TButton").grid(row=0, column=1, padx=(6, 0))
        ttk.Label(body, textvariable=self.sr6_summary_var, style="Muted.TLabel", wraplength=270).grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))

    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        for tab_id in notebook.tabs():
            if str(notebook.tab(tab_id, "text")) != "3D Pose":
                continue
            pose = notebook.nametowidget(tab_id)
            pose.rowconfigure(0, weight=1)
            ttk.Label(pose, textvariable=self.sr6_pose_status_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))
            break

    def browse_sr6_geometry(self):
        path = filedialog.askopenfilename(
            title="Open SR6 geometry profile",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._load_sr6_geometry(path)

    def _load_sr6_geometry(self, path: str, *, silent=False):
        try:
            geometry = load_geometry_profile(path)
        except Exception as exc:
            if not silent:
                messagebox.showerror("PythonDancer", f"SR6 geometry load failed:\n{exc}")
            return False
        self.sr6_geometry = geometry
        self.sr6_geometry_path_var.set(str(path))
        self.sr6_summary_var.set(f"SR6 diagnostics: loaded geometry · receiver X {geometry.receiver_x_hundredths_mm / 100.0:.1f} mm")
        if self.plan:
            self._update_sr6_diagnostics(self.plan)
        return True

    # ---------- calibration-aware generation ----------
    def _quality_config(self):
        independent, optimizer = super()._quality_config()
        optimizer = optimizer_from_calibration(optimizer, self.calibration_profile)
        return independent, optimizer

    def _load_calibration(self, path: str, *, silent=False):
        result = super()._load_calibration(path, silent=silent)
        if result and self.generated_config is not None:
            self.generated_config = replace(
                self.generated_config,
                optimizer=optimizer_from_calibration(self.generated_config.optimizer, self.calibration_profile),
            )
        return result

    # ---------- mechanical simulation / diagnostics ----------
    def _update_sr6_diagnostics(self, plan):
        diagnostics = trajectory_kinematics_diagnostics(plan, self.sr6_geometry)
        self.sr6_summary_var.set(
            "SR6 diagnostics: "
            f"{diagnostics['unreachable_ratio'] * 100.0:.1f}% unreachable · "
            f"max servo {diagnostics['max_abs_servo_angle_deg']:.1f}° · "
            f"{diagnostics['samples']} samples"
        )
        return diagnostics

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self._update_sr6_diagnostics(plan)
        self._draw_pose(float(self.timeline_var.get()))

    def _draw_pose(self, at: float):
        super()._draw_pose(at)
        if not hasattr(self, "pose_axes"):
            return
        solution = solve_sr6_pose(self._pose_values(at), self.sr6_geometry)
        state = "Reachable" if solution.reachable else "Unreachable"
        angles = " · ".join(
            f"{name.replace('_', ' ')} {angle * 57.2957795:+.1f}°"
            for name, angle in solution.servo_angles_rad.items()
        )
        raw = f"SR6 pose: {state} · max servo {solution.max_abs_angle_deg:.1f}° · twist {solution.twist_normalized:+.2f}"
        self.sr6_pose_status_var.set(raw)
        detail = self._tr(state) + "\n" + angles
        try:
            self.pose_axes.text2D(
                .02, .02, detail,
                transform=self.pose_axes.transAxes,
                fontsize=7,
                va="bottom",
                ha="left",
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": .78, "edgecolor": "#CBD5E1"},
            )
            self.pose_canvas.draw_idle()
        except Exception:
            pass

    # ---------- project/export persistence ----------
    def _project_document(self):
        project = super()._project_document()
        project.ui["language"] = self.language_var.get()
        project.device["sr6_geometry_profile"] = self.sr6_geometry_path_var.get().strip()
        return project

    def _load_project_document(self, project):
        super()._load_project_document(project)
        geometry_path = str((project.device or {}).get("sr6_geometry_profile", "") or "")
        if geometry_path:
            self._load_sr6_geometry(geometry_path, silent=True)
        language = str((project.ui or {}).get("language", "") or "")
        if language in (LANG_ZH, LANG_EN):
            self.language_var.set(language)
            if self.i18n is not None:
                self.i18n.set_language(language)
        if self.plan:
            self._update_sr6_diagnostics(self.plan)
            self._draw_pose(float(self.timeline_var.get()))

    def _export_metadata(self):
        metadata = super()._export_metadata()
        plan = self.plan or self.base_plan
        if plan:
            metadata["sr6_kinematics"] = self._update_sr6_diagnostics(plan)
            metadata["sr6_geometry"] = {
                name: float(getattr(self.sr6_geometry, name))
                for name in self.sr6_geometry.__dataclass_fields__
            }
        metadata["ui_language"] = self.language_var.get()
        return metadata


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
