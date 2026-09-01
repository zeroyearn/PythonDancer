# PythonDancer 2.6

PythonDancer turns audio/video soundtracks into editable six-axis choreography for `L0/L1/L2/R0/R1/R2`, exports MultiFunPlayer-compatible funscript bundles/TCode, and can stream live motion through serial TCode or Intiface Central / Buttplug.

2.6 is the **Generation Quality** release: the secondary axes no longer need to share L0's keyframe clock. Optional stems, continuous Motion Intent, learned reference style, advanced gesture blocks and a 6D optimizer work together before the existing editing/safety/device layers.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## 2.6 architecture

```text
Audio / video
    ↓
Mixed features + optional Demucs/provided stems
    ↓
Beat / bar / phrase / section analysis
    ↓
Continuous Motion Intent
 intensity · aggression · flow · complexity
 symmetry · rotation · translation · accents
    ↓
Reference Style / ChoreographyProfile
    ↓
Independent axis event planners
 L1 bass · L2 hi-hat · R0 vocal motion
 R1 snare · R2 vocal energy
    ↓
Gesture planner / editable Gesture Timeline
    ↓
6D pose planner
    ↓
Cross-axis optimizer
 pose load · simultaneous velocity
 speed · acceleration · jerk
    ↓
2.5 editing & safety workstation
    ↓
Device calibration + latency compensation
    ↓
Funscript / TCode / Intiface
```

The exported funscript/TCode timeline remains canonical. Device calibration, measured latency, Soft Start and Auto Home are live-output policies unless explicitly saved as project metadata.

## Main 2.6 capabilities

### Independent six-axis timing

L0 remains the primary adaptive stroke planner. In choreography mode, the five secondary axes now choose their own musically meaningful timestamps:

```text
L0 stroke   primary beat/subdivision planner
L1 surge    bass energy
L2 sway     hi-hat/high-frequency activity
R0 twist    vocal pitch motion
R1 roll     snare/drum accents
R2 pitch    vocal/harmonic energy
```

Each axis may insert extra subdivisions when its source feature crosses the configured accent threshold. Section boundaries are also eligible synchronization points.

Disable the layer for A/B testing:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --no-independent-axes
```

Control density:

```bash
--axis_density 1.4
--axis_accent_threshold 0.68
```

### Motion Intent

PythonDancer infers an inspectable 0..1 intent envelope instead of mapping audio directly to fixed formulas:

- `intensity`
- `aggression`
- `flow`
- `complexity`
- `symmetry`
- `rotation_bias`
- `translation_bias`
- `accent_density`

The workstation shows the global values. The planner samples the envelope at each axis's own timestamps.

CLI:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --show_intent
```

### Rich separated-stem features

Stem mode remains optional. PythonDancer can consume an existing directory containing:

```text
drums.wav
bass.wav
vocals.wav
other.wav
```

or use an externally installed Demucs backend in `auto` / `required` mode.

2.6 extracts additional source-aware features:

```text
drums  energy · onset · kick proxy · snare proxy · hi-hat proxy
bass   energy · onset · low-band energy
vocals energy · pitch · pitch motion
other  energy · spectral centroid
```

Example:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --stems auto --stem_dir ./stems/song
```

Demucs is deliberately not a mandatory package dependency. If it is unavailable, `auto` can fall back while `required` fails explicitly.

### Multi-reference style learning

A single reference bundle still works:

```bash
--reference_bundle favorite.funscript
```

2.6 also supports multiple bundles and weighted blending:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --reference_library ref-a.funscript ref-b.funscript ref-c.funscript \
  --reference_weights 2 1 1 \
  --save_learned_profile my-style.json
```

Optional deterministic style clustering:

```bash
--style_clusters 3
```

Cluster labels are derived from learned motion character, e.g. Smooth Flow, Rhythm Heavy, Rotation Heavy and Translation Heavy.

Reference learning is statistical style transfer. New motion still follows the new track's beats, structure, stems and Motion Intent; reference timestamps are not copied onto the new song.

### Advanced Gesture Timeline

Gesture blocks support:

```text
pulse / sway / rock / circle / spiral / wave / accent
strength
per-axis mix L0..R2
phase offset
cycle count
forward / reverse direction
blend-in / blend-out
```

This makes the timeline closer to a choreography/DAW automation lane instead of a fixed gesture label list.

`.pdance` schema 2 persists these fields. Schema 1 projects remain readable.

### 6D optimizer + jerk limits

After independent planning, PythonDancer projects the combined motion into a configurable safety/quality envelope:

- normalized simultaneous 6D pose budget;
- normalized simultaneous velocity budget;
- per-axis maximum speed;
- per-axis maximum acceleration;
- per-axis maximum jerk.

Defaults preserve the existing axis hierarchy:

```text
L0      speed 400   accel 2400   jerk 16000
L1/L2   speed 180   accel 1000   jerk  7000
R0      speed 300   accel 1800   jerk 12000
R1/R2   speed 200   accel 1200   jerk  8000
```

CLI controls:

```bash
--pose_budget 1.85
--velocity_budget 2.25
--optimizer_iterations 3
```

Disable for A/B testing:

```bash
--no-motion-optimizer
```

## Device calibration and timing

### DeviceCalibrationProfile

A calibration JSON can define each axis's:

```text
minimum / maximum
neutral
inverted
max_speed
max_acceleration
max_jerk
```

Normalized choreography is mapped piecewise around the configured neutral:

```text
0   → minimum
50  → neutral
100 → maximum
```

The workstation can run a conservative one-axis-at-a-time ±5% verification sequence. Keep access to device STOP/emergency power during any hardware test.

CLI:

```bash
--calibration_profile my-sr6.json
```

### Latency compensation

Live playback can schedule commands earlier by a configured transport/device latency:

```bash
--latency_ms 45
--manual_offset_ms -8
```

For serial devices, PythonDancer can estimate request/response timing using harmless `D1` queries and use half the median RTT as a one-way scheduling estimate:

```bash
--measure_latency
```

The timing profile records latency and jitter. Mechanical latency may differ from protocol RTT, so manual offset remains available.

## 2.5 editing & safety layer retained

2.6 keeps the full 2.5 workstation:

- direct keyframe add/drag/delete;
- Beat Snap / nearest / floor / ceil quantization;
- Linear / Smoothstep / PCHIP / Makima interpolation;
- Motion Heatmap and combined Risk Heatmap;
- Smart Limit `safe / balanced / open` profiles;
- music-aware ambient/beat/repeat gap filling;
- Axis Link gain/delay/smoothing/position-or-velocity/only-if-empty;
- Soft Start and optional Auto Home;
- `.pdance` projects, autosave, recent projects and full Undo/Redo;
- Intiface Central / Buttplug v4;
- exception-safe serial DSTOP behavior;
- speed-aware TCode `I<ms>` scaling while safety ramps stay real-time.

## Workstation layout

Run:

```bash
python -m dancer scene.mp4 --multiaxis
```

The GUI keeps the 2.4/2.5 workflow and adds:

```text
Left
  Motion setup
  Musical intelligence
  Axis controls
  Safety & shaping
  Generation Quality

Center
  Motion plots
  Wave/Section/Gesture timeline
  3D pose
  Curve editor
  Diagnostics
  Intent / Gesture

Right
  Local regenerate
  TCode device
  Export
  Project
  Intiface
  Playback safety
  Timing & calibration
```

Generation Quality exposes independent-axis density/threshold, optimizer budgets/passes and the current Motion Intent. The Intent/Gesture tab exposes advanced gesture block settings.

## Install

Python 3.10+ is supported.

Minimal source install:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

Intiface support for source installs:

```bash
pip install -e '.[intiface]'
```

Development/tests:

```bash
pip install -e '.[test,intiface]'
python -m pytest
```

Desktop release builds install Intiface support automatically. macOS release apps bundle FFmpeg. Demucs remains optional/external.

## CLI examples

Default 2.6 six-axis generation:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis
```

Stem-aware expressive choreography:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --multiaxis_preset expressive \
  --stems auto \
  --gesture_strength 1.25 \
  --axis_density 1.2
```

Inspect sections and Motion Intent:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --show_sections --show_intent
```

TCode live playback with calibration/latency:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --serial_port /dev/ttyUSB0 \
  --calibration_profile my-sr6.json \
  --latency_ms 30 \
  --measure_latency
```

Intiface:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --intiface --intiface_address ws://127.0.0.1:12345
```

## Output bundle

```text
scene.funscript        L0 stroke
scene.surge.funscript  L1 surge
scene.sway.funscript   L2 sway
scene.twist.funscript  R0 twist
scene.roll.funscript   R1 roll
scene.pitch.funscript  R2 pitch
scene.motion.json      manifest / generation metadata
```

The 2.6 manifest is version `1.4` and may include section analysis, Motion Intent, independent-axis settings, optimizer settings, learned profile and stem-analysis metadata.

## TCode and live safety

TCode v0.3 support includes:

- D0/D1/D2 discovery;
- D2 saved-range mapping;
- multi-axis ramp commands;
- scheduled `.tcode` export;
- Play / Pause / Resume / Seek;
- `DSTOP` on stop/interruption and best-effort `DSTOP` on exceptional serial-context exit;
- live playback-speed-aware `I<ms>` intervals;
- Soft Start synchronization;
- optional Auto Home.

When L0 is muted, remaining axes can provide the TCode event timeline.

## Intiface / Buttplug

Default server:

```text
ws://127.0.0.1:12345
```

Generic mapping currently uses:

```text
L0 position               → POSITION_WITH_DURATION
six-axis motion intensity → VIBRATE
absolute R0 excursion     → ROTATE
```

Unsupported outputs are skipped.

## macOS packaging

Release builds target native:

```text
macOS arm64
macOS Intel x86_64
```

FFmpeg is bundled. Builds are ad-hoc signed but not Apple-notarized; first launch may require Control-click/right-click → **Open**.

## Development status

2.6 is developed on top of the fully validated 2.5 branch. Before merge/release, the final 2.6 head must pass:

```text
Python 3.10 tests
Python 3.12 tests
Python 3.13 tests
Windows PyInstaller build
macOS arm64 app/ZIP/DMG build
macOS Intel x86_64 app/ZIP/DMG build
```

Do not treat an intermediate feature-branch artifact as a published release until the tagged GitHub Release exists.
