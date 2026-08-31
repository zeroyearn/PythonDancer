from __future__ import annotations

from pathlib import Path

from .libfun import autoval, create_actions, dump_csv, dump_funscript, load_audio_data, render_heatmap
from .motion import MotionConfig
from .multiaxis import AXIS_ORDER, MultiAxisConfig, analyze_multiaxis, bundle_paths, export_funscript_bundle, plan_multiaxis
from .stems import enrich_with_stems
from .style import ChoreographyProfile, learn_profile_from_bundle, load_profile, save_profile
from .tcode import (
    SerialTCodeDevice,
    TCodePlaybackController,
    build_tcode_events,
    default_tcode_path,
    export_tcode_script,
    list_serial_ports,
)
from .util import cli_args, ffmpeg_check, ffmpeg_conv


def _multiaxis_existing_outputs(base_path: Path, include_manifest: bool) -> list[Path]:
    paths = bundle_paths(base_path)
    candidates = list(paths.values())
    if include_manifest:
        candidates.append(paths["L0"].with_suffix(".motion.json"))
    return [path for path in candidates if path.exists()]


def _requested_tcode_path(args, out_file: Path) -> Path | None:
    if args.tcode_out:
        return Path(args.tcode_out)
    if args.tcode:
        return default_tcode_path(out_file)
    return None


def _print_device_profile(profile) -> None:
    firmware = " | ".join(profile.firmware) or "no D0 response"
    version = " | ".join(profile.tcode) or "no D1 response"
    print(f"Device: {firmware}")
    print(f"Protocol: {version}")
    if profile.axes:
        print("D2 axes / saved ranges:")
        for axis in sorted(profile.axes):
            item = profile.axes[axis]
            suffix = f" {item.name}" if item.name else ""
            print(f"  {axis}: {item.minimum}..{item.maximum}{suffix}")
    else:
        print("D2 axes: no parseable axis rows; falling back to generated axes/full range.")


def _handle_tcode(args, plan, out_file: Path, source: Path) -> int:
    requested = bool(args.tcode or args.tcode_out or args.tcode_preview > 0 or args.serial_port)
    if not requested:
        return 0

    events = build_tcode_events(plan)
    if not events:
        print("No TCode events could be generated.")
        return 2

    path = _requested_tcode_path(args, out_file)
    if path is not None:
        written = export_tcode_script(path, events, source=str(source))
        print(f"TCode script: {written} ({len(events)} scheduled frames)")

    if args.tcode_preview > 0:
        count = min(int(args.tcode_preview), len(events))
        print(f"TCode preview ({count}/{len(events)}):")
        for event in events[:count]:
            print(f"  {int(round(event.send_at * 1000)):>7} ms  {event.command}")

    if args.serial_port:
        print(f"Opening TCode serial device {args.serial_port} @ {args.baud}...")
        try:
            with SerialTCodeDevice(args.serial_port, baud=args.baud, timeout=args.serial_timeout) as device:
                profile = device.profile()
                _print_device_profile(profile)
                active = profile.active_motion_axes(plan)
                if profile.axes:
                    print("Playback axes: " + ", ".join(active or ("none",)))
                    if not active:
                        print("The device did not report any generated motion axes in D2.")
                        return 2
                calibration = "D2 range mapping" if not args.no_device_ranges else "full 0000..9999 range"
                controller = TCodePlaybackController(
                    plan,
                    device,
                    speed=args.play_speed,
                    profile=profile,
                    use_device_ranges=not args.no_device_ranges,
                    seek_ramp_ms=args.seek_ramp_ms,
                )
                print(f"Playing from {args.start_at:.3f}s at {args.play_speed:g}x using {calibration}. Ctrl+C sends DSTOP.")
                try:
                    controller.play(start_at=args.start_at)
                except KeyboardInterrupt:
                    controller.stop()
                    print("Playback interrupted; DSTOP sent.")
                    return 130
        except Exception as exc:
            print(f"TCode serial playback failed: {exc}")
            return 2
        print("TCode playback complete.")
    return 0


def _device_info(args) -> int:
    if not args.serial_port:
        print("--device_info requires --serial_port.")
        return 2
    try:
        with SerialTCodeDevice(args.serial_port, baud=args.baud, timeout=args.serial_timeout) as device:
            _print_device_profile(device.profile())
    except Exception as exc:
        print(f"Unable to query TCode device: {exc}")
        return 2
    return 0


def _resolve_choreography_profile(args) -> ChoreographyProfile | None:
    if args.profile and args.reference_bundle:
        raise ValueError("Use either --profile or --reference_bundle, not both.")
    if args.reference_bundle:
        learned = learn_profile_from_bundle(args.reference_bundle, name=args.profile_name)
        if args.save_learned_profile:
            path = save_profile(args.save_learned_profile, learned)
            print(f"Learned choreography profile: {path}")
        return learned
    if args.save_learned_profile:
        raise ValueError("--save_learned_profile requires --reference_bundle.")
    if args.profile:
        return load_profile(args.profile)
    return None


def _multi_config(args, motion: MotionConfig, profile: ChoreographyProfile | None = None) -> MultiAxisConfig:
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
    )


def _choreography_metadata(config: MultiAxisConfig, analysis, data) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": config.mode,
        "preset": config.preset,
        "axis_strength": float(config.strength),
        "gesture_strength": float(config.gesture_strength),
        "analysis": analysis.to_dict(),
    }
    if config.profile is not None:
        payload["profile"] = config.profile.to_dict()
    stem_analysis = data.get("stem_analysis")
    if isinstance(stem_analysis, dict):
        payload["stems"] = dict(stem_analysis)
    return payload


def _enrich_stems(args, data, source: Path):
    mode = "auto" if args.stem_dir and args.stems == "off" else args.stems
    if mode == "off":
        return data
    print(f"Stem analysis: mode={mode}, model={args.demucs_model}...")
    enriched = enrich_with_stems(
        data,
        source,
        mode=mode,
        stem_dir=args.stem_dir,
        cache_dir=args.stem_cache,
        model=args.demucs_model,
    )
    status = enriched.get("stem_analysis", {}).get("status", "unknown")
    print(f"Stem analysis status: {status}")
    return enriched


def cmd(args):
    if args.list_ports:
        try:
            ports = list_serial_ports()
        except Exception as exc:
            print(f"Unable to list serial ports: {exc}")
            return 2
        if not ports:
            print("No serial ports found.")
            return 0
        print("Serial ports:")
        for device, description in ports:
            print(f"  {device}: {description}")
        return 0

    if args.device_info:
        return _device_info(args)

    if not args.audio_path:
        print("No audio file specified!")
        return 2
    audio_file = Path(args.audio_path)
    if not audio_file.exists():
        print("Audio file doesn't exist!")
        return 2
    if args.multiaxis and args.csv:
        print("--csv is single-axis only; omit it to write a six-axis funscript bundle.")
        return 2
    if args.multiaxis and args.planner != "adaptive":
        print("--multiaxis currently requires --planner adaptive for the primary L0 axis.")
        return 2
    if args.axis_strength < 0 or args.gesture_strength < 0:
        print("--axis_strength and --gesture_strength must be non-negative.")
        return 2
    if args.beats_per_bar <= 0 or args.bars_per_phrase <= 0 or args.section_bars <= 0:
        print("--beats_per_bar, --bars_per_phrase, and --section_bars must be positive integers.")
        return 2
    if args.play_speed <= 0:
        print("--play_speed must be greater than zero.")
        return 2
    if args.start_at < 0:
        print("--start_at must be non-negative.")
        return 2
    if args.seek_ramp_ms < 0:
        print("--seek_ramp_ms must be non-negative.")
        return 2

    try:
        choreography_profile = _resolve_choreography_profile(args) if args.multiaxis else None
    except Exception as exc:
        print(f"Unable to load/learn choreography profile: {exc}")
        return 2

    out_file = Path(args.out_path) if args.out_path else audio_file.with_suffix(".csv" if args.csv else ".funscript")
    if args.multiaxis:
        existing = _multiaxis_existing_outputs(out_file, include_manifest=not args.no_manifest)
        if existing and not args.yes:
            print("Multi-axis output already exists:")
            for path in existing:
                print(f"  {path}")
            return 2
    elif out_file.exists() and not args.yes:
        print(f"Output already exists: {out_file}")
        return 2

    tcode_output = _requested_tcode_path(args, out_file)
    if tcode_output is not None and tcode_output.exists() and not args.yes:
        print(f"TCode output already exists: {tcode_output}")
        return 2

    converted_file = None
    if args.convert:
        print("Converting audio...")
        if ffmpeg_check():
            return 2
        tmp_dir = Path("tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        converted_file = tmp_dir / f"{audio_file.stem}.wav"
        try:
            ffmpeg_conv(audio_file, converted_file)
            audio_file = converted_file
        except Exception as exc:
            print(f"Failed to convert audio: {exc}")
            return 2

    try:
        print("Loading audio features...")
        data = load_audio_data(audio_file, plp=not args.no_plp)
        if args.multiaxis:
            try:
                data = _enrich_stems(args, data, audio_file)
            except Exception as exc:
                print(f"Stem analysis failed: {exc}")
                return 2
        if args.automap:
            print("Automapping...")
            pitch, energy = autoval(
                data,
                tpi=args.auto_pitch,
                target_speed=args.auto_speed,
                v2above=args.auto_per / 100.0,
                opt=args.auto_mod - 1,
                planner=args.planner,
            )
            args.pitch = pitch
            args.energy = energy
            print(f"Automap: pitch={pitch:.2f}, energy={energy:.2f}")

        if args.multiaxis:
            motion = MotionConfig(
                energy_multiplier=float(args.energy),
                pitch_range=float(args.pitch),
                overflow=int(args.overflow),
                amplitude_centering=float(args.amplitude_centering),
                center_offset=float(args.center_offset),
                subdivision=int(args.subdivision),
                max_speed=float(args.max_speed),
                max_acceleration=float(args.max_acceleration),
                min_interval=float(args.min_interval),
            )
            config = _multi_config(args, motion, choreography_profile)
            analysis = analyze_multiaxis(data, config)
            profile_label = config.profile.name if config.profile is not None else "built-in"
            print(f"Creating six-axis motion ({config.mode}, preset={config.preset}, profile={profile_label})...")
            if args.show_sections and analysis.sections:
                print("Detected sections:")
                for section in analysis.sections:
                    print(
                        f"  beats {section.start_beat:>4}-{section.end_beat:<4} {section.label:<10} "
                        f"energy={section.energy:.2f} activity={section.activity:.2f} novelty={section.novelty:.2f}"
                    )
            plan = plan_multiaxis(data, config)
            if not plan["L0"]:
                print("No actions could be generated from this input.")
                return 2
            summary = analysis.summary()
            choreography = _choreography_metadata(config, analysis, data)
            written = export_funscript_bundle(
                out_file,
                plan,
                metadata={
                    "notes": (
                        f"planner=multiaxis; mode={config.mode}; preset={config.preset}; profile={profile_label}; "
                        f"gesture_strength={config.gesture_strength}; subdivision={args.subdivision}; "
                        f"axis_strength={args.axis_strength}"
                    ),
                    "choreography_sections": summary,
                    "choreography": choreography,
                },
                manifest=not args.no_manifest,
            )
            print("Wrote multi-axis bundle:")
            for axis in AXIS_ORDER:
                print(f"  {axis}: {written[axis]} ({len(plan[axis])} actions)")
            if "manifest" in written:
                print(f"  manifest: {written['manifest']}")
            if summary:
                print(f"Sections: {summary}")
            if args.heatmap:
                heatmap_file = written["L0"].with_stem(written["L0"].stem + "_heatmap").with_suffix(".png")
                render_heatmap(
                    data,
                    args.energy,
                    args.pitch,
                    args.overflow,
                    amplitude_centering=args.amplitude_centering,
                    center_offset=args.center_offset,
                    planner="adaptive",
                    subdivision=args.subdivision,
                    max_speed=args.max_speed,
                    max_acceleration=args.max_acceleration,
                    min_interval=args.min_interval,
                ).savefig(heatmap_file, bbox_inches="tight", pad_inches=0)
                print(f"L0 heatmap: {heatmap_file}")
            tcode_status = _handle_tcode(args, plan, written["L0"], Path(args.audio_path))
            if tcode_status:
                return tcode_status
            print("Done: six-axis bundle generated")
            return 0

        print("Creating actions...")
        actions = create_actions(
            data,
            energy_multiplier=args.energy,
            pitch_range=args.pitch,
            overflow=args.overflow,
            amplitude_centering=args.amplitude_centering,
            center_offset=args.center_offset,
            planner=args.planner,
            subdivision=args.subdivision,
            max_speed=args.max_speed,
            max_acceleration=args.max_acceleration,
            min_interval=args.min_interval,
        )
        if not actions:
            print("No actions could be generated from this input.")
            return 2
        out_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"Writing {out_file}...")
        with out_file.open("w", encoding="utf8") as handle:
            if args.csv:
                dump_csv(handle, actions)
            else:
                dump_funscript(handle, actions, metadata={"notes": f"planner={args.planner}; subdivision={args.subdivision}"})
        if args.heatmap:
            heatmap_file = out_file.with_stem(out_file.stem + "_heatmap").with_suffix(".png")
            render_heatmap(
                data,
                args.energy,
                args.pitch,
                args.overflow,
                amplitude_centering=args.amplitude_centering,
                center_offset=args.center_offset,
                planner=args.planner,
                subdivision=args.subdivision,
                max_speed=args.max_speed,
                max_acceleration=args.max_acceleration,
                min_interval=args.min_interval,
            ).savefig(heatmap_file, bbox_inches="tight", pad_inches=0)
            print(f"Heatmap: {heatmap_file}")
        tcode_status = _handle_tcode(args, {"L0": actions}, out_file, Path(args.audio_path))
        if tcode_status:
            return tcode_status
        print(f"Done: {len(actions)} actions")
        return 0
    finally:
        if converted_file and converted_file.exists():
            try:
                converted_file.unlink()
                if not any(converted_file.parent.iterdir()):
                    converted_file.parent.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(cmd(cli_args().parse_args()))
