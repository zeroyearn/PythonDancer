"""Asynchronous Quality Intelligence runtime for the 2.7 workstation.

Full weak-range scoring stays off the Tk thread. Mutating background jobs use
optimistic concurrency: they work from immutable snapshots and are discarded if
the editable motion state changes before completion.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Thread
from tkinter import messagebox

from .improvement import ImprovementConfig, auto_improve
from .multiaxis import AXIS_ORDER, plan_multiaxis
from .quality import score_plan
from .workspace import copy_plan, splice_plan
from .workstation_ui_v27_hotfix import MultiAxisWindow as _HotfixWindow, _effective_output_snapshot


def _plan_fingerprint(plan):
    if plan is None:
        return ()
    result = []
    for axis in AXIS_ORDER:
        rows = tuple(
            (round(float(at), 6), round(float(pos), 5))
            for at, pos in plan.get(axis, ())
        )
        result.append((axis, len(rows), hash(rows)))
    return tuple(result)


class MultiAxisWindow(_HotfixWindow):
    def _build_ui(self):
        self.score_worker: Thread | None = None
        self._score_revision = 0
        self._score_pending = None
        self._closing = False
        super()._build_ui()

    def after(self, ms, func=None, *args):
        """Drop late worker callbacks once shutdown has started."""
        if getattr(self, "_closing", False) and func is not None:
            return None
        try:
            return super().after(ms, func, *args)
        except Exception:
            if getattr(self, "_closing", False):
                return None
            raise

    def _motion_state_fingerprint(self):
        return (
            _plan_fingerprint(self.base_plan),
            self._candidate_context(),
            repr(self.generated_config),
            repr(sorted(self.section_intent_overrides.items())) if hasattr(self, "section_intent_overrides") else "",
        )

    # ---------- asynchronous current-plan scoring ----------
    def score_current(self):
        if not self.plan or self.data is None or self._closing:
            return
        try:
            snapshot = (
                copy_plan(self.plan),
                self.data,
                list(self._sections_payload()),
                self.sr6_geometry,
                self._mechanical_config(),
            )
        except Exception as exc:
            self.quality_summary_var.set(f"Quality scoring failed: {exc}")
            return

        self._score_revision += 1
        revision = self._score_revision
        self._score_pending = (revision, snapshot)
        self.quality_summary_var.set("Quality Intelligence · scoring in background…")
        self._launch_pending_score()

    def _launch_pending_score(self):
        if self._closing or self._score_pending is None:
            return
        if self.score_worker is not None and self.score_worker.is_alive():
            return

        revision, snapshot = self._score_pending
        self._score_pending = None
        plan, data, sections, geometry, mechanical = snapshot

        def work():
            try:
                report = score_plan(
                    plan,
                    data,
                    sections=sections,
                    geometry=geometry,
                    mechanical_config=mechanical,
                )
            except Exception as exc:
                self._schedule_score_callback(lambda e=exc: self._score_failed_async(revision, e))
                return
            self._schedule_score_callback(lambda r=report: self._score_done_async(revision, r))

        self.score_worker = Thread(target=work, daemon=True)
        self.score_worker.start()

    def _schedule_score_callback(self, callback):
        if self._closing:
            return
        try:
            self.after(0, callback)
        except Exception:
            pass

    def _score_done_async(self, revision, report):
        self.score_worker = None
        if self._closing:
            return
        if revision == self._score_revision:
            self.quality_report = report
            self._update_quality_display(report)
        self._launch_pending_score()

    def _score_failed_async(self, revision, exc):
        self.score_worker = None
        if self._closing:
            return
        if revision == self._score_revision:
            self.quality_summary_var.set(f"Quality scoring failed: {exc}")
        self._launch_pending_score()

    def apply_mechanical_policy(self):
        """Commit the visible mechanical policy to the actual output plan now."""
        try:
            mechanical = self._mechanical_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return
        self._checkpoint()
        if self.generated_config is not None:
            self.generated_config = replace(
                self.generated_config,
                mechanical=mechanical,
                geometry=self.sr6_geometry,
            )
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.score_current()
        if self.quality_candidates:
            self._refresh_candidate_scores(mark_changed=False)
        self.status_var.set("Mechanical policy applied · current output reprojected and candidates rescored")

    # ---------- stale-result protection for mutating workers ----------
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
        try:
            config = ImprovementConfig(
                max_iterations=int(self.improve_iterations_var.get()),
                target_score=float(self.improve_target_var.get()),
                minimum_improvement=float(self.improve_min_gain_var.get()),
                candidates=max(2, min(8, int(self.quality_candidate_count_var.get()))),
            )
            generation = self._v27_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return

        self.improvement_summary_var.set("Auto Improvement: scoring weak ranges…")
        data = self.data
        base = copy_plan(self.base_plan)
        locked = tuple(self.workspace.locked_axes())
        sections = deepcopy(self._sections_payload())
        geometry = self.sr6_geometry
        workspace = deepcopy(self.workspace)
        curve_settings = deepcopy(self.curve_settings)
        safety_settings = deepcopy(self.safety_settings)
        context = self._motion_state_fingerprint()

        def score_transform(plan, scoring_config):
            return _effective_output_snapshot(
                plan,
                scoring_config,
                base_plan=base,
                workspace=workspace,
                curve_settings=curve_settings,
                safety_settings=safety_settings,
                data=data,
            )

        def work():
            try:
                result = auto_improve(
                    data,
                    base,
                    generation,
                    config=config,
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

    def _improvement_done_guarded(self, context, result):
        if self._closing:
            return
        if context != self._motion_state_fingerprint():
            self.improvement_summary_var.set("Auto Improvement · discarded because the editor changed while it was running")
            return
        return super()._improvement_done(result)

    def regenerate_intent_section(self):
        index = self._selected_section_index()
        if (
            self.data is None
            or self.generated_config is None
            or not self.workspace
            or not 0 <= index < len(self.workspace.sections)
            or (self.quality_worker and self.quality_worker.is_alive())
        ):
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before regenerating a section.")
            return

        # Keep the original behavior of applying the visible section Intent
        # first, then snapshot every input used by the worker.
        self.apply_section_intent()
        section = self.workspace.sections[index]
        start, end, label = float(section.start), float(section.end), str(section.label)
        config = self._v27_config()
        data = self.data
        base = copy_plan(self.base_plan)
        locked = tuple(self.workspace.locked_axes())
        context = self._motion_state_fingerprint()
        self.section_intent_summary_var.set(f"Section Intent · regenerating {label}…")

        def work():
            try:
                replacement = plan_multiaxis(data, config)
                merged = splice_plan(
                    base,
                    replacement,
                    start,
                    end,
                    locked_axes=locked,
                    blend=.30,
                )
                self.after(0, lambda: self._section_regenerated_guarded(index, label, context, merged))
            except Exception as exc:
                self.after(0, lambda e=exc: self._quality_failed(e))

        self.quality_worker = Thread(target=work, daemon=True)
        self.quality_worker.start()

    def _section_regenerated_guarded(self, index, label, context, merged):
        if self._closing:
            return
        if context != self._motion_state_fingerprint():
            self.section_intent_summary_var.set(
                f"Section Intent · {label} result discarded because the editor changed"
            )
            return
        return super()._section_regenerated(index, merged)

    def _on_close(self):
        # Prevent all completed worker threads from scheduling callbacks into a
        # destroyed Tcl interpreter. Hardware shutdown/autosave remain handled
        # by the hardened parent close path.
        self._closing = True
        self._score_pending = None
        return super()._on_close()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
