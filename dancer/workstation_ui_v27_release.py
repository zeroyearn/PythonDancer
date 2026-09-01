"""Release entry layer for the PythonDancer 2.7 bilingual workstation."""
from __future__ import annotations

from .candidates import CandidateResult, candidate_config_from_dict
from .i18n_v27 import install_v27_translations
from .intent import INTENT_FIELDS
from .multiaxis import AXIS_ORDER
from .workstation_ui_v27 import MultiAxisWindow as _QualityWindow


class MultiAxisWindow(_QualityWindow):
    def _build_ui(self):
        install_v27_translations()
        super()._build_ui()
        self.title("PythonDancer 2.7 · Quality Intelligence Workstation")
        if self.i18n is not None:
            self.i18n.bind_object(self)
            self.i18n.refresh(force=True)
        self._refresh_quality_i18n()

    def _timeline_edit_changed(self, committed=True):
        super()._timeline_edit_changed(committed=committed)
        if committed:
            self._refresh_section_intent_combo()
            self._sync_section_intent_ranges()
            if self.quality_report is not None:
                self.score_current()

    def _apply_section_label(self):
        super()._apply_section_label()
        self._refresh_section_intent_combo()
        self._sync_section_intent_ranges()

    def _adopt_candidate_config(self, config):
        """Keep the visible controls and subsequent regeneration on the same candidate character."""
        self.generated_config = config
        self.preset_var.set(config.preset)
        self.strength_var.set(float(config.strength))
        self.gesture_strength_var.set(float(config.gesture_strength))
        self.independent_axes_var.set(bool(config.independent.enabled))
        self.axis_density_var.set(float(config.independent.density))
        self.axis_threshold_var.set(float(config.independent.accent_threshold))
        self.motion_optimizer_var.set(bool(config.optimizer.enabled))
        self.pose_budget_var.set(float(config.optimizer.pose_budget))
        self.velocity_budget_var.set(float(config.optimizer.velocity_budget))
        self.optimizer_iterations_var.set(int(config.optimizer.iterations))
        if hasattr(self, "intent_override_amount_var"):
            self.intent_override_amount_var.set(float(config.independent.intent_override_amount))
        if hasattr(self, "manual_intent_vars"):
            for field in INTENT_FIELDS:
                if field in config.independent.intent_override:
                    self.manual_intent_vars[field].set(float(config.independent.intent_override[field]))

    def use_candidate(self, which):
        candidate = self._candidate_by_name(self.candidate_a_var.get() if which == "A" else self.candidate_b_var.get())
        if candidate is not None:
            self._adopt_candidate_config(candidate.config)
        super().use_candidate(which)

    def _load_project_document(self, project):
        super()._load_project_document(project)
        state = project.quality_intelligence or {}
        raw_candidates = list(state.get("candidates", []) or [])
        if self.generated_config is None or not raw_candidates:
            return

        # Schema-3 files written before candidate config persistence still load:
        # their top-level preset/strength/gesture fields are used as a fallback.
        try:
            base = self._v27_config(self.generated_config)
        except Exception:
            base = self.generated_config
        restored = []
        for item in raw_candidates:
            quality = self._report_from_dict(item.get("quality"))
            if quality is None:
                continue
            plan = {
                axis: [(float(row[0]), float(row[1])) for row in (item.get("plan") or {}).get(axis, [])]
                for axis in AXIS_ORDER
            }
            config_payload = item.get("config") or {
                "preset": item.get("preset", base.preset),
                "strength": item.get("strength", base.strength),
                "gesture_strength": item.get("gesture_strength", base.gesture_strength),
            }
            try:
                candidate_config = candidate_config_from_dict(base, config_payload)
            except Exception:
                candidate_config = base
            restored.append(CandidateResult(str(item.get("name", "Candidate")), candidate_config, plan, quality))

        if not restored:
            return
        self.quality_candidates = restored
        self._populate_candidate_tree()
        names = [item.name for item in restored]
        self.candidate_a_combo["values"] = names
        self.candidate_b_combo["values"] = names
        selected_a = state.get("candidate_a")
        selected_b = state.get("candidate_b")
        self.candidate_a_var.set(selected_a if selected_a in names else names[0])
        self.candidate_b_var.set(selected_b if selected_b in names else names[min(1, len(names) - 1)])
        self.compare_ab()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
