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

The multi-axis planner generates the standard SR6/OSR6 axis set:

| Axis | Channel | Motion |
| --- | --- | --- |
| `L0` | stroke | main up/down stroke |
| `L1` | surge | forward/backward |
| `L2` | sway | left/right |
| `R0` | twist | rotation around the main axis |
| `R1` | roll | side-to-side tilt |
| `R2` | pitch | forward/backward tilt |

L0 stays on the V2 adaptive planner. The secondary axes share its timing skeleton but use different rhythmic/spectral feature mixes, phase rates and physical limits instead of mirroring L0.

TCode v0.3 output maps normalized positions to `0000..9999`, combines all active axes in one newline-delimited command, and uses `I<milliseconds>` ramp intervals so targets are sent ahead of their arrival time instead of after the deadline.

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

FFmpeg is recommended and is required for media containers that the normal audio decoder cannot read directly. `pyserial` is installed with the package for TCode serial playback.

## Run

GUI:

```bash
python -m dancer
```

Single-axis CLI:

```bash
python -m dancer song.mp3 --cli --yes
```

Adaptive planner with a heatmap:

```bash
python -m dancer video.mp4 --cli --yes --heatmap \
  --planner adaptive \
  --subdivision 0 \
  --max_speed 400 \
  --max_acceleration 2400
```

Compare against the original mapping:

```bash
python -m dancer song.mp3 --cli --yes --planner legacy
```

## Six-axis GUI

Launch the dedicated six-axis GUI with a media file:

```bash
python -m dancer scene.mp4 --multiaxis
```

It provides a six-channel preview, `balanced/rhythm/expressive` preset selection, secondary-axis strength control, subdivision selection, optional L0 automap, refresh, one-click funscript bundle export, scheduled `.tcode` export, serial-port discovery, live TCode playback, and `DSTOP`.

The original GUI remains the default when `--multiaxis` is omitted.

## Six-axis / SR6 output

Generate a standard six-file funscript bundle:

```bash
python -m dancer scene.mp4 --cli --yes \
  --multiaxis \
  --multiaxis_preset balanced
```

The default output names follow the naming used by MultiFunPlayer and related TCode tooling:

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        bundle manifest
```

Use `--out_path custom-name.funscript` to set the bundle prefix.

### Multi-axis presets

```text
balanced    moderate, general-purpose six-axis motion
rhythm      stronger transient/percussive coupling
expressive  larger spectral/rotational movement
```

`--axis_strength` only scales the five secondary axes. L0 continues to use the normal motion settings. The multi-axis planner currently requires `--planner adaptive`; `--csv` remains a single-axis export.

## TCode v0.3 device layer

Export a scheduled TCode script:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
```

This writes `scene.tcode`. Each non-comment line uses:

```text
send_at_ms<TAB>TCode command
```

Example:

```text
0       L01234I250 L15000I250 L25000I250 R05000I250 R15000I250 R25000I250
250     L08765I250 L15200I250 L24800I250 R06000I250 R14500I250 R25500I250
```

Use `--tcode_out PATH` for a custom file. Preview commands without hardware with:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode_preview 5
```

List serial ports:

```bash
python -m dancer --cli --list_ports
```

Play directly to a serial device:

```bash
python -m dancer scene.mp4 --cli --yes \
  --multiaxis \
  --serial_port /dev/ttyUSB0 \
  --baud 115200
```

Windows example:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --serial_port COM4
```

Device flags:

```text
--serial_port PORT       serial device
--baud 115200            serial baud rate
--serial_timeout 0.25    D0/D1/D2 response timeout
--play_speed 1.0         real-time playback speed multiplier
--tcode_preview N        print first N scheduled commands
--tcode                  also save the generated .tcode schedule
--tcode_out PATH         save schedule to a custom path
```

Before playback PythonDancer sends `D0`, `D1`, and `D2` to identify the firmware/protocol/axes. `Ctrl+C` in CLI playback or the GUI **STOP** button sends `DSTOP`.

### Scheduling model

For a target at `t[n]`, PythonDancer sends the frame at `t[n-1]` with `I=(t[n]-t[n-1])` milliseconds. The controller therefore ramps toward the next target during the interval. All six axes are put on the same line and committed by one newline so they begin the next segment together.

## Motion architecture

```text
Audio
  ├─ beat / PLP
  ├─ onset strength
  ├─ RMS energy
  ├─ pitch
  ├─ bass / mid / high energy
  └─ harmonic / percussive energy
            │
            ▼
      Beat-aligned features
            │
            ▼
       L0 adaptive planner
            │
            ▼
      L0 action timeline
            │
            ├─ L1: bass + harmonic + slow phase
            ├─ L2: high/mid + percussive activity
            ├─ R0: pitch + high-frequency movement
            ├─ R1: percussive + stroke counter-motion
            └─ R2: harmonic + pitch trend + slow phase
            │
            ▼
      Per-axis constraint layer
            │
            ├─ six-file funscript bundle
            └─ TCode v0.3 scheduler
                       ├─ .tcode export
                       └─ serial playback
```

The secondary axes deliberately use different phase rates and feature mixtures. The goal is coordinated motion, not six synchronized copies of the stroke axis.

## Adaptive subdivision

`--subdivision 0` lets the L0 planner choose density from local rhythmic activity. You can force `1`, `2`, or `4` strokes per beat for predictable output. The six-axis planner inherits the resulting L0 action timeline.

## Physical limits

L0 defaults to max speed `400` normalized position units/s, max acceleration `2400` normalized position units/s², and minimum action interval `0.02s`.

Secondary axes use lower axis-specific defaults:

```text
L1/L2  180 units/s, 1000 units/s²
R0     300 units/s, 1800 units/s²
R1/R2  200 units/s, 1200 units/s²
```

All scripts remain normalized to `0..100`; TCode conversion maps normalized output to `0000..9999`.

## Automap

`--automap` searches for an L0 pitch range and energy multiplier. It can be combined with `--multiaxis`; L0 is calibrated first and the secondary planner derives the other axes from the same analyzed audio.

## Output compatibility

Single-axis `.funscript` output remains unchanged (`at` in milliseconds, `pos` in `0..100`). Six-axis output is emitted as separate standard funscript files, plus an optional `.motion.json` manifest.

TCode output is a host-scheduled text format consumed by PythonDancer's device layer; the command portion of every line is standard TCode v0.3 ASCII.

Six-axis generation and TCode playback are available through the dedicated Tk GUI, CLI, and Python API. The original single-axis GUI remains available unchanged.
