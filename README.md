# PythonDancer 2

PythonDancer turns audio or video soundtracks into `.funscript` motion. This fork keeps the original GUI/CLI workflow, replaces the core mapping with a beat-aware motion engine, and adds an SR6/OSR6-style six-axis planner.

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

### 2.1: six-axis motion

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

FFmpeg is recommended and is required for media containers that the normal audio decoder cannot read directly.

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

Example:

```bash
python -m dancer scene.mp4 --cli --yes \
  --multiaxis \
  --multiaxis_preset expressive \
  --axis_strength 1.2 \
  --heatmap
```

`--axis_strength` only scales the five secondary axes. L0 continues to use `--energy`, `--pitch`, `--max_speed`, `--max_acceleration` and the other normal motion settings.

The multi-axis planner currently requires `--planner adaptive`. `--csv` remains a single-axis export.

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
            ▼
   6-file funscript bundle
```

The secondary axes deliberately use different phase rates and feature mixtures. The goal is coordinated motion, not six synchronized copies of the stroke axis.

## Adaptive subdivision

`--subdivision 0` lets the L0 planner choose density from local rhythmic activity. You can force `1`, `2`, or `4` strokes per beat for predictable output. The six-axis planner inherits the resulting L0 action timeline.

## Physical limits

L0 defaults to:

- max speed: `400` normalized position units/s;
- max acceleration: `2400` normalized position units/s²;
- minimum action interval: `0.02s`.

Secondary axes use lower axis-specific defaults before export:

```text
L1/L2  180 units/s, 1000 units/s²
R0     300 units/s, 1800 units/s²
R1/R2  200 units/s, 1200 units/s²
```

All scripts remain normalized to `0..100`. Device-side range preferences and servo geometry should be handled by the playback/device layer.

## Automap

`--automap` searches for an L0 pitch range and energy multiplier. The objectives remain compatible with the original three modes:

```text
--auto_mod 1  mean action speed
--auto_mod 2  percentage above target speed
--auto_mod 3  average travel length
```

Automap can be combined with `--multiaxis`; it calibrates L0 first, then the secondary planner derives the other five axes from the same analyzed audio.

## Output compatibility

Single-axis `.funscript` output remains unchanged (`at` in milliseconds, `pos` in `0..100`).

Six-axis output is emitted as separate standard funscript files so existing multi-axis players can load each channel independently. A `.motion.json` manifest is written for inspection and tooling; disable it with `--no_manifest`.

The current Tk GUI still previews/exports the single-axis path. Six-axis generation is available through the CLI and Python API.
