"""PythonDancer 2.8 AI Choreography DAW CLI integration."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Mapping

import numpy as np

from . import cli_v26, cli_v26_release, cli_v27
from .automation import AutomationSet, StyleMorphTimeline
from .candidate_composer import CandidateComposition, compose_candidates
from .candidates import generate_candidates
from .comparison import _slice_data, merge_candidate_sections
from .daw_transform import apply_daw_transform
from .device_twin import DeviceTwinProfile, load_device_twin
from .geometry_profile import load_geometry_profile
from .improvement import ImprovementConfig, auto_improve
from .live import LiveChoreographyConfig, LiveChoreographyEngine
from .live_io import LiveSession, SoundDeviceLiveSource, TCodeLiveSink
from .mechanical_safety import MechanicalProjectionConfig, trajectory_mechanical_risk
from .multiaxis import analyze_multiaxis
from .plan_window import slice_plan
from .quality import score_plan
from .workspace_constraints import constrain_workspace_plan


def add_cli_arguments(parser):
    parser = cli_v27.add_cli_arguments(parser)
    group = parser.add_argument_group("AI choreography DAW 2.8")
    group.add_argument("--automation", dest="automation", help="AutomationSet JSON file")
    group.add_argument("--style_morph", "--style-morph", dest="style_morph", help="StyleMorphTimeline JSON file")
    group.add_argument("--candidate_composition", "--candidate-composition", dest="candidate_composition", help="Manual Candidate Composer JSON file")
    group.add_argument("--device_twin", "--device-twin", dest="device_twin", help="Device Twin JSON profile")
    group.add_argument("--live", action="store_true", help="Run predictive Live Choreography instead of offline generation")
    group.add_argument("--live_audio_device", "--live-audio-device", dest="live_audio_device", type=int, help="sounddevice input index")
    group.add_argument("--live_bpm", "--live-bpm", dest="live_bpm", type=float, default=120.0, help="Initial/live tempo")
    group.add_argument("--live_prediction_ms", "--live-prediction-ms", dest="live_prediction_ms", type=float, default=420.0, help="Live prediction horizon in milliseconds")
    group.add_argument("--live_tcode", "--live-tcode", dest="live_tcode", action="store_true", help="Send Live Choreography to --serial_port")
    group.add_argument("--live_seconds", "--live-seconds", dest="live_seconds", type=float, default=0.0, help="Stop Live mode after N seconds; 0 runs until Ctrl+C")
    return parser


def _read_mapping(path: str | None):
    if not path:
        return {}
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _load_automation(path):
    return AutomationSet.from_dict(_read_mapping(path))


def _load_styles(path):
    return StyleMorphTimeline.from_dict(_read_mapping(path))


def _load_composition(path):
    return CandidateComposition.from_dict(_read_mapping(path)) if path else None


def _validate_v28(args):
    invalid = cli_v27._validate_args(args)
    if invalid:
        return invalid
    for name in ("live_bpm", "live_prediction_ms", "live_seconds"):
        value = float(getattr(args, name, 0.0))
        if not np.isfinite(value):
            return f"--{name} must be finite."
    if not 30.0 <= float(args.live_bpm) <= 300.0:
        return "--live_bpm must be within 30..300."
    if float(args.live_prediction_ms) < 20.0:
        return "--live_prediction_ms must be at least 20 ms."
    if float(args.live_seconds) < 0.0:
        return "--live_seconds must be non-negative."
    return None


def _run_live(args, twin: DeviceTwinProfile):
    if args.live_tcode and not getattr(args, "serial_port", None):
        print("--live_tcode requires --serial_port.")
        return 2
    try:
        source = SoundDeviceLiveSource(device=args.live_audio_device)
        engine = LiveChoreographyEngine(LiveChoreographyConfig(
            prediction_horizon_ms=float(args.live_prediction_ms),
            latency_ms=float(twin.timing.command_lead_ms),
        ))
        sink = None
        if args.live_tcode:
            sink = TCodeLiveSink(
                str(args.serial_port),
                baud=int(args.baud),
                timeout=float(args.serial_timeout),
            )

        def pose_transform(pose):
            mapped, _, _ = twin.safe_pose(pose, calibrate=True)
            return mapped

        def on_motion(features, motion, output_pose):
            print(
                f"LIVE bpm={motion.bpm:.1f} conf={motion.beat_confidence:.2f} "
                f"gesture={motion.gesture} predict={motion.prediction_ms:.0f}ms "
                f"L0={output_pose.get('L0', 50):.1f} R0={output_pose.get('R0', 50):.1f}",
                end="\r",
                flush=True,
            )

        session = LiveSession(
            source,
            engine,
            sink=sink,
            on_motion=on_motion,
            pose_transform=pose_transform,
            bpm=float(args.live_bpm),
        )
        session.start()
        started = time.monotonic()
        try:
            while session.worker and session.worker.is_alive():
                if args.live_seconds and time.monotonic() - started >= float(args.live_seconds):
                    break
                time.sleep(.08)
        except KeyboardInterrupt:
            pass
        finally:
            session.stop()
            if session.worker:
                session.worker.join(timeout=2.0)
        print("\nLive Choreography stopped.")
        return 0
    except Exception as exc:
        print(f"Live Choreography failed: {exc}")
        return 2


def _section_ranges(data, analysis, duration: float):
    return cli_v27._section_ranges(data, analysis, duration)


def _best_section_merge_daw(candidates, sections, data, transform, *, base_plan=None, locked_axes=()):
    if not candidates:
        raise ValueError("at least one candidate is required")
    choices = {}
    section_scores = {}
    for index, section in enumerate(sections):
        start, end = float(section["start"]), float(section["end"])
        if end <= start:
            choices[index] = 0
            section_scores[index] = [0.0 for _ in candidates]
            continue
        local_data = _slice_data(data, start, end)
        scores = []
        for candidate in candidates:
            effective = transform(candidate.plan, candidate.config)
            local = slice_plan(effective, start, end, rebase=True)
            scores.append(float(score_plan(
                local,
                local_data,
                geometry=candidate.config.geometry,
                mechanical_config=candidate.config.mechanical,
                compute_windows=False,
            ).overall))
        choices[index] = int(np.argmax(scores))
        section_scores[index] = scores
    merged = merge_candidate_sections(
        candidates,
        sections,
        choices,
        base_plan=base_plan,
        locked_axes=locked_axes,
        blend=.30,
    )
    return merged, choices, section_scores


def cmd(args):
    invalid = _validate_v28(args)
    if invalid:
        print(invalid)
        return 2
    try:
        automation = _load_automation(getattr(args, "automation", None))
        styles = _load_styles(getattr(args, "style_morph", None))
        composition = _load_composition(getattr(args, "candidate_composition", None))
        twin = load_device_twin(args.device_twin) if getattr(args, "device_twin", None) else DeviceTwinProfile()
    except Exception as exc:
        print(f"2.8 configuration error: {exc}")
        return 2

    if getattr(args, "live", False):
        return _run_live(args, twin)

    original_multi = cli_v26._multi_config
    original_plan = cli_v26.legacy.plan_multiaxis
    original_export = cli_v26.legacy.export_funscript_bundle
    state: dict[str, object] = {}

    def multi_config(inner_args, motion, profile=None):
        config = original_multi(inner_args, motion, profile)
        geometry = load_geometry_profile(inner_args.sr6_geometry) if getattr(inner_args, "sr6_geometry", None) else config.geometry
        mechanical = MechanicalProjectionConfig(
            enabled=bool(getattr(inner_args, "mechanical_projection", True)),
            max_risk=float(getattr(inner_args, "mechanical_max_risk", .82)),
            servo_limit_deg=float(getattr(inner_args, "servo_limit_deg", 88.0)),
            sensitivity_limit_deg_per_unit=float(getattr(inner_args, "singularity_sensitivity", 2.5)),
            neutral=float(config.neutral),
        )
        section_intents = cli_v27._load_section_overrides(getattr(inner_args, "section_intents", None))
        return replace(config, section_intents=section_intents, mechanical=mechanical, geometry=geometry)

    def final_transform(plan, config):
        shaped = apply_daw_transform(plan, automation, styles)
        shaped = constrain_workspace_plan(shaped, config)
        if getattr(args, "device_twin", None):
            shaped, _ = twin.canonical_safe_plan(shaped)
        return shaped

    def plan_multiaxis(data, config):
        base = original_plan(data, config)
        duration = max((float(t) for rows in base.values() for t, _ in rows), default=0.0)
        analysis = analyze_multiaxis(data, config)
        sections = _section_ranges(data, analysis, duration)
        final_raw = base
        active_config = config
        candidate_results = []
        count = int(getattr(args, "quality_candidates", 1))
        need_candidates = count > 1 or getattr(args, "merge_best_sections", False) or getattr(args, "auto_improve", False) or composition is not None
        if need_candidates:
            candidate_results = generate_candidates(
                data,
                config,
                count=max(count, 2),
                geometry=config.geometry,
                sections=sections,
                score_transform=final_transform,
            )
            print("DAW quality candidates:")
            for rank, candidate in enumerate(candidate_results, 1):
                print(f"  {rank}. {candidate.name:18s} {candidate.quality.overall:5.1f}")
            if not getattr(args, "keep_base_candidate", False):
                final_raw = {axis: list(rows) for axis, rows in candidate_results[0].plan.items()}
                active_config = candidate_results[0].config

        if composition is not None and candidate_results and sections:
            final_raw, choices = compose_candidates(
                candidate_results,
                sections,
                composition,
                base_plan=final_raw,
            )
            active_config = config
            state["candidate_composition"] = {str(index): name for index, name in choices.items()}
            print("Candidate Composer: " + " | ".join(f"{index + 1}:{name}" for index, name in sorted(choices.items())))
        elif getattr(args, "merge_best_sections", False) and candidate_results and sections:
            final_raw, choices, section_scores = _best_section_merge_daw(
                candidate_results,
                sections,
                data,
                final_transform,
                base_plan=final_raw,
            )
            active_config = config
            state["section_choices"] = {str(k): int(v) for k, v in choices.items()}
            print("Best-section merge:")
            for index, section in enumerate(sections):
                selected = choices[index]
                print(f"  {section['label']:12s} -> {candidate_results[selected].name} ({section_scores[index][selected]:.1f})")

        if getattr(args, "auto_improve", False):
            result = auto_improve(
                data,
                final_raw,
                active_config,
                config=ImprovementConfig(
                    max_iterations=int(args.improve_iterations),
                    target_score=float(args.improve_target),
                    minimum_improvement=float(args.improve_min_gain),
                    candidates=max(2, count),
                ),
                geometry=active_config.geometry,
                sections=sections,
                score_transform=final_transform,
            )
            final_raw = {axis: list(rows) for axis, rows in result.plan.items()}
            state["improvement"] = result.to_dict()
            print(f"Auto Improvement: {result.quality.overall:.1f} · {result.stopped_reason}")

        final = final_transform(final_raw, active_config)
        report = score_plan(
            final,
            data,
            sections=sections,
            geometry=active_config.geometry,
            mechanical_config=active_config.mechanical,
        )
        state["quality"] = report.to_dict()
        state["candidates"] = [item.to_dict(include_plan=False) for item in candidate_results]
        state["mechanical"] = trajectory_mechanical_risk(final, active_config.geometry, active_config.mechanical)
        state["daw"] = {
            "automation": automation.to_dict(),
            "style_morph": styles.to_dict(),
            "device_twin": twin.to_dict() if getattr(args, "device_twin", None) else None,
        }
        if getattr(args, "quality_score", False) or need_candidates:
            cli_v27._print_quality(report)
        return final

    def export_bundle(base_path, plan, *, metadata=None, manifest=True):
        payload = dict(metadata or {})
        payload["daw"] = {"version": "2.8", **dict(state.get("daw") or {})}
        if state:
            payload["quality_intelligence"] = {
                key: value for key, value in state.items() if key != "daw"
            }
        return original_export(base_path, plan, metadata=payload, manifest=manifest)

    cli_v26._multi_config = multi_config
    cli_v26.legacy.plan_multiaxis = plan_multiaxis
    cli_v26.legacy.export_funscript_bundle = export_bundle
    try:
        status = cli_v26_release.cmd(args)
    finally:
        cli_v26._multi_config = original_multi
        cli_v26.legacy.plan_multiaxis = original_plan
        cli_v26.legacy.export_funscript_bundle = original_export

    report_path = getattr(args, "quality_report", None)
    if report_path and state:
        target = Path(report_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Quality/DAW report: {target}")
    return status
