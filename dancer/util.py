from __future__ import annotations

import argparse
import subprocess


def ffmpeg_check():
    try:
        subprocess.check_call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("FFmpeg is missing or unavailable.")
        print("Install it from https://ffmpeg.org/download.html or your package manager.")
        return True
    return False


def ffmpeg_conv(in_file, out_file):
    subprocess.check_call(["ffmpeg", "-y", "-i", str(in_file), "-map", "0:a:0", "-ar", "48000", "-ac", "1", str(out_file)])


def cli_args():
    parser = argparse.ArgumentParser(
        prog="python-dancer",
        description="Create single- or six-axis funscripts from audio using beat-aligned motion planning",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("audio_path", nargs="?", default=None, help="Path to input media")
    parser.add_argument("--out_path", help="Path to export funscript or multi-axis bundle prefix")
    parser.add_argument("--csv", help="Export as CSV instead of funscript (single-axis only)", action="store_true")
    parser.add_argument("-m", "--heatmap", help="Export a speed heatmap", action="store_true")
    parser.add_argument("-c", "--convert", help="Convert input media to mono WAV with ffmpeg first", action="store_true")
    parser.add_argument("-a", "--automap", help="Automatically select pitch range and energy", action="store_true")
    parser.add_argument("-y", "--yes", help="Overwrite an existing output", action="store_true")
    parser.add_argument("--no_plp", help="Disable PLP beat estimation", action="store_true")
    parser.add_argument("--cli", help="Use command line mode instead of GUI", action="store_true")

    parser.add_argument("--planner", choices=("adaptive", "legacy"), default="adaptive", help="Primary L0 motion planner")
    parser.add_argument("--subdivision", type=int, choices=(0, 1, 2, 4), default=0, help="Strokes per beat; 0 selects automatically")
    parser.add_argument("--max_speed", type=float, default=400.0, help="Maximum L0 position units per second; <=0 disables")
    parser.add_argument("--max_acceleration", type=float, default=2400.0, help="Maximum L0 position units/s^2; <=0 disables")
    parser.add_argument("--min_interval", type=float, default=0.02, help="Minimum seconds between emitted actions")

    parser.add_argument("--multiaxis", action="store_true", help="Generate an SR6/OSR6-style L0/L1/L2/R0/R1/R2 funscript bundle")
    parser.add_argument("--multiaxis_preset", choices=("balanced", "rhythm", "expressive"), default="balanced", help="Secondary-axis motion character")
    parser.add_argument("--axis_strength", type=float, default=1.0, metavar="[0+]", help="Global amplitude multiplier for L1/L2/R0/R1/R2")
    parser.add_argument("--no_manifest", action="store_true", help="Do not write the .motion.json bundle manifest")

    tcode = parser.add_argument_group("TCode v0.3 device output")
    tcode.add_argument("--tcode", action="store_true", help="Export a scheduled .tcode script next to the normal output")
    tcode.add_argument("--tcode_out", help="Custom path for the scheduled .tcode script")
    tcode.add_argument("--tcode_preview", type=int, default=0, metavar="N", help="Print the first N scheduled TCode commands")
    tcode.add_argument("--serial_port", help="Stream generated TCode to a serial device, e.g. COM4 or /dev/ttyUSB0")
    tcode.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    tcode.add_argument("--serial_timeout", type=float, default=0.25, help="Serial read timeout in seconds")
    tcode.add_argument("--play_speed", type=float, default=1.0, metavar="[0+]", help="Real-time TCode playback speed multiplier")
    tcode.add_argument("--start_at", type=float, default=0.0, metavar="SECONDS", help="Start serial playback at this timeline position")
    tcode.add_argument("--seek_ramp_ms", type=int, default=120, metavar="MS", help="Ramp time used to synchronize the device after a seek")
    tcode.add_argument("--no_device_ranges", action="store_true", help="Ignore D2 min/max preferences and send the full 0000..9999 range")
    tcode.add_argument("--device_info", action="store_true", help="Query D0/D1/D2 from --serial_port and exit")
    tcode.add_argument("--list_ports", action="store_true", help="List serial ports and exit")

    parser.add_argument("--auto_pitch", type=float, default=50.0, metavar="[0-100]", help="Target average position")
    parser.add_argument("--auto_speed", type=float, default=250.0, metavar="[0+]", help="Target action speed in units/s")
    parser.add_argument("--auto_per", type=float, default=65.0, metavar="[0-100]", help="Target percent of actions above target speed")
    parser.add_argument("--auto_mod", type=int, default=2, choices=(1, 2, 3), help="Optimizer objective: mean speed, high-speed share, or travel length")

    parser.add_argument("--pitch", type=float, default=100.0, metavar="[-200-200]", help="Pitch-to-center range")
    parser.add_argument("--energy", type=float, default=1.0, metavar="[0+]", help="Energy-to-range multiplier")
    parser.add_argument("--amplitude_centering", type=float, default=0.0, metavar="[-200-200]", help="Energy-based center shift")
    parser.add_argument("--overflow", type=int, default=0, choices=(0, 1, 2), help="Overflow mode: crop, bounce, fold")
    parser.add_argument("--center_offset", type=float, default=0.0, metavar="[-300-300]", help="Center offset shift")
    return parser