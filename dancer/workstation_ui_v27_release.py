"""Release entry layer for the PythonDancer 2.7 bilingual workstation."""
from __future__ import annotations

from .i18n_v27 import install_v27_translations
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


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
