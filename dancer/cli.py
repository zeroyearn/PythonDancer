from __future__ import annotations

from pathlib import Path

from .libfun import autoval, create_actions, dump_csv, dump_funscript, load_audio_data, render_heatmap
from .motion import MotionConfig
from .multiaxis import MultiAxisConfig, AXIS_ORDER, bundle_paths, export_funscript_bundle, plan_multiaxis
from .util import cli_args, ffmpeg_check, ffmpeg_conv


def _multiaxis_existing_outputs(base_path: Path, include_manifest: bool) -> list[Path]:
    paths = bundle_paths(base_path)
    candidates = list(paths.values())
    if include_manifest:
        candidates.append(paths["L0"].with_suffix(".motion.json"))
    return [path for path in candidates if path.exists()]


def cmd(args):
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
    if args.axis_strength < 0:
        print("--axis_strength must be non-negative.")
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
            print(f"Creating six-axis motion ({args.multiaxis_preset})...")
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
            plan = plan_multiaxis(
                data,
                MultiAxisConfig(motion=motion, preset=args.multiaxis_preset, strength=float(args.axis_strength)),
            )
            if not plan["L0"]:
                print("No actions could be generated from this input.")
                return 2

            written = export_funscript_bundle(
                out_file,
                plan,
                metadata={
                    "notes": (
                        f"planner=multiaxis; preset={args.multiaxis_preset}; "
                        f"subdivision={args.subdivision}; axis_strength={args.axis_strength}"
                    ),
                },
                manifest=not args.no_manifest,
            )
            print("Wrote multi-axis bundle:")
            for axis in AXIS_ORDER:
                print(f"  {axis}: {written[axis]} ({len(plan[axis])} actions)")
            if "manifest" in written:
                print(f"  manifest: {written['manifest']}")

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
