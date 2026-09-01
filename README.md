# PythonDancer 2.7

PythonDancer turns audio/video soundtracks into editable six-axis choreography for `L0/L1/L2/R0/R1/R2`, exports MultiFunPlayer-compatible Funscript bundles/TCode, and streams live motion through serial TCode or Intiface Central / Buttplug.

**2.7 — Quality Intelligence** adds scored multi-candidate generation, A/B preview, automatic weak-range improvement, per-section Motion Intent and SR6 mechanical-risk projection on top of the 2.6 generation-quality engine and the 2.5 editing/safety workstation.

The desktop workstation supports runtime **简体中文 / English** switching. Internal motion/protocol tokens are never translated.

> Upstream: `NodudeWasTaken/PythonDancer`, itself a Python port of `ncdxncdx/FunscriptDancer`.

## Architecture

```text
Audio / video
    ↓
Mixed features + optional stems
    ↓
Beat / bar / phrase / section analysis
    ↓
Continuous Motion Intent
    + section-level overrides
    ↓
Reference Style
    ↓
Independent six-axis planners
    ↓
Gesture Timeline
    ↓
6D pose / velocity / acceleration / jerk optimizer
    ↓
SR6 mechanical risk + nearest-safe-pose projection
    ↓
Motion Quality Scorer
 rhythm · phrase · smoothness · diversity
 coherence · repetition · safety · jerk · stems
    ↓
Multi-Candidate / A-B / Best-section Merge
    ↓
Auto Improvement of weak ranges
    ↓
2.5 keyframe / curve / safety editing
    ↓
Calibration + latency compensation
    ↓
Funscript / TCode / Intiface
```

## Quality Intelligence

Every plan can be scored from 0–100 on nine dimensions:

- Rhythm alignment
- Phrase alignment
- Smoothness
- Axis diversity
- Cross-axis coherence
- Repetition
- Mechanical safety
- Jerk comfort
- Stem responsiveness

The scorer also identifies the weakest timeline windows.

```bash
python -m dancer song.mp3 --cli --yes --multiaxis --quality-score
```

Write the complete report:

```bash
--quality-report quality.json
```

### Multi-candidate generation

Generate and rank 2–8 materially different plans:

```bash
--quality-candidates 6
```

Built-in candidate characters include Balanced, Expressive, Rhythm Heavy, Smooth Flow, Rotation Heavy, Deep Translation, Accent Dense and Experimental. Candidate generation varies preset, gesture strength, independent-axis density, accent threshold, optimizer budgets and Motion Intent bias.

Use `--keep-base-candidate` to rank alternatives without automatically adopting the winner.

### A/B preview

The GUI provides Candidate A/B selectors with:

- Preview A / Preview B — non-destructive curve + 3D pose preview;
- score and strongest metric delta;
- Use A / Use B only when the user confirms the choice;
- Reset preview to return to the current editable plan.

### Best-section merge

Each candidate is rescored inside every detected or manually edited Section. PythonDancer can splice the locally best candidate for Intro/Verse/Build/Chorus/Drop/Breakdown/Outro with crossfaded boundaries.

```bash
--quality-candidates 6 --merge-best-sections
```

### Auto Improvement

The automatic improvement loop:

```text
score → weakest range → try candidate replacements
      → re-score whole track → accept only a real gain → repeat
```

```bash
--auto-improve \
--improve-iterations 4 \
--improve-target 90 \
--improve-min-gain 0.35
```

Locked axes are preserved. A replacement that lowers the score is never accepted.

## Section-level Motion Intent

Each musical section may independently override:

```text
intensity
aggression
flow
complexity
symmetry
rotation_bias
translation_bias
accent_density
```

Overrides have an amount and edge blend. If section boundaries move in the timeline editor, their Intent ranges move with them.

The GUI can **Apply section intent**, **Regenerate section**, or **Clear section intent**. CLI can load JSON:

```bash
--section-intents section-intents.json
```

## Mechanical risk and nearest-safe projection

The SR6 firmware-model solver now estimates:

- reachability;
- maximum servo angle;
- servo safety margin;
- finite-difference linkage sensitivity;
- singularity risk;
- mean / peak trajectory risk;
- unsafe and singularity ratios;
- first unsafe timestamp.

When a requested pose exceeds the configured risk envelope, PythonDancer finds a close safe pose by radial search toward neutral plus coordinate refinement. The projected trajectory is then passed through speed/acceleration/jerk constraints and mechanically checked again.

```bash
--mechanical-projection \
--mechanical-max-risk 0.82 \
--servo-limit-deg 88 \
--singularity-sensitivity 2.5
```

For A/B analysis:

```bash
--no-mechanical-projection
```

This is a planning/diagnostic safety layer. The TCode device firmware still owns real servo/PWM calibration and control.

## Generation Quality retained from 2.6

PythonDancer keeps:

- independent L1/L2/R0/R1/R2 event clocks;
- optional Demucs/provided stems;
- drums/kick/snare/hi-hat, bass, vocal and other stem features;
- continuous 8D Motion Intent;
- manual Intent blending;
- multi-reference style learning and clustering;
- advanced Gesture Timeline blocks;
- simultaneous 6D pose/velocity budgets;
- per-axis speed, acceleration and jerk constraints;
- SR6 geometry/reachability diagnostics;
- device calibration limits feeding the optimizer;
- latency/manual-offset compensation.

Secondary-axis musical mapping:

```text
L0 stroke   primary beat/subdivision planner
L1 surge    bass energy
L2 sway     hi-hat/high-frequency activity
R0 twist    vocal pitch motion
R1 roll     snare/drum accents
R2 pitch    vocal/harmonic energy
```

## Editing & device layer retained from 2.5

- direct keyframe add/drag/delete;
- Beat Snap / Quantize;
- Linear / Smoothstep / PCHIP / Makima interpolation;
- Motion/Risk Heatmaps;
- Smart cross-axis limits;
- music-aware gap filling;
- Axis Link gain/delay/smoothing/position-or-velocity/only-if-empty;
- Solo / Mute / Lock;
- local regeneration;
- Soft Start and optional Auto Home;
- `.pdance` project, autosave, recent projects and Undo/Redo;
- serial TCode v0.3 and D0/D1/D2;
- speed-aware TCode `I<ms>`;
- exception-safe `DSTOP`;
- Intiface Central / Buttplug v4.

## `.pdance` schema 3

2.7 projects persist the complete editable workspace plus Quality Intelligence state:

- last QualityReport;
- candidate plans and scores;
- A/B selection;
- section-level Intent;
- mechanical-projection settings;
- Auto Improvement parameters/history;
- language, SR6 geometry, calibration, Gesture/Curve/Safety/Device settings.

Schema 1 and 2 projects remain readable.

## Bilingual workstation / 中英双语 GUI

Run:

```bash
python -m dancer scene.mp4 --multiaxis
```

The Language menu switches at runtime:

```text
简体中文
English
```

Quality Intelligence, candidates, A/B preview, automatic improvement, Section Intent, mechanical risk, existing editing/device controls, status text and dialogs are localized. Engine tokens such as `balanced`, `forward`, `L0` and protocol data stay unchanged.

CJK rendering uses installed system fonts; PythonDancer does not bundle font files.

Detailed Chinese guide: `docs/PythonDancer-2.7-ZH-CN.md`.

## CLI examples

Default six-axis generation:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis
```

Generate six candidates, merge the best sections and auto-improve:

```bash
python -m dancer song.mp3 --cli --yes --multiaxis \
  --stems auto \
  --quality-candidates 6 \
  --merge-best-sections \
  --auto-improve \
  --quality-report song-quality.json
```

Live serial playback with calibration/latency:

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

## Install

Python 3.10+:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
```

Intiface source install:

```bash
pip install -e '.[intiface]'
```

Development/tests:

```bash
pip install -e '.[test,intiface]'
python -m pytest
```

Desktop release builds install Intiface support automatically. FFmpeg is bundled in macOS packages. Demucs remains optional/external.

## Output bundle

```text
scene.funscript        L0 stroke
scene.surge.funscript  L1 surge
scene.sway.funscript   L2 sway
scene.twist.funscript  R0 twist
scene.roll.funscript   R1 roll
scene.pitch.funscript  R2 pitch
scene.motion.json      manifest / metadata
```

The 2.7 motion manifest is version **1.5**. Normalized Funscript motion remains 0–100; device-specific ranges stay in calibration/live-output policy unless saved as project metadata.

## macOS

Native packages target:

```text
macOS arm64
macOS Intel x86_64
```

Builds are ad-hoc signed but not Apple-notarized. First launch may require Control-click/right-click → **Open**.

## Validation gate

A release candidate is considered validated only after the same final commit passes:

```text
Python 3.10 tests
Python 3.12 tests
Python 3.13 tests
Windows PyInstaller build + artifact
macOS arm64 app/ZIP/DMG + artifact
macOS Intel x86_64 app/ZIP/DMG + artifact
```

A workflow artifact is not the same thing as a published GitHub Release.
