# PythonDancer 2.3

PythonDancer turns audio or video soundtracks into single- or six-axis `.funscript` motion and can stream generated motion directly to TCode v0.3 devices.

This fork keeps the original workflow but replaces the old amplitude mapping with a beat-aware planner, SR6/OSR6 six-axis choreography, editable/learnable style profiles, optional separated-stem analysis, D2-aware TCode playback, and a seekable device timeline.

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

- continuous beat / bar / phrase phase;
- phrase-aligned `intro / verse / build / chorus / drop / breakdown / outro` detection;
- reusable gestures: `pulse / sway / rock / circle / spiral / wave / accent`;
- section-dependent gesture selection and gain;
- explicit cross-axis 6D pose coupling;
- `balanced / rhythm / expressive` styles;
- `reactive` compatibility mode;
- choreography analysis persisted in `.motion.json`.

### 2.3 — style learning + stem-aware choreography

2.3 adds a portable style layer above the 2.2 choreography engine.

- editable JSON choreography profiles;
- statistical style learning from an existing six-axis funscript bundle;
- learned per-axis travel/amplitude;
- learned smooth-vs-accent character;
- learned L2↔R1, L1↔R2 and L0↔R0 relationship strength;
- profile-controlled gesture weights, section gains, reactive/gesture mix and smoothing;
- optional `drums / bass / vocals / other` stem enrichment;
- optional Demucs invocation when Demucs is installed;
- direct support for an existing stem directory without Demucs;
- full GUI controls for Profile / Reference bundle / Stems;
- learned profiles can be saved and reused on new tracks.

Reference learning is statistical style transfer, not semantic imitation or model training. The new song keeps its own beat, bar, phrase and section timing; the reference supplies movement character.

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

Demucs is intentionally **not** a required dependency. The official Meta Demucs repository is archived, so PythonDancer treats it as an optional external accelerator. In a normal Python install it can use an importable `demucs` module or a `demucs` executable on `PATH`. In a frozen/PyInstaller build it uses the external `demucs` executable on `PATH`; otherwise use an existing stem directory. If neither is available, `auto` falls back and `required` reports an error.

## Run

Single-axis GUI:

```bash
python -m dancer
```

Six-axis GUI:

```bash
python -m dancer scene.mp4 --multiaxis
```

Six-axis CLI:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis
```

## 2.3 architecture

```text
Audio / video
      │
      ├─ beat / tempo / PLP
      ├─ RMS / onset
      ├─ bass / mid / high
      ├─ pitch / harmonic / percussive
      │
      ├──────── optional stems ────────┐
      │        drums / bass            │
      │        vocals / other          │
      │                                │
      ▼                                ▼
Beat-aligned feature stream + optional stem features
      │
      ├──────────────► L0 adaptive planner
      │                    │
      │                    ▼
      │              L0 action timeline
      │
      ▼
Beat / bar / phrase phase
      │
      ▼
Section Analyzer
      │
      ▼
Gesture Planner
      │
      ├──────── Choreography Profile
      │          axis scale
      │          gesture gain
      │          section gain
      │          coupling gain
      │          smoothing
      │          stem influence
      │
      ▼
6D pose synthesis
      │
      ▼
Per-axis physical constraints
      │
      ▼
Funscript bundle / TCode
```

## Musical choreography

The default secondary-axis planner uses the actual musical timeline rather than `action_index × π`.

Default musical grid:

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

The section analyzer is a deterministic musical-intent heuristic based on energy, rhythmic activity, novelty and local dynamic slope. It is not a semantic music classifier.

## Gesture primitives

The secondary axes are built from reusable 6D gestures:

```text
pulse    beat-driven rotational/accent motion
sway     bar-scale lateral movement
rock     forward/back L1 + R2 movement
circle   quadrature L1/L2 translation
spiral   phrase-scale twist and support motion
wave     slow R1/R2-dominant phrase motion
accent   transient alternating-direction hit
```

Typical section mixtures:

```text
intro       wave + rock
verse       sway + rock + light pulse
build       circle + pulse + spiral
chorus      circle + spiral + sway
DROP        pulse + spiral + accent
breakdown   wave + rock
outro       slow wave / sway
```

Cross-axis coupling is explicit:

```text
L2 sway   <-> R1 counter-roll
L1 surge  <-> R2 counter-pitch
L0 stroke -> R0 twist support
bass/L0   -> small L1 correction
```

## Choreography profiles

A profile is ordinary JSON. See:

```text
examples/choreography-profile.json
```

The main fields are:

```text
axis_scale      per-axis amplitude multipliers
                 L1 L2 R0 R1 R2

gesture_gain    pulse sway rock circle spiral wave accent
section_gain    intro verse build chorus drop breakdown outro
coupling_gain   sway_roll surge_pitch stroke_twist stroke_bass_l1
reactive_mix    0..1 local-reactive contribution
smoothing       0..0.49 temporal smoothing
stem_influence  0..3 separated-stem contribution
```

Use a profile:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --profile examples/choreography-profile.json
```

The GUI exposes a Profile field and file picker as well.

## Learn style from a reference bundle

Given an existing bundle:

```text
reference.funscript
reference.surge.funscript
reference.sway.funscript
reference.twist.funscript
reference.roll.funscript
reference.pitch.funscript
```

learn and immediately apply its movement style:

```bash
python -m dancer new-song.mp3 --cli --yes --multiaxis \
  --reference_bundle reference.funscript
```

Save the learned style for reuse:

```bash
python -m dancer new-song.mp3 --cli --yes --multiaxis \
  --reference_bundle reference.funscript \
  --profile_name my-style \
  --save_learned_profile my-style.json
```

The learner estimates each reference axis's own center before measuring robust travel, then normalizes that travel against axis-specific balanced baselines. It also measures movement activity/smoothness and cross-axis correlations. It converts those statistics into a `ChoreographyProfile`; it does **not** copy timestamps or positions from the reference.

The GUI has separate Profile and Reference bundle fields. They are mutually exclusive. A profile learned from a reference can be saved with **Save learned profile**.

## Optional separated stems

PythonDancer can use:

```text
drums.wav
bass.wav
vocals.wav
other.wav
```

from an existing directory:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --stems auto \
  --stem_dir ./stems/song
```

Or, if Demucs is available:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --stems auto
```

Require stems and fail instead of falling back:

```text
--stems required
```

Disable completely:

```text
--stems off
```

Other controls:

```text
--stem_cache .dancer_stems
--demucs_model htdemucs
```

Mapping inside the choreography layer:

```text
drums onset/energy -> onset + percussive activity
bass energy        -> bass feature / L1 character
vocals pitch       -> pitch-driven R0/R2 character
vocals energy      -> harmonic character
other energy       -> light global/phrase support
```

If stems are unavailable in `auto` mode, the normal 2.2 feature path remains active.

## Choreography controls

Default mode:

```text
--choreography_mode choreography
```

A/B against the original fixed reactive formulas:

```bash
python -m dancer scene.mp4 --cli --yes --multiaxis \
  --choreography_mode reactive
```

Core controls:

```text
--multiaxis_preset balanced|rhythm|expressive
--axis_strength 1.0
--gesture_strength 1.0
--beats_per_bar 4
--bars_per_phrase 4
--section_bars 4
```

## Six-axis output

PythonDancer follows the standard MultiFunPlayer file naming convention:

```text
scene.funscript          L0 / stroke
scene.surge.funscript    L1 / surge
scene.sway.funscript     L2 / sway
scene.twist.funscript    R0 / twist
scene.roll.funscript     R1 / roll
scene.pitch.funscript    R2 / pitch
scene.motion.json        bundle/choreography manifest
```

The manifest includes generation settings, complete section metrics, profile contents when used, and stem-analysis status.

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

```text
L0 0%   -> 1000
L0 50%  -> 5000
L0 100% -> 9000
```

This is profile/range mapping only; it does not physically seek hardware end stops.

Disable D2 mapping with:

```text
--no_device_ranges
```

## Pause / Resume / Seek

The GUI playback controller supports:

- **Pause** — capture timeline time and send `DSTOP`; no position frame is emitted while paused.
- **Resume** — synchronize to the frozen pose and rebuild future ramp-ahead events.
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

## Validation status

The branch includes regression coverage for choreography phase/sections, profile round trips, reference-style learning, profile-driven trajectory changes, stem discovery/fallback, stem-driven trajectory changes, six-axis export, TCode, D2 mapping, and seekable playback. GitHub Actions on this fork is still not creating workflow runs, so these newly added 2.3 tests have not been executed by remote CI in this PR.
