# PythonDancer 2.5

PythonDancer turns audio or video soundtracks into editable single- or six-axis `.funscript` choreography and can stream the final motion to TCode v0.3 devices or Intiface Central / Buttplug devices.

This fork combines beat-aware motion generation, SR6/OSR6 six-axis choreography, learnable style profiles, optional separated stems, precision curve editing, non-destructive projects, motion diagnostics, cross-axis safety shaping, and live device playback.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## 2.5 — precision editing & safety

2.5 extends the 2.4 choreography workstation with ten production-oriented capabilities:

1. direct six-axis keyframe editing;
2. Beat Snap and nearest/floor/ceil quantization;
3. Linear / Smoothstep / PCHIP / Makima curve interpolation;
4. six-axis Motion Heatmap plus combined Risk Heatmap;
5. Smart Limit cross-axis envelopes with `safe / balanced / open` profiles;
6. real Soft Start and optional Auto Home for live playback;
7. music-aware `ambient / beat / repeat` gap filling;
8. configurable Axis Linking with gain, delay, smoothing, position/velocity mode, and only-if-empty behavior;
9. portable `.pdance` projects, autosave, recent-project tracking, and bounded Undo/Redo;
10. Intiface Central / Buttplug protocol v4 output over WebSocket.

The effective editing/output pipeline is:

```text
Audio / video
     ↓
Beat/bar/phrase analysis + optional stems
     ↓
Automatic six-axis choreography
     ↓
Base plan
     ↓
Workspace gestures / sections / Mute / Lock
     ↓
Keyframe + curve editing
     ↓
Axis Linking
     ↓
Music-aware Gap Fill
     ↓
Smart cross-axis limits
     ↓
Per-axis physical speed/acceleration constraints
     ↓
Preview / Funscript / TCode / Intiface
```

Manual editing and safety shaping therefore affect the real exported or streamed plan, not only the preview.

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

### 2.4 — editable choreography workstation
- waveform + beat + section + gesture timeline;
- draggable section boundaries and labels;
- Gesture Timeline Editor;
- per-axis Solo / Mute / Lock;
- selection-local regeneration with crossfade;
- normalized live 3D six-axis pose preview;
- post-edit physical constraint pass.

## Install

Python 3.10+ is supported.

Minimal source install:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

Enable Intiface support in a source install:

```bash
pip install -e '.[intiface]'
```

Development/tests:

```bash
pip install -e '.[test,intiface]'
python -m pytest
```

Desktop release builds install the Intiface extra automatically. FFmpeg is bundled in macOS release apps and is recommended for source installs that process media containers. `pyserial` is a normal dependency. Demucs remains optional/external.

## Run

Single-axis GUI:

```bash
python -m dancer
```

Six-axis 2.5 workstation:

```bash
python -m dancer scene.mp4 --multiaxis
```

Six-axis CLI:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis
```

## Workstation

### Motion + Timeline

The six independent motion plots remain:

```text
L0 stroke     R0 twist
L1 surge      R1 roll
L2 sway       R2 pitch
```

The timeline combines:

```text
Wave      waveform + beat grid
Section   intro / verse / build / chorus / drop / breakdown / outro
Gesture   pulse / sway / rock / circle / spiral / wave / accent
```

- drag empty waveform space to select a range;
- drag section dividers to correct boundaries;
- click a section to relabel it;
- add, move, resize, or delete gesture blocks;
- locally regenerate only the selected time range;
- locked axes remain unchanged during local regeneration.

Axis semantics:

```text
Solo   preview only; never removes an axis from export/device output
Mute   removes that axis from export and live device playback
Lock   preserves that axis during local regeneration
```

If L0 is muted, TCode uses the remaining active axes as its timing source.

### Curve editor

Select any of `L0 / L1 / L2 / R0 / R1 / R2` and edit its actual keyframes:

- double-click to insert a keyframe;
- drag a point to change time and position;
- delete the selected point;
- Smooth a selected range;
- Flatten a selected range;
- Scale amplitude around neutral;
- apply positional Offset;
- Snap to Beat while editing;
- Quantize selected keyframes using `nearest`, `floor`, or `ceil`.

Per-axis interpolation modes:

```text
linear
smoothstep
pchip
makima
```

PCHIP and Makima use SciPy interpolation and are resampled before the final physical constraint pass.

### Diagnostics

The Diagnostics tab shows:

```text
L0 motion intensity
L1 motion intensity
L2 motion intensity
R0 motion intensity
R1 motion intensity
R2 motion intensity
combined RISK
```

Risk estimates combine:

- normalized travel/excursion;
- per-axis velocity;
- per-axis acceleration;
- L2/R1 and L1/R2 coupled excursion;
- simultaneous six-axis normalized velocity load.

The heatmap is a planning diagnostic, not a substitute for the real device's mechanical limits.

## Smart Limit

Smart Limit operates before the final per-axis constraint pass.

Profiles:

```text
safe      strongest coupled-pose and simultaneous-velocity restriction
balanced  default workstation envelope
open      wider coupled-pose and concurrent-motion budget
```

Examples of enforced relationships include:

- extreme L0 travel scales back R0/R1;
- extreme L1 travel scales back R2;
- L2 + R1 share a combined excursion budget;
- simultaneous multi-axis motion shares a normalized velocity budget.

## Gap filling

Long gaps can be filled without replacing the surrounding generated motion:

```text
none      leave gaps untouched
ambient   low-amplitude alternating motion
beat      stronger beat-aligned continuation
repeat    reuse the preceding motion character
```

Existing beat timestamps are preferred; a fallback temporal grid is used when no beat falls inside the gap.

## Axis Linking

Axis Linking can derive or blend one axis from another.

Controls:

```text
Source -> Target
Gain
Delay (ms)
Smoothing 0..1
Mode: position / velocity
Only-if-empty
```

Example concepts:

```text
L2 -> R1   gain -0.35   counter-roll
L1 -> R2   gain  0.25   surge/pitch coupling
L0 -> R0   velocity     motion-reactive twist
```

Links are applied before Smart Limit and before the final physical constraint pass.

## `.pdance` projects

A `.pdance` project persists the editable session rather than only the final six files.

It stores:

- media path;
- base six-axis plan;
- workspace sections and gesture blocks;
- selection and Solo/Mute/Lock state;
- generation configuration and choreography profile;
- per-axis curve/interpolation settings;
- Smart Limit / Gap Fill / Axis Link / playback-safety settings;
- serial and Intiface connection preferences;
- analysis data needed to reopen the editing workspace.

Project writes are atomic. Autosaves are stored under:

```text
~/.pythondancer/autosave/
```

Recent projects are tracked in:

```text
~/.pythondancer/recent.json
```

Undo/Redo snapshots cover the editable plan, workspace, curve settings, and safety shaping state.

## Live playback safety

### Soft Start

For TCode playback from timeline zero, PythonDancer sends a real ramped pose command before normal playback begins. Seeking from another time uses at least the configured Soft Start duration as its synchronization ramp.

For Intiface POSITION_WITH_DURATION devices, the start pose is likewise entered over the Soft Start interval while vibration/rotation outputs remain off.

### Auto Home

When enabled, a neutral-return keyframe is appended to the **live playback plan only**. It is not written into the canonical exported `.funscript` or scheduled `.tcode` files.

The same principle applies to Soft Start: exported scripts preserve the authored timeline; playback safety is a transport policy.

Unexpected TCode playback errors attempt `DSTOP`, and normal completion also stops the serial device after the final transition.

## Intiface / Buttplug

PythonDancer 2.5 supports Intiface Central over WebSocket using the Buttplug protocol v4 Python client.

Default server:

```text
ws://127.0.0.1:12345
```

The current generic mapping is:

```text
L0 position                  -> POSITION_WITH_DURATION
six-axis motion intensity    -> VIBRATE
absolute R0 excursion        -> ROTATE
```

Unsupported device outputs are skipped.

GUI workflow:

```text
Start Intiface Central
→ Scan
→ choose device
→ Play
```

CLI:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --intiface
```

Choose a device/address and safety settings:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --intiface \
  --intiface_address ws://127.0.0.1:12345 \
  --intiface_device 1 \
  --soft_start_ms 900 \
  --home_ms 900
```

A single CLI invocation intentionally allows only one live transport: either `--serial_port` or `--intiface`.

## TCode v0.3

Export scheduled TCode:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis --tcode
```

List / inspect serial devices:

```bash
python -m dancer --cli --list_ports
python -m dancer --cli --serial_port COM4 --device_info
```

Live serial playback with safety timing:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --serial_port COM4 \
  --soft_start_ms 900 \
  --auto_home \
  --home_ms 800
```

D2 saved ranges map normalized `0..100` motion into device preferences and unsupported axes are filtered.

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

## Physical limits

After curve editing, gap filling, axis linking, Smart Limit, and workspace overlays, the final authoritative pass reapplies:

```text
L0     400 units/s, 2400 units/s²
L1/L2  180 units/s, 1000 units/s²
R0     300 units/s, 1800 units/s²
R1/R2  200 units/s, 1200 units/s²
```

## Validation

GitHub Actions covers Python 3.10 / 3.12 / 3.13, Windows PyInstaller packaging, and native macOS Apple Silicon / Intel packaging. The 2.5 regression suite includes keyframe operations, quantization/interpolation, safety heatmaps, coupled Smart Limits, simultaneous velocity budgets, Axis Link modes/delay, Gap Fill, Soft Start/Auto Home helpers, `.pdance` round trips, Intiface frame mapping and soft-start sequencing, plus the existing choreography/profile/stem/TCode/D2/playback/workspace tests.
