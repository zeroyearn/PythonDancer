# PythonDancer 2

PythonDancer turns audio or video soundtracks into `.funscript` motion. This fork keeps the original GUI/CLI workflow, replaces the core mapping with a beat-aware motion engine, and adds an SR6/OSR6-style six-axis planner plus TCode v0.3 device playback.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## What changed

### 2.0: beat-aware single-axis engine

- beat-aligned feature extraction with the original segmentation off-by-one fixed;
- safe normalization for silent/constant/invalid feature windows;
- onset, bass/mid/high spectral energy, harmonic and percussive features;
- an adaptive L0 motion planner;
- automatic `1x / 2x / 4x` beat subdivision;
- velocity, acceleration and minimum-action-interval constraints;
- `adaptive` and `legacy` planners for A/B comparison;
- corrected automap, heatmap wiring and module entry point;
- modern Python packaging and regression tests.

### 2.1: six-axis motion + TCode

The multi-axis planner generates the standard SR6/OSR6 axis set: `L0` stroke, `L1` surge, `L2` sway, `R0` twist, `R1` roll and `R2` pitch. L0 stays on the V2 adaptive planner; secondary axes share its timing skeleton but use different rhythmic/spectral feature mixes and physical limits instead of mirroring L0.

TCode v0.3 output maps normalized positions to device ranges, combines active axes in one newline-delimited command, and uses `I<milliseconds>` ramp intervals so targets are sent ahead of arrival time.

## Install

Python 3.10+ is supported.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

For development/tests:

```bash
pip install -e '.[test]'
python -m pytest
```

FFmpeg is recommended for media containers. `pyserial` is included for TCode serial playback.

## Run

Single-axis GUI:

```bash
python -m dancer
```

Single-axis CLI:

```bash
python -m dancer song.mp3 --cli --yes
```

Six-axis GUI:

```bash
python -m dancer scene.mp4 --multiaxis
```

The six-axis GUI previews all channels and includes preset/strength controls, TCode export, serial-port discovery, D2 device probing, live playback, a seekable timeline, Pause/Resume, and `DSTOP`.

## Six-axis / SR6 output

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --multiaxis_preset balanced
```

Default bundle names:

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        bundle manifest
```

Presets: `balanced`, `rhythm`, `expressive`. `--axis_strength` scales L1/L2/R0/R1/R2 only.

## TCode v0.3 device layer

Export a scheduled TCode script:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
```

Each non-comment `.tcode` line uses:

```text
send_at_ms<TAB>TCode command
```

Example:

```text
0       L01234I250 L15000I250 L25000I250 R05000I250 R15000I250 R25000I250
250     L08765I250 L15200I250 L24800I250 R06000I250 R14500I250 R25500I250
```

Preview without hardware:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode_preview 5
```

List ports:

```bash
python -m dancer --cli --list_ports
```

Probe one device without generating motion:

```bash
python -m dancer --cli --serial_port COM4 --device_info
```

Live serial playback:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --serial_port /dev/ttyUSB0 --baud 115200
```

Start at a specific timeline position:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --serial_port COM4 \
  --start_at 42.5
```

Key flags:

```text
--serial_port PORT
--baud 115200
--serial_timeout 0.25
--play_speed 1.0
--start_at SECONDS
--seek_ramp_ms 120
--no_device_ranges
--device_info
--tcode_preview N
--tcode
--tcode_out PATH
```

Before playback PythonDancer sends `D0`, `D1` and `D2`. `Ctrl+C` in CLI playback or the GUI **STOP** button sends `DSTOP`.

### D2 axis range auto-mapping

TCode devices commonly report D2 rows in this form:

```text
L0 1000 9000 Up
R0 2000 8000 Twist
```

PythonDancer parses these saved device preferences and, by default, maps its normalized `0..100` motion into each reported range. It also sends only generated axes that the device actually reports. For the example above:

```text
L0 0%   -> 1000
L0 50%  -> 5000
L0 100% -> 9000
```

This is a profile/range mapping step; it does **not** physically drive the mechanism into end stops. Use `--no_device_ranges` or uncheck **Use D2 ranges** in the GUI to force the full `0000..9999` command range.

### Scheduling model

For target `t[n]`, PythonDancer sends the frame at `t[n-1]` with `I=(t[n]-t[n-1])` milliseconds. All active axes are placed on one line and committed by one newline, so the device ramps toward the next synchronized target during the interval.

### Pause / Resume / Seek

The six-axis GUI contains a live timeline slider:

- **Pause** records the current timeline point and sends `DSTOP`. No additional position command is sent while paused.
- **Resume** synchronizes the device to the frozen timeline position using `--seek_ramp_ms`, then rebuilds future ramp-ahead events from that point.
- **Seek** can be used during playback or while paused. Releasing the timeline slider sends `DSTOP`, maps all active axes to the selected timestamp, ramps to that pose, and rebuilds the remaining schedule.
- **STOP** terminates playback and sends `DSTOP`.

The playback controller is also exposed through Python as `TCodePlaybackController` for external player integrations.

## Physical limits

L0 defaults to `400` normalized units/s, `2400` units/s² and minimum interval `0.02s`. Secondary axes use lower axis-specific limits before export. All generated scripts remain normalized to `0..100`; the device layer performs the final TCode range mapping.

## Output compatibility

Single-axis `.funscript` stays standard. Six-axis output is separate MultiFunPlayer-style files plus optional `.motion.json`. The `.tcode` file is PythonDancer's host schedule; the command portion of each line is standard TCode v0.3 ASCII.