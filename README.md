# PythonDancer 2.4

PythonDancer turns audio or video soundtracks into editable single- or six-axis `.funscript` choreography and can stream the final motion directly to TCode v0.3 devices.

This fork now combines a beat-aware motion engine, SR6/OSR6 six-axis choreography, learnable style profiles, optional separated stems, a non-destructive choreography workstation, and D2-aware seekable TCode playback.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## Releases

### 2.0 — beat-aware L0
- beat-aligned audio features and safe normalization;
- onset, bass/mid/high, pitch, harmonic and percussive features;
- adaptive `1x / 2x / 4x` subdivision;
- speed / acceleration / minimum-interval constraints;
- corrected automap, heatmap and module entry point.

### 2.1 — six-axis + TCode
- L0 stroke, L1 surge, L2 sway, R0 twist, R1 roll, R2 pitch;
- MultiFunPlayer-style six-file bundles;
- TCode v0.3 export and serial playback;
- D0/D1/D2 probing and saved-range mapping;
- Play / Pause / Resume / Seek / DSTOP.

### 2.2 — musical choreography
- continuous beat / bar / phrase phase;
- `intro / verse / build / chorus / drop / breakdown / outro` intent;
- `pulse / sway / rock / circle / spiral / wave / accent` gestures;
- explicit cross-axis coupling;
- `balanced / rhythm / expressive` presets and `reactive` A/B mode.

### 2.3 — style learning + stems
- editable `ChoreographyProfile` JSON;
- statistical style learning from an existing six-axis bundle;
- learned axis travel, smoothness/activity and cross-axis relationships;
- optional `drums / bass / vocals / other` stem enrichment;
- optional Demucs or direct use of an existing stem directory.

### 2.4 — interactive choreography workstation

2.4 turns the automatic generator into a non-destructive editing workstation:

- waveform overview with beat grid;
- editable section lane with draggable boundaries and labels;
- Gesture Timeline Editor with movable/resizable gesture blocks;
- per-axis **Solo / Mute / Lock** controls;
- local selection regeneration with boundary crossfades;
- live 3D six-axis pose preview;
- edited workspace state persisted into export metadata;
- every manual edit is re-run through per-axis speed/acceleration constraints before funscript export or TCode playback.

Semantics are deliberate:

```text
Solo   preview only; never removes an axis from export/device output
Mute   removes that axis from export and live device playback
Lock   preserves that axis during local regeneration
```

The 3D tab is a normalized 6DoF pose visualization. It is not yet an exact SR6 linkage/inverse-kinematics simulation.

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

FFmpeg is recommended for media containers. `pyserial` is included for serial TCode playback.

Demucs is intentionally optional. A normal Python installation can use an importable `demucs` module or a `demucs` executable on `PATH`; frozen builds can use an external `demucs` executable or an existing stem directory. `--stems auto` falls back cleanly when unavailable, while `--stems required` reports an error.

## Run

Single-axis GUI:

```bash
python -m dancer
```

Six-axis 2.4 workstation:

```bash
python -m dancer scene.mp4 --multiaxis
```

Six-axis CLI:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis
```

## 2.4 workstation workflow

```text
Audio / video
     ↓
Beat-aligned analysis + optional stems
     ↓
Automatic L0 + six-axis choreography
     ↓
Base plan
     ↓
┌────────────────────────────────────┐
│ Non-destructive Workspace          │
│                                    │
│ Waveform + Beat grid               │
│ Section boundary / label edits     │
│ Gesture blocks                     │
│ Axis Solo / Mute / Lock            │
│ Selection + local regeneration     │
└────────────────────────────────────┘
     ↓
Edited effective plan
     ↓
Physical constraint pass
     ↓
┌────────────────┬───────────────────┐
│ six-axis files │ TCode controller  │
└────────────────┴───────────────────┘
```

### Motion tab

Six independent plots avoid hiding one axis behind another:

```text
L0 stroke     R0 twist
L1 surge      R1 roll
L2 sway       R2 pitch
```

The playback timeline remains synchronized with device seek/playback.

### Timeline editor

The editor has three lanes:

```text
Wave      waveform + beat grid
Section   intro / verse / build / chorus / drop / breakdown / outro
Gesture   pulse / sway / rock / circle / spiral / wave / accent
```

Controls:
- drag empty waveform space to make a selection;
- drag a section divider to correct its boundary;
- click a section and apply a different label;
- add a gesture to the selected range;
- drag the gesture body to move it;
- drag either gesture edge to resize it;
- delete the selected gesture.

Gesture blocks are real motion overlays, not display-only labels. Their edited positions are used by funscript export and TCode playback.

### Local regeneration

Select a range, choose a local preset/strength and press **Regenerate selection**. PythonDancer generates a candidate plan, applies the edited section intent, replaces only the selected interval, and crossfades both boundaries.

Locked axes are copied through unchanged.

### 3D pose preview

The pose tab samples the exact edited/constrained output at the current playhead:

```text
L0 -> vertical stroke
L1 -> forward/back surge
L2 -> left/right sway
R0 -> twist/yaw
R1 -> roll
R2 -> pitch
```

It updates during timeline seek and live playback.

## 2.4 architecture

```text
Audio / video
      │
      ├─ beat / tempo / PLP
      ├─ RMS / onset
      ├─ bass / mid / high
      ├─ pitch / harmonic / percussive
      └─ optional drums / bass / vocals / other stems
      │
      ▼
Beat / bar / phrase phase
      │
      ▼
Section analyzer
      │
      ▼
Gesture + profile choreography
      │
      ▼
Automatic 6D base plan
      │
      ▼
2.4 Workspace
      ├─ section edits
      ├─ gesture overlays
      ├─ Solo / Mute / Lock
      └─ local regenerate + crossfade
      │
      ▼
Per-axis physical constraint pass
      │
      ├─ six-axis funscript bundle
      └─ TCode v0.3 / D2 mapping / seekable playback
```

## Musical choreography

The default secondary-axis planner uses the actual musical timeline rather than an action-index-only phase.

Default grid:

```text
beats_per_bar   = 4
bars_per_phrase = 4
section_bars    = 4
```

Override it:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --beats_per_bar 4 \
  --bars_per_phrase 4 \
  --section_bars 4
```

Show detected sections:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --show_sections
```

The automatic section analyzer is a deterministic musical-intent heuristic based on energy, rhythmic activity, novelty and local dynamic slope. 2.4 lets the user correct that heuristic manually in the timeline.

## Choreography profiles

See `examples/choreography-profile.json`.

Main fields:

```text
axis_scale      L1 L2 R0 R1 R2 amplitude multipliers
gesture_gain    pulse sway rock circle spiral wave accent
section_gain    intro verse build chorus drop breakdown outro
coupling_gain   sway_roll surge_pitch stroke_twist stroke_bass_l1
reactive_mix    local reactive contribution
smoothing       temporal smoothing
stem_influence  separated-stem contribution
```

Use a profile:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --profile examples/choreography-profile.json
```

## Learn style from a reference bundle

Given:

```text
reference.funscript
reference.surge.funscript
reference.sway.funscript
reference.twist.funscript
reference.roll.funscript
reference.pitch.funscript
```

learn and apply its statistical movement character:

```bash
python -m dancer new-song.mp3 --cli --yes --multiaxis \
  --reference_bundle reference.funscript
```

Save the learned style:

```bash
python -m dancer new-song.mp3 --cli --yes --multiaxis \
  --reference_bundle reference.funscript \
  --profile_name my-style \
  --save_learned_profile my-style.json
```

The learner estimates robust axis travel/activity and cross-axis relationships. It does not copy timestamps or positions from the reference.

## Optional separated stems

Existing stems:

```text
drums.wav
bass.wav
vocals.wav
other.wav
```

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --stems auto \
  --stem_dir ./stems/song
```

Or let PythonDancer use optional Demucs when available:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --stems auto
```

```text
--stems required     fail if stems cannot be provided
--stems off          disable stem enrichment
--stem_cache PATH
--demucs_model htdemucs
```

## Six-axis output

PythonDancer follows the MultiFunPlayer-style naming convention:

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        bundle/choreography/workspace manifest
```

The manifest records automatic analysis plus the 2.4 workspace selection, edited sections, gesture blocks, Mute/Lock state and Solo preview state.

## TCode v0.3 device layer

Export TCode:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
```

Preview without hardware:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode_preview 5
```

List ports / probe / live playback:

```bash
python -m dancer --cli --list_ports
python -m dancer --cli --serial_port COM4 --device_info
python -m dancer scene.mp4 --cli --yes --multiaxis --serial_port COM4
```

Start at a timeline point:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --serial_port COM4 \
  --start_at 42.5
```

## D2 range mapping

If a device reports:

```text
L0 1000 9000 Up
R0 2000 8000 Twist
```

PythonDancer maps normalized `0..100` motion into each saved range and only emits supported axes. This is saved-range mapping, not physical end-stop calibration.

Disable it with `--no_device_ranges`.

## Pause / Resume / Seek

- **Pause** captures timeline time and sends `DSTOP`; no hidden position frame is emitted while paused.
- **Resume** synchronizes to the frozen pose and rebuilds future ramp-ahead events.
- **Seek** sends `DSTOP`, moves to the selected pose with a configurable seek ramp, then resumes scheduling.
- **STOP** terminates playback and sends `DSTOP`.

## Physical limits

Default L0:

```text
max speed         400 normalized units/s
max acceleration  2400 units/s²
minimum interval  0.02 s
```

Secondary defaults:

```text
L1/L2  180 units/s, 1000 units/s²
R0     300 units/s, 1800 units/s²
R1/R2  200 units/s, 1200 units/s²
```

2.4 explicitly reapplies these constraints after manual gesture overlays and local regeneration before output reaches export or hardware.

## Validation

GitHub Actions is active on this fork. The test matrix runs supported Python versions and Windows packaging. Workstation regression coverage includes waveform envelopes, gesture overlays, Solo/Mute semantics, axis Lock behavior, range splicing/crossfades, section edits, workspace serialization, and the post-edit physical constraint pass, in addition to the existing choreography/profile/stem/TCode/D2/playback tests.
