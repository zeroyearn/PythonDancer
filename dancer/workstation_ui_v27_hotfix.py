"""Final runtime hardening for the PythonDancer 2.7 workstation.

Candidate quality, A/B preview, best-section selection, adopted output and device
playback all use the same effective motion chain. Candidate generation snapshots
editable state and scores that effective output in its worker, so the Tk thread
stays responsive and raw candidate plans remain non-destructive base plans.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Thread
from tkinter import messagebox

import numpy as np

from .candidates import CandidateResult, generate_candidates
from .comparison import _slice_data, compare_plans, merge_candidate_sections
from .editing import resample_curve
from .multiaxis import AXIS_ORDER
from .plan_window import slice_plan
from .quality import score_plan
from .safety import apply_axis_links, apply_smart_limits, fill_motion_gaps
from .workspace import copy_plan
from .workspace_constraints import constrain_workspace_plan
from .workstation_ui_v27 import MultiAxisWindow as _WorkerScoredWindow, _METRIC_LABELS
from .workstation_ui_v27_release import MultiAxisWindow as _ReleaseWindow


def _section_signature(workspace):
    if workspace is None:
        return ()
    return tuple(
        (round(float(section.start), 9), round(float(section.end), 9), str(section.label))
        for section in workspace.sections
    )


def _workspace_motion_signature(workspace):
    if workspace is None:
        return ()
    gestures = tuple(
        (
            round(float(item.start), 9), round(float(item.end), 9), item.gesture,
            round(float(item.strength), 9), tuple(sorted((str(k), round(float(v), 9)) for k, v in item.axis_mix.items())),
            round(float(item.phase_offset), 9), round(float(item.cycles), 9), int(item.direction),
            round(float(item.blend_in), 9), round(float(item.blend_out), 9),
        )
        for item in workspace.gestures
    )
    axes = tuple(
        (axis, bool(workspace.axes[axis].muted), bool(workspace.axes[axis].locked))
        for axis in AXIS_ORDER
    )
    return (_section_signature(workspace), gestures, axes)


def _mechanical_signature(config):
    payload = config.to_dict()
    return tuple(sorted((str(key), repr(value)) for key, value in payload.items()))


def _curve_signature(curve_settings):
    return tuple((axis, repr(curve_settings[axis])) for axis in AXIS_ORDER)


def _safety_signature(settings):
    return repr(settings)


def _locked_base_signature(base_plan, workspace):
    if base_plan is None or workspace is None:
        return ()
    result = []
    for axis in workspace.locked_axes():
        rows = tuple((round(float(t), 6), round(float(p), 5)) for t, p in base_plan.get(axis, ()))
        result.append((axis, hash(rows)))
    return tuple(result)


def _curve_plan_snapshot(plan, curve_settings):
    result = copy_plan(plan)
    for axis in AXIS_ORDER:
        settings = curve_settings[axis]
        actions = result[axis]
        if settings.interpolation == "linear" or len(actions) < 2:
            continue
        start, end = actions[0][0], actions[-1][0]
        count = max(2, int(np.ceil((end - start) * 20.0)) + 1)
        sample = np.linspace(start, end, count)
        result[axis] = resample_curve(actions, sample, settings.interpolation)
    return result


def _effective_output_snapshot(raw_plan, config, *, base_plan, workspace, curve_settings, safety_settings, data):
    base = copy_plan(raw_plan)
    for axis in workspace.locked_axes():
        base[axis] = list(base_plan.get(axis, ()))

    plan = workspace.output_plan(base)
    plan = _curve_plan_snapshot(plan, curve_settings)
    if safety_settings.links:
        plan = apply_axis_links(plan, safety_settings.links)
    if safety_settings.gap_fill != "none":
        plan = fill_motion_gaps(
            plan,
            (data or {}).get("beats", []),
            mode=safety_settings.gap_fill,
            threshold=safety_settings.gap_threshold,
        )
    if safety_settings.smart_limits:
        plan = apply_smart_limits(plan, safety_settings.profile)
    for axis in AXIS_ORDER:
        if workspace.axes[axis].muted:
            plan[axis] = []
    return constrain_workspace_plan(plan, config)


class MultiAxisWindow(_ReleaseWindow):
    def _candidate_context(self):
        return (
            _workspace_motion_signature(self.workspace),
            _curve_signature(self.curve_settings),
            _safety_signature(self.safety_settings),
            _mechanical_signature(self._mechanical_config()),
            _locked_base_signature(self.base_plan, self.workspace),
        )

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)
        self._candidate_generation_context = None
        self._candidate_scores_stale = False

    def generate_quality_candidates(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PythonDancer", "Finish the current track generation before generating candidates.")
            return
        if self.data is None or self.generated_config is None or (self.quality_worker and self.quality_worker.is_alive()):
            return
        try:
            count = max(2, min(8, int(self.quality_candidate_count_var.get())))
            config = self._v27_config()
        except Exception as exc:
            messagebox.showerror("PythonDancer", str(exc))
            return

        data = self.data
        sections = self._sections_payload()
        geometry = self.sr6_geometry
        base_plan = copy_plan(self.base_plan)
        workspace = deepcopy(self.workspace)
        curve_settings = deepcopy(self.curve_settings)
        safety_settings = deepcopy(self.safety_settings)
        generation_context = self._candidate_context()
        self._candidate_generation_context = generation_context
        self._candidate_scores_stale = False
        self.generate_candidates_button.configure(state="disabled")
        self.comparison_summary_var.set("Generating and scoring candidates…")

        def transform(plan, candidate_config):
            effective_config = replace(candidate_config, mechanical=config.mechanical, geometry=geometry)
            return _effective_output_snapshot(
                plan,
                effective_config,
                base_plan=base_plan,
                workspace=workspace,
                curve_settings=curve_settings,
                safety_settings=safety_settings,
                data=data,
            )

        def work():
            try:
                results = generate_candidates(
                    data,
                    config,
                    count=count,
                    geometry=geometry,
                    sections=sections,
                    score_transform=transform,
                )
                self.after(0, lambda: self._candidates_done(results))
            except Exception as exc:
                self.after(0, lambda e=exc: self._quality_failed(e))

        self.quality_worker = Thread(target=work, daemon=True)
        self.quality_worker.start()

    def _candidate_base_plan(self, candidate):
        plan = copy_plan(candidate.plan)
        if self.workspace is not None and self.base_plan is not None:
            for axis in self.workspace.locked_axes():
                plan[axis] = list(self.base_plan.get(axis, ()))
        return plan

    def _effective_candidate_plan(self, candidate):
        if self.workspace is None or self.base_plan is None:
            return copy_plan(candidate.plan)
        config = replace(
            candidate.config,
            mechanical=self._mechanical_config(),
            geometry=self.sr6_geometry,
        )
        return _effective_output_snapshot(
            candidate.plan,
            config,
            base_plan=self.base_plan,
            workspace=self.workspace,
            curve_settings=self.curve_settings,
            safety_settings=self.safety_settings,
            data=self.data,
        )

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
                compute_windows=False,
            )
            config = replace(candidate.config, mechanical=mechanical, geometry=self.sr6_geometry)
            rescored.append(CandidateResult(candidate.name, config, candidate.plan, quality))
        rescored.sort(key=lambda item: (-item.quality.overall, item.name))
        return rescored

    def _candidate_cache_is_current(self):
        if getattr(self, "_candidate_scores_stale", False):
            return False
        generated = getattr(self, "_candidate_generation_context", None)
        return generated is not None and generated == self._candidate_context()

    def _mark_candidate_scores_stale_if_needed(self):
        if not self.quality_candidates:
            return
        if not self._candidate_cache_is_current():
            self._candidate_scores_stale = True
            self.comparison_summary_var.set("Candidate scores changed with the editor state · A/B will refresh on demand")

    def _candidates_done(self, results):
        final = list(results) if self._candidate_cache_is_current() else self._rescore_candidate_list(results)
        # Skip the release-layer unconditional rescore: the worker already
        # scored effective output when the editor context stayed unchanged.
        _WorkerScoredWindow._candidates_done(self, final)
        self._candidate_generation_context = self._candidate_context()
        self._candidate_scores_stale = False
        self._mark_changed()

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
        self._candidate_generation_context = self._candidate_context()
        self._candidate_scores_stale = False
        if names:
            self.compare_ab()
        if mark_changed:
            self._mark_changed()

    def _apply_workspace(self, redraw=True):
        super()._apply_workspace(redraw=redraw)
        if hasattr(self, "quality_candidates"):
            self._mark_candidate_scores_stale_if_needed()

    def _timeline_edit_changed(self, committed=True):
        super()._timeline_edit_changed(committed=committed)
        if committed:
            self._mark_candidate_scores_stale_if_needed()

    def _axis_controls_changed(self):
        super()._axis_controls_changed()
        self._mark_candidate_scores_stale_if_needed()

    def compare_ab(self):
        a = self._candidate_by_name(self.candidate_a_var.get())
        b = self._candidate_by_name(self.candidate_b_var.get())
        if not a or not b:
            return
        if not self._candidate_cache_is_current():
            self._refresh_candidate_scores(mark_changed=False)
            a = self._candidate_by_name(self.candidate_a_var.get())
            b = self._candidate_by_name(self.candidate_b_var.get())
            if not a or not b:
                return
        effective_a = self._effective_candidate_plan(a)
        effective_b = self._effective_candidate_plan(b)
        report = compare_plans(
            effective_a,
            effective_b,
            self.data,
            report_a=a.quality,
            report_b=b.quality,
            geometry=self.sr6_geometry,
            mechanical_config=self._mechanical_config(),
        )
        strongest = max(report.metric_delta, key=lambda key: abs(report.metric_delta[key])) if report.metric_delta else ""
        self.comparison_summary_var.set(
            f"A/B · B−A {report.score_delta:+.1f} · {_METRIC_LABELS.get(strongest, strongest)} {report.metric_delta.get(strongest, 0):+.1f}"
        )

    def use_candidate(self, which):
        candidate = self._candidate_by_name(self.candidate_a_var.get() if which == "A" else self.candidate_b_var.get())
        if candidate is None or not self.workspace:
            return
        self._checkpoint()
        self._adopt_candidate_config(candidate.config)
        self.base_plan = self._candidate_base_plan(candidate)
        self.preview_candidate_plan = None
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.score_current()
        self.status_var.set(f"Applied candidate: {candidate.name} · locked axes preserved")

    def merge_best_sections(self):
        if len(self.quality_candidates) < 2 or not self.workspace:
            messagebox.showwarning("PythonDancer", "Generate at least two candidates first.")
            return
        if not self._candidate_cache_is_current():
            self._refresh_candidate_scores(mark_changed=False)

        effective_plans = [self._effective_candidate_plan(candidate) for candidate in self.quality_candidates]
        choices = {}
        for index, section in enumerate(self.workspace.sections):
            start, end = float(section.start), float(section.end)
            if end <= start:
                choices[index] = 0
                continue
            local_data = _slice_data(self.data, start, end)
            scores = []
            for candidate, effective in zip(self.quality_candidates, effective_plans):
                local = slice_plan(effective, start, end, rebase=True)
                scores.append(float(score_plan(
                    local,
                    local_data,
                    geometry=self.sr6_geometry,
                    mechanical_config=self._mechanical_config(),
                    compute_windows=False,
                ).overall))
            choices[index] = int(np.argmax(scores))

        self._checkpoint()
        self.base_plan = merge_candidate_sections(
            self.quality_candidates,
            self.workspace.sections,
            choices,
            base_plan=self.base_plan,
            locked_axes=self.workspace.locked_axes(),
            blend=.25,
        )
        self.preview_candidate_plan = None
        self._apply_workspace(redraw=True)
        self._mark_changed()
        self.score_current()
        summary = []
        for index, section in enumerate(self.workspace.sections):
            selected = choices.get(index, 0)
            summary.append(f"{section.label}:{self.quality_candidates[selected].name}")
        self.comparison_summary_var.set("Best sections · " + " | ".join(summary))
        self.status_var.set("Merged highest-scoring effective candidate per section · locked axes preserved")

    def _load_project_document(self, project):
        super()._load_project_document(project)
        if self.quality_candidates:
            self._candidate_generation_context = self._candidate_context()
            self._candidate_scores_stale = False

    def _on_close(self):
        # Preserve the latest editable state before Tk variables disappear.
        try:
            if getattr(self, "project_dirty", False):
                self.autosave_now(silent=True)
        except Exception:
            pass

        # Serial and Intiface use independent stop mechanisms; closing the app
        # must signal both before the Tk main loop is destroyed.
        try:
            self.intiface_stop.set()
        except Exception:
            pass
        try:
            self.serial_prestart_cancel.set()
        except Exception:
            pass
        try:
            self.stop_device()
        except Exception:
            pass
        try:
            if self.active_device is not None:
                self.active_device.stop()
        except Exception:
            pass
        self.destroy()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()