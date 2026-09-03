"""PythonDancer 3.0 Intelligent Choreography workstation integration."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .automation import AutomationSet, StyleMorphTimeline
from .batch_queue import load_batch_manifest
from .candidates import CandidateResult
from .control_surface import ControlState, LinkClock, MidiControlBridge, OSCControlBridge, mappings_from_dict
from .copilot import apply_copilot_plan, compile_instruction
from .device_feedback import TelemetrySample, estimate_feedback, simulate_dynamic_load
from .device_twin import DeviceTwinProfile
from .i18n_v30 import install_v30_translations
from .motion_grammar import MotionPrimitive, MotionProgram, blend_motion_program
from .motion_pack import MotionPack, MotionPackManifest, load_motion_pack, save_motion_pack
from .plan_window import slice_plan
from .plugin_api import GLOBAL_PLUGINS
from .preferences import PreferenceModel, load_preference_model, save_preference_model
from .quality import score_plan
from .reference_retrieval import ReferenceSectionIndex, adapt_reference_plan, load_reference_index, plan_motion_features
from .versioning import ProjectVersionGraph
from .workspace import splice_plan
from .workstation_ui_v28_final import MultiAxisWindow as _V28Window


class MultiAxisWindow(_V28Window):
    def _build_ui(self):
        install_v30_translations()
        self.preference_model = PreferenceModel()
        self.motion_program = MotionProgram()
        self.version_graph = ProjectVersionGraph()
        self.reference_index = ReferenceSectionIndex()
        self.reference_matches = ()
        self.copilot_plan = None
        self.control_resources = []
        self.control_provider = None
        self.loaded_motion_pack = None

        self.copilot_instruction_var = tk.StringVar(value="")
        self.intelligence_summary_var = tk.StringVar(value="Copilot ready · deterministic operations → DAW → safety")
        self.preference_summary_var = tk.StringVar(value="Preference Learning · 0 observations")
        self.primitive_var = tk.StringVar(value="wave")
        self.primitive_start_var = tk.DoubleVar(value=0.0)
        self.primitive_end_var = tk.DoubleVar(value=8.0)
        self.primitive_amount_var = tk.DoubleVar(value=.75)
        self.primitive_cycles_var = tk.DoubleVar(value=4.0)
        self.motion_summary_var = tk.StringVar(value="Motion Grammar · empty program")
        self.reference_summary_var = tk.StringVar(value="Reference Retrieval · no index")
        self.version_message_var = tk.StringVar(value="Choreography edit")
        self.version_branch_var = tk.StringVar(value="experiment")
        self.version_summary_var = tk.StringVar(value="Project Versions · main")
        self.plugin_summary_var = tk.StringVar(value="Plugin SDK · not scanned")
        self.telemetry_summary_var = tk.StringVar(value="Device Twin 2.0 · no telemetry model")
        self.midi_input_var = tk.StringVar(value="")
        self.osc_port_var = tk.IntVar(value=9000)
        self.link_enabled_var = tk.BooleanVar(value=False)
        self.control_summary_var = tk.StringVar(value="Control Surfaces · stopped")
        self.batch_summary_var = tk.StringVar(value="Batch Queue · idle")

        super()._build_ui()
        self.title("PythonDancer 3.0 · Intelligent Choreography Workstation")
        if self.i18n is not None:
            self.i18n.bind_object(self)
            self.i18n.refresh(force=True)
        self._refresh_intelligence_panels()

    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        root = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        notebook.add(root, text="Intelligence")
        tabs = ttk.Notebook(root)
        tabs.grid(row=0, column=0, sticky="nsew")

        ai = ttk.Frame(tabs, style="Card.TFrame", padding=10)
        library = ttk.Frame(tabs, style="Card.TFrame", padding=10)
        ecosystem = ttk.Frame(tabs, style="Card.TFrame", padding=10)
        tabs.add(ai, text="Copilot & Learning")
        tabs.add(library, text="Library & Versions")
        tabs.add(ecosystem, text="Device & Ecosystem")
        self._build_copilot_learning(ai)
        self._build_library_versions(library)
        self._build_ecosystem(ecosystem)

    def _build_copilot_learning(self, parent):
        parent.columnconfigure(0, weight=1)
        copilot = ttk.LabelFrame(parent, text="Choreography Copilot", padding=10)
        copilot.grid(row=0, column=0, sticky="ew")
        copilot.columnconfigure(1, weight=1)
        ttk.Label(copilot, text="Instruction", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(copilot, textvariable=self.copilot_instruction_var).grid(row=0, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(copilot, text="Apply Copilot", command=self.apply_copilot, style="Accent.TButton").grid(row=0, column=2)
        ttk.Label(copilot, textvariable=self.intelligence_summary_var, style="Muted.TLabel", wraplength=820).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        preference = ttk.LabelFrame(parent, text="Preference Learning", padding=10)
        preference.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        preference.columnconfigure(4, weight=1)
        ttk.Button(preference, text="Prefer A", command=lambda: self.record_preference("A"), style="Compact.TButton").grid(row=0, column=0, padx=(0,4))
        ttk.Button(preference, text="Prefer B", command=lambda: self.record_preference("B"), style="Compact.TButton").grid(row=0, column=1, padx=4)
        ttk.Button(preference, text="Load preference…", command=self.load_preference_dialog, style="Compact.TButton").grid(row=0, column=2, padx=4)
        ttk.Button(preference, text="Save preference…", command=self.save_preference_dialog, style="Compact.TButton").grid(row=0, column=3, padx=4)
        ttk.Label(preference, textvariable=self.preference_summary_var, style="Muted.TLabel", wraplength=760).grid(row=1, column=0, columnspan=5, sticky="w", pady=(8,0))

        grammar = ttk.LabelFrame(parent, text="Motion Grammar", padding=10)
        grammar.grid(row=2, column=0, sticky="ew", pady=(10,0))
        grammar.columnconfigure(7, weight=1)
        ttk.Label(grammar, text="Primitive", style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Combobox(grammar, textvariable=self.primitive_var, values=("hold","drift","pulse","wave","spiral","orbit","rock","sweep","twist","accent","recoil"), state="readonly", width=12).grid(row=0,column=1,padx=(5,10))
        ttk.Label(grammar,text="Start",style="Muted.TLabel").grid(row=0,column=2)
        ttk.Spinbox(grammar,textvariable=self.primitive_start_var,from_=0,to=99999,increment=.1,width=8).grid(row=0,column=3,padx=(4,10))
        ttk.Label(grammar,text="End",style="Muted.TLabel").grid(row=0,column=4)
        ttk.Spinbox(grammar,textvariable=self.primitive_end_var,from_=0,to=99999,increment=.1,width=8).grid(row=0,column=5,padx=(4,10))
        ttk.Label(grammar,text="Amount",style="Muted.TLabel").grid(row=0,column=6)
        ttk.Spinbox(grammar,textvariable=self.primitive_amount_var,from_=0,to=2,increment=.05,width=8).grid(row=0,column=7,sticky="w",padx=(4,10))
        row = ttk.Frame(grammar, style="Card.TFrame"); row.grid(row=1,column=0,columnspan=8,sticky="ew",pady=(8,0)); row.columnconfigure((0,1,2),weight=1)
        ttk.Button(row,text="Add primitive",command=self.add_motion_primitive,style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,3))
        ttk.Button(row,text="Apply motion program",command=self.apply_motion_program,style="Accent.TButton").grid(row=0,column=1,sticky="ew",padx=3)
        ttk.Button(row,text="Clear program",command=self.clear_motion_program,style="Compact.TButton").grid(row=0,column=2,sticky="ew",padx=(3,0))
        ttk.Label(grammar,textvariable=self.motion_summary_var,style="Muted.TLabel").grid(row=2,column=0,columnspan=8,sticky="w",pady=(8,0))

    def _build_library_versions(self, parent):
        parent.columnconfigure(0, weight=1); parent.rowconfigure(1, weight=1)
        ref = ttk.LabelFrame(parent, text="Reference Retrieval", padding=10)
        ref.grid(row=0,column=0,sticky="ew")
        row=ttk.Frame(ref,style="Card.TFrame"); row.grid(row=0,column=0,sticky="ew"); row.columnconfigure((0,1,2),weight=1)
        ttk.Button(row,text="Load index…",command=self.load_reference_dialog,style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,3))
        ttk.Button(row,text="Retrieve section",command=self.retrieve_reference,style="Compact.TButton").grid(row=0,column=1,sticky="ew",padx=3)
        ttk.Button(row,text="Apply best reference",command=self.apply_best_reference,style="Accent.TButton").grid(row=0,column=2,sticky="ew",padx=(3,0))
        ttk.Label(ref,textvariable=self.reference_summary_var,style="Muted.TLabel",wraplength=850).grid(row=1,column=0,sticky="w",pady=(8,0))

        versions = ttk.LabelFrame(parent, text="Project Versions", padding=10)
        versions.grid(row=1,column=0,sticky="nsew",pady=(10,0)); versions.columnconfigure(0,weight=1); versions.rowconfigure(2,weight=1)
        controls=ttk.Frame(versions,style="Card.TFrame"); controls.grid(row=0,column=0,sticky="ew"); controls.columnconfigure(0,weight=2); controls.columnconfigure(1,weight=1)
        ttk.Entry(controls,textvariable=self.version_message_var).grid(row=0,column=0,sticky="ew",padx=(0,5))
        ttk.Button(controls,text="Commit version",command=self.commit_version,style="Accent.TButton").grid(row=0,column=1,sticky="ew")
        branches=ttk.Frame(versions,style="Card.TFrame"); branches.grid(row=1,column=0,sticky="ew",pady=(7,0)); branches.columnconfigure(0,weight=1)
        ttk.Entry(branches,textvariable=self.version_branch_var).grid(row=0,column=0,sticky="ew",padx=(0,5))
        ttk.Button(branches,text="Create branch",command=self.create_version_branch,style="Compact.TButton").grid(row=0,column=1,padx=(0,4))
        ttk.Button(branches,text="Checkout",command=self.checkout_version,style="Compact.TButton").grid(row=0,column=2,padx=4)
        ttk.Button(branches,text="Merge selected",command=self.merge_version,style="Compact.TButton").grid(row=0,column=3,padx=(4,0))
        self.version_tree=ttk.Treeview(versions,columns=("branch","message","id"),show="headings",height=8)
        self.version_tree.grid(row=2,column=0,sticky="nsew",pady=(8,0))
        for name,width in (("branch",110),("message",330),("id",150)):
            self.version_tree.heading(name,text=name.title()); self.version_tree.column(name,width=width)
        ttk.Label(versions,textvariable=self.version_summary_var,style="Muted.TLabel").grid(row=3,column=0,sticky="w",pady=(6,0))

        packs = ttk.LabelFrame(parent, text="Motion Packs", padding=10)
        packs.grid(row=2,column=0,sticky="ew",pady=(10,0)); packs.columnconfigure((0,1),weight=1)
        ttk.Button(packs,text="Load pack…",command=self.load_motion_pack_dialog,style="Compact.TButton").grid(row=0,column=0,sticky="ew",padx=(0,4))
        ttk.Button(packs,text="Save pack…",command=self.save_motion_pack_dialog,style="Compact.TButton").grid(row=0,column=1,sticky="ew",padx=(4,0))

    def _build_ecosystem(self, parent):
        parent.columnconfigure(0,weight=1)
        plugins=ttk.LabelFrame(parent,text="Plugin SDK",padding=10); plugins.grid(row=0,column=0,sticky="ew")
        ttk.Button(plugins,text="Discover plugins",command=self.discover_plugins,style="Compact.TButton").grid(row=0,column=0,sticky="w")
        ttk.Label(plugins,textvariable=self.plugin_summary_var,style="Muted.TLabel",wraplength=820).grid(row=1,column=0,sticky="w",pady=(7,0))

        twin=ttk.LabelFrame(parent,text="Device Twin 2.0",padding=10); twin.grid(row=1,column=0,sticky="ew",pady=(10,0))
        ttk.Button(twin,text="Load telemetry…",command=self.load_telemetry_dialog,style="Accent.TButton").grid(row=0,column=0,sticky="w")
        ttk.Label(twin,textvariable=self.telemetry_summary_var,style="Muted.TLabel",wraplength=820).grid(row=1,column=0,sticky="w",pady=(7,0))

        controls=ttk.LabelFrame(parent,text="Control Surfaces",padding=10); controls.grid(row=2,column=0,sticky="ew",pady=(10,0)); controls.columnconfigure(1,weight=1)
        ttk.Label(controls,text="MIDI",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Entry(controls,textvariable=self.midi_input_var).grid(row=0,column=1,sticky="ew",padx=(6,10))
        ttk.Label(controls,text="OSC",style="Muted.TLabel").grid(row=0,column=2)
        ttk.Spinbox(controls,textvariable=self.osc_port_var,from_=1,to=65535,width=8).grid(row=0,column=3,padx=(5,10))
        ttk.Checkbutton(controls,text="Ableton Link",variable=self.link_enabled_var).grid(row=0,column=4)
        ttk.Button(controls,text="Start controls",command=self.start_controls,style="Compact.TButton").grid(row=1,column=0,columnspan=2,sticky="ew",pady=(8,0),padx=(0,4))
        ttk.Button(controls,text="Stop controls",command=self.stop_controls,style="Compact.TButton").grid(row=1,column=2,columnspan=3,sticky="ew",pady=(8,0),padx=(4,0))
        ttk.Label(controls,textvariable=self.control_summary_var,style="Muted.TLabel").grid(row=2,column=0,columnspan=5,sticky="w",pady=(7,0))

        batch=ttk.LabelFrame(parent,text="Batch Queue",padding=10); batch.grid(row=3,column=0,sticky="ew",pady=(10,0))
        ttk.Button(batch,text="Run manifest…",command=self.run_batch_dialog,style="Accent.TButton").grid(row=0,column=0,sticky="w")
        ttk.Label(batch,textvariable=self.batch_summary_var,style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(7,0))

    # ---------- preference / scoring ----------
    def _rescore_candidate_list(self, candidates):
        if self.data is None:
            return list(candidates)
        mechanical = self._mechanical_config()
        sections = self._sections_payload()
        weights = self.preference_model.as_quality_weights()
        rescored=[]
        for candidate in candidates:
            effective=self._effective_candidate_plan(candidate)
            quality=score_plan(effective,self.data,sections=sections,geometry=self.sr6_geometry,mechanical_config=mechanical,weights=weights)
            config=replace(candidate.config,mechanical=mechanical,geometry=self.sr6_geometry)
            rescored.append(CandidateResult(candidate.name,config,candidate.plan,quality))
        rescored.sort(key=lambda item:(-item.quality.overall,item.name))
        return rescored

    def record_preference(self, which):
        a=self._candidate_by_name(self.candidate_a_var.get()) if hasattr(self,"candidate_a_var") else None
        b=self._candidate_by_name(self.candidate_b_var.get()) if hasattr(self,"candidate_b_var") else None
        if not a or not b or a.name==b.name:
            messagebox.showwarning("PythonDancer","Choose two different candidates first."); return
        selected,rejected=(a,b) if which=="A" else (b,a)
        self.preference_model.record_reports(selected.name,selected.quality,rejected.name,rejected.quality,section=self._selected_section_label())
        self._refresh_candidate_scores(mark_changed=False)
        self._mark_changed(); self._refresh_preference_summary()
        self.status_var.set(f"Preference updated · {selected.name} > {rejected.name}")

    def _refresh_preference_summary(self):
        weights=self.preference_model.quality_weights
        strongest=sorted(weights,key=weights.get,reverse=True)[:3]
        summary=" · ".join(f"{name} {weights[name]:.2f}×" for name in strongest)
        self.preference_summary_var.set(f"Preference Learning · {self.preference_model.observations} observations · {summary}")

    def load_preference_dialog(self):
        path=filedialog.askopenfilename(title="Load preference",filetypes=[("JSON","*.json"),("All files","*.*")])
        if not path:return
        try:self.preference_model=load_preference_model(path); self._refresh_preference_summary(); self._refresh_candidate_scores(mark_changed=False) if self.quality_candidates else None; self._mark_changed()
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def save_preference_dialog(self):
        path=filedialog.asksaveasfilename(title="Save preference",defaultextension=".json",filetypes=[("JSON","*.json")])
        if path:
            try:save_preference_model(path,self.preference_model)
            except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    # ---------- Copilot / grammar ----------
    def apply_copilot(self):
        if self.base_plan is None or self.workspace is None:return
        instruction=self.copilot_instruction_var.get().strip()
        if not instruction:return
        try:plan=compile_instruction(instruction,sections=self.workspace.sections,duration=self.duration)
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc)); return
        self._checkpoint(); self.copilot_plan=plan
        self.automation,self.style_morph=apply_copilot_plan(plan,self.automation,self.style_morph)
        for axis in plan.axis_locks:
            if axis in self.workspace.axes:self.workspace.axes[axis].locked=True
        if plan.motion_program.primitives:
            self.base_plan=blend_motion_program(self.base_plan,plan.motion_program,duration=self.duration)
        self._refresh_automation_tree(); self._refresh_style_tree(); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        if self.quality_candidates:self._refresh_candidate_scores(mark_changed=False)
        self.intelligence_summary_var.set("Copilot applied · "+plan.summary)

    def add_motion_primitive(self):
        try:
            item=MotionPrimitive(self.primitive_var.get(),float(self.primitive_start_var.get()),float(self.primitive_end_var.get()),amount=float(self.primitive_amount_var.get()),cycles=float(self.primitive_cycles_var.get()))
            self.motion_program=replace(self.motion_program,primitives=self.motion_program.primitives+(item,))
            self.motion_summary_var.set("Motion Grammar · "+" → ".join(p.kind for p in self.motion_program.primitives))
            self._mark_changed()
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def apply_motion_program(self):
        if not self.base_plan or not self.motion_program.primitives:return
        self._checkpoint(); self.base_plan=blend_motion_program(self.base_plan,self.motion_program,duration=self.duration); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        self.status_var.set("Motion program applied · final safety chain re-run")

    def clear_motion_program(self):
        self.motion_program=MotionProgram(); self.motion_summary_var.set("Motion Grammar · empty program"); self._mark_changed()

    # ---------- reference retrieval ----------
    def _selected_section_label(self):
        if not self.workspace:return ""
        selection=self.workspace.selection.normalized(self.duration)
        middle=(selection.start+selection.end)*.5 if selection.duration>.01 else float(self.timeline_var.get())
        for section in self.workspace.sections:
            if section.start<=middle<=section.end:return section.label
        return self.workspace.sections[0].label if self.workspace.sections else ""

    def _selected_section_bounds(self):
        if not self.workspace:return 0.0,self.duration,""
        selection=self.workspace.selection.normalized(self.duration)
        if selection.duration>.10:return selection.start,selection.end,self._selected_section_label()
        at=float(self.timeline_var.get())
        for section in self.workspace.sections:
            if section.start<=at<=section.end:return section.start,section.end,section.label
        return 0.0,self.duration,"all"

    def load_reference_dialog(self):
        path=filedialog.askopenfilename(title="Load reference index",filetypes=[("JSON","*.json"),("All files","*.*")])
        if not path:return
        try:self.reference_index=load_reference_index(path); self.reference_summary_var.set(f"Reference Retrieval · {len(self.reference_index.sections)} sections loaded"); self._mark_changed()
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def retrieve_reference(self):
        if not self.reference_index.sections or not self.plan:return
        start,end,label=self._selected_section_bounds(); local=slice_plan(self.plan,start,end,rebase=True); features=plan_motion_features(local,duration=end-start)
        beats=np.asarray((self.data or {}).get("beats",[]),dtype=float); beats=beats[(beats>=start)&(beats<=end)]
        if beats.size>1:features["bpm"]=60.0/max(float(np.median(np.diff(beats))),1e-6)
        for key in ("energy","bass","vocal","high"):
            raw=np.asarray((self.data or {}).get(key,[]),dtype=float).reshape(-1)
            if raw.size:features[key]=float(np.nanmean(raw))
        self.reference_matches=self.reference_index.query(features,top_k=5,label=label if label!="all" else None)
        if not self.reference_matches:self.reference_summary_var.set("Reference Retrieval · no match"); return
        self.reference_summary_var.set("Reference Retrieval · "+" | ".join(f"{m.reference.identifier} {m.similarity:.2f}" for m in self.reference_matches))

    def apply_best_reference(self):
        if not self.reference_matches or not self.base_plan:return
        match=self.reference_matches[0]; payload=match.reference.payload; raw=payload.get("plan") if isinstance(payload,dict) else None
        if not isinstance(raw,dict):messagebox.showwarning("PythonDancer","Selected reference does not include a plan payload."); return
        start,end,_=self._selected_section_bounds(); parsed={axis:[(float(v[0]),float(v[1])) for v in raw.get(axis,())] for axis in ("L0","L1","L2","R0","R1","R2")}
        source_duration=max((t for rows in parsed.values() for t,_ in rows),default=end-start); adapted=adapt_reference_plan(parsed,source_duration=source_duration,target_duration=end-start,amplitude=.85)
        shifted={axis:[(t+start,p) for t,p in rows] for axis,rows in adapted.items()}
        self._checkpoint(); self.base_plan=splice_plan(self.base_plan,shifted,start,end,locked_axes=self.workspace.locked_axes(),blend=.30); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        self.status_var.set(f"Reference applied · {match.reference.identifier} · similarity {match.similarity:.2f}")

    # ---------- project version graph ----------
    def commit_version(self):
        if not self.base_plan:return
        snapshot=self.version_graph.commit(self.base_plan,self.version_message_var.get().strip() or "Edit",metadata={"quality":self.quality_report.to_dict() if self.quality_report else {}})
        self.version_summary_var.set(f"Version committed · {snapshot.identifier}"); self._refresh_version_tree(); self._mark_changed()

    def create_version_branch(self):
        try:self.version_graph.create_branch(self.version_branch_var.get()); self.version_summary_var.set(f"Project Versions · {self.version_graph.current_branch}"); self._refresh_version_tree(); self._mark_changed()
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def _selected_version_id(self):
        selection=self.version_tree.selection() if hasattr(self,"version_tree") else ()
        if not selection:return None
        values=self.version_tree.item(selection[0],"values"); return str(values[2]) if len(values)>=3 else None

    def checkout_version(self):
        identifier=self._selected_version_id()
        if not identifier:return
        try:self._checkpoint(); self.base_plan=self.version_graph.checkout(identifier); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current(); self.version_summary_var.set(f"Checkout · {identifier}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def merge_version(self):
        identifier=self._selected_version_id(); head=self.version_graph.branches.get(self.version_graph.current_branch)
        if not identifier or not head or not self.workspace:return
        try:self._checkpoint(); self.base_plan=self.version_graph.merge_sections(head,identifier,self.workspace.sections); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current(); self.version_summary_var.set(f"Merged · {identifier}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def _refresh_version_tree(self):
        if not hasattr(self,"version_tree"):return
        for item in self.version_tree.get_children():self.version_tree.delete(item)
        for snapshot in sorted(self.version_graph.snapshots.values(),key=lambda item:item.created_at,reverse=True):self.version_tree.insert("","end",values=(snapshot.branch,snapshot.message,snapshot.identifier))

    # ---------- packs / plugins / device feedback ----------
    def load_motion_pack_dialog(self):
        path=filedialog.askopenfilename(title="Load motion pack",filetypes=[("PythonDancer Motion Pack","*.pdmotion"),("ZIP","*.zip"),("All files","*.*")])
        if not path:return
        try:
            pack=load_motion_pack(path); self.loaded_motion_pack=pack
            if pack.motion_programs:self.motion_program=MotionProgram.from_dict(next(iter(pack.motion_programs.values())))
            if pack.preference_profiles:self.preference_model=PreferenceModel.from_dict(next(iter(pack.preference_profiles.values())))
            if pack.device_twins:self.device_twin=DeviceTwinProfile.from_dict(next(iter(pack.device_twins.values()))); self.apply_device_twin(record=True)
            if pack.automation_presets:self.automation=AutomationSet.from_dict(next(iter(pack.automation_presets.values())))
            if pack.style_morphs:self.style_morph=StyleMorphTimeline.from_dict(next(iter(pack.style_morphs.values())))
            self._refresh_intelligence_panels(); self._refresh_automation_tree(); self._refresh_style_tree(); self._mark_changed(); self.status_var.set(f"Motion Pack loaded · {pack.manifest.name}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def save_motion_pack_dialog(self):
        path=filedialog.asksaveasfilename(title="Save motion pack",defaultextension=".pdmotion",filetypes=[("PythonDancer Motion Pack","*.pdmotion")])
        if not path:return
        try:
            pack=MotionPack(MotionPackManifest("My PythonDancer Pack",version="3.0"),motion_programs={self.motion_program.name:self.motion_program.to_dict()} if self.motion_program.primitives else {},style_morphs={"current":self.style_morph.to_dict()},automation_presets={"current":self.automation.to_dict()},device_twins={self.device_twin.name:self.device_twin.to_dict()},preference_profiles={"personal":self.preference_model.to_dict()})
            save_motion_pack(path,pack); self.status_var.set(f"Motion Pack saved · {Path(path).name}")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    def discover_plugins(self):
        GLOBAL_PLUGINS.discover(); descriptors=GLOBAL_PLUGINS.descriptors(); names=", ".join(f"{item.kind}:{item.name}" for item in descriptors[:8]); self.plugin_summary_var.set(f"Plugin SDK · {len(descriptors)} loaded · {names or 'no third-party plugins'}"+(f" · {len(GLOBAL_PLUGINS.errors)} errors" if GLOBAL_PLUGINS.errors else ""))

    def load_telemetry_dialog(self):
        path=filedialog.askopenfilename(title="Load telemetry",filetypes=[("JSON","*.json"),("All files","*.*")])
        if not path:return
        try:
            payload=json.loads(Path(path).read_text(encoding="utf-8")); rows=payload.get("samples",()) if isinstance(payload,dict) else payload; feedback=estimate_feedback([TelemetrySample.from_dict(item) for item in rows]); self.device_twin=replace(self.device_twin,feedback=feedback); self.apply_device_twin(record=True)
            load=simulate_dynamic_load(self.plan or self.base_plan or {},self.device_twin.dynamics); self.telemetry_summary_var.set(f"Telemetry calibrated · {feedback.samples} samples · latency {feedback.latency_ms:.1f} ms · RMS {np.mean(list(feedback.rms_error.values())):.2f} · peak thermal model {load.peak_temperature_c:.1f}°C")
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc))

    # ---------- control surfaces / batch ----------
    def start_controls(self):
        self.stop_controls(); shared=ControlState(bpm=float(self.live_bpm_var.get())); mappings=()
        def on_change(target,value):
            if target=="bpm":shared.bpm=float(value)
            else:shared.update(target,value)
        try:
            midi_name=self.midi_input_var.get().strip()
            if midi_name:self.control_resources.append(MidiControlBridge(mappings,input_name=midi_name,on_change=on_change).open())
            port=int(self.osc_port_var.get())
            if port:self.control_resources.append(OSCControlBridge(mappings,port=port,on_change=on_change).start())
            link=None
            if self.link_enabled_var.get():link=LinkClock(shared.bpm).connect(); link.start(); self.control_resources.append(link)
            self.control_provider=(link.snapshot if link is not None else (lambda:shared)); self.control_summary_var.set(f"Control Surfaces · running · MIDI {'on' if midi_name else 'off'} · OSC {port} · Link {'on' if link else 'off'}")
        except Exception as exc:self.stop_controls(); messagebox.showerror("PythonDancer",str(exc))

    def stop_controls(self):
        for resource in reversed(self.control_resources):
            try:
                if hasattr(resource,"stop"):resource.stop()
                if hasattr(resource,"close"):resource.close()
            except Exception:pass
        self.control_resources=[]; self.control_provider=None
        if hasattr(self,"control_summary_var"):self.control_summary_var.set("Control Surfaces · stopped")

    def start_live(self):
        result=super().start_live()
        if self.live_session is not None and self.control_provider is not None:self.live_session.control_state=self.control_provider
        return result

    def run_batch_dialog(self):
        path=filedialog.askopenfilename(title="Batch manifest",filetypes=[("JSON","*.json"),("All files","*.*")])
        if not path:return
        try:queue=load_batch_manifest(path)
        except Exception as exc:messagebox.showerror("PythonDancer",str(exc)); return
        self.batch_summary_var.set(f"Batch Queue · {len(queue.jobs)} jobs running…")
        def worker(job):
            command=[sys.executable,"-m","dancer",job.media_path,"--cli","--multiaxis","--yes"]
            if job.output_path:command.extend(["--out_path",job.output_path])
            for key,value in job.options.items():
                flag="--"+str(key)
                if isinstance(value,bool):
                    if value:command.append(flag)
                elif value is not None:command.extend([flag,str(value)])
            run=subprocess.run(command,capture_output=True,text=True)
            if run.returncode:raise RuntimeError((run.stderr or run.stdout).strip()[-600:])
            return job.output_path or job.media_path
        def work():
            results=queue.run(worker); ok=sum(1 for item in results if item.success); self.after(0,lambda:self.batch_summary_var.set(f"Batch Queue · {ok}/{len(results)} completed"))
        Thread(target=work,daemon=True).start()

    # ---------- generation / project persistence ----------
    def _generation_done(self,data,plan,analysis,config,pitch,energy):
        super()._generation_done(data,plan,analysis,config,pitch,energy)
        # Pre-entered Copilot/Motion Grammar is applied as one explicit editable
        # transform, then the normal workspace/DAW/mechanical chain runs again.
        if self.base_plan and (self.copilot_instruction_var.get().strip() or self.motion_program.primitives):
            if self.copilot_instruction_var.get().strip():
                self.copilot_plan=compile_instruction(self.copilot_instruction_var.get(),sections=self.workspace.sections,duration=self.duration); self.automation,self.style_morph=apply_copilot_plan(self.copilot_plan,self.automation,self.style_morph)
                if self.copilot_plan.motion_program.primitives:self.base_plan=blend_motion_program(self.base_plan,self.copilot_plan.motion_program,duration=self.duration)
            if self.motion_program.primitives:self.base_plan=blend_motion_program(self.base_plan,self.motion_program,duration=self.duration)
            self._apply_workspace(redraw=True); self.score_current()
        self._refresh_intelligence_panels()

    def _project_document(self):
        project=super()._project_document(); project.intelligence={"version":"3.0","copilot_instruction":self.copilot_instruction_var.get(),"copilot_plan":self.copilot_plan.to_dict() if self.copilot_plan else None,"preference_model":self.preference_model.to_dict(),"motion_program":self.motion_program.to_dict(),"reference_index":self.reference_index.to_dict(),"version_graph":self.version_graph.to_dict(),"plugin_state":GLOBAL_PLUGINS.to_dict()}; return project

    def _load_project_document(self,project):
        super()._load_project_document(project); state=project.intelligence or {}; self.copilot_instruction_var.set(str(state.get("copilot_instruction",""))); self.preference_model=PreferenceModel.from_dict(state.get("preference_model")); self.motion_program=MotionProgram.from_dict(state.get("motion_program")); self.reference_index=ReferenceSectionIndex.from_dict(state.get("reference_index")); self.version_graph=ProjectVersionGraph.from_dict(state.get("version_graph")); self.copilot_plan=None; self._refresh_intelligence_panels(); self.project_dirty=False

    def _export_metadata(self):
        metadata=super()._export_metadata(); metadata["intelligence"]={"version":"3.0","preference_model":self.preference_model.to_dict(),"motion_program":self.motion_program.to_dict(),"copilot":self.copilot_plan.to_dict() if self.copilot_plan else None,"device_dynamics":self.device_twin.dynamics.to_dict(),"device_feedback":self.device_twin.feedback.to_dict()}; metadata["notes"]=str(metadata.get("notes",""))+"; workstation=3.0-intelligent-choreography"; return metadata

    def _refresh_intelligence_panels(self):
        self._refresh_preference_summary(); self.motion_summary_var.set("Motion Grammar · "+(" → ".join(item.kind for item in self.motion_program.primitives) if self.motion_program.primitives else "empty program")); self.reference_summary_var.set(f"Reference Retrieval · {len(self.reference_index.sections)} indexed sections" if self.reference_index.sections else "Reference Retrieval · no index"); self.version_summary_var.set(f"Project Versions · {self.version_graph.current_branch} · {len(self.version_graph.snapshots)} snapshots"); self._refresh_version_tree()

    def _on_close(self):
        self.stop_controls(); return super()._on_close()


def ux(args):
    app=MultiAxisWindow(args); app.mainloop()
