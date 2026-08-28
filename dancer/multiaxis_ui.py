"""Tk GUI for six-axis PythonDancer planning and bundle export."""
from __future__ import annotations

from pathlib import Path
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .libfun import autoval, load_audio_data
from .motion import MotionConfig
from .multiaxis import AXIS_CHANNELS, AXIS_ORDER, MultiAxisConfig, export_funscript_bundle, plan_multiaxis


class MultiAxisWindow(tk.Tk):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.data = None
        self.plan = None
        self.source_path: Path | None = Path(args.audio_path) if args.audio_path else None
        self.worker: Thread | None = None

        self.title("PythonDancer - Six-axis planner")
        self.geometry("1120x820")
        self.minsize(920, 680)

        self.path_var = tk.StringVar(value=str(self.source_path or ""))
        self.preset_var = tk.StringVar(value=args.multiaxis_preset)
        self.strength_var = tk.DoubleVar(value=args.axis_strength)
        self.subdivision_var = tk.IntVar(value=args.subdivision)
        self.automap_var = tk.BooleanVar(value=args.automap)
        self.status_var = tk.StringVar(value="Select media and generate a six-axis plan.")

        self._build_ui()
        if self.source_path:
            self.after(150, self.generate)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.Frame(self, padding=10)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Media").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.path_entry = ttk.Entry(controls, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Browse", command=self.browse).grid(row=0, column=2, padx=(8, 0))

        settings = ttk.Frame(controls)
        settings.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        ttk.Label(settings, text="Preset").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            settings,
            textvariable=self.preset_var,
            values=("balanced", "rhythm", "expressive"),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=(6, 18))

        ttk.Label(settings, text="Axis strength").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            settings,
            textvariable=self.strength_var,
            from_=0.0,
            to=3.0,
            increment=0.05,
            width=7,
        ).grid(row=0, column=3, padx=(6, 18))

        ttk.Label(settings, text="Subdivision").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            settings,
            textvariable=self.subdivision_var,
            values=(0, 1, 2, 4),
            state="readonly",
            width=5,
        ).grid(row=0, column=5, padx=(6, 18))

        ttk.Checkbutton(settings, text="Automap L0", variable=self.automap_var).grid(row=0, column=6, padx=(0, 18))
        self.generate_button = ttk.Button(settings, text="Generate / Refresh", command=self.generate)
        self.generate_button.grid(row=0, column=7, padx=(0, 8))
        self.export_button = ttk.Button(settings, text="Export bundle", command=self.export, state="disabled")
        self.export_button.grid(row=0, column=8)

        preview = ttk.LabelFrame(self, text="Six-axis preview", padding=6)
        preview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(10, 6), tight_layout=True)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_ylim(0, 100)
        self.axes.set_xlabel("Time (s)")
        self.axes.set_ylabel("Normalized position")
        self.canvas = FigureCanvasTkAgg(self.figure, master=preview)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        footer = ttk.Frame(self, padding=(10, 0, 10, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.summary_label = ttk.Label(footer, text="")
        self.summary_label.grid(row=0, column=1, sticky="e")

    def browse(self):
        path = filedialog.askopenfilename(title="Open media")
        if path:
            self.source_path = Path(path)
            self.path_var.set(path)
            self.generate()

    def _motion_config(self, pitch: float, energy: float, subdivision: int) -> MotionConfig:
        return MotionConfig(
            energy_multiplier=float(energy),
            pitch_range=float(pitch),
            overflow=int(self.args.overflow),
            amplitude_centering=float(self.args.amplitude_centering),
            center_offset=float(self.args.center_offset),
            subdivision=int(subdivision),
            max_speed=float(self.args.max_speed),
            max_acceleration=float(self.args.max_acceleration),
            min_interval=float(self.args.min_interval),
        )

    def generate(self):
        if self.worker and self.worker.is_alive():
            return

        raw_path = self.path_var.get().strip()
        if not raw_path:
            messagebox.showwarning("PythonDancer", "Choose a media file first.")
            return
        source = Path(raw_path)
        if not source.exists():
            messagebox.showerror("PythonDancer", f"File does not exist:\n{source}")
            return

        try:
            strength = float(self.strength_var.get())
            if strength < 0:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror("PythonDancer", "Axis strength must be a non-negative number.")
            return

        preset = self.preset_var.get()
        subdivision = int(self.subdivision_var.get())
        automap = bool(self.automap_var.get())

        self.source_path = source
        self.status_var.set("Analyzing audio and planning six axes...")
        self.generate_button.configure(state="disabled")
        self.export_button.configure(state="disabled")

        def work():
            try:
                data = load_audio_data(source, plp=not self.args.no_plp)
                pitch = float(self.args.pitch)
                energy = float(self.args.energy)
                if automap:
                    pitch, energy = autoval(
                        data,
                        tpi=self.args.auto_pitch,
                        target_speed=self.args.auto_speed,
                        v2above=self.args.auto_per / 100.0,
                        opt=self.args.auto_mod - 1,
                        planner="adaptive",
                    )
                config = MultiAxisConfig(
                    motion=self._motion_config(pitch, energy, subdivision),
                    preset=preset,
                    strength=strength,
                )
                plan = plan_multiaxis(data, config)
                if not plan["L0"]:
                    raise ValueError("No actions could be generated from this input")
                self.after(0, lambda: self._generation_done(data, plan, pitch, energy))
            except Exception as exc:
                self.after(0, lambda e=exc: self._generation_failed(e))

        self.worker = Thread(target=work, daemon=True)
        self.worker.start()

    def _generation_done(self, data, plan, pitch, energy):
        self.data = data
        self.plan = plan
        self.generate_button.configure(state="normal")
        self.export_button.configure(state="normal")

        self.axes.clear()
        for axis in AXIS_ORDER:
            actions = plan[axis]
            if not actions:
                continue
            t = np.asarray([at for at, _ in actions], dtype=np.float64)
            p = np.asarray([pos for _, pos in actions], dtype=np.float64)
            self.axes.plot(t, p, linewidth=0.9, label=f"{axis} {AXIS_CHANNELS[axis]}")

        self.axes.set_ylim(0, 100)
        self.axes.set_xlabel("Time (s)")
        self.axes.set_ylabel("Normalized position")
        self.axes.legend(loc="upper right", ncol=3, fontsize=8)
        self.canvas.draw_idle()

        duration = float(data.get("at", 0.0) or 0.0)
        counts = "/".join(str(len(plan[axis])) for axis in AXIS_ORDER)
        self.status_var.set(
            f"Ready — {duration:.1f}s, preset={self.preset_var.get()}, "
            f"L0 pitch={pitch:.1f}, energy={energy:.2f}"
        )
        self.summary_label.configure(text=f"actions L0..R2: {counts}")

    def _generation_failed(self, exc: Exception):
        self.generate_button.configure(state="normal")
        self.export_button.configure(state="disabled")
        self.status_var.set(f"Generation failed: {exc}")
        messagebox.showerror("PythonDancer", f"Generation failed:\n{exc}")

    def export(self):
        if not self.plan or not self.source_path:
            return

        initial = self.source_path.with_suffix(".funscript").name
        selected = filedialog.asksaveasfilename(
            title="Export six-axis funscript bundle",
            defaultextension=".funscript",
            initialfile=initial,
            filetypes=[("Funscript", "*.funscript"), ("All files", "*.*")],
        )
        if not selected:
            return

        try:
            written = export_funscript_bundle(
                selected,
                self.plan,
                metadata={
                    "notes": (
                        f"planner=multiaxis; preset={self.preset_var.get()}; "
                        f"axis_strength={float(self.strength_var.get())}"
                    )
                },
                manifest=not self.args.no_manifest,
            )
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"Export failed:\n{exc}")
            return

        self.status_var.set(f"Exported six-axis bundle to {written['L0'].parent}")
        messagebox.showinfo(
            "PythonDancer",
            "Six-axis bundle exported.\n\n" + "\n".join(f"{axis}: {written[axis].name}" for axis in AXIS_ORDER),
        )


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()


if __name__ == "__main__":
    from .util import cli_args
    ux(cli_args().parse_args())
