# PythonDancer 2.2

PythonDancer turns audio or video soundtracks into single- or six-axis `.funscript` motion and can stream the generated six-axis motion directly to TCode v0.3 devices.

This fork keeps the original workflow but replaces the old amplitude mapping with a beat-aware planner, adds SR6/OSR6 six-axis motion, a musical choreography engine, D2-aware TCode playback, and a seekable device timeline.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## Releases

### 2.0 — beat-aware L0

- beat-aligned audio features;
- safe normalization;
- onset, bass/mid/high, pitch, harmonic and percussive features;
- adaptive `1x / 2x / 4x` subdivision;
- speed / acceleration / minimum-interval constraints;
- corrected automap, heatmap and module entry point;
- `adaptive` and `legacy` planners for A/B testing.

### 2.1 — six-axis + TCode

- L0 stroke, L1 surge, L2 sway, R0 twist, R1 roll, R2 pitch;
- MultiFunPlayer-style six-file funscript bundles;
- TCode v0.3 export and serial playback;
- D0/D1/D2 device probing;
- D2 min/max range mapping and unsupported-axis filtering;
- Play / Pause / Resume / Seek / DSTOP;
- dedicated six-axis GUI.

### 2.2 — musical choreography

The default secondary-axis planner is now a choreography engine instead of a fixed reactive formula set.

It adds:

- continuous beat / bar / phrase phase;
- phrase-aligned section detection: `intro`, `verse`, `build`, `chorus`, `drop`, `breakdown`, `outro`;
- reusable multi-axis gestures: `pulse`, `sway`, `rock`, `circle`, `spiral`, `wave`, `accent`;
- section-dependent gesture selection and gain;
- explicit cross-axis coupling for coherent 6D poses;
- `balanced`, `rhythm`, and `expressive` gesture styles;
- `reactive` compatibility mode for A/B comparison;
- choreography structure stored in funscript metadata and `.motion.json`.

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

## Run

Single-axis GUI:

```bash
python -m dancer
```

Six-axis choreography GUI:

```bash
python -m dancer scene.mp4 --multiaxis
```

Six-axis CLI:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis
```

## Choreography architecture

```text
Audio / video soundtrack
        │
        ├─ beat / tempo / PLP
        ├─ RMS energy
        ├─ onset
        ├─ bass / mid / high
        ├─ pitch
        ├─ harmonic
        └─ percussive
        │
        ▼
Beat-aligned feature stream
        │
        ├──────────────► L0 adaptive planner
        │                    │
        │                    ▼
        │              L0 action timeline
        │
        ▼
Musical Grid
  beat phase
  bar phase
  phrase phase
        │
        ▼
Section Analyzer
  intro / verse / build / chorus
  drop / breakdown / outro
        │
        ▼
Gesture Planner
  pulse / sway / rock / circle
  spiral / wave / accent
        │
        ▼
6D Pose Synthesis
  L1 / L2 / R0 / R1 / R2
        │
        ▼
Cross-axis coupling
        │
        ▼
Per-axis physical constraints
        │
        ▼
Funscript bundle / TCode
```

L0 still owns the action timestamps. The choreography engine evaluates beat/bar/phrase phase and musical sections on that timeline, then creates coordinated secondary-axis poses.

## Musical phase

The old 2.1 secondary planner used an action-index phase such as `action_index × π`. 2.2 uses the actual beat timestamps instead.

The engine maintains three continuous coordinates:

```text
beat_phase    position inside one beat
bar_phase     position inside one bar
phrase_phase  position inside a multi-bar phrase
```

Default grid:

```text
beats_per_bar   = 4
bars_per_phrase = 4
section_bars    = 4
```

Override from CLI:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --beats_per_bar 4 \
  --bars_per_phrase 4 \
  --section_bars 4
```

## Section detection

Section detection is a deterministic musical-intent heuristic, not a semantic ML classifier. It compares phrase-window energy, rhythmic activity, novelty, and within-window dynamics.

Typical output:

```text
intro → verse → build → drop → verse → chorus → breakdown → chorus → outro
```

Show the detected structure:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --show_sections
```

The GUI shows the same structure after generation.

## Gesture primitives

The choreography engine blends reusable multi-axis gestures instead of calculating every axis independently.

### `pulse`

Beat-driven rotational/accent motion. Strongest contribution is usually R0 with smaller L1/L2/R1/R2 support.

### `sway`

Bar-scale left/right movement. L2 and R1 are deliberately counter-coupled.

### `rock`

Forward/back movement: L1 and R2 move as a coupled pair.

### `circle`

L1/L2 use quadrature phase to create a circular translation pattern while R1/R2 follow the pose.

### `spiral`

Phrase-scale twist with slower L2/R2 support. Used more heavily in chorus/drop and expressive mode.

### `wave`

Slow phrase motion dominated by R1/R2. Favored in intro/breakdown/outro.

### `accent`

Transient, alternating-direction motion driven by onset/percussive energy. Favored in rhythm and drop sections.

## Section choreography

Different sections choose different gesture mixtures and amplitude gains.

Examples:

```text
intro       wave + rock, reduced gain
verse       sway + rock + light pulse
build       circle + pulse + spiral, rising activity
chorus      circle + spiral + sway
DROP        pulse + spiral + accent, highest gain
breakdown   wave + rock, reduced gain
outro       slow wave / sway, reduced gain
```

This is why 2.2 no longer looks like five unrelated audio-reactive curves.

## Cross-axis coupling

After gesture blending, the engine explicitly coordinates related axes:

```text
L2 sway   <-> R1 counter-roll
L1 surge  <-> R2 counter-pitch
L0 stroke -> R0 twist support
bass/L0   -> small L1 correction
```

The final five secondary signals are smoothed and then passed through the existing speed/acceleration constraint layer.

## Choreography controls

Default mode:

```text
--choreography_mode choreography
```

A/B against the previous 2.1 formulas:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --choreography_mode reactive
```

Gesture contribution:

```text
--gesture_strength 1.0
```

`0` keeps only the low-level reactive contribution inside choreography mode; values above `1` emphasize the gesture layer.

Presets:

```text
balanced    general-purpose 6D motion
rhythm      stronger pulse/accent/percussion response
expressive  stronger circle/spiral/wave movement
```

Global secondary-axis amplitude remains controlled by:

```text
--axis_strength 1.0
```

## Six-axis output

Default files:

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        bundle/choreography manifest
```

The manifest includes the generation metadata and detected section summary so a bundle can be inspected later.

## TCode v0.3 device layer

Export TCode:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
```

Preview without hardware:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode_preview 5
```

List serial ports:

```bash
python -m dancer --cli --list_ports
```

Probe a device:

```bash
python -m dancer --cli --serial_port COM4 --device_info
```

Live playback:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --serial_port COM4
```

Start at a timeline point:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --serial_port COM4 \
  --start_at 42.5
```

## D2 range mapping

Devices may report:

```text
L0 1000 9000 Up
R0 2000 8000 Twist
```

PythonDancer maps normalized `0..100` motion into each saved device range and only emits axes reported by D2.

Example:

```text
L0 0%   -> 1000
L0 50%  -> 5000
L0 100% -> 9000
```

This is profile mapping only; it does not physically seek hardware end stops.

Disable D2 mapping with:

```text
--no_device_ranges
```

## Pause / Resume / Seek

The GUI playback controller supports:

- **Pause** — captures timeline time and sends `DSTOP`; no position frame is emitted while paused.
- **Resume** — synchronizes to the frozen pose and rebuilds future ramp-ahead events.
- **Seek** — `DSTOP`, move to the selected pose using the configured seek ramp, then rebuild future events.
- **STOP** — terminate playback and send `DSTOP`.

The controller is exposed as `TCodePlaybackController` for other player integrations.

## Physical limits

L0 defaults to:

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

All planner output remains normalized to `0..100`; the TCode layer performs final device-range mapping.
