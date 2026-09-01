"""Asynchronous Quality Intelligence scoring for the 2.7 workstation.

The full score includes weak-range analysis and can be expensive on long media.
This layer keeps it off the Tk thread, serializes requests, and only publishes
the newest revision after rapid edits.
"""
from __future__ import annotations

from threading import Thread

from .quality import score_plan
from .workspace import copy_plan
from .workstation_ui_v27_hotfix import MultiAxisWindow as _HotfixWindow


class MultiAxisWindow(_HotfixWindow):
    def _build_ui(self):
        self.score_worker: Thread | None = None
        self._score_revision = 0
        self._score_pending = None
        self._closing = False
        super()._build_ui()

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
            # The window may have been destroyed between the closing check and
            # Tk accepting the callback. Scoring is read-only, so dropping the
            # callback is safe.
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

    def _on_close(self):
        # Prevent completed CPU workers from scheduling callbacks into a
        # destroyed Tcl interpreter. Hardware shutdown/autosave remain handled
        # by the hardened parent close path.
        self._closing = True
        self._score_pending = None
        return super()._on_close()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()
