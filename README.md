# PythonDancer 2.4

PythonDancer turns audio or video soundtracks into editable single- or six-axis `.funscript` choreography and can stream the final motion directly to TCode v0.3 devices.

This fork now combines a beat-aware motion engine, SR6/OSR6 six-axis choreography, learnable style profiles, optional separated stems, a non-destructive choreography workstation, and D2-aware seekable TCode playback.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## 2.4 — interactive choreography workstation

2.4 turns the automatic generator into a non-destructive editing workstation:

- waveform overview with beat grid;
- editable section lane with draggable boundaries and labels;
- Gesture Timeline Editor with movable/resizable `pulse / sway / rock / circle / spiral / wave / accent` blocks;
- per-axis **Solo / Mute / Lock** controls;
- local selection regeneration with boundary crossfades;
- live 3D six-axis pose preview;
- edited workspace state persisted into export metadata;
- every manual edit is re-run through per-axis speed/acceleration constraints before funscript export or TCode playback.

```text
Solo   preview only; never removes an axis from export/device output
Mute   removes that axis from export and live device playback
Lock   preserves that axis during local regeneration
```

If L0 is muted, the workstation removes the empty L0 channel from its device plan so TCode uses the remaining active axes as its timing source.

The 3D tab is a normalized 6DoF pose visualization, not an exact SR6 linkage/inverse-kinematics simulation.

## Previous engine layers

### 2.0 — beat-aware L0
- beat-aligned audio features and safe normalization;
- onset, bass/mid/high, pitch, harmonic and percussive features;
- adaptive `1x / 2x / 4x` subdivision;
- speed / acceleration / minimum-interval constraints.

### 2.1 — six-axis + TCode
- L0 stroke, L1 surge, L2 sway, R0 twist, R1 roll, R2 pitch;
- MultiFunPlayer-style six-file bundles;
- TCode v0.3 export and serial playback;
- D0/D1/D2 probing and saved-range mapping;
- Play / Pause / Resume / Seek / DSTOP.

### 2.2 — musical choreography
- continuous beat / bar / phrase phase;
- `intro / verse / build / chorus / drop / breakdown / outro` intent;
- reusable six-axis gesture primitives;
- explicit cross-axis coupling;
- `balanced / rhythm / expressive` presets and `reactive` A/B mode.

### 2.3 — style learning + stems
- editable `ChoreographyProfile` JSON;
- statistical style learning from existing six-axis bundles;
- learned axis travel, smoothness/activity and cross-axis relationships;
- optional `drums / bass / vocals / other` enrichment;
- optional Demucs or direct existing-stem directories.

## Install

Python 3.10+ is supported.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

Development/tests:

```bash
pip install -e '.[test]'
python -m pytest
```

FFmpeg is recommended for media containers. `pyserial` is included. Demucs remains optional/external.

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

## Workstation workflow

```text
Audio / video
     ↓
Beat-aligned analysis + optional stems
     ↓
Automatic six-axis choreography
     ↓
Base plan
     ↓
┌────────────────────────────────────┐
│ Non-destructive Workspace          │
│ Waveform + beat grid               │
│ Section boundary / label edits     │
│ Gesture blocks                     │
│ Axis Solo / Mute / Lock            │
│ Selection + local regeneration     │
└────────────────────────────────────┘
     ↓
Edited plan
     ↓
Per-axis physical constraint pass
     ↓
Funscript bundle / TCode playback
```

### Motion tab

Six independent plots:

```text
L0 stroke     R0 twist
L1 surge      R1 roll
L2 sway       R2 pitch
```

### Timeline editor

```text
Wave      waveform + beat grid
Section   intro / verse / build / chorus / drop / breakdown / outro
Gesture   pulse / sway / rock / circle / spiral / wave / accent
```

- Drag empty waveform space to select a range.
- Drag section dividers to correct boundaries.
- Click a section and change its label.
- Add a gesture to the selection.
- Drag gesture bodies to move them; drag edges to resize.
- Delete selected gestures.

Gesture blocks modify the real plan and therefore affect funscript and TCode output.

### Local regeneration

Select a range, set local preset/axis/gesture strength, then press **Regenerate selection**. The candidate motion replaces only that range; adjacent boundaries are crossfaded, and locked axes remain unchanged.

### 3D pose preview

The current playhead samples the exact edited/constrained plan:

```text
L0 -> vertical stroke
L1 -> forward/back surge
L2 -> left/right sway
R0 -> twist/yaw
R1 -> roll
R2 -> pitch
```

## Choreography profiles

See `examples/choreography-profile.json`.

```text
axis_scale      per-axis amplitude
gesture_gain    gesture weights
section_gain    section intensity
coupling_gain   cross-axis coupling
reactive_mix    reactive contribution
smoothing       temporal smoothing
stem_influence  separated-stem contribution
```

Use a profile:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --profile examples/choreography-profile.json
```

Learn style from a reference bundle:

```bash
python -m dancer new-song.mp3 --cli --yes --multiaxis --reference_bundle reference.funscript
```

## Optional stems

Existing directories may contain:

```text
drums.wav
bass.wav
vocals.wav
other.wav
```

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --stems auto --stem_dir ./stems/song
```

Or use optional Demucs when available:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --stems auto
```

## Six-axis output

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        choreography/workspace manifest
```

The manifest includes automatic analysis and the 2.4 workspace state: edited sections, gesture blocks, selection, Mute/Lock state, and Solo preview state.

## TCode v0.3

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
python -m dancer --cli --list_ports
python -m dancer --cli --serial_port COM4 --device_info
python -m dancer scene.mp4 --cli --yes --multiaxis --serial_port COM4
```

D2 saved ranges map normalized `0..100` motion into device preferences and unsupported axes are filtered.

## Physical limits

```text
L0     400 units/s, 2400 units/s²
L1/L2  180 units/s, 1000 units/s²
R0     300 units/s, 1800 units/s²
R1/R2  200 units/s, 1200 units/s²
```

The workstation reapplies these constraints after manual overlays and local regeneration before output reaches export or hardware.

## Validation

GitHub Actions is active. Regression coverage includes waveform envelopes, gesture overlays, Solo/Mute semantics, Lock behavior, range splice/crossfade, section edits, workspace serialization, non-L0 TCode timelines, post-edit physical constraints, plus the existing choreography/profile/stem/TCode/D2/playback tests.
