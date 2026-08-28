# PythonDancer 2

PythonDancer turns audio or video soundtracks into `.funscript` motion. This fork keeps the original GUI/CLI workflow but replaces the core mapping with a beat-aware motion engine.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## What changed in 2.0

The original engine primarily mapped beat timing + RMS energy + pitch directly to a single up/down stroke per beat. V2 adds:

- beat-aligned feature extraction with the original segmentation off-by-one fixed;
- safe normalization for silent/constant/invalid feature windows;
- onset, bass/mid/high spectral energy, harmonic and percussive features;
- an adaptive motion planner that combines rhythmic and spectral cues;
- automatic `1x / 2x / 4x` beat subdivision;
- velocity, acceleration and minimum-action-interval constraints;
- `adaptive` and `legacy` planners for A/B comparison;
- a corrected automapper that optimizes the pitch range it actually returns;
- robust empty/audio-less input handling;
- fixed CLI heatmap argument wiring;
- a real `python -m dancer` entry point;
- modern Python packaging and regression tests.

## Install

Python 3.10+ is supported.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
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

CLI:

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

## Motion model

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
       Motion planner
      ├─ intensity / range
      ├─ center movement
      ├─ transient accents
      └─ auto subdivision
            │
            ▼
      Constraint layer
      ├─ range / overflow
      ├─ max velocity
      ├─ max acceleration
      └─ minimum interval
            │
            ▼
        .funscript / CSV
```

### Adaptive subdivision

`--subdivision 0` lets the planner choose density from local rhythmic activity. You can force `1`, `2`, or `4` strokes per beat for predictable output.

### Safety/physical limits

The adaptive planner defaults to:

- max speed: `400` position units/s;
- max acceleration: `2400` position units/s²;
- minimum action interval: `0.02s`.

Set a speed or acceleration value to `0` or below to disable that limit.

## Automap

`--automap` searches for a pitch range and energy multiplier. The objectives remain compatible with the original three modes:

```text
--auto_mod 1  mean action speed
--auto_mod 2  percentage above target speed
--auto_mod 3  average travel length
```

Example:

```bash
python -m dancer song.wav --cli --yes --automap \
  --auto_pitch 50 \
  --auto_speed 250 \
  --auto_per 65
```

## Output compatibility

`.funscript` output remains the standard single-axis action format (`at` in milliseconds, `pos` in `0..100`). Existing consumers should continue to work.

V2 is structured so additional device/axis planners can be layered above the shared feature engine later without coupling audio analysis to a particular actuator layout.
