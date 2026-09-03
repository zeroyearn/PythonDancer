# PythonDancer 3.0

PythonDancer turns audio/video into editable six-axis choreography for `L0/L1/L2/R0/R1/R2`, exports MultiFunPlayer-compatible Funscript bundles/TCode, and supports serial TCode, Intiface Central / Buttplug and predictive Live Choreography.

**3.0 — Intelligent Choreography** adds a semantic intelligence layer above the validated 2.8 DAW: natural-language Copilot editing, Motion Grammar, local preference learning, section-level reference retrieval, Plugin SDK, MIDI/OSC/Link-style control surfaces, Device Twin 2.0 feedback/dynamics, project versioning, batch workflows and portable Motion Packs.

The desktop workstation supports runtime **简体中文 / English** switching. Internal axis/protocol tokens are never translated.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## Safety architecture

3.0 intelligence is deliberately **not** allowed to send arbitrary hardware commands. Copilot, Motion Grammar, retrieval and plugins produce canonical choreography or deterministic editing operations. Physical output still flows through the existing optimizer, mechanical projection and Device Twin safety chain.

```text
Audio / video
    ↓
Beat / bar / phrase / section + optional stems
    ↓
Continuous Motion Intent
    ↓
Reference Style / Section Retrieval
    ↓
Copilot → deterministic operations
Motion Grammar → semantic motion program
Preference Model → personalized QualityWeights
    ↓
Independent six-axis planners
Gesture Timeline
DAW Automation + Style Morphing
Candidate Composer
    ↓
6D optimizer
SR6 mechanical projection
Device Twin 2.0
  geometry · calibration · timing
  velocity · acceleration · jerk
  telemetry gain/bias/latency
  dynamic/thermal load model
    ↓
Effective-output Quality Intelligence
    ↓
Funscript / TCode / Intiface / Live
```

Firmware remains authoritative for real device PWM/servo control, emergency stops and hardware-specific safety.

## Choreography Copilot

Copilot accepts Chinese or English editing instructions and compiles them into explicit DAW/Motion Grammar operations instead of raw keyframes or device commands.

Examples:

```text
副歌更激进一点，锁住 L0，R1 少一点，加 wave
Drop more aggressive, keep L0, reduce R1 and add a spiral
Breakdown smoother and safer
```

CLI:

```bash
python -m dancer song.mp3 --cli --multiaxis --yes \
  --copilot "副歌更激进一点，锁住 L0，加 wave"
```

The desktop **Intelligence** workspace exposes the same operation compiler.

## Motion Grammar / Motion Compiler

Semantic primitives currently include:

```text
hold · drift · pulse · wave · spiral · orbit
rock · sweep · twist · accent · recoil
```

A Motion Program is a portable deterministic description of high-level choreography:

```json
{
  "name": "drop-program",
  "blend": 0.45,
  "primitives": [
    {"kind": "spiral", "start": 32, "end": 40, "amount": 0.9, "cycles": 4},
    {"kind": "accent", "start": 40, "end": 44, "amount": 1.1, "cycles": 8}
  ]
}
```

```bash
--motion-program program.json --motion-blend 0.45
```

The compiler outputs canonical 0–100 six-axis motion. Device constraints are applied afterwards.

## Preference Learning / personalized Quality Intelligence

Explicit Candidate A/B choices can update a local `PreferenceModel`. The model adapts the existing Quality Intelligence metric weights rather than replacing the scorer.

Quality dimensions remain:

- rhythm alignment;
- phrase alignment;
- smoothness;
- axis diversity;
- cross-axis coherence;
- repetition;
- mechanical safety;
- jerk comfort;
- stem responsiveness.

The profile is local, deterministic and JSON-serializable:

```bash
--preference-profile my-preferences.json
--save-preference-profile my-preferences.json
```

The GUI provides **Prefer A / Prefer B** controls and automatically re-ranks candidates using the learned weights.

## Section Reference Retrieval

`ReferenceSectionIndex` stores compact music/motion descriptors:

```text
BPM · energy · bass · vocal · high-frequency activity
duration · rotation · translation · complexity
```

The current section can retrieve nearby reference motion, adapt its duration/amplitude and splice it into the editable plan while respecting locked axes.

```bash
--reference-index references.json \
--reference-query '{"bpm":138,"energy":0.9,"bass":0.85,"duration":8}' \
--reference-top-k 5 \
--reference-amount 0.35
```

## Plugin SDK

PythonDancer discovers third-party entry points under:

```text
pythondancer.plugins
```

Supported plugin kinds:

```text
gesture
quality_metric
device
exporter
analyzer
planner
copilot_backend
control_surface
```

Plugin discovery is isolated: one broken plugin does not prevent PythonDancer from launching.

```bash
--discover-plugins
```

## MIDI / OSC / Link-style transport

Optional control dependencies:

```bash
pip install -e '.[control]'
```

Control mappings can target DAW/Live parameters through MIDI CC/notes or OSC paths. Live Choreography can sample an external BPM/beat-phase provider every audio block.

```bash
--control-map controls.json
--midi-input "My MIDI Device"
--osc-port 9000
--ableton-link
```

`LinkClock` provides the shared transport interface and deterministic fallback. Availability of a real network Link backend depends on an installed compatible Python binding.

## Device Twin 2.0

The Device Twin now combines:

- SR6 geometry;
- axis calibration;
- transport latency/jitter;
- velocity / acceleration / jerk limits;
- mechanical risk policy;
- optional telemetry-derived command gain/bias;
- estimated response latency and RMS tracking error;
- conservative dynamic-load / reversal / thermal estimates.

Telemetry format:

```json
{
  "samples": [
    {
      "timestamp": 0.0,
      "commanded": {"L0": 50, "L1": 50, "L2": 50, "R0": 50, "R1": 50, "R2": 50},
      "actual": {"L0": 49.8, "L1": 50.1, "L2": 50, "R0": 50, "R1": 50, "R2": 50}
    }
  ]
}
```

```bash
--device-twin device.json \
--telemetry-log telemetry.json \
--write-adaptive-twin adaptive-device.json
```

Feedback compensation is opt-in. It does not replace firmware calibration or emergency safety.

## Project Versions

`ProjectVersionGraph` provides lightweight choreography version control inside the application:

```text
main
 ├─ base
 ├─ smoother-verse
 └─ aggressive-drop
```

Supported operations:

- content-addressed snapshots;
- named branches;
- checkout;
- history;
- section-level merge between versions.

Version graph state can be persisted inside `.pdance` and exported through CLI:

```bash
--version-graph-out versions.json --version-message "stronger chorus"
```

## Motion Packs

Portable `.pdmotion` packs are ZIP containers with a JSON manifest and can include:

- Motion Programs;
- Automation presets;
- Style Morph timelines;
- Device Twins;
- Preference profiles;
- plugin configuration.

CLI:

```bash
--motion-pack creator-pack.pdmotion
--motion-program-name spiral-drop
--preference-name personal
--device-twin-name My-SR6
```

Export the active session assets:

```bash
--export-motion-pack my-pack.pdmotion
```

## Batch Queue

Batch manifests describe multiple media jobs and per-job options:

```json
{
  "workers": 2,
  "jobs": [
    {"identifier":"track-a","media_path":"a.mp3","output_path":"out/a","options":{"copilot_instruction":"drop wave"}},
    {"identifier":"track-b","media_path":"b.mp3","output_path":"out/b","options":{"quality_candidates":6}}
  ]
}
```

```bash
--batch-manifest jobs.json --batch-workers 2
```

The desktop Batch Queue executes jobs in isolated subprocesses so one job cannot mutate another project's runtime state.

## 2.8 DAW retained

3.0 retains all validated 2.8 functionality:

- DAW Automation Lanes;
- Style Morphing;
- Candidate Composer with exact section-level effective-output scoring;
- waveform / beat grid;
- Gesture Timeline;
- Solo / Mute / Lock;
- local regeneration;
- Quality Intelligence / A-B / Auto Improvement;
- predictive Live Choreography;
- Device profiles and calibration;
- serial TCode and Intiface playback;
- bilingual GUI;
- Windows/macOS packaging.

When the 3.0 intelligence layer is unused, the existing 2.8 editing/output chain remains the baseline behavior.

## `.pdance` schema 5

Schema 5 stores the complete editable project plus 3.0 intelligence state:

- Copilot instruction/state;
- Preference Model;
- Motion Program;
- Reference index state;
- Project Version Graph;
- Device Twin 2.0 feedback/dynamics;
- existing Automation, Style Morph, Candidate Composer and Live settings;
- Quality Intelligence, generation, workspace, curves, safety and device state.

Schemas **1 / 2 / 3 / 4 remain readable**.

## CLI quick start

Default six-axis generation:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis
```

Open desktop workstation:

```bash
python -m dancer song.mp3 --multiaxis
```

Copilot + candidates + personalized scoring:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --copilot "drop more aggressive with spiral" \
  --quality-candidates 6 \
  --preference-profile preferences.json
```

Predictive Live mode:

```bash
python -m dancer --cli --multiaxis --live --live-bpm 128
```

Use `python -m dancer --help` for the complete CLI surface.

## Optional dependencies

```bash
# Intiface / Buttplug
pip install -e '.[intiface]'

# Live audio
pip install -e '.[live]'

# MIDI / OSC controls
pip install -e '.[control]'

# Development / tests / packaging
pip install -e '.[test,build,intiface,live,control]'
```

## Release packaging

Release targets:

- Windows x86_64;
- macOS arm64;
- macOS Intel x86_64.

macOS packages are ad-hoc signed, not Apple-notarized. Live audio may require microphone/input permission. OSC/Link-style local networking may require local-network permission.
