"""Redesigned desktop GUI for six-axis choreography.

This module intentionally subclasses the stable device/generation window so the
2.3 motion engine and TCode behavior stay untouched while the information
architecture and visualization are improved.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .multiaxis import AXIS_CHANNELS, AXIS_ORDER
from .multiaxis_ui import MultiAxisWindow as _CoreMultiAxisWindow


BG = "#F3F5F8"
CARD = "#FFFFFF"
BORDER = "#DDE3EA"
TEXT = "#172033"
MUTED = "#667085"
ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
DANGER = "#DC2626"
DANGER_HOVER = "#B91C1C"
PLOT_BG = "#FBFCFE"
GRID = "#E7EBF0"
TRANSLATION = "#2563EB"
ROTATION = "#7C3AED"


class MultiAxisWindow(_CoreMultiAxisWindow):
    """UI-only redesign over the validated six-axis/TCode implementation."""

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.configure(background=BG)
        style.configure("App.TFrame", background=BG)
        style.configure("Header.TFrame", background=CARD)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure(
            "Title.TLabel",
            background=CARD,
            foreground=TEXT,
            font=("TkDefaultFont", 17, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=CARD,
            foreground=MUTED,
            font=("TkDefaultFont", 9),
        )
        style.configure(
            "Section.TLabel",
            background=CARD,
            foreground=TEXT,
            font=("TkDefaultFont", 11, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=CARD,
            foreground=MUTED,
            font=("TkDefaultFont", 9),
        )
        style.configure(
            "Metric.TLabel",
            background=CARD,
            foreground=TEXT,
            font=("TkDefaultFont", 9, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=BG,
            foreground=MUTED,
            font=("TkDefaultFont", 9),
        )
        style.configure(
            "Accent.TButton",
            foreground="#FFFFFF",
            background=ACCENT,
            bordercolor=ACCENT,
            padding=(15, 8),
            font=("TkDefaultFont", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", "#AFC4F4")],
            bordercolor=[("active", ACCENT_HOVER), ("disabled", "#AFC4F4")],
        )
        style.configure(
            "Danger.TButton",
            foreground="#FFFFFF",
            background=DANGER,
            bordercolor=DANGER,
            padding=(10, 6),
            font=("TkDefaultFont", 9, "bold"),
        )
        style.map(
            "Danger.TButton",
            background=[("active", DANGER_HOVER), ("disabled", "#F2B7B7")],
            bordercolor=[("active", DANGER_HOVER), ("disabled", "#F2B7B7")],
        )
        style.configure("Soft.TButton", padding=(10, 6))
        style.configure("Compact.TButton", padding=(8, 5))
        style.configure("TEntry", padding=(7, 6))
        style.configure("TCombobox", padding=(6, 5))
        style.configure("TSpinbox", padding=(6, 5))
        style.configure("TCheckbutton", background=CARD, foreground=TEXT)

    def _card(self, parent, title: str, subtitle: str | None = None):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        row = 1
        if subtitle:
            ttk.Label(
                frame,
                text=subtitle,
                style="Muted.TLabel",
                wraplength=280,
                justify="left",
            ).grid(row=row, column=0, sticky="ew", pady=(3, 10))
            row += 1
        body = ttk.Frame(frame, style="Card.TFrame")
        body.grid(row=row, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        return frame, body

    def _label(self, parent, text: str, row: int, **grid):
        ttk.Label(parent, text=text, style="Muted.TLabel").grid(
            row=row, column=0, sticky="w", **grid
        )

    def _build_ui(self):
        self.title("PythonDancer · Six-axis Choreography")
        self.geometry("1480x900")
        self.minsize(1180, 760)
        self._configure_style()

        self.device_status_var = tk.StringVar(value="Not connected")
        self.result_summary_var = tk.StringVar(value="No choreography generated")
        self.axis_count_vars = {
            axis: tk.StringVar(value=f"{axis} · {AXIS_CHANNELS[axis]} · —")
            for axis in AXIS_ORDER
        }

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()

        body = ttk.Frame(self, style="App.TFrame", padding=(12, 12, 12, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=300)
        body.columnconfigure(1, weight=1, minsize=520)
        body.columnconfigure(2, minsize=310)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)

        center = ttk.Frame(body, style="App.TFrame")
        center.grid(row=0, column=1, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)

        right = ttk.Frame(body, style="App.TFrame")
        right.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)

        self._build_motion_card(left)
        self._build_intelligence_card(left)
        self._build_result_header(center)
        self._build_preview(center)
        self._build_timeline(center)
        self._build_device_card(right)
        self._build_export_card(right)

        footer = ttk.Frame(self, style="App.TFrame", padding=(14, 3, 14, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.summary_label = ttk.Label(footer, text="", style="Status.TLabel")
        self.summary_label.grid(row=0, column=1, sticky="e")

    def _build_header(self):
        header = ttk.Frame(self, style="Header.TFrame", padding=(16, 13, 16, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        brand = ttk.Frame(header, style="Header.TFrame")
        brand.grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(brand, text="PythonDancer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(brand, text="Six-axis music choreography", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(1, 0)
        )

        source = ttk.Frame(header, style="Header.TFrame")
        source.grid(row=0, column=1, sticky="ew")
        source.columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(source, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(source, text="Browse…", command=self.browse, style="Soft.TButton").grid(
            row=0, column=1, padx=(8, 0)
        )
        self.generate_button = ttk.Button(
            source,
            text="Generate motion",
            command=self.generate,
            style="Accent.TButton",
        )
        self.generate_button.grid(row=0, column=2, padx=(8, 0))

    def _build_motion_card(self, parent):
        card, body = self._card(
            parent,
            "1 · Motion setup",
            "Start here. These controls define the overall movement character.",
        )
        card.grid(row=0, column=0, sticky="ew")

        rows = [
            ("Preset", self.preset_var, ("balanced", "rhythm", "expressive"), "combo"),
            ("Mode", self.mode_var, ("choreography", "reactive"), "combo"),
            ("Axis strength", self.strength_var, None, "strength"),
            ("Gesture strength", self.gesture_strength_var, None, "strength"),
            ("Subdivision", self.subdivision_var, (0, 1, 2, 4), "combo"),
        ]
        for row, (label, variable, values, kind) in enumerate(rows):
            self._label(body, label, row, pady=(8 if row else 0, 0))
            if kind == "combo":
                widget = ttk.Combobox(body, textvariable=variable, values=values, state="readonly")
            else:
                widget = ttk.Spinbox(body, textvariable=variable, from_=0.0, to=3.0, increment=0.05)
            widget.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=(8 if row else 0, 0))

        ttk.Checkbutton(
            body,
            text="Auto-tune L0 pitch and energy",
            variable=self.automap_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_intelligence_card(self, parent):
        card, body = self._card(
            parent,
            "2 · Musical intelligence",
            "Optional structure, learned style, and stem-aware controls.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        notebook = ttk.Notebook(body)
        notebook.grid(row=0, column=0, columnspan=2, sticky="ew")

        structure = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        structure.columnconfigure(1, weight=1)
        notebook.add(structure, text="Structure")
        for row, (label, variable, upper) in enumerate(
            (
                ("Beats / bar", self.beats_per_bar_var, 12),
                ("Bars / phrase", self.bars_per_phrase_var, 16),
                ("Section bars", self.section_bars_var, 16),
            )
        ):
            ttk.Label(structure, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", pady=(7 if row else 0, 0)
            )
            ttk.Spinbox(structure, textvariable=variable, from_=1, to=upper, increment=1).grid(
                row=row, column=1, sticky="ew", padx=(10, 0), pady=(7 if row else 0, 0)
            )

        style_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        style_tab.columnconfigure(0, weight=1)
        notebook.add(style_tab, text="Style & stems")

        ttk.Label(style_tab, text="Choreography profile", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        row = ttk.Frame(style_tab, style="Card.TFrame")
        row.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.profile_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Choose…", command=self.browse_profile, style="Compact.TButton").grid(
            row=0, column=1, padx=(6, 0)
        )

        ttk.Label(style_tab, text="Reference bundle", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        row = ttk.Frame(style_tab, style="Card.TFrame")
        row.grid(row=3, column=0, sticky="ew", pady=(4, 8))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.reference_bundle_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Choose…", command=self.browse_reference, style="Compact.TButton").grid(
            row=0, column=1, padx=(6, 0)
        )

        stem = ttk.Frame(style_tab, style="Card.TFrame")
        stem.grid(row=4, column=0, sticky="ew")
        stem.columnconfigure(1, weight=1)
        ttk.Label(stem, text="Stems", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            stem,
            textvariable=self.stem_mode_var,
            values=("off", "auto", "required"),
            state="readonly",
            width=10,
        ).grid(row=0, column=1, sticky="e")

        row = ttk.Frame(style_tab, style="Card.TFrame")
        row.grid(row=5, column=0, sticky="ew", pady=(7, 0))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.stem_dir_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Stem folder…", command=self.browse_stem_dir, style="Compact.TButton").grid(
            row=0, column=1, padx=(6, 0)
        )

    def _build_result_header(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(14, 11))
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="Motion preview", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, textvariable=self.result_summary_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )
        ttk.Label(card, textvariable=self.section_summary_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(card, textvariable=self.style_summary_var, style="Muted.TLabel").grid(
            row=1, column=1, sticky="e", pady=(3, 0)
        )

    def _build_preview(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=8)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(8.6, 5.7), dpi=100, facecolor=CARD)
        self.preview_axes = {}
        for axis in AXIS_ORDER:
            index = int(axis[1])
            column = 0 if axis.startswith("L") else 1
            self.preview_axes[axis] = self.figure.add_subplot(3, 2, index * 2 + column + 1)
        self.axes = self.preview_axes["L0"]  # compatibility with the core window
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        widget = self.canvas.get_tk_widget()
        widget.configure(background=CARD, highlightthickness=0)
        widget.grid(row=0, column=0, sticky="nsew")

    def _style_axes(self):
        for axis in AXIS_ORDER:
            ax = self.preview_axes[axis]
            ax.set_facecolor(PLOT_BG)
            ax.set_ylim(0, 100)
            ax.set_yticks((0, 50, 100))
            ax.grid(axis="y", color=GRID, linewidth=0.7)
            ax.set_title(
                f"{axis} · {AXIS_CHANNELS[axis]}",
                loc="left",
                fontsize=9,
                fontweight="bold",
                color=TEXT,
                pad=5,
            )
            ax.tick_params(axis="both", labelsize=7, colors=MUTED, length=2)
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            if axis not in ("L2", "R2"):
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.set_xlabel("Time (s)", fontsize=8, color=MUTED)
        self.figure.subplots_adjust(left=0.07, right=0.98, top=0.96, bottom=0.09, hspace=0.35, wspace=0.16)

    def _build_timeline(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10))
        frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        top = ttk.Frame(frame, style="Card.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Playback timeline", style="Metric.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.timeline_label_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        self.timeline_scale = ttk.Scale(frame, variable=self.timeline_var, from_=0.0, to=1.0)
        self.timeline_scale.grid(row=1, column=0, sticky="ew", pady=(7, 8))
        self.timeline_scale.bind("<ButtonPress-1>", self._timeline_press)
        self.timeline_scale.bind("<ButtonRelease-1>", self._timeline_release)

        counts = ttk.Frame(frame, style="Card.TFrame")
        counts.grid(row=2, column=0, sticky="ew")
        for index, axis in enumerate(AXIS_ORDER):
            counts.columnconfigure(index, weight=1)
            ttk.Label(counts, textvariable=self.axis_count_vars[axis], style="Muted.TLabel").grid(
                row=0, column=index, sticky="w" if index == 0 else "e", padx=(0 if index == 0 else 5, 0)
            )

    def _build_device_card(self, parent):
        card, body = self._card(
            parent,
            "3 · TCode device",
            "Probe the controller, then play the generated motion.",
        )
        card.grid(row=0, column=0, sticky="ew")

        ttk.Label(body, text="Device status", style="Muted.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, textvariable=self.device_status_var, style="Metric.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 10)
        )

        self._label(body, "Serial port", 2)
        self.port_combo = ttk.Combobox(body, textvariable=self.port_var)
        self.port_combo.grid(row=2, column=1, sticky="ew", padx=(10, 0))

        row = ttk.Frame(body, style="Card.TFrame")
        row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        ttk.Button(row, text="Refresh ports", command=self.refresh_ports, style="Compact.TButton").grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(row, text="Probe D0/D1/D2", command=self.probe_device, style="Compact.TButton").grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self._label(body, "Baud", 4, pady=(10, 0))
        ttk.Combobox(body, textvariable=self.baud_var, values=(115200, 250000, 500000, 1000000)).grid(
            row=4, column=1, sticky="ew", padx=(10, 0), pady=(10, 0)
        )
        self._label(body, "Playback speed", 5, pady=(10, 0))
        ttk.Spinbox(body, textvariable=self.play_speed_var, from_=0.1, to=4.0, increment=0.1).grid(
            row=5, column=1, sticky="ew", padx=(10, 0), pady=(10, 0)
        )
        ttk.Checkbutton(body, text="Respect D2 axis ranges", variable=self.device_ranges_var).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(11, 0)
        )

        transport = ttk.Frame(body, style="Card.TFrame")
        transport.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(13, 0))
        transport.columnconfigure(0, weight=1)
        transport.columnconfigure(1, weight=1)
        self.play_button = ttk.Button(
            transport, text="▶  Play", command=self.play_device, state="disabled", style="Accent.TButton"
        )
        self.play_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.pause_button = ttk.Button(
            transport, text="Pause", command=self.pause_device, state="disabled", style="Soft.TButton"
        )
        self.pause_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.resume_button = ttk.Button(
            transport, text="Resume", command=self.resume_device, state="disabled", style="Soft.TButton"
        )
        self.resume_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        self.stop_button = ttk.Button(
            transport, text="■  STOP", command=self.stop_device, state="disabled", style="Danger.TButton"
        )
        self.stop_button.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(8, 0))

    def _build_export_card(self, parent):
        card, body = self._card(
            parent,
            "4 · Export",
            "Save a six-axis bundle, scheduled TCode, or learned profile.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.export_button = ttk.Button(
            body, text="Export six-axis bundle…", command=self.export, state="disabled", style="Soft.TButton"
        )
        self.export_button.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.tcode_export_button = ttk.Button(
            body, text="Export scheduled .tcode…", command=self.export_tcode, state="disabled", style="Soft.TButton"
        )
        self.tcode_export_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.save_profile_button = ttk.Button(
            body, text="Save learned profile…", command=self.save_generated_profile, state="disabled", style="Soft.TButton"
        )
        self.save_profile_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(
            body,
            text="Output: L0/L1/L2/R0/R1/R2 standard funscript bundle.",
            style="Muted.TLabel",
            wraplength=270,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def _generation_done(self, data, plan, analysis, config, pitch, energy):
        super()._generation_done(data, plan, analysis, config, pitch, energy)

        duration = float(data.get("at", 0.0) or self.duration)
        self.result_summary_var.set(
            f"{duration:.1f}s · {config.mode} · {config.preset} · gesture {config.gesture_strength:.2f}"
        )
        for axis in AXIS_ORDER:
            self.axis_count_vars[axis].set(f"{axis} · {AXIS_CHANNELS[axis]} · {len(plan[axis])}")
        self._redraw_six_axis_preview(data, plan, analysis)

    def _redraw_six_axis_preview(self, data, plan, analysis):
        for axis in AXIS_ORDER:
            self.preview_axes[axis].clear()
        self._style_axes()

        beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
        section_times = []
        if analysis and beats.size:
            for section in analysis.sections:
                if 0 <= section.start_beat < beats.size:
                    section_times.append((float(beats[section.start_beat]), section.label))

        for axis in AXIS_ORDER:
            ax = self.preview_axes[axis]
            actions = plan[axis]
            if actions:
                t = np.asarray([at for at, _ in actions], dtype=np.float64)
                p = np.asarray([pos for _, pos in actions], dtype=np.float64)
                color = TRANSLATION if axis.startswith("L") else ROTATION
                ax.plot(t, p, linewidth=1.15, color=color)
            for at, _label in section_times:
                ax.axvline(at, linewidth=0.6, color=MUTED, alpha=0.22)

        for axis in ("L0", "R0"):
            ax = self.preview_axes[axis]
            for at, label in section_times:
                ax.text(at, 98, label, rotation=90, va="top", ha="right", fontsize=6.5, color=MUTED, alpha=0.75)
        self.canvas.draw_idle()

    def _generation_failed(self, exc: Exception):
        super()._generation_failed(exc)
        self.result_summary_var.set("Generation failed")

    def probe_device(self):
        self.device_status_var.set("Probing device…")
        super().probe_device()

    def _probe_done(self, profile):
        super()._probe_done(profile)
        axes = [axis for axis in AXIS_ORDER if axis in profile.axes]
        self.device_status_var.set(
            f"Connected · {len(axes)} motion axes" if axes else "Connected · D2 ranges unavailable"
        )

    def play_device(self):
        if self.port_var.get().strip():
            self.device_status_var.set(f"Opening {self.port_var.get().strip()}…")
        super().play_device()

    def pause_device(self):
        super().pause_device()
        if self.active_controller is not None:
            self.device_status_var.set("Paused")

    def resume_device(self):
        super().resume_device()
        if self.active_controller is not None:
            self.device_status_var.set("Resuming…")

    def stop_device(self):
        super().stop_device()
        self.device_status_var.set("Stopping…")

    def _tick_playback(self):
        controller = self.active_controller
        if controller is not None:
            state = controller.state
            if state == "playing":
                self.device_status_var.set(f"Playing · {controller.position:.1f}s")
            elif state == "paused":
                self.device_status_var.set(f"Paused · {controller.position:.1f}s")
        super()._tick_playback()

    def _device_done(self):
        super()._device_done()
        self.device_status_var.set("Ready")

    def _device_failed(self, exc: Exception):
        super()._device_failed(exc)
        self.device_status_var.set("Playback failed")


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()


if __name__ == "__main__":
    from .util import cli_args

    ux(cli_args().parse_args())
