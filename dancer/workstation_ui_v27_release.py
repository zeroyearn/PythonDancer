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


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
