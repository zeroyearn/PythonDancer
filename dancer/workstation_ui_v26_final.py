"""Final PythonDancer 2.6 workstation integration layer."""
from __future__ import annotations

from dataclasses import replace
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from .intent import INTENT_FIELDS, infer_motion_intent
from .reference_library import cluster_profiles
from .style import learn_profile_from_bundle
from .workstation_ui_v26 import MultiAxisWindow as _V26Window


class MultiAxisWindow(_V26Window):
    def _build_ui(self):
        self.intent_override_amount_var = tk.DoubleVar(value=float(getattr(self.args, "intent_override_amount", 0.0)))
        self.manual_intent_vars = {
            field: tk.DoubleVar(value=float(getattr(self.args, f"intent_{field}", .5)))
            for field in INTENT_FIELDS
        }
        self.effective_intent_summary_var = tk.StringVar(value="Effective Intent: audio-driven")
        self.cluster_summary_var = tk.StringVar(value="Reference clusters: not analyzed")
        super()._build_ui()

    def _build_work_tabs(self, parent):
        super()._build_work_tabs(parent)
        notebooks = [child for child in parent.winfo_children() if isinstance(child, ttk.Notebook)]
        if not notebooks:
            return
        notebook = notebooks[-1]
        tabs = notebook.tabs()
        if not tabs:
            return
        quality = notebook.nametowidget(tabs[-1])
        manual = ttk.LabelFrame(quality, text="Manual Motion Intent blend", padding=10)
        manual.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for column in range(5):
            manual.columnconfigure(column, weight=1)
        ttk.Label(manual, text="Override amount", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Scale(manual, variable=self.intent_override_amount_var, from_=0.0, to=1.0, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", padx=(0, 8))
        ttk.Label(manual, textvariable=self.effective_intent_summary_var, style="Muted.TLabel", wraplength=350).grid(row=0, column=3, columnspan=2, rowspan=2, sticky="w")
        for index, field in enumerate(INTENT_FIELDS):
            row = 2 + index // 4
            column = index % 4
            box = ttk.Frame(manual, style="Card.TFrame")
            box.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0), pady=(9, 0))
            ttk.Label(box, text=field.replace("_", " "), style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Spinbox(box, textvariable=self.manual_intent_vars[field], from_=0.0, to=1.0, increment=.05, width=7).grid(row=1, column=0, sticky="ew")
        ttk.Button(manual, text="Copy inferred → manual", command=self._copy_inferred_intent, style="Compact.TButton").grid(row=4, column=4, sticky="ew", padx=(8, 0), pady=(9, 0))

    def _build_intelligence_card(self, parent):
        super()._build_intelligence_card(parent)
        cards = [child for child in parent.winfo_children() if int(child.grid_info().get("row", -1)) == 1]
        if not cards:
            return
        frames = [child for child in cards[-1].winfo_children() if isinstance(child, ttk.Frame)]
        if not frames:
            return
        body = frames[-1]
        row = ttk.Frame(body, style="Card.TFrame")
        row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, textvariable=self.cluster_summary_var, style="Muted.TLabel", wraplength=190).grid(row=0, column=0, sticky="w")
        ttk.Button(row, text="Cluster", command=self._cluster_reference_library, style="Compact.TButton").grid(row=0, column=1, padx=(6, 0))

    def _manual_intent(self):
        result = {}
        for field, variable in self.manual_intent_vars.items():
            value = float(variable.get())
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field.replace('_', ' ')} must be within 0..1")
            result[field] = value
        amount = float(self.intent_override_amount_var.get())
        if not 0.0 <= amount <= 1.0:
            raise ValueError("Intent override amount must be within 0..1")
        return result, amount

    def _quality_config(self):
        independent, optimizer = super()._quality_config()
        manual, amount = self._manual_intent()
        independent = replace(independent, intent_override=manual, intent_override_amount=amount)
        return independent, optimizer

    def _copy_inferred_intent(self):
        try:
            for field in INTENT_FIELDS:
                self.manual_intent_vars[field].set(float(self.intent_value_vars[field].get()))
            self.intent_override_amount_var.set(1.0)
            self.effective_intent_summary_var.set("Effective Intent: manual = current inferred values")
        except Exception:
            messagebox.showwarning("PythonDancer", "Generate a track before copying inferred Motion Intent.")

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        inferred = infer_motion_intent(data, analysis).global_intent.to_dict()
        manual = dict(config.independent.intent_override)
        amount = float(config.independent.intent_override_amount)
        effective = {
            field: (1.0 - amount) * inferred[field] + amount * manual.get(field, inferred[field])
            for field in INTENT_FIELDS
        }
        self.effective_intent_summary_var.set(
            f"Effective Intent · blend {amount:.2f} · intensity {effective['intensity']:.2f} · aggression {effective['aggression']:.2f} · flow {effective['flow']:.2f}"
        )

    def _cluster_reference_library(self):
        if not self.reference_library_paths:
            messagebox.showwarning("PythonDancer", "Choose a reference library first.")
            return
        self.cluster_summary_var.set("Reference clusters: analyzing…")
        paths = list(self.reference_library_paths)

        def work():
            try:
                profiles = [learn_profile_from_bundle(path) for path in paths]
                count = min(4, max(1, round(len(profiles) ** .5)))
                clusters = cluster_profiles(profiles, clusters=count)
                text = " · ".join(f"{cluster.name} ({len(cluster.member_indices)})" for cluster in clusters)
                self.after(0, lambda: self.cluster_summary_var.set("Reference clusters: " + text))
            except Exception as exc:
                self.after(0, lambda e=exc: self.cluster_summary_var.set(f"Reference clustering failed: {e}"))
        Thread(target=work, daemon=True).start()

    def _load_project_document(self, project):
        super()._load_project_document(project)
        saved_library = list((project.ui or {}).get("reference_library", []) or [])
        if saved_library:
            self.reference_library_paths = [str(value) for value in saved_library]
            self.reference_library_var.set(self._reference_library_label())
        if self.generated_config is not None:
            independent = self.generated_config.independent
            self.intent_override_amount_var.set(independent.intent_override_amount)
            for field in INTENT_FIELDS:
                self.manual_intent_vars[field].set(float(independent.intent_override.get(field, .5)))

    def _export_metadata(self):
        metadata = super()._export_metadata()
        if self.generated_config is not None:
            choreography = dict(metadata.get("choreography") or {})
            independent = dict(choreography.get("independent_axes") or {})
            independent["intent_override_amount"] = float(self.generated_config.independent.intent_override_amount)
            independent["intent_override"] = dict(self.generated_config.independent.intent_override)
            choreography["independent_axes"] = independent
            metadata["choreography"] = choreography
        return metadata


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
