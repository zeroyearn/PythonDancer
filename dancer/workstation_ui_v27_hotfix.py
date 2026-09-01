"""Final runtime hardening for the PythonDancer 2.7 workstation.

Keeps candidate ranking responsive by reusing worker-computed quality reports
when their scoring context is still current, while still invalidating cached
scores after locks, section edits, or mechanical-policy changes. It also makes
window shutdown stop both hardware transports and preserve a last autosave.
"""
from __future__ import annotations

from .quality import score_plan
from .workstation_ui_v27 import MultiAxisWindow as _WorkerScoredWindow
from .workstation_ui_v27_release import MultiAxisWindow as _ReleaseWindow


def _section_signature(workspace):
    if workspace is None:
        return ()
    return tuple(
        (round(float(section.start), 9), round(float(section.end), 9), str(section.label))
        for section in workspace.sections
    )


def _mechanical_signature(config):
    payload = config.to_dict()
    return tuple(sorted((str(key), repr(value)) for key, value in payload.items()))


class MultiAxisWindow(_ReleaseWindow):
    def _candidate_context(self):
        locked = tuple(self.workspace.locked_axes()) if self.workspace is not None else ()
        return (
            locked,
            _section_signature(self.workspace),
            _mechanical_signature(self._mechanical_config()),
        )

    def generate_quality_candidates(self):
        can_start = (
            self.data is not None
            and self.generated_config is not None
            and not (self.quality_worker and self.quality_worker.is_alive())
            and not (self.worker and self.worker.is_alive())
        )
        if can_start:
            self._candidate_generation_context = self._candidate_context()
        return super().generate_quality_candidates()

    def _rescore_candidate_list(self, candidates):
        """Rank candidates under the current editor state without weak-window scans."""
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
            from dataclasses import replace
            from .candidates import CandidateResult
            config = replace(candidate.config, mechanical=mechanical, geometry=self.sr6_geometry)
            rescored.append(CandidateResult(candidate.name, config, candidate.plan, quality))
        rescored.sort(key=lambda item: (-item.quality.overall, item.name))
        return rescored

    def _candidate_cache_is_current(self):
        generated = getattr(self, "_candidate_generation_context", None)
        if generated is None:
            return False
        current = self._candidate_context()
        # Candidate generation does not preserve editor-locked axes, so any lock
        # requires an effective-plan rescore even if the lock existed at launch.
        if current[0]:
            return False
        return current[1:] == generated[1:]

    def _candidates_done(self, results):
        final = list(results) if self._candidate_cache_is_current() else self._rescore_candidate_list(results)
        # Skip the release-layer unconditional rescore; the worker reports are
        # already valid when the generation context is unchanged.
        _WorkerScoredWindow._candidates_done(self, final)
        self._candidate_generation_context = self._candidate_context()
        self._mark_changed()

    def _refresh_candidate_scores(self, *, mark_changed=False):
        super()._refresh_candidate_scores(mark_changed=mark_changed)
        if self.quality_candidates:
            self._candidate_generation_context = self._candidate_context()

    def _timeline_edit_changed(self, committed=True):
        super()._timeline_edit_changed(committed=committed)
        if committed and self.quality_candidates:
            # Section boundaries participate in phrase alignment, so cached
            # candidate scores are invalid after a committed timeline edit.
            self._refresh_candidate_scores(mark_changed=False)

    def compare_ab(self):
        a = self._candidate_by_name(self.candidate_a_var.get())
        b = self._candidate_by_name(self.candidate_b_var.get())
        if not a or not b:
            return
        if self._candidate_cache_is_current():
            from .comparison import compare_plans
            from .workstation_ui_v27 import _METRIC_LABELS
            report = compare_plans(
                a.plan,
                b.plan,
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
            return
        return super().compare_ab()

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