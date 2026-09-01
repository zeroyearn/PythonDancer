"""PythonDancer 2.6 CLI compatibility layer.

The 2.5 CLI remains the stable command implementation; this module upgrades its
extension points for multi-reference learning, independent-axis generation,
Motion Intent metadata, optimizer controls, calibration and latency-aware live
playback without duplicating the entire command parser.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import sleep

from . import cli as legacy
from .calibration import apply_calibration, load_calibration_profile
from .independent_planner import IndependentAxisConfig
from .intent import infer_motion_intent
from .latency import DeviceTimingProfile, compensate_plan_latency, measure_query_latency
from .multiaxis import MultiAxisConfig
from .optimizer import OptimizerConfig
from .reference_library import cluster_profiles, learn_profile_from_bundles
from .style import ChoreographyProfile, learn_profile_from_bundle, load_profile, save_profile
from .tcode import SerialTCodeDevice, TCodePlaybackController, build_tcode_events, encode_plan_frame, export_tcode_script


def _resolve_choreography_profile(args) -> ChoreographyProfile | None:
    sources = int(bool(args.profile)) + int(bool(args.reference_bundle)) + int(bool(args.reference_library))
    if sources > 1:
        raise ValueError("Use only one of --profile, --reference_bundle, or --reference_library.")
    learned = None
    if args.reference_library:
        learned = learn_profile_from_bundles(
            args.reference_library,
            weights=args.reference_weights,
            name=args.profile_name or "learned-library",
        )
        if args.style_clusters:
            individual = [learn_profile_from_bundle(path) for path in args.reference_library]
            print("Reference style clusters:")
            for cluster in cluster_profiles(individual, clusters=args.style_clusters):
                print(f"  {cluster.name}: {len(cluster.member_indices)} references")
    elif args.reference_bundle:
        learned = learn_profile_from_bundle(args.reference_bundle, name=args.profile_name)
    elif args.profile:
        return load_profile(args.profile)

    if args.save_learned_profile:
        if learned is None:
            raise ValueError("--save_learned_profile requires --reference_bundle or --reference_library.")
        path = save_profile(args.save_learned_profile, learned)
        print(f"Learned choreography profile: {path}")
    return learned


def _multi_config(args, motion, profile=None) -> MultiAxisConfig:
    independent = IndependentAxisConfig(
        enabled=bool(args.independent_axes),
        min_interval=max(float(args.min_interval), .02),
        density=float(args.axis_density),
        accent_threshold=float(args.axis_accent_threshold),
    )
    optimizer = OptimizerConfig(
        enabled=bool(args.motion_optimizer),
        pose_budget=float(args.pose_budget),
        velocity_budget=float(args.velocity_budget),
        iterations=int(args.optimizer_iterations),
    )
    return MultiAxisConfig(
        motion=motion,
        preset=args.multiaxis_preset,
        strength=float(args.axis_strength),
        mode=args.choreography_mode,
        gesture_strength=float(args.gesture_strength),
        beats_per_bar=int(args.beats_per_bar),
        bars_per_phrase=int(args.bars_per_phrase),
        section_bars=int(args.section_bars),
        profile=profile,
        independent=independent,
        optimizer=optimizer,
    )


def _choreography_metadata(config, analysis, data):
    intent = infer_motion_intent(data, analysis)
    payload = {
        "mode": config.mode,
        "preset": config.preset,
        "axis_strength": float(config.strength),
        "gesture_strength": float(config.gesture_strength),
        "analysis": analysis.to_dict(),
        "intent": intent.to_dict(),
        "independent_axes": {
            "enabled": bool(config.independent.enabled),
            "density": float(config.independent.density),
            "accent_threshold": float(config.independent.accent_threshold),
        },
        "optimizer": config.optimizer.to_dict(),
    }
    if config.profile is not None:
        payload["profile"] = config.profile.to_dict()
    if isinstance(data.get("stem_analysis"), dict):
        payload["stems"] = dict(data["stem_analysis"])
    return payload


def _calibrated_live_plan(args, plan):
    playback = legacy._live_plan(args, plan)
    calibration = load_calibration_profile(args.calibration_profile) if args.calibration_profile else None
    playback = apply_calibration(playback, calibration)
    timing = DeviceTimingProfile(
        transport="intiface" if args.intiface else "serial",
        latency_ms=float(args.latency_ms) + (float(calibration.latency_ms) if calibration else 0.0),
        manual_offset_ms=float(args.manual_offset_ms),
    )
    return compensate_plan_latency(playback, timing), calibration, timing


def _handle_tcode(args, plan, out_file: Path, source: Path) -> int:
    requested = bool(args.tcode or args.tcode_out or args.tcode_preview > 0 or args.serial_port)
    if not requested:
        return 0
    events = build_tcode_events(plan)
    if not events:
        print("No TCode events could be generated.")
        return 2

    path = legacy._requested_tcode_path(args, out_file)
    if path is not None:
        written = export_tcode_script(path, events, source=str(source))
        print(f"TCode script: {written} ({len(events)} scheduled frames)")
    if args.tcode_preview > 0:
        count = min(int(args.tcode_preview), len(events))
        print(f"TCode preview ({count}/{len(events)}):")
        for event in events[:count]:
            print(f"  {int(round(event.send_at * 1000)):>7} ms  {event.command}")
    if not args.serial_port:
        return 0

    try:
        playback_plan, calibration_profile, configured_timing = _calibrated_live_plan(args, plan)
    except Exception as exc:
        print(f"Unable to prepare calibrated playback: {exc}")
        return 2

    print(f"Opening TCode serial device {args.serial_port} @ {args.baud}...")
    try:
        with SerialTCodeDevice(args.serial_port, baud=args.baud, timeout=args.serial_timeout) as device:
            profile = device.profile()
            legacy._print_device_profile(profile)
            timing = configured_timing
            if args.measure_latency:
                measured = measure_query_latency(device)
                timing = replace(
                    timing,
                    latency_ms=float(timing.latency_ms) + float(measured.latency_ms),
                    jitter_ms=float(measured.jitter_ms),
                )
                playback_plan = compensate_plan_latency(legacy._live_plan(args, apply_calibration(plan, calibration_profile)), timing)
                print(f"Measured transport latency: {measured.latency_ms:.1f} ms one-way estimate · jitter {measured.jitter_ms:.1f} ms")
            active = profile.active_motion_axes(playback_plan)
            if profile.axes and not active:
                print("The device did not report any generated motion axes in D2.")
                return 2
            controller_profile = profile if not args.no_device_ranges else None
            seek_ramp_ms = max(int(args.seek_ramp_ms), int(args.soft_start_ms))
            if args.soft_start_ms > 0 and args.start_at <= 1e-9:
                device.stop()
                command = encode_plan_frame(playback_plan, 0.0, profile=controller_profile, interval_ms=int(args.soft_start_ms))
                if command:
                    device.send(command)
                    sleep(args.soft_start_ms / 1000.0)
            controller = TCodePlaybackController(
                playback_plan,
                device,
                speed=args.play_speed,
                profile=profile,
                use_device_ranges=not args.no_device_ranges,
                seek_ramp_ms=seek_ramp_ms,
            )
            print(
                f"Playing from {args.start_at:.3f}s at {args.play_speed:g}x; "
                f"command lead={timing.command_lead_ms:.1f} ms; calibration={calibration_profile.name if calibration_profile else 'none'}."
            )
            try:
                controller.play(start_at=args.start_at)
            except KeyboardInterrupt:
                controller.stop()
                print("Playback interrupted; DSTOP sent.")
                return 130
            device.stop()
    except Exception as exc:
        print(f"TCode serial playback failed: {exc}")
        return 2
    print("TCode playback complete.")
    return 0


def _handle_intiface(args, plan) -> int:
    if not args.intiface:
        return 0
    try:
        playback_plan, calibration, timing = _calibrated_live_plan(args, plan)
    except Exception as exc:
        print(f"Unable to prepare calibrated Intiface playback: {exc}")
        return 2
    print(
        f"Opening Intiface Central at {args.intiface_address}; "
        f"command lead={timing.command_lead_ms:.1f} ms; calibration={calibration.name if calibration else 'none'}..."
    )
    try:
        legacy.play_plan_intiface_sync(
            playback_plan,
            address=args.intiface_address,
            device_index=args.intiface_device,
            speed=args.play_speed,
            start_at=args.start_at,
            soft_start_ms=args.soft_start_ms,
        )
    except KeyboardInterrupt:
        print("Intiface playback interrupted; device stop requested by client cleanup.")
        return 130
    except Exception as exc:
        print(f"Intiface playback failed: {exc}")
        return 2
    print("Intiface playback complete.")
    return 0


def cmd(args):
    if getattr(args, "axis_density", 1.0) <= 0:
        print("--axis_density must be greater than zero.")
        return 2
    if not 0.0 <= getattr(args, "axis_accent_threshold", .62) <= 1.0:
        print("--axis_accent_threshold must be within 0..1.")
        return 2
    if getattr(args, "pose_budget", 1.85) <= 0 or getattr(args, "velocity_budget", 2.25) <= 0:
        print("--pose_budget and --velocity_budget must be greater than zero.")
        return 2
    if getattr(args, "optimizer_iterations", 3) < 1:
        print("--optimizer_iterations must be at least 1.")
        return 2
    if getattr(args, "reference_weights", None) and not getattr(args, "reference_library", None):
        print("--reference_weights requires --reference_library.")
        return 2
    if getattr(args, "reference_library", None) and getattr(args, "reference_weights", None):
        if len(args.reference_library) != len(args.reference_weights):
            print("--reference_weights must have one value per reference bundle.")
            return 2

    legacy._resolve_choreography_profile = _resolve_choreography_profile
    legacy._multi_config = _multi_config
    legacy._choreography_metadata = _choreography_metadata
    legacy._handle_tcode = _handle_tcode
    legacy._handle_intiface = _handle_intiface

    status = legacy.cmd(args)
    return status
