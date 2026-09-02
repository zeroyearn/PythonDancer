"""PythonDancer 2.8 AI Choreography DAW workstation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .automation import AutomationSet, MotionIntent, StyleKeyframe, StyleMorphTimeline
from .candidate_composer import CandidateComposition, auto_assign_by_section_scores, compose_candidates
from .candidates import generate_candidates
from .daw_transform import apply_daw_transform
from .device_twin import DeviceTwinProfile, load_device_twin, save_device_twin
from .i18n_v28 import install_v28_translations
from .live import LiveChoreographyConfig, LiveChoreographyEngine
from .live_io import LiveSession, SoundDeviceLiveSource, TCodeLiveSink, list_audio_devices
from .multiaxis import AXIS_ORDER
from .workspace_constraints import constrain_workspace_plan
from .workstation_ui_v27_async import MultiAxisWindow as _V27AsyncWindow
from .workstation_ui_v27_hotfix import _effective_output_snapshot
from .workstation_ui_v27_release import _QualityHistory


STYLE_PRESETS = {
    "Smooth": MotionIntent(intensity=.52, aggression=.20, flow=.90, complexity=.38, symmetry=.76, rotation_bias=.55, translation_bias=.48, accent_density=.28),
    "Expressive": MotionIntent(intensity=.76, aggression=.46, flow=.78, complexity=.68, symmetry=.50, rotation_bias=.72, translation_bias=.62, accent_density=.58),
    "Aggressive": MotionIntent(intensity=.92, aggression=.92, flow=.30, complexity=.72, symmetry=.30, rotation_bias=.62, translation_bias=.86, accent_density=.94),
    "Rotation": MotionIntent(intensity=.70, aggression=.48, flow=.72, complexity=.70, symmetry=.42, rotation_bias=.96, translation_bias=.26, accent_density=.58),
    "Minimal": MotionIntent(intensity=.34, aggression=.18, flow=.74, complexity=.18, symmetry=.82, rotation_bias=.36, translation_bias=.38, accent_density=.16),
}


class _DAWHistory(_QualityHistory):
    @staticmethod
    def capture(window):
        snapshot = _QualityHistory.capture(window)
        snapshot["automation"] = deepcopy(getattr(window, "automation", AutomationSet()))
        snapshot["style_morph"] = deepcopy(getattr(window, "style_morph", StyleMorphTimeline()))
        snapshot["candidate_composition"] = deepcopy(getattr(window, "candidate_composition", CandidateComposition()))
        snapshot["device_twin"] = deepcopy(getattr(window, "device_twin", DeviceTwinProfile()))
        return snapshot


class MultiAxisWindow(_V27AsyncWindow):
    def _build_ui(self):
        install_v28_translations()
        self.automation = AutomationSet()
        self.style_morph = StyleMorphTimeline()
        self.candidate_composition = CandidateComposition()
        self.device_twin = DeviceTwinProfile()
        self.live_session: LiveSession | None = None
        self.live_audio_devices = []

        self.automation_lane_var = tk.StringVar(value="energy")
        self.automation_time_var = tk.DoubleVar(value=0.0)
        self.automation_value_var = tk.DoubleVar(value=1.0)
        self.automation_easing_var = tk.StringVar(value="smoothstep")
        self.style_time_var = tk.DoubleVar(value=0.0)
        self.style_name_var = tk.StringVar(value="Smooth")
        self.style_strength_var = tk.DoubleVar(value=1.0)
        self.composer_section_var = tk.StringVar(value="")
        self.composer_candidate_var = tk.StringVar(value="")
        self.composer_summary_var = tk.StringVar(value="Candidate composition: not configured")
        self.twin_summary_var = tk.StringVar(value="Device Twin: default SR6 safe profile")
        self.live_audio_var = tk.StringVar(value="")
        self.live_bpm_var = tk.DoubleVar(value=120.0)
        self.live_prediction_var = tk.DoubleVar(value=420.0)
        self.live_send_tcode_var = tk.BooleanVar(value=False)
        self.live_status_var = tk.StringVar(value="Live idle")
        self.live_pose_var = tk.StringVar(value="—")

        super()._build_ui()
        self.history = _DAWHistory(limit=100)
        self.title("PythonDancer 2.8 · AI Choreography DAW")
        if self.i18n is not None:
            self.i18n.bind_object(self)
            self.i18n.refresh(force=True)
        self.after(150, self._refresh_audio_devices)

    # ---------- tab layout ----------
    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        daw = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        daw.columnconfigure(0, weight=1); daw.columnconfigure(1, weight=1)
        daw.rowconfigure(1, weight=1)
        notebook.add(daw, text="DAW Automation")
        self._build_automation_panel(daw)
        self._build_style_panel(daw)
        self._build_composer_panel(daw)

        live = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        live.columnconfigure(1, weight=1)
        notebook.add(live, text="Live Choreography")
        self._build_live_panel(live)

    def _build_automation_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="Automation lanes", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Lane", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(frame, textvariable=self.automation_lane_var, values=tuple(self.automation.lanes), state="readonly")
        combo.grid(row=0, column=1, sticky="ew", padx=(6, 0)); combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_automation_tree())
        ttk.Label(frame, text="Point time", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Spinbox(frame, textvariable=self.automation_time_var, from_=0, to=99999, increment=.1).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(7, 0))
        ttk.Label(frame, text="Point value", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(7, 0))
        ttk.Spinbox(frame, textvariable=self.automation_value_var, from_=0, to=3, increment=.05).grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(7, 0))
        ttk.Label(frame, text="Easing", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(7, 0))
        ttk.Combobox(frame, textvariable=self.automation_easing_var, values=("linear", "smoothstep", "ease-in", "ease-out"), state="readonly").grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(7, 0))
        row = ttk.Frame(frame, style="Card.TFrame"); row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0)); row.columnconfigure((0,1,2), weight=1)
        ttk.Button(row, text="Add / update point", command=self._add_automation_point, style="Compact.TButton").grid(row=0, column=0, sticky="ew", padx=(0,3))
        ttk.Button(row, text="Remove nearest", command=self._remove_automation_point, style="Compact.TButton").grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(row, text="Quantize to beats", command=self._quantize_automation, style="Compact.TButton").grid(row=0, column=2, sticky="ew", padx=(3,0))
        self.automation_tree = ttk.Treeview(frame, columns=("time","value","easing"), show="headings", height=7)
        self.automation_tree.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        for name, width in (("time",80),("value",80),("easing",110)):
            self.automation_tree.heading(name, text=name.title()); self.automation_tree.column(name, width=width, anchor="center")

    def _build_style_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="Style Morphing", padding=10)
        frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Style time", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(frame, textvariable=self.style_time_var, from_=0, to=99999, increment=.1).grid(row=0, column=1, sticky="ew", padx=(6,0))
        ttk.Label(frame, text="Style", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(7,0))
        ttk.Combobox(frame, textvariable=self.style_name_var, values=tuple(STYLE_PRESETS), state="readonly").grid(row=1, column=1, sticky="ew", padx=(6,0), pady=(7,0))
        ttk.Label(frame, text="Style strength", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(7,0))
        ttk.Spinbox(frame, textvariable=self.style_strength_var, from_=0, to=2, increment=.05).grid(row=2, column=1, sticky="ew", padx=(6,0), pady=(7,0))
        row = ttk.Frame(frame, style="Card.TFrame"); row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8,0)); row.columnconfigure((0,1), weight=1)
        ttk.Button(row, text="Add style keyframe", command=self._add_style_keyframe, style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,3))
        ttk.Button(row, text="Remove style keyframe", command=self._remove_style_keyframe, style="Compact.TButton").grid(row=0,column=1,sticky="ew",padx=(3,0))
        self.style_tree = ttk.Treeview(frame, columns=("time","style","strength"), show="headings", height=7)
        self.style_tree.grid(row=4,column=0,columnspan=2,sticky="nsew",pady=(8,0))
        for name,width in (("time",75),("style",130),("strength",75)):
            self.style_tree.heading(name,text=name.title()); self.style_tree.column(name,width=width,anchor="center")

    def _build_composer_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="Candidate Composer", padding=10)
        frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10,0))
        frame.columnconfigure(1, weight=1); frame.columnconfigure(3, weight=1)
        ttk.Label(frame, text="Section", style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        self.composer_section_combo = ttk.Combobox(frame,textvariable=self.composer_section_var,state="readonly")
        self.composer_section_combo.grid(row=0,column=1,sticky="ew",padx=(6,10))
        ttk.Label(frame,text="Candidate",style="Muted.TLabel").grid(row=0,column=2,sticky="w")
        self.composer_candidate_combo = ttk.Combobox(frame,textvariable=self.composer_candidate_var,state="readonly")
        self.composer_candidate_combo.grid(row=0,column=3,sticky="ew",padx=(6,0))
        row=ttk.Frame(frame,style="Card.TFrame"); row.grid(row=1,column=0,columnspan=4,sticky="ew",pady=(8,0)); row.columnconfigure((0,1,2),weight=1)
        ttk.Button(row,text="Assign section",command=self._assign_candidate_section,style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,3))
        ttk.Button(row,text="Auto assign",command=self._auto_assign_composer,style="Compact.TButton").grid(row=0,column=1,sticky="ew",padx=3)
        ttk.Button(row,text="Compose sections",command=self._compose_candidate_sections,style="Soft.TButton").grid(row=0,column=2,sticky="ew",padx=(3,0))
        self.composer_tree=ttk.Treeview(frame,columns=("section","candidate"),show="headings",height=6)
        self.composer_tree.grid(row=2,column=0,columnspan=4,sticky="ew",pady=(8,0)); self.composer_tree.heading("section",text="Section"); self.composer_tree.heading("candidate",text="Candidate")
        ttk.Label(frame,textvariable=self.composer_summary_var,style="Muted.TLabel").grid(row=3,column=0,columnspan=4,sticky="w",pady=(6,0))

    def _build_live_panel(self, frame):
        ttk.Label(frame,text="Audio input",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        self.live_audio_combo=ttk.Combobox(frame,textvariable=self.live_audio_var,state="readonly")
        self.live_audio_combo.grid(row=0,column=1,sticky="ew",padx=(8,8))
        ttk.Button(frame,text="Refresh devices",command=self._refresh_audio_devices,style="Compact.TButton").grid(row=0,column=2)
        ttk.Label(frame,text="Live BPM",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(8,0))
        ttk.Spinbox(frame,textvariable=self.live_bpm_var,from_=30,to=300,increment=.1).grid(row=1,column=1,sticky="ew",padx=(8,0),pady=(8,0))
        ttk.Label(frame,text="Prediction horizon",style="Muted.TLabel").grid(row=2,column=0,sticky="w",pady=(8,0))
        ttk.Spinbox(frame,textvariable=self.live_prediction_var,from_=50,to=1200,increment=10).grid(row=2,column=1,sticky="ew",padx=(8,0),pady=(8,0))
        ttk.Checkbutton(frame,text="Send TCode",variable=self.live_send_tcode_var).grid(row=3,column=0,columnspan=2,sticky="w",pady=(10,0))
        row=ttk.Frame(frame,style="Card.TFrame"); row.grid(row=4,column=0,columnspan=3,sticky="ew",pady=(10,0)); row.columnconfigure((0,1),weight=1)
        ttk.Button(row,text="Start live",command=self.start_live,style="Accent.TButton").grid(row=0,column=0,sticky="ew",padx=(0,4))
        ttk.Button(row,text="Stop live",command=self.stop_live,style="Danger.TButton").grid(row=0,column=1,sticky="ew",padx=(4,0))
        ttk.Label(frame,textvariable=self.live_status_var,style="Metric.TLabel").grid(row=5,column=0,columnspan=3,sticky="w",pady=(12,0))
        ttk.Label(frame,textvariable=self.live_pose_var,style="Muted.TLabel",wraplength=760).grid(row=6,column=0,columnspan=3,sticky="w",pady=(6,0))
        twin=ttk.LabelFrame(frame,text="Device Twin",padding=10); twin.grid(row=7,column=0,columnspan=3,sticky="ew",pady=(14,0)); twin.columnconfigure(0,weight=1)
        ttk.Checkbutton(twin,text="Safe mode",command=self._toggle_twin_safe_mode).grid(row=0,column=0,sticky="w")
        buttons=ttk.Frame(twin,style="Card.TFrame"); buttons.grid(row=1,column=0,sticky="ew",pady=(8,0)); buttons.columnconfigure((0,1,2),weight=1)
        ttk.Button(buttons,text="Load twin…",command=self.load_twin_dialog,style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,3))
        ttk.Button(buttons,text="Save twin…",command=self.save_twin_dialog,style="Compact.TButton").grid(row=0,column=1,sticky="ew",padx=3)
        ttk.Button(buttons,text="Apply twin",command=self.apply_device_twin,style="Compact.TButton").grid(row=0,column=2,sticky="ew",padx=(3,0))
        ttk.Label(twin,textvariable=self.twin_summary_var,style="Muted.TLabel",wraplength=740).grid(row=2,column=0,sticky="w",pady=(7,0))

    # ---------- final output / candidate truth ----------
    def _apply_workspace(self, redraw=True):
        super()._apply_workspace(redraw=False)
        if self.plan is None:
            return
        self.plan = apply_daw_transform(self.plan, self.automation, self.style_morph)
        self.plan = constrain_workspace_plan(self.plan, self.generated_config)
        if redraw:
            self.work_timeline.set_model(self.workspace, self.data)
            self._redraw_workspace_preview(); self._draw_pose(float(self.timeline_var.get())); self._redraw_curve_editor(); self._redraw_diagnostics()

    def _candidate_context(self):
        return super()._candidate_context() + (repr(self.automation.to_dict()), repr(self.style_morph.to_dict()))

    def _effective_candidate_plan(self, candidate):
        plan = super()._effective_candidate_plan(candidate)
        plan = apply_daw_transform(plan, self.automation, self.style_morph)
        return constrain_workspace_plan(plan, replace(candidate.config, mechanical=self._mechanical_config(), geometry=self.sr6_geometry))

    def generate_quality_candidates(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before generating candidates."); return
        if self.data is None or self.generated_config is None or self.base_plan is None or self.workspace is None or (self.quality_worker and self.quality_worker.is_alive()):
            return
        try:
            count=max(2,min(8,int(self.quality_candidate_count_var.get()))); config=self._v27_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer",str(exc)); return
        data=self.data; sections=self._sections_payload(); geometry=self.sr6_geometry
        base_plan=deepcopy(self.base_plan); workspace=deepcopy(self.workspace); curves=deepcopy(self.curve_settings); safety=deepcopy(self.safety_settings)
        automation=deepcopy(self.automation); styles=deepcopy(self.style_morph); context=self._candidate_context()
        self._candidate_generation_context=context; self._candidate_scores_stale=False
        self.generate_candidates_button.configure(state="disabled"); self.comparison_summary_var.set("Generating and scoring DAW candidates…")
        def transform(plan,candidate_config):
            effective_config=replace(candidate_config,mechanical=config.mechanical,geometry=geometry)
            output=_effective_output_snapshot(plan,effective_config,base_plan=base_plan,workspace=workspace,curve_settings=curves,safety_settings=safety,data=data)
            output=apply_daw_transform(output,automation,styles)
            return constrain_workspace_plan(output,effective_config)
        def work():
            try:
                results=generate_candidates(data,config,count=count,geometry=geometry,sections=sections,score_transform=transform)
                self.after(0,lambda:self._candidates_done(results))
            except Exception as exc:self.after(0,lambda e=exc:self._quality_failed(e))
        self.quality_worker=Thread(target=work,daemon=True); self.quality_worker.start()

    # ---------- automation/style ----------
    def _daw_changed(self, status):
        self._apply_workspace(redraw=True); self._mark_changed(); self.score_current(); self.status_var.set(status)

    def _add_automation_point(self):
        lane=self.automation.lanes[self.automation_lane_var.get()]; self._checkpoint()
        lane.set_point(float(self.automation_time_var.get()),float(self.automation_value_var.get()),easing=self.automation_easing_var.get())
        self._refresh_automation_tree(); self._daw_changed("Automation updated")

    def _remove_automation_point(self):
        lane=self.automation.lanes[self.automation_lane_var.get()]; self._checkpoint(); lane.remove_near(float(self.automation_time_var.get()),.08)
        self._refresh_automation_tree(); self._daw_changed("Automation updated")

    def _quantize_automation(self):
        lane=self.automation.lanes[self.automation_lane_var.get()]; self._checkpoint(); lane.quantize((self.data or {}).get("beats",[]))
        self._refresh_automation_tree(); self._daw_changed("Automation updated")

    def _refresh_automation_tree(self):
        if not hasattr(self,"automation_tree"):return
        for item in self.automation_tree.get_children():self.automation_tree.delete(item)
        lane=self.automation.lanes[self.automation_lane_var.get()]
        self.automation_value_var.set(lane.default)
        for point in lane.points:self.automation_tree.insert("","end",values=(f"{point.time:.2f}",f"{point.value:.3f}",point.easing))

    def _add_style_keyframe(self):
        name=self.style_name_var.get(); self._checkpoint(); key=StyleKeyframe(float(self.style_time_var.get()),name,STYLE_PRESETS[name],float(self.style_strength_var.get()))
        self.style_morph.keyframes=[item for item in self.style_morph.keyframes if abs(item.time-key.time)>1e-6]+[key]; self.style_morph.keyframes.sort(key=lambda item:item.time)
        self._refresh_style_tree(); self._daw_changed("Style morph updated")

    def _remove_style_keyframe(self):
        at=float(self.style_time_var.get()); self._checkpoint(); self.style_morph.keyframes=[item for item in self.style_morph.keyframes if abs(item.time-at)>.08]
        self._refresh_style_tree(); self._daw_changed("Style morph updated")

    def _refresh_style_tree(self):
        if not hasattr(self,"style_tree"):return
        for item in self.style_tree.get_children():self.style_tree.delete(item)
        for key in self.style_morph.keyframes:self.style_tree.insert("","end",values=(f"{key.time:.2f}",key.name,f"{key.strength:.2f}"))

    # ---------- candidate composer ----------
    def _refresh_composer(self):
        if not hasattr(self,"composer_section_combo"):return
        sections=[f"{i+1} · {s.label} · {s.start:.1f}-{s.end:.1f}s" for i,s in enumerate(self.workspace.sections)] if self.workspace else []
        names=[item.name for item in self.quality_candidates]
        self.composer_section_combo["values"]=sections; self.composer_candidate_combo["values"]=names
        if sections and self.composer_section_var.get() not in sections:self.composer_section_var.set(sections[0])
        if names and self.composer_candidate_var.get() not in names:self.composer_candidate_var.set(names[0])
        for item in self.composer_tree.get_children():self.composer_tree.delete(item)
        if self.workspace:
            for index,name in sorted(self.candidate_composition.assignments.items()):
                if 0<=index<len(self.workspace.sections):self.composer_tree.insert("","end",values=(self.workspace.sections[index].label,name))

    def _assign_candidate_section(self):
        try:index=int(self.composer_section_var.get().split("·",1)[0].strip())-1
        except Exception:return
        name=self.composer_candidate_var.get().strip()
        if not name:return
        self._checkpoint(); self.candidate_composition.assign(index,name); self._refresh_composer(); self._mark_changed()

    def _auto_assign_composer(self):
        if not self.quality_candidates or not self.workspace:return
        self._checkpoint(); self.candidate_composition=auto_assign_by_section_scores(self.quality_candidates,self.workspace.sections); self._refresh_composer(); self._mark_changed()

    def _compose_candidate_sections(self):
        if not self.quality_candidates or not self.workspace:return
        try:
            merged,choices=compose_candidates(self.quality_candidates,self.workspace.sections,self.candidate_composition,base_plan=self.base_plan,locked_axes=self.workspace.locked_axes())
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc));return
        self._checkpoint(); self.base_plan=merged; self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        self.composer_summary_var.set("Candidate composition · "+" | ".join(f"{i+1}:{name}" for i,name in sorted(choices.items())))

    def _candidates_done(self, results):
        super()._candidates_done(results); self._refresh_composer()

    # ---------- device twin ----------
    def _toggle_twin_safe_mode(self):
        self.device_twin=replace(self.device_twin,safe_mode=not self.device_twin.safe_mode); self.apply_device_twin()

    def load_twin_dialog(self):
        path=filedialog.askopenfilename(title="Load device twin",filetypes=[("Device Twin","*.json"),("All files","*.*")])
        if not path:return
        try:self.device_twin=load_device_twin(path); self.apply_device_twin(); self.twin_summary_var.set(f"Device twin loaded · {self.device_twin.name}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def save_twin_dialog(self):
        path=filedialog.asksaveasfilename(title="Save device twin",defaultextension=".json",filetypes=[("JSON","*.json")])
        if not path:return
        try:save_device_twin(path,self.device_twin); self.twin_summary_var.set(f"Device twin saved · {self.device_twin.name}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def apply_device_twin(self):
        self._checkpoint(); twin=self.device_twin
        self.sr6_geometry=twin.geometry; self.calibration_profile=twin.calibration
        self.latency_ms_var.set(twin.timing.latency_ms); self.manual_offset_var.set(twin.timing.manual_offset_ms)
        self.mechanical_projection_var.set(twin.mechanical.enabled); self.mechanical_max_risk_var.set(twin.mechanical.max_risk); self.servo_limit_var.set(twin.mechanical.servo_limit_deg); self.singularity_sensitivity_var.set(twin.mechanical.sensitivity_limit_deg_per_unit)
        self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        self.twin_summary_var.set(f"Device Twin · {twin.name} · {twin.device_type} · safe {'on' if twin.safe_mode else 'off'} · latency {twin.timing.command_lead_ms:.1f} ms")

    # ---------- live ----------
    def _refresh_audio_devices(self):
        try:self.live_audio_devices=[item for item in list_audio_devices() if item["inputs"]>0]
        except Exception as exc:self.live_audio_devices=[]; self.live_status_var.set(f"Live audio unavailable: {exc}"); return
        values=[f"{item['index']} · {item['name']}" for item in self.live_audio_devices]; self.live_audio_combo["values"]=values
        if values:self.live_audio_var.set(values[0]); self.live_status_var.set(f"Live ready · {len(values)} input(s)")

    def start_live(self):
        if self.live_session and self.live_session.worker and self.live_session.worker.is_alive():return
        try:
            selected=self.live_audio_var.get().strip(); device=int(selected.split("·",1)[0].strip()) if selected else None
            bpm=float(self.live_bpm_var.get()); horizon=float(self.live_prediction_var.get())
            engine=LiveChoreographyEngine(LiveChoreographyConfig(prediction_horizon_ms=horizon,latency_ms=self.device_twin.timing.command_lead_ms))
            source=SoundDeviceLiveSource(device=device)
            sink=None
            if self.live_send_tcode_var.get():
                port=self.port_var.get().strip()
                if not port:raise ValueError("Select a serial port before enabling live TCode output")
                sink=TCodeLiveSink(port,baud=int(self.baud_var.get()),timeout=float(self.args.serial_timeout))
            def safe_pose(pose):
                mapped,_,_=self.device_twin.safe_pose(pose,calibrate=True); return mapped
            def on_motion(features,motion,output_pose):
                if getattr(self,"_closing",False):return
                self.after(0,lambda:self._live_motion_update(features,motion,output_pose))
            self.live_session=LiveSession(source,engine,sink=sink,on_motion=on_motion,pose_transform=safe_pose,bpm=bpm); self.live_session.start(); self.live_status_var.set("Live running")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc)); self.live_status_var.set(f"Live failed: {exc}")

    def _live_motion_update(self,features,motion,output_pose):
        self.live_status_var.set(f"LIVE · BPM {motion.bpm:.1f} · confidence {motion.beat_confidence*100:.0f}% · {motion.gesture} · predict {motion.prediction_ms:.0f} ms")
        self.live_pose_var.set(" · ".join(f"{axis} {output_pose.get(axis,50):.1f}" for axis in AXIS_ORDER))

    def stop_live(self):
        if self.live_session:self.live_session.stop()
        self.live_status_var.set("Live stopped")

    # ---------- history / persistence ----------
    def _restore_snapshot(self, snapshot):
        super()._restore_snapshot(snapshot)
        self.automation=deepcopy(snapshot.get("automation",AutomationSet())); self.style_morph=deepcopy(snapshot.get("style_morph",StyleMorphTimeline())); self.candidate_composition=deepcopy(snapshot.get("candidate_composition",CandidateComposition())); self.device_twin=deepcopy(snapshot.get("device_twin",DeviceTwinProfile()))
        self._refresh_automation_tree(); self._refresh_style_tree(); self._refresh_composer(); self._apply_workspace(redraw=True)

    def _generation_done(self,data,plan,analysis,config,pitch,energy):
        super()._generation_done(data,plan,analysis,config,pitch,energy); self.history=_DAWHistory(limit=100); self._refresh_composer()

    def _project_document(self):
        project=super()._project_document(); project.daw={"automation":self.automation.to_dict(),"style_morph":self.style_morph.to_dict(),"candidate_composition":self.candidate_composition.to_dict(),"device_twin":self.device_twin.to_dict(),"live":{"bpm":float(self.live_bpm_var.get()),"prediction_horizon_ms":float(self.live_prediction_var.get()),"send_tcode":bool(self.live_send_tcode_var.get())}}
        return project

    def _load_project_document(self,project):
        super()._load_project_document(project); state=project.daw or {}; self.automation=AutomationSet.from_dict(state.get("automation")); self.style_morph=StyleMorphTimeline.from_dict(state.get("style_morph")); self.candidate_composition=CandidateComposition.from_dict(state.get("candidate_composition"));
        if state.get("device_twin"):self.device_twin=DeviceTwinProfile.from_dict(state["device_twin"])
        live=state.get("live") or {}; self.live_bpm_var.set(float(live.get("bpm",120.0))); self.live_prediction_var.set(float(live.get("prediction_horizon_ms",420.0))); self.live_send_tcode_var.set(bool(live.get("send_tcode",False)))
        self._refresh_automation_tree(); self._refresh_style_tree(); self._refresh_composer(); self.apply_device_twin()

    def _export_metadata(self):
        metadata=super()._export_metadata(); metadata["daw"]={"version":"2.8","automation":self.automation.to_dict(),"style_morph":self.style_morph.to_dict(),"candidate_composition":self.candidate_composition.to_dict(),"device_twin":self.device_twin.to_dict()}; metadata["notes"]=str(metadata.get("notes", ""))+"; workstation=2.8-ai-choreography-daw"; return metadata

    def _on_close(self):
        self.stop_live(); return super()._on_close()


def ux(args):
    app=MultiAxisWindow(args); app.mainloop()
