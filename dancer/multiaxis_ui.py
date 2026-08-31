"""Tk GUI for six-axis PythonDancer planning, export, and TCode playback."""
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
from .tcode import (
    SerialTCodeDevice,
    TCodePlaybackController,
    build_tcode_events,
    default_tcode_path,
    export_tcode_script,
    list_serial_ports,
    plan_duration,
)


class MultiAxisWindow(tk.Tk):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.data = None
        self.plan = None
        self.source_path: Path | None = Path(args.audio_path) if args.audio_path else None
        self.worker: Thread | None = None
        self.device_worker: Thread | None = None
        self.active_device: SerialTCodeDevice | None = None
        self.active_controller: TCodePlaybackController | None = None
        self.device_profile = None
        self.timeline_dragging = False
        self.duration = 0.0

        self.title("PythonDancer - Six-axis planner")
        self.geometry("1240x940")
        self.minsize(1040, 760)

        self.path_var = tk.StringVar(value=str(self.source_path or ""))
        self.preset_var = tk.StringVar(value=args.multiaxis_preset)
        self.strength_var = tk.DoubleVar(value=args.axis_strength)
        self.subdivision_var = tk.IntVar(value=args.subdivision)
        self.automap_var = tk.BooleanVar(value=args.automap)
        self.status_var = tk.StringVar(value="Select media and generate a six-axis plan.")
        self.port_var = tk.StringVar(value=args.serial_port or "")
        self.baud_var = tk.IntVar(value=args.baud)
        self.play_speed_var = tk.DoubleVar(value=args.play_speed)
        self.device_ranges_var = tk.BooleanVar(value=not args.no_device_ranges)
        self.timeline_var = tk.DoubleVar(value=max(0.0, float(args.start_at)))
        self.timeline_label_var = tk.StringVar(value="0.0 / 0.0 s")

        self._build_ui()
        self.refresh_ports(silent=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._tick_playback)
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
        ttk.Combobox(settings, textvariable=self.preset_var, values=("balanced", "rhythm", "expressive"), state="readonly", width=12).grid(row=0, column=1, padx=(6, 18))
        ttk.Label(settings, text="Axis strength").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(settings, textvariable=self.strength_var, from_=0.0, to=3.0, increment=0.05, width=7).grid(row=0, column=3, padx=(6, 18))
        ttk.Label(settings, text="Subdivision").grid(row=0, column=4, sticky="w")
        ttk.Combobox(settings, textvariable=self.subdivision_var, values=(0, 1, 2, 4), state="readonly", width=5).grid(row=0, column=5, padx=(6, 18))
        ttk.Checkbutton(settings, text="Automap L0", variable=self.automap_var).grid(row=0, column=6, padx=(0, 18))
        self.generate_button = ttk.Button(settings, text="Generate / Refresh", command=self.generate)
        self.generate_button.grid(row=0, column=7, padx=(0, 8))
        self.export_button = ttk.Button(settings, text="Export bundle", command=self.export, state="disabled")
        self.export_button.grid(row=0, column=8)

        device = ttk.LabelFrame(controls, text="TCode v0.3 device", padding=8)
        device.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        device.columnconfigure(1, weight=1)
        device.columnconfigure(7, weight=1)

        ttk.Label(device, text="Serial port").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(device, textvariable=self.port_var, width=24)
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        ttk.Button(device, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(device, text="Probe D2", command=self.probe_device).grid(row=0, column=3, padx=(0, 12))
        ttk.Label(device, text="Baud").grid(row=0, column=4, sticky="w")
        ttk.Combobox(device, textvariable=self.baud_var, values=(115200, 250000, 500000, 1000000), width=9).grid(row=0, column=5, padx=(6, 12))
        ttk.Label(device, text="Speed").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(device, textvariable=self.play_speed_var, from_=0.1, to=4.0, increment=0.1, width=6).grid(row=0, column=7, sticky="w", padx=(6, 12))
        ttk.Checkbutton(device, text="Use D2 ranges", variable=self.device_ranges_var).grid(row=0, column=8, padx=(0, 12))
        self.tcode_export_button = ttk.Button(device, text="Export .tcode", command=self.export_tcode, state="disabled")
        self.tcode_export_button.grid(row=0, column=9)

        ttk.Label(device, text="Timeline").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.timeline_scale = ttk.Scale(device, variable=self.timeline_var, from_=0.0, to=1.0)
        self.timeline_scale.grid(row=1, column=1, columnspan=6, sticky="ew", padx=(6, 8), pady=(10, 0))
        self.timeline_scale.bind("<ButtonPress-1>", self._timeline_press)
        self.timeline_scale.bind("<ButtonRelease-1>", self._timeline_release)
        ttk.Label(device, textvariable=self.timeline_label_var, width=18).grid(row=1, column=7, sticky="w", pady=(10, 0))
        self.play_button = ttk.Button(device, text="Play", command=self.play_device, state="disabled")
        self.play_button.grid(row=1, column=8, padx=(0, 6), pady=(10, 0))
        self.pause_button = ttk.Button(device, text="Pause", command=self.pause_device, state="disabled")
        self.pause_button.grid(row=1, column=9, padx=(0, 6), pady=(10, 0))
        self.resume_button = ttk.Button(device, text="Resume", command=self.resume_device, state="disabled")
        self.resume_button.grid(row=1, column=10, padx=(0, 6), pady=(10, 0))
        self.stop_button = ttk.Button(device, text="STOP", command=self.stop_device, state="disabled")
        self.stop_button.grid(row=1, column=11, pady=(10, 0))

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

    def refresh_ports(self, silent: bool = False):
        try:
            ports = list_serial_ports()
        except Exception as exc:
            if not silent:
                messagebox.showerror("PythonDancer", f"Unable to list serial ports:\n{exc}")
            return
        values = [device for device, _ in ports]
        self.port_combo.configure(values=values)
        if not self.port_var.get() and values:
            self.port_var.set(values[0])
        if not silent:
            descriptions = " | ".join(f"{device}: {description}" for device, description in ports) or "No serial ports found."
            self.status_var.set(descriptions)

    def _serial_settings(self):
        port = self.port_var.get().strip()
        if not port:
            raise ValueError("Select or enter a serial port first.")
        baud = int(self.baud_var.get())
        speed = float(self.play_speed_var.get())
        if baud <= 0 or speed <= 0:
            raise ValueError("Baud and playback speed must be positive numbers.")
        return port, baud, speed

    def _profile_summary(self, profile) -> str:
        version = " | ".join(profile.tcode) or "no D1 response"
        if not profile.axes:
            return f"{version}; no parseable D2 rows"
        axes = ", ".join(f"{axis} {item.minimum}-{item.maximum}" for axis, item in sorted(profile.axes.items()) if axis in AXIS_ORDER)
        return f"{version}; {axes or 'no motion axes'}"

    def probe_device(self):
        try:
            port, baud, _ = self._serial_settings()
        except (tk.TclError, ValueError) as exc:
            messagebox.showwarning("PythonDancer", str(exc))
            return
        timeout = float(self.args.serial_timeout)
        self.status_var.set(f"Querying D0/D1/D2 on {port}...")

        def work():
            try:
                with SerialTCodeDevice(port, baud=baud, timeout=timeout) as device:
                    profile = device.profile()
                self.after(0, lambda: self._probe_done(profile))
            except Exception as exc:
                self.after(0, lambda e=exc: messagebox.showerror("PythonDancer", f"Device probe failed:\n{e}"))

        Thread(target=work, daemon=True).start()

    def _probe_done(self, profile):
        self.device_profile = profile
        self.status_var.set("Device profile: " + self._profile_summary(profile))

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
        for button in (self.generate_button, self.export_button, self.tcode_export_button, self.play_button):
            button.configure(state="disabled")

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
                config = MultiAxisConfig(motion=self._motion_config(pitch, energy, subdivision), preset=preset, strength=strength)
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
        self.duration = plan_duration(plan)
        for button in (self.generate_button, self.export_button, self.tcode_export_button, self.play_button):
            button.configure(state="normal")
        self.timeline_scale.configure(to=max(0.001, self.duration))
        self.timeline_var.set(float(np.clip(self.timeline_var.get(), 0.0, self.duration)))
        self._update_timeline_label()

        self.axes.clear()
        for axis in AXIS_ORDER:
            actions = plan[axis]
            if actions:
                t = np.asarray([at for at, _ in actions], dtype=np.float64)
                p = np.asarray([pos for _, pos in actions], dtype=np.float64)
                self.axes.plot(t, p, linewidth=0.9, label=f"{axis} {AXIS_CHANNELS[axis]}")
        self.axes.set_ylim(0, 100)
        self.axes.set_xlabel("Time (s)")
        self.axes.set_ylabel("Normalized position")
        self.axes.legend(loc="upper right", ncol=3, fontsize=8)
        self.canvas.draw_idle()

        duration = float(data.get("at", 0.0) or self.duration)
        counts = "/".join(str(len(plan[axis])) for axis in AXIS_ORDER)
        self.status_var.set(f"Ready — {duration:.1f}s, preset={self.preset_var.get()}, L0 pitch={pitch:.1f}, energy={energy:.2f}")
        self.summary_label.configure(text=f"actions L0..R2: {counts}")

    def _generation_failed(self, exc: Exception):
        self.generate_button.configure(state="normal")
        for button in (self.export_button, self.tcode_export_button, self.play_button):
            button.configure(state="disabled")
        self.status_var.set(f"Generation failed: {exc}")
        messagebox.showerror("PythonDancer", f"Generation failed:\n{exc}")

    def export(self):
        if not self.plan or not self.source_path:
            return
        selected = filedialog.asksaveasfilename(
            title="Export six-axis funscript bundle",
            defaultextension=".funscript",
            initialfile=self.source_path.with_suffix(".funscript").name,
            filetypes=[("Funscript", "*.funscript"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            written = export_funscript_bundle(
                selected,
                self.plan,
                metadata={"notes": f"planner=multiaxis; preset={self.preset_var.get()}; axis_strength={float(self.strength_var.get())}"},
                manifest=not self.args.no_manifest,
            )
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"Export failed:\n{exc}")
            return
        self.status_var.set(f"Exported six-axis bundle to {written['L0'].parent}")
        messagebox.showinfo("PythonDancer", "Six-axis bundle exported.\n\n" + "\n".join(f"{axis}: {written[axis].name}" for axis in AXIS_ORDER))

    def export_tcode(self):
        if not self.plan or not self.source_path:
            return
        selected = filedialog.asksaveasfilename(
            title="Export scheduled TCode script",
            defaultextension=".tcode",
            initialfile=default_tcode_path(self.source_path).name,
            filetypes=[("TCode script", "*.tcode"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            profile = self.device_profile if self.device_ranges_var.get() else None
            events = build_tcode_events(self.plan, profile=profile)
            path = export_tcode_script(selected, events, source=str(self.source_path))
        except Exception as exc:
            messagebox.showerror("PythonDancer", f"TCode export failed:\n{exc}")
            return
        mapping = "D2 mapped" if profile and profile.axes else "full range"
        self.status_var.set(f"Exported {len(events)} scheduled TCode frames to {path.name} ({mapping})")

    def play_device(self):
        if not self.plan or (self.device_worker and self.device_worker.is_alive()):
            return
        try:
            port, baud, speed = self._serial_settings()
        except (tk.TclError, ValueError) as exc:
            messagebox.showwarning("PythonDancer", str(exc))
            return
        timeout = float(self.args.serial_timeout)
        start_at = float(np.clip(self.timeline_var.get(), 0.0, self.duration))
        use_ranges = bool(self.device_ranges_var.get())
        seek_ramp_ms = int(self.args.seek_ramp_ms)
        self.play_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Opening {port} @ {baud}...")

        def work():
            try:
                with SerialTCodeDevice(port, baud=baud, timeout=timeout) as device:
                    self.active_device = device
                    profile = device.profile()
                    self.device_profile = profile
                    controller = TCodePlaybackController(
                        self.plan,
                        device,
                        speed=speed,
                        profile=profile,
                        use_device_ranges=use_ranges,
                        seek_ramp_ms=seek_ramp_ms,
                    )
                    self.active_controller = controller
                    summary = self._profile_summary(profile)
                    self.after(0, lambda: self.status_var.set(f"Playing on {port} at {speed:g}x — {summary}"))
                    controller.play(start_at=start_at)
                self.after(0, self._device_done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._device_failed(e))
            finally:
                self.active_controller = None
                self.active_device = None

        self.device_worker = Thread(target=work, daemon=True)
        self.device_worker.start()

    def pause_device(self):
        controller = self.active_controller
        if controller is not None:
            controller.pause()
            self.status_var.set(f"Paused at {controller.position:.2f}s (DSTOP).")

    def resume_device(self):
        controller = self.active_controller
        if controller is not None:
            controller.resume()
            self.status_var.set(f"Resuming from {controller.position:.2f}s...")

    def stop_device(self):
        controller = self.active_controller
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                pass
        elif self.active_device is not None:
            try:
                self.active_device.stop()
            except Exception:
                pass
        self.status_var.set("Stopping device playback...")

    def _timeline_press(self, _event):
        self.timeline_dragging = True

    def _timeline_release(self, _event):
        self.timeline_dragging = False
        target = float(np.clip(self.timeline_var.get(), 0.0, self.duration))
        controller = self.active_controller
        if controller is not None:
            controller.seek(target)
            self.status_var.set(f"Seeking device to {target:.2f}s...")
        self._update_timeline_label()

    def _update_timeline_label(self):
        position = float(np.clip(self.timeline_var.get(), 0.0, self.duration)) if self.duration > 0 else 0.0
        state = self.active_controller.state if self.active_controller is not None else "ready"
        self.timeline_label_var.set(f"{position:.1f} / {self.duration:.1f}s · {state}")

    def _tick_playback(self):
        controller = self.active_controller
        if controller is not None and not self.timeline_dragging:
            self.timeline_var.set(controller.position)
        self._update_timeline_label()
        self.after(100, self._tick_playback)

    def _device_done(self):
        self.play_button.configure(state="normal" if self.plan else "disabled")
        self.pause_button.configure(state="disabled")
        self.resume_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Device playback complete or stopped.")

    def _device_failed(self, exc: Exception):
        self.play_button.configure(state="normal" if self.plan else "disabled")
        self.pause_button.configure(state="disabled")
        self.resume_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_var.set(f"Device playback failed: {exc}")
        messagebox.showerror("PythonDancer", f"Device playback failed:\n{exc}")

    def _on_close(self):
        try:
            self.stop_device()
        finally:
            self.destroy()


def ux(args):
    app = MultiAxisWindow(args)
    app.mainloop()


if __name__ == "__main__":
    from .util import cli_args

    ux(cli_args().parse_args())