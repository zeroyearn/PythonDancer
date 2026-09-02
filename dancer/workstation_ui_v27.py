"""PythonDancer 2.7 Quality Intelligence workstation.

Adds scored candidates, A/B non-destructive preview, best-section merge,
automatic weak-range improvement, section-level Motion Intent, and tunable SR6
mechanical safe-set projection on top of the bilingual 2.6 workstation.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from .candidates import CandidateResult, generate_candidates
from .comparison import best_section_merge, compare_plans
from .improvement import ImprovementConfig, auto_improve
from .intent import INTENT_FIELDS, MotionIntent, infer_motion_intent
from .libfun import autoval, load_audio_data
from .mechanical_safety import MechanicalProjectionConfig, trajectory_mechanical_risk
from .multiaxis import AXIS_ORDER, MultiAxisConfig, analyze_multiaxis, plan_multiaxis
from .multiaxis_ui_v2 import MUTED, ROTATION, TRANSLATION
from .quality import METRICS, QualityReport, QualityWindow, score_plan
from .reference_library import learn_profile_from_bundles
from .section_intent import SectionIntentOverride, overrides_from_dict, overrides_to_dict
from .stems import enrich_with_stems
from .style import learn_profile_from_bundle, load_profile
from .workspace import sample_axis, splice_plan
from .workstation_ui_v26_release import MultiAxisWindow as _V26ReleaseWindow


_METRIC_LABELS = {
    "rhythm_alignment": "Rhythm alignment",
    "phrase_alignment": "Phrase alignment",
    "smoothness": "Smoothness",
    "axis_diversity": "Axis diversity",
    "cross_axis_coherence": "Cross-axis coherence",
    "repetition": "Repetition",
    "mechanical_safety": "Mechanical safety",
    "jerk_comfort": "Jerk comfort",
    "stem_responsiveness": "Stem responsiveness",
}


class MultiAxisWindow(_V26ReleaseWindow):
    def _build_ui(self):
        self.quality_overall_var = tk.StringVar(value="—")
        self.quality_summary_var = tk.StringVar(value="Quality Intelligence: generate or score a track")
        self.quality_metric_vars = {name: tk.StringVar(value="—") for name in METRICS}
        self.quality_candidate_count_var = tk.IntVar(value=max(2, min(8, int(getattr(self.args, "quality_candidates", 6)))))
        self.quality_candidates: list[CandidateResult] = []
        self.quality_report: QualityReport | None = None
        self.quality_worker: Thread | None = None
        self.candidate_a_var = tk.StringVar(value="")
        self.candidate_b_var = tk.StringVar(value="")
        self.comparison_summary_var = tk.StringVar(value="A/B: generate candidates first")
        self.preview_candidate_plan = None
        self.preview_candidate_name = ""

        self.improve_iterations_var = tk.IntVar(value=max(1, int(getattr(self.args, "improve_iterations", 4))))
        self.improve_target_var = tk.DoubleVar(value=float(getattr(self.args, "improve_target", 90.0)))
        self.improve_min_gain_var = tk.DoubleVar(value=float(getattr(self.args, "improve_min_gain", .35)))
        self.improvement_summary_var = tk.StringVar(value="Auto Improvement: not run")
        self.improvement_history: list[dict[str, object]] = []

        self.mechanical_projection_var = tk.BooleanVar(value=bool(getattr(self.args, "mechanical_projection", True)))
        self.mechanical_max_risk_var = tk.DoubleVar(value=float(getattr(self.args, "mechanical_max_risk", .82)))
        self.servo_limit_var = tk.DoubleVar(value=float(getattr(self.args, "servo_limit_deg", 88.0)))
        self.singularity_sensitivity_var = tk.DoubleVar(value=float(getattr(self.args, "singularity_sensitivity", 2.5)))
        self.mechanical_quality_var = tk.StringVar(value="Mechanical risk: not scored")

        self.section_intent_overrides: dict[int, SectionIntentOverride] = {}
        self.section_intent_selector_var = tk.StringVar(value="")
        self.section_intent_amount_var = tk.DoubleVar(value=1.0)
        self.section_intent_vars = {name: tk.DoubleVar(value=.5) for name in INTENT_FIELDS}
        self.section_intent_summary_var = tk.StringVar(value="Section Intent: select a section")

        super()._build_ui()
        self.title("PythonDancer 2.7 · Quality Intelligence Workstation")
        if self.i18n is not None:
            self.i18n.bind_object(self)
            self.i18n.refresh(force=True)
        self._refresh_quality_i18n()

    # ---------- UI ----------
    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        quality = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        quality.columnconfigure(0, weight=1)
        quality.rowconfigure(2, weight=1)
        notebook.add(quality, text="Quality Intelligence")

        score = ttk.LabelFrame(quality, text="Motion Quality", padding=10)
        score.grid(row=0, column=0, sticky="ew")
        score.columnconfigure(0, weight=1)
        head = ttk.Frame(score, style="Card.TFrame")
        head.grid(row=0, column=0, columnspan=6, sticky="ew")
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Overall", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, textvariable=self.quality_overall_var, style="Metric.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(head, text="Score current", command=self.score_current, style="Compact.TButton").grid(row=0, column=2, padx=(8, 0))
        ttk.Label(score, textvariable=self.quality_summary_var, style="Muted.TLabel", wraplength=740).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        metrics = ttk.Frame(score, style="Card.TFrame")
        metrics.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        for index, name in enumerate(METRICS):
            row, col = divmod(index, 5)
            box = ttk.Frame(metrics, style="Card.TFrame")
            box.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 12, 0), pady=(0 if row == 0 else 7, 0))
            ttk.Label(box, text=_METRIC_LABELS[name], style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(box, textvariable=self.quality_metric_vars[name], style="Metric.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(score, textvariable=self.mechanical_quality_var, style="Muted.TLabel").grid(row=3, column=0, columnspan=6, sticky="w", pady=(7, 0))

        candidate = ttk.LabelFrame(quality, text="Candidates / A-B Preview", padding=10)
        candidate.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        candidate.columnconfigure(0, weight=1)
        controls = ttk.Frame(candidate, style="Card.TFrame")
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(4, weight=1)
        ttk.Label(controls, text="Candidates", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(controls, textvariable=self.quality_candidate_count_var, from_=2, to=8, increment=1, width=5).grid(row=0, column=1, padx=(6, 8))
        self.generate_candidates_button = ttk.Button(controls, text="Generate candidates", command=self.generate_quality_candidates, style="Soft.TButton")
        self.generate_candidates_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Button(controls, text="Best-section merge", command=self.merge_best_sections, style="Compact.TButton").grid(row=0, column=3, padx=(0, 6))
        ttk.Label(controls, textvariable=self.comparison_summary_var, style="Muted.TLabel", wraplength=300).grid(row=0, column=4, sticky="e")

        self.candidate_tree = ttk.Treeview(candidate, columns=("rank", "name", "score", "safety", "rhythm"), show="headings", height=6, selectmode="browse")
        self.candidate_tree.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.candidate_tree.column("rank", width=45, anchor="center", stretch=False)
        self.candidate_tree.column("name", width=180, anchor="w")
        self.candidate_tree.column("score", width=75, anchor="center")
        self.candidate_tree.column("safety", width=85, anchor="center")
        self.candidate_tree.column("rhythm", width=85, anchor="center")
        self.candidate_tree.bind("<<TreeviewSelect>>", self._candidate_tree_selected)

        ab = ttk.Frame(candidate, style="Card.TFrame")
        ab.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for col in range(9): ab.columnconfigure(col, weight=1 if col in (1, 5) else 0)
        ttk.Label(ab, text="A", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.candidate_a_combo = ttk.Combobox(ab, textvariable=self.candidate_a_var, state="readonly")
        self.candidate_a_combo.grid(row=0, column=1, sticky="ew", padx=(5, 5))
        ttk.Button(ab, text="Preview A", command=lambda: self.preview_candidate("A"), style="Compact.TButton").grid(row=0, column=2, padx=3)
        ttk.Button(ab, text="Use A", command=lambda: self.use_candidate("A"), style="Compact.TButton").grid(row=0, column=3, padx=3)
        ttk.Label(ab, text="B", style="Muted.TLabel").grid(row=0, column=4, padx=(12, 0), sticky="w")
        self.candidate_b_combo = ttk.Combobox(ab, textvariable=self.candidate_b_var, state="readonly")
        self.candidate_b_combo.grid(row=0, column=5, sticky="ew", padx=(5, 5))
        ttk.Button(ab, text="Preview B", command=lambda: self.preview_candidate("B"), style="Compact.TButton").grid(row=0, column=6, padx=3)
        ttk.Button(ab, text="Use B", command=lambda: self.use_candidate("B"), style="Compact.TButton").grid(row=0, column=7, padx=3)
        ttk.Button(ab, text="Reset preview", command=self.reset_candidate_preview, style="Compact.TButton").grid(row=0, column=8, padx=(8, 0))
        self.candidate_a_combo.bind("<<ComboboxSelected>>", lambda _e: self.compare_ab())
        self.candidate_b_combo.bind("<<ComboboxSelected>>", lambda _e: self.compare_ab())

        lower = ttk.Frame(quality, style="Card.TFrame")
        lower.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        lower.columnconfigure(0, weight=1); lower.columnconfigure(1, weight=1)

        improve = ttk.LabelFrame(lower, text="Auto Improvement", padding=10)
        improve.grid(row=0, column=0, sticky="new", padx=(0, 5))
        improve.columnconfigure(1, weight=1)
        self._label(improve, "Iterations", 0)
        ttk.Spinbox(improve, textvariable=self.improve_iterations_var, from_=1, to=12, width=7).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._label(improve, "Target score", 1, pady=(7, 0))
        ttk.Spinbox(improve, textvariable=self.improve_target_var, from_=50, to=100, increment=.5, width=7).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(7, 0))
        self._label(improve, "Minimum gain", 2, pady=(7, 0))
        ttk.Spinbox(improve, textvariable=self.improve_min_gain_var, from_=0, to=10, increment=.1, width=7).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(7, 0))
        ttk.Button(improve, text="Auto improve weak ranges", command=self.run_auto_improvement, style="Soft.TButton").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        ttk.Label(improve, textvariable=self.improvement_summary_var, style="Muted.TLabel", wraplength=330).grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 0))

        section = ttk.LabelFrame(lower, text="Section-level Motion Intent", padding=10)
        section.grid(row=0, column=1, sticky="new", padx=(5, 0))
        section.columnconfigure(1, weight=1)
        ttk.Label(section, text="Section", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.section_intent_combo = ttk.Combobox(section, textvariable=self.section_intent_selector_var, state="readonly")
        self.section_intent_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(7, 0))
        self.section_intent_combo.bind("<<ComboboxSelected>>", self._section_intent_selected)
        ttk.Label(section, text="Override amount", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Scale(section, variable=self.section_intent_amount_var, from_=0.0, to=1.0, orient="horizontal").grid(row=1, column=1, columnspan=3, sticky="ew", padx=(7, 0), pady=(7, 0))
        intent_grid = ttk.Frame(section, style="Card.TFrame")
        intent_grid.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for index, field in enumerate(INTENT_FIELDS):
            row, col = divmod(index, 4)
            box = ttk.Frame(intent_grid, style="Card.TFrame")
            box.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0), pady=(0 if row == 0 else 5, 0))
            ttk.Label(box, text=field.replace("_", " "), style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Spinbox(box, textvariable=self.section_intent_vars[field], from_=0, to=1, increment=.05, width=7).grid(row=1, column=0, sticky="ew")
        actions = ttk.Frame(section, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Apply section intent", command=self.apply_section_intent, style="Compact.TButton").pack(side="left")
        ttk.Button(actions, text="Regenerate section", command=self.regenerate_intent_section, style="Compact.TButton").pack(side="left", padx=(5, 0))
        ttk.Button(actions, text="Clear section intent", command=self.clear_section_intent, style="Compact.TButton").pack(side="left", padx=(5, 0))
        ttk.Label(section, textvariable=self.section_intent_summary_var, style="Muted.TLabel", wraplength=350).grid(row=4, column=0, columnspan=4, sticky="w", pady=(7, 0))

        mechanical = ttk.LabelFrame(quality, text="Mechanical projection / singularity", padding=10)
        mechanical.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for col in range(8): mechanical.columnconfigure(col, weight=1 if col in (1, 3, 5, 7) else 0)
        ttk.Checkbutton(mechanical, text="Nearest-safe-pose projection", variable=self.mechanical_projection_var).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(mechanical, text="Maximum risk", style="Muted.TLabel").grid(row=0, column=2, sticky="e")
        ttk.Spinbox(mechanical, textvariable=self.mechanical_max_risk_var, from_=0, to=1, increment=.02, width=7).grid(row=0, column=3, sticky="ew", padx=(5, 10))
        ttk.Label(mechanical, text="Servo limit", style="Muted.TLabel").grid(row=0, column=4, sticky="e")
        ttk.Spinbox(mechanical, textvariable=self.servo_limit_var, from_=30, to=180, increment=1, width=7).grid(row=0, column=5, sticky="ew", padx=(5, 10))
        ttk.Label(mechanical, text="Singularity sensitivity", style="Muted.TLabel").grid(row=0, column=6, sticky="e")
        ttk.Spinbox(mechanical, textvariable=self.singularity_sensitivity_var, from_=.5, to=10, increment=.1, width=7).grid(row=0, column=7, sticky="ew", padx=(5, 0))

    def _refresh_quality_i18n(self):
        if not hasattr(self, "candidate_tree"):
            return
        tr = self._tr
        for key, text in (("rank", "Rank"), ("name", "Candidate"), ("score", "Score"), ("safety", "Safety"), ("rhythm", "Rhythm")):
            self.candidate_tree.heading(key, text=tr(text))

    def _language_changed(self):
        super()._language_changed()
        self._refresh_quality_i18n()

    # ---------- config ----------
    def _mechanical_config(self):
        return MechanicalProjectionConfig(
            enabled=bool(self.mechanical_projection_var.get()),
            max_risk=float(self.mechanical_max_risk_var.get()),
            servo_limit_deg=float(self.servo_limit_var.get()),
            sensitivity_limit_deg_per_unit=float(self.singularity_sensitivity_var.get()),
            neutral=50.0,
        )

    def _sync_section_intent_ranges(self):
        if not self.workspace:
            return tuple(self.section_intent_overrides.values())
        synced = {}
        for index, override in self.section_intent_overrides.items():
            if 0 <= index < len(self.workspace.sections):
                section = self.workspace.sections[index]
                synced[index] = replace(override, start=float(section.start), end=float(section.end), label=section.label)
        self.section_intent_overrides = synced
        return tuple(synced[index] for index in sorted(synced))

    def _v27_config(self, base: MultiAxisConfig | None = None):
        if base is None:
            if self.generated_config is None:
                raise ValueError("Generate a track first")
            base = self.generated_config
        independent, optimizer = self._quality_config()
        return replace(
            base,
            independent=independent,
            optimizer=optimizer,
            section_intents=self._sync_section_intent_ranges(),
            mechanical=self._mechanical_config(),
            geometry=self.sr6_geometry,
        )

    def _sections_payload(self):
        if not self.workspace:
            return []
        return [{"start": float(s.start), "end": float(s.end), "label": s.label} for s in self.workspace.sections]

    # ---------- first/full generation ----------
    def generate(self):
        if self.worker and self.worker.is_alive(): return
        raw_path = self.path_var.get().strip()
        if not raw_path:
            messagebox.showwarning("PythonDancer", "Choose a media file first."); return
        source = Path(raw_path)
        if not source.exists():
            messagebox.showerror("PythonDancer", f"File does not exist:\n{source}"); return
        try:
            strength=float(self.strength_var.get()); gesture_strength=float(self.gesture_strength_var.get())
            beats_per_bar=int(self.beats_per_bar_var.get()); bars_per_phrase=int(self.bars_per_phrase_var.get()); section_bars=int(self.section_bars_var.get())
            independent,optimizer=self._quality_config(); mechanical=self._mechanical_config()
            if strength<0 or gesture_strength<0 or min(beats_per_bar,bars_per_phrase,section_bars)<=0: raise ValueError
        except Exception:
            messagebox.showerror("PythonDancer", "Quality Intelligence parameters are invalid."); return
        profile_path=self.profile_path_var.get().strip(); reference_bundle=self.reference_bundle_var.get().strip()
        if int(bool(profile_path))+int(bool(reference_bundle))+int(bool(self.reference_library_paths))>1:
            messagebox.showerror("PythonDancer", "Choose one style source: Profile, Reference bundle, or Reference library."); return
        preset=self.preset_var.get(); mode=self.mode_var.get(); subdivision=int(self.subdivision_var.get()); automap=bool(self.automap_var.get())
        stem_mode=self.stem_mode_var.get(); stem_dir=self.stem_dir_var.get().strip() or None
        if stem_dir and stem_mode=="off": stem_mode="auto"
        self.source_path=source
        self.status_var.set("Analyzing music and generating Quality Intelligence trajectory…")
        for button in (self.generate_button,self.export_button,self.tcode_export_button,self.play_button,self.save_profile_button): button.configure(state="disabled")

        def work():
            try:
                if self.reference_library_paths: style_profile=learn_profile_from_bundles(self.reference_library_paths,name=self.args.profile_name or "GUI reference library")
                elif reference_bundle: style_profile=learn_profile_from_bundle(reference_bundle,name=self.args.profile_name)
                elif profile_path: style_profile=load_profile(profile_path)
                else: style_profile=None
                data=load_audio_data(source,plp=not self.args.no_plp)
                if stem_mode!="off": data=enrich_with_stems(data,source,mode=stem_mode,stem_dir=stem_dir,cache_dir=self.args.stem_cache,model=self.args.demucs_model)
                pitch=float(self.args.pitch); energy=float(self.args.energy)
                if automap: pitch,energy=autoval(data,tpi=self.args.auto_pitch,target_speed=self.args.auto_speed,v2above=self.args.auto_per/100.,opt=self.args.auto_mod-1,planner="adaptive")
                config=MultiAxisConfig(
                    motion=self._motion_config(pitch,energy,subdivision),preset=preset,strength=strength,mode=mode,gesture_strength=gesture_strength,
                    beats_per_bar=beats_per_bar,bars_per_phrase=bars_per_phrase,section_bars=section_bars,profile=style_profile,
                    independent=independent,optimizer=optimizer,section_intents=self._sync_section_intent_ranges(),mechanical=mechanical,geometry=self.sr6_geometry,
                )
                analysis=analyze_multiaxis(data,config); plan=plan_multiaxis(data,config)
                if not plan["L0"]: raise ValueError("No actions could be generated from this input")
                self.after(0,lambda:self._generation_done(data,plan,analysis,config,pitch,energy))
            except Exception as exc: self.after(0,lambda e=exc:self._generation_failed(e))
        self.worker=Thread(target=work,daemon=True); self.worker.start()

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data,plan,analysis,config,pitch,energy)
        self.generated_config=replace(config,geometry=self.sr6_geometry,mechanical=self._mechanical_config())
        self.quality_candidates=[]; self.preview_candidate_plan=None
        self._refresh_section_intent_combo()
        self.score_current()
        self.result_summary_var.set(f"2.7 Quality Intelligence · {sum(len(plan[a]) for a in AXIS_ORDER)} keyframes · scoring ready")

    # ---------- scoring ----------
    def score_current(self):
        if not self.plan or self.data is None: return
        try:
            report=score_plan(self.plan,self.data,sections=self._sections_payload(),geometry=self.sr6_geometry,mechanical_config=self._mechanical_config())
        except Exception as exc:
            self.quality_summary_var.set(f"Quality scoring failed: {exc}"); return
        self.quality_report=report
        self._update_quality_display(report)

    def _update_quality_display(self, report: QualityReport):
        self.quality_overall_var.set(f"{report.overall:.1f}/100")
        for name in METRICS: self.quality_metric_vars[name].set(f"{report.metrics.get(name,0.0):.1f}")
        weakest=min(report.metrics,key=report.metrics.get) if report.metrics else "—"
        weak_text="none" if not report.weak_ranges else " · ".join(f"{w.start:.1f}-{w.end:.1f}s {w.score:.0f}" for w in report.weak_ranges[:3])
        self.quality_summary_var.set(f"Overall {report.overall:.1f} · weakest {_METRIC_LABELS.get(weakest,weakest)} {report.metrics.get(weakest,0.0):.1f} · weak ranges {weak_text}")
        mech=report.mechanical
        self.mechanical_quality_var.set(f"Mechanical risk · mean {float(mech.get('mean_risk',0)):.2f} · peak {float(mech.get('peak_risk',0)):.2f} · unsafe {float(mech.get('unsafe_ratio',0))*100:.1f}% · margin {float(mech.get('min_servo_margin_deg',0)):.1f}°")

    # ---------- candidates / A-B ----------
    def generate_quality_candidates(self):
        if self.data is None or self.generated_config is None or (self.quality_worker and self.quality_worker.is_alive()): return
        try: count=max(2,min(8,int(self.quality_candidate_count_var.get()))); config=self._v27_config()
        except Exception as exc: messagebox.showerror("PythonDancer",str(exc)); return
        self.generate_candidates_button.configure(state="disabled"); self.comparison_summary_var.set("Generating and scoring candidates…")
        data=self.data; sections=self._sections_payload(); geometry=self.sr6_geometry
        def work():
            try:
                results=generate_candidates(data,config,count=count,geometry=geometry,sections=sections)
                self.after(0,lambda:self._candidates_done(results))
            except Exception as exc: self.after(0,lambda e=exc:self._quality_failed(e))
        self.quality_worker=Thread(target=work,daemon=True); self.quality_worker.start()

    def _quality_failed(self, exc):
        self.generate_candidates_button.configure(state="normal"); self.comparison_summary_var.set(f"Quality Intelligence failed: {exc}")

    def _candidates_done(self, results):
        self.quality_candidates=list(results); self.generate_candidates_button.configure(state="normal")
        self._populate_candidate_tree()
        if results:
            names=[item.name for item in results]; self.candidate_a_combo["values"]=names; self.candidate_b_combo["values"]=names
            self.candidate_a_var.set(names[0]); self.candidate_b_var.set(names[1] if len(names)>1 else names[0]); self.compare_ab()
            self.comparison_summary_var.set(f"Recommended: {results[0].name} · {results[0].quality.overall:.1f}/100")

    def _populate_candidate_tree(self):
        for item in self.candidate_tree.get_children(): self.candidate_tree.delete(item)
        for rank,candidate in enumerate(self.quality_candidates,1):
            self.candidate_tree.insert("", "end", iid=str(rank-1), values=(rank,candidate.name,f"{candidate.quality.overall:.1f}",f"{candidate.quality.metrics.get('mechanical_safety',0):.1f}",f"{candidate.quality.metrics.get('rhythm_alignment',0):.1f}"))

    def _candidate_tree_selected(self,_event=None):
        selected=self.candidate_tree.selection()
        if not selected: return
        index=int(selected[0])
        if 0<=index<len(self.quality_candidates): self.candidate_a_var.set(self.quality_candidates[index].name); self.compare_ab()

    def _candidate_by_name(self,name):
        return next((item for item in self.quality_candidates if item.name==name),None)

    def compare_ab(self):
        a=self._candidate_by_name(self.candidate_a_var.get()); b=self._candidate_by_name(self.candidate_b_var.get())
        if not a or not b: return
        report=compare_plans(a.plan,b.plan,self.data,report_a=a.quality,report_b=b.quality,geometry=self.sr6_geometry)
        strongest=max(report.metric_delta,key=lambda key:abs(report.metric_delta[key])) if report.metric_delta else ""
        self.comparison_summary_var.set(f"A/B · B−A {report.score_delta:+.1f} · {_METRIC_LABELS.get(strongest,strongest)} {report.metric_delta.get(strongest,0):+.1f}")

    def _render_candidate_preview(self,plan):
        for axis in AXIS_ORDER: self.preview_axes[axis].clear()
        self._style_axes()
        for axis in AXIS_ORDER:
            actions=plan.get(axis,())
            if actions:
                times=np.asarray([t for t,_ in actions]); positions=np.asarray([p for _,p in actions])
                self.preview_axes[axis].plot(times,positions,linewidth=1.15,color=TRANSLATION if axis.startswith("L") else ROTATION)
            if self.workspace:
                for section in self.workspace.sections[1:]: self.preview_axes[axis].axvline(section.start,color=MUTED,linewidth=.6,alpha=.2)
        self.canvas.draw_idle(); self._draw_pose(float(self.timeline_var.get()))

    def preview_candidate(self,which):
        candidate=self._candidate_by_name(self.candidate_a_var.get() if which=="A" else self.candidate_b_var.get())
        if not candidate: return
        self.preview_candidate_plan={axis:list(rows) for axis,rows in candidate.plan.items()}; self.preview_candidate_name=candidate.name
        self._render_candidate_preview(self.preview_candidate_plan); self.status_var.set(f"Preview only · {candidate.name} · output remains unchanged")

    def reset_candidate_preview(self):
        self.preview_candidate_plan=None; self.preview_candidate_name=""
        self._redraw_workspace_preview(); self._draw_pose(float(self.timeline_var.get())); self.status_var.set("Candidate preview cleared")

    def _pose_values(self,at:float):
        if self.preview_candidate_plan is None: return super()._pose_values(at)
        values={axis:sample_axis(self.preview_candidate_plan.get(axis,()),at,50.) for axis in AXIS_ORDER}
        if self.calibration_profile: values={axis:self.calibration_profile.axes[axis].map_normalized(value) for axis,value in values.items()}
        return values

    def use_candidate(self,which):
        candidate=self._candidate_by_name(self.candidate_a_var.get() if which=="A" else self.candidate_b_var.get())
        if not candidate or not self.workspace: return
        self._checkpoint(); self.base_plan={axis:list(rows) for axis,rows in candidate.plan.items()}; self.preview_candidate_plan=None
        self._apply_workspace(redraw=True); self._mark_changed(); self.score_current(); self.status_var.set(f"Applied candidate: {candidate.name}")

    def merge_best_sections(self):
        if len(self.quality_candidates)<2 or not self.workspace: messagebox.showwarning("PythonDancer","Generate at least two candidates first."); return
        try: merged,choices,scores=best_section_merge(self.quality_candidates,self.workspace.sections,self.data,geometry=self.sr6_geometry)
        except Exception as exc: messagebox.showerror("PythonDancer",str(exc)); return
        self._checkpoint(); self.base_plan=merged; self.preview_candidate_plan=None; self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        summary=[]
        for index,section in enumerate(self.workspace.sections):
            selected=choices.get(index,0); summary.append(f"{section.label}:{self.quality_candidates[selected].name}")
        self.comparison_summary_var.set("Best sections · "+" | ".join(summary)); self.status_var.set("Merged highest-scoring candidate per section")

    # ---------- auto improvement ----------
    def run_auto_improvement(self):
        if not self.base_plan or self.data is None or self.generated_config is None or not self.workspace or (self.quality_worker and self.quality_worker.is_alive()): return
        try:
            config=ImprovementConfig(max_iterations=int(self.improve_iterations_var.get()),target_score=float(self.improve_target_var.get()),minimum_improvement=float(self.improve_min_gain_var.get()),candidates=max(2,min(8,int(self.quality_candidate_count_var.get()))))
            generation=self._v27_config()
        except Exception as exc: messagebox.showerror("PythonDancer",str(exc)); return
        self.improvement_summary_var.set("Auto Improvement: scoring weak ranges…")
        data=self.data; base={axis:list(rows) for axis,rows in self.base_plan.items()}; locked=self.workspace.locked_axes(); sections=self._sections_payload(); geometry=self.sr6_geometry
        def work():
            try:
                result=auto_improve(data,base,generation,config=config,geometry=geometry,sections=sections,locked_axes=locked)
                self.after(0,lambda:self._improvement_done(result))
            except Exception as exc: self.after(0,lambda e=exc:self._quality_failed(e))
        self.quality_worker=Thread(target=work,daemon=True); self.quality_worker.start()

    def _improvement_done(self,result):
        if not self.workspace:return
        self._checkpoint(); self.base_plan={axis:list(rows) for axis,rows in result.plan.items()}; self._apply_workspace(redraw=True); self._mark_changed()
        self.improvement_history=[step.to_dict() for step in result.history]
        self.improvement_summary_var.set(f"Auto Improvement · {result.quality.overall:.1f}/100 · {len(result.history)} accepted pass(es) · {result.stopped_reason}")
        self.score_current()

    # ---------- section-level intent ----------
    def _refresh_section_intent_combo(self):
        if not hasattr(self,"section_intent_combo") or not self.workspace:return
        values=[f"{index+1} · {section.label} · {section.start:.1f}-{section.end:.1f}s" for index,section in enumerate(self.workspace.sections)]
        self.section_intent_combo["values"]=values
        if values and not self.section_intent_selector_var.get(): self.section_intent_selector_var.set(values[0]); self._section_intent_selected()

    def _selected_section_index(self):
        text=self.section_intent_selector_var.get().strip()
        try:return int(text.split("·",1)[0].strip())-1
        except Exception:return -1

    def _section_intent_selected(self,_event=None):
        index=self._selected_section_index()
        if not self.workspace or not 0<=index<len(self.workspace.sections):return
        section=self.workspace.sections[index]; override=self.section_intent_overrides.get(index)
        if override:
            values=override.intent.to_dict(); self.section_intent_amount_var.set(override.amount)
        elif self.data is not None and self.analysis is not None:
            envelope=infer_motion_intent(self.data,self.analysis); sampled=envelope.sample([(section.start+section.end)*.5]); values={field:float(sampled[field][0]) for field in INTENT_FIELDS}; self.section_intent_amount_var.set(1.0)
        else: values={field:.5 for field in INTENT_FIELDS}
        for field,value in values.items(): self.section_intent_vars[field].set(value)
        state="override" if override else "inferred baseline"; self.section_intent_summary_var.set(f"Section Intent · {section.label} · {state}")

    def apply_section_intent(self):
        index=self._selected_section_index()
        if not self.workspace or not 0<=index<len(self.workspace.sections):return
        try:
            intent=MotionIntent(**{field:float(var.get()) for field,var in self.section_intent_vars.items()}); amount=float(self.section_intent_amount_var.get())
        except Exception as exc: messagebox.showerror("PythonDancer",str(exc));return
        section=self.workspace.sections[index]
        self.section_intent_overrides[index]=SectionIntentOverride(section.start,section.end,intent,amount,section.label)
        self.section_intent_summary_var.set(f"Section Intent · {section.label} · override {amount:.2f}"); self._mark_changed()

    def clear_section_intent(self):
        index=self._selected_section_index(); self.section_intent_overrides.pop(index,None); self._section_intent_selected(); self._mark_changed()

    def regenerate_intent_section(self):
        index=self._selected_section_index()
        if self.data is None or self.generated_config is None or not self.workspace or not 0<=index<len(self.workspace.sections) or (self.quality_worker and self.quality_worker.is_alive()):return
        self.apply_section_intent(); section=self.workspace.sections[index]; config=self._v27_config(); data=self.data; locked=self.workspace.locked_axes()
        self.section_intent_summary_var.set(f"Section Intent · regenerating {section.label}…")
        def work():
            try:
                replacement=plan_multiaxis(data,config)
                merged=splice_plan(self.base_plan,replacement,section.start,section.end,locked_axes=locked,blend=.30)
                self.after(0,lambda:self._section_regenerated(index,merged))
            except Exception as exc:self.after(0,lambda e=exc:self._quality_failed(e))
        self.quality_worker=Thread(target=work,daemon=True); self.quality_worker.start()

    def _section_regenerated(self,index,merged):
        if not self.workspace:return
        self._checkpoint(); self.base_plan=merged; self.generated_config=self._v27_config(); self._apply_workspace(redraw=True); self._mark_changed(); self.score_current()
        section=self.workspace.sections[index]; self.section_intent_summary_var.set(f"Section Intent · regenerated {section.label}")

    # ---------- persistence/export ----------
    @staticmethod
    def _report_from_dict(payload):
        if not payload:return None
        windows=tuple(QualityWindow(float(item.get("start",0)),float(item.get("end",0)),float(item.get("score",0)),str(item.get("weakest_metric",""))) for item in payload.get("weak_ranges",[]))
        return QualityReport(float(payload.get("overall",0)),{str(k):float(v) for k,v in (payload.get("metrics") or {}).items()},windows,dict(payload.get("mechanical") or {}))

    def _project_document(self):
        project=super()._project_document()
        project.quality_intelligence={
            "report":self.quality_report.to_dict() if self.quality_report else None,
            "section_intents":overrides_to_dict(self._sync_section_intent_ranges()),
            "mechanical":self._mechanical_config().to_dict(),
            "candidate_count":int(self.quality_candidate_count_var.get()),
            "candidate_a":self.candidate_a_var.get(),"candidate_b":self.candidate_b_var.get(),
            "candidates":[item.to_dict(include_plan=True) for item in self.quality_candidates],
            "improvement":{"iterations":int(self.improve_iterations_var.get()),"target":float(self.improve_target_var.get()),"minimum_gain":float(self.improve_min_gain_var.get()),"history":list(self.improvement_history)},
        }
        return project

    def _load_project_document(self,project):
        super()._load_project_document(project)
        state=project.quality_intelligence or {}; self.section_intent_overrides={}
        raw_overrides=overrides_from_dict(state.get("section_intents",[])) if state.get("section_intents") else ()
        if self.workspace:
            for override in raw_overrides:
                center=(override.start+override.end)*.5
                index=next((i for i,s in enumerate(self.workspace.sections) if s.start-1e-6<=center<=s.end+1e-6),None)
                if index is not None:self.section_intent_overrides[index]=override
        mech=state.get("mechanical") or {}
        if mech:
            self.mechanical_projection_var.set(bool(mech.get("enabled",True))); self.mechanical_max_risk_var.set(float(mech.get("max_risk",.82))); self.servo_limit_var.set(float(mech.get("servo_limit_deg",88.))); self.singularity_sensitivity_var.set(float(mech.get("sensitivity_limit_deg_per_unit",2.5)))
        self.quality_candidate_count_var.set(int(state.get("candidate_count",6))); improvement=state.get("improvement") or {}
        self.improve_iterations_var.set(int(improvement.get("iterations",4))); self.improve_target_var.set(float(improvement.get("target",90.))); self.improve_min_gain_var.set(float(improvement.get("minimum_gain",.35))); self.improvement_history=list(improvement.get("history",[]) or [])
        report=self._report_from_dict(state.get("report")); self.quality_report=report
        if report:self._update_quality_display(report)
        restored=[]
        if self.generated_config is not None:
            for item in state.get("candidates",[]) or []:
                q=self._report_from_dict(item.get("quality"))
                plan={axis:[(float(row[0]),float(row[1])) for row in (item.get("plan") or {}).get(axis,[])] for axis in AXIS_ORDER}
                if q:restored.append(CandidateResult(str(item.get("name","Candidate")),self.generated_config,plan,q))
        self.quality_candidates=restored; self._populate_candidate_tree()
        names=[item.name for item in restored]; self.candidate_a_combo["values"]=names; self.candidate_b_combo["values"]=names
        if names:self.candidate_a_var.set(state.get("candidate_a") if state.get("candidate_a") in names else names[0]); self.candidate_b_var.set(state.get("candidate_b") if state.get("candidate_b") in names else names[min(1,len(names)-1)]); self.compare_ab()
        self._refresh_section_intent_combo()

    def _export_metadata(self):
        metadata=super()._export_metadata(); quality={
            "version":"2.7","report":self.quality_report.to_dict() if self.quality_report else None,
            "section_intents":overrides_to_dict(self._sync_section_intent_ranges()),"mechanical":self._mechanical_config().to_dict(),
            "candidates":[item.to_dict(include_plan=False) for item in self.quality_candidates],"improvement_history":list(self.improvement_history),
        }
        if self.plan: quality["mechanical_diagnostics"]=trajectory_mechanical_risk(self.plan,self.sr6_geometry,self._mechanical_config())
        metadata["quality_intelligence"]=quality; metadata["notes"]=str(metadata.get("notes", ""))+"; generation=2.7-quality-intelligence"
        return metadata


def ux(args):
    app=MultiAxisWindow(args); app.mainloop()
