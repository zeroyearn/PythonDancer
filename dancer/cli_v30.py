"""PythonDancer 3.0 Intelligent Choreography CLI integration."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping

from . import candidates as candidates_module
from . import cli_v26, cli_v28
from .batch_queue import load_batch_manifest
from .control_surface import ControlState, LinkClock, MidiControlBridge, OSCControlBridge, mappings_from_dict
from .copilot import compile_instruction
from .device_feedback import TelemetrySample, estimate_feedback
from .device_twin import DeviceTwinProfile, load_device_twin, save_device_twin
from .intelligence_runtime import IntelligenceState, apply_intelligence
from .motion_grammar import MotionProgram
from .motion_pack import MotionPack, MotionPackManifest, load_motion_pack, save_motion_pack
from .multiaxis import analyze_multiaxis
from .plugin_api import GLOBAL_PLUGINS
from .preferences import PreferenceModel, load_preference_model, save_preference_model
from .reference_retrieval import load_reference_index
from .versioning import ProjectVersionGraph


def add_cli_arguments(parser):
    parser = cli_v28.add_cli_arguments(parser)
    group = parser.add_argument_group("Intelligent choreography 3.0")
    group.add_argument("--copilot", dest="copilot_instruction", help="Natural-language choreography edit")
    group.add_argument("--copilot-file", dest="copilot_file", help="UTF-8 text file containing a Copilot instruction")
    group.add_argument("--motion-program", dest="motion_program", help="Motion Grammar JSON program")
    group.add_argument("--motion-blend", dest="motion_blend", type=float, help="Override Motion Grammar blend 0..1")
    group.add_argument("--preference-profile", dest="preference_profile", help="Personal PreferenceModel JSON")
    group.add_argument("--save-preference-profile", dest="save_preference_profile", help="Write the active PreferenceModel JSON")
    group.add_argument("--reference-index", dest="reference_index", help="ReferenceSectionIndex JSON")
    group.add_argument("--reference-query", dest="reference_query", help="JSON object/file with section retrieval features")
    group.add_argument("--reference-top-k", dest="reference_top_k", type=int, default=5)
    group.add_argument("--reference-amount", dest="reference_amount", type=float, default=.35)
    group.add_argument("--motion-pack", dest="motion_pack", help="Load .pdmotion pack")
    group.add_argument("--motion-program-name", dest="motion_program_name", help="Motion program asset in --motion-pack")
    group.add_argument("--preference-name", dest="preference_name", help="Preference profile asset in --motion-pack")
    group.add_argument("--device-twin-name", dest="device_twin_name", help="Device Twin asset in --motion-pack")
    group.add_argument("--export-motion-pack", dest="export_motion_pack", help="Export active 3.0 assets as .pdmotion")
    group.add_argument("--telemetry-log", dest="telemetry_log", help="JSON telemetry samples for adaptive Device Twin calibration")
    group.add_argument("--write-adaptive-twin", dest="write_adaptive_twin", help="Write feedback-calibrated Device Twin JSON")
    group.add_argument("--control-map", dest="control_map", help="MIDI/OSC control mappings JSON")
    group.add_argument("--midi-input", dest="midi_input", help="Enable MIDI input; optional port name")
    group.add_argument("--osc-port", dest="osc_port", type=int, help="Enable OSC UDP input on this port")
    group.add_argument("--ableton-link", dest="ableton_link", action="store_true", help="Follow Link-style BPM/beat phase in Live mode")
    group.add_argument("--discover-plugins", dest="discover_plugins", action="store_true", help="Discover pythondancer.plugins entry points")
    group.add_argument("--version-graph-out", dest="version_graph_out", help="Write exported choreography into ProjectVersionGraph JSON")
    group.add_argument("--version-message", dest="version_message", default="CLI render")
    group.add_argument("--batch-manifest", dest="batch_manifest", help="Run a BatchQueue JSON manifest")
    group.add_argument("--batch-workers", dest="batch_workers", type=int, default=2)
    return parser


def _read_json_object(value: str | None):
    if not value:
        return {}
    path = Path(value).expanduser()
    text = path.read_text(encoding="utf-8") if path.exists() else value
    payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("expected a JSON object")
    return payload


def _load_motion_program(path: str | None):
    if not path:
        return MotionProgram()
    return MotionProgram.from_dict(_read_json_object(path))


def _load_telemetry(path: str | None):
    if not path:
        return []
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        payload = payload.get("samples", ())
    return [TelemetrySample.from_dict(item) for item in payload]


def _reference_plan(args):
    if not args.reference_index or not args.reference_query:
        return None, ()
    index = load_reference_index(args.reference_index)
    query = _read_json_object(args.reference_query)
    matches = index.query(query, top_k=max(1, int(args.reference_top_k)))
    if not matches:
        return None, ()
    payload = matches[0].reference.payload
    plan = payload.get("plan") if isinstance(payload, Mapping) else None
    if not isinstance(plan, Mapping):
        return None, matches
    parsed = {
        axis: [(float(item[0]), float(item[1])) for item in plan.get(axis, ())]
        for axis in ("L0", "L1", "L2", "R0", "R1", "R2")
    }
    return parsed, matches


def _prepare_pack(args, state: IntelligenceState, preference: PreferenceModel, twin: DeviceTwinProfile):
    if not args.motion_pack:
        return state, preference, twin
    pack = load_motion_pack(args.motion_pack)
    if args.motion_program_name:
        state.motion_program = MotionProgram.from_dict(pack.asset("motion_programs", args.motion_program_name))
    if args.preference_name:
        preference = PreferenceModel.from_dict(pack.asset("preference_profiles", args.preference_name))
    if args.device_twin_name:
        twin = DeviceTwinProfile.from_dict(pack.asset("device_twins", args.device_twin_name))
    return state, preference, twin


def _prepare_controls(args):
    mappings = mappings_from_dict(_read_json_object(args.control_map)) if args.control_map else ()
    shared = ControlState(bpm=float(args.live_bpm))
    resources = []

    def on_change(target, value):
        if target == "bpm":
            shared.bpm = max(20.0, min(400.0, float(value)))
        else:
            shared.update(target, value)

    midi = None
    if args.midi_input is not None:
        midi = MidiControlBridge(mappings, input_name=args.midi_input or None, on_change=on_change).open()
        resources.append(midi)
    if args.osc_port:
        osc = OSCControlBridge(mappings, port=args.osc_port, on_change=on_change).start()
        resources.append(osc)
    link = None
    if args.ableton_link:
        link = LinkClock(shared.bpm).connect()
        link.start()
        resources.append(link)

    def provider():
        if link is not None:
            state = link.snapshot()
            if midi is not None and "bpm" in midi.state.values:
                state.bpm = midi.state.values["bpm"]
            return state
        return shared

    return provider if resources else None, resources


def _close_controls(resources):
    for resource in reversed(resources):
        try:
            if hasattr(resource, "stop"):
                resource.stop()
            if hasattr(resource, "close"):
                resource.close()
        except Exception:
            pass


def _run_single(args):
    if args.discover_plugins:
        GLOBAL_PLUGINS.discover()
        print(f"Plugins: {len(GLOBAL_PLUGINS.descriptors())} loaded; {len(GLOBAL_PLUGINS.errors)} error(s)")

    instruction = str(args.copilot_instruction or "")
    if args.copilot_file:
        instruction = Path(args.copilot_file).expanduser().read_text(encoding="utf-8").strip()
    state = IntelligenceState(copilot_instruction=instruction, motion_program=_load_motion_program(args.motion_program))
    if args.motion_blend is not None:
        state.motion_program = replace(state.motion_program, blend=max(0.0, min(1.0, float(args.motion_blend))))
    preference = load_preference_model(args.preference_profile) if args.preference_profile else PreferenceModel()
    twin = load_device_twin(args.device_twin) if getattr(args, "device_twin", None) else DeviceTwinProfile()
    state, preference, twin = _prepare_pack(args, state, preference, twin)

    reference_plan, matches = _reference_plan(args)
    if matches:
        print("Reference Retrieval:")
        for match in matches:
            print(f"  {match.similarity:.3f}  {match.reference.identifier}  {match.reference.label}")
    state.reference_plan = reference_plan
    state.reference_amount = max(0.0, min(1.0, float(args.reference_amount))) if reference_plan else 0.0

    if args.telemetry_log:
        feedback = estimate_feedback(_load_telemetry(args.telemetry_log))
        twin = replace(twin, feedback=feedback)
        print(f"Adaptive Device Twin: samples={feedback.samples} latency={feedback.latency_ms:.1f} ms")
        if args.write_adaptive_twin:
            save_device_twin(args.write_adaptive_twin, twin)

    temporary_twin = None
    if twin.to_dict() != DeviceTwinProfile().to_dict() or getattr(args, "device_twin", None):
        handle = tempfile.NamedTemporaryFile(prefix="pythondancer-twin-", suffix=".json", delete=False)
        handle.close()
        temporary_twin = Path(handle.name)
        save_device_twin(temporary_twin, twin)
        args.device_twin = str(temporary_twin)

    original_plan = cli_v26.legacy.plan_multiaxis
    original_candidate_plan = candidates_module.plan_multiaxis
    original_generate = cli_v28.generate_candidates
    original_score = cli_v28.score_plan
    original_export = cli_v26.legacy.export_funscript_bundle
    original_live_session = cli_v28.LiveSession
    control_provider, controls = _prepare_controls(args)

    def intelligent_plan(data, config):
        base = original_plan(data, config)
        duration = max((float(t) for rows in base.values() for t, _ in rows), default=0.0)
        analysis = analyze_multiaxis(data, config)
        sections = cli_v28._section_ranges(data, analysis, duration)
        if state.copilot_instruction:
            state.copilot_plan = compile_instruction(state.copilot_instruction, sections=sections, duration=duration)
        return apply_intelligence(base, state)

    def generate_with_preferences(*a, **kw):
        kw.setdefault("weights", preference.as_quality_weights())
        return original_generate(*a, **kw)

    def score_with_preferences(*a, **kw):
        kw.setdefault("weights", preference.as_quality_weights())
        return original_score(*a, **kw)

    version_graph = ProjectVersionGraph()

    def versioned_export(base_path, plan, *, metadata=None, manifest=True):
        if args.version_graph_out:
            snapshot = version_graph.commit(plan, args.version_message, metadata={"source": str(getattr(args, "audio_path", ""))})
            Path(args.version_graph_out).expanduser().write_text(json.dumps(version_graph.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Version snapshot: {snapshot.identifier}")
        return original_export(base_path, plan, metadata=metadata, manifest=manifest)

    def live_session(*a, **kw):
        if control_provider is not None:
            kw["control_state"] = control_provider
        return original_live_session(*a, **kw)

    cli_v26.legacy.plan_multiaxis = intelligent_plan
    candidates_module.plan_multiaxis = intelligent_plan
    cli_v28.generate_candidates = generate_with_preferences
    cli_v28.score_plan = score_with_preferences
    cli_v26.legacy.export_funscript_bundle = versioned_export
    cli_v28.LiveSession = live_session
    try:
        status = cli_v28.cmd(args)
    finally:
        cli_v26.legacy.plan_multiaxis = original_plan
        candidates_module.plan_multiaxis = original_candidate_plan
        cli_v28.generate_candidates = original_generate
        cli_v28.score_plan = original_score
        cli_v26.legacy.export_funscript_bundle = original_export
        cli_v28.LiveSession = original_live_session
        _close_controls(controls)
        if temporary_twin is not None:
            try:
                temporary_twin.unlink()
            except OSError:
                pass

    if args.save_preference_profile:
        save_preference_model(args.save_preference_profile, preference)
    if args.export_motion_pack:
        pack = MotionPack(
            MotionPackManifest("PythonDancer 3.0 session", version="3.0"),
            motion_programs={state.motion_program.name: state.motion_program.to_dict()} if state.motion_program.primitives else {},
            device_twins={twin.name: twin.to_dict()},
            preference_profiles={"personal": preference.to_dict()},
        )
        save_motion_pack(args.export_motion_pack, pack)
    return status


def _job_cli_arguments(job):
    """Convert one batch job into a fresh Python process command.

    Process isolation is intentional: the 3.0 CLI temporarily wraps validated
    2.8 module functions while a render is active. Running multiple jobs in the
    same interpreter would make those wrappers race with each other.
    """
    command = [sys.executable, "-m", "dancer", job.media_path, "--cli", "--multiaxis", "--yes"]
    if job.output_path:
        command.extend(["--out_path", job.output_path])
    for key, value in dict(job.options or {}).items():
        flag = "--" + str(key).replace("_", "-")
        if isinstance(value, bool):
            if value:
                command.append(flag)
        elif value is not None:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            command.extend([flag, str(value)])
    return command


def _run_batch(args):
    queue = load_batch_manifest(args.batch_manifest)
    queue.workers = max(1, int(args.batch_workers))

    def worker(job):
        run = subprocess.run(_job_cli_arguments(job), capture_output=True, text=True)
        if run.returncode:
            detail = (run.stderr or run.stdout or "batch job failed").strip()
            raise RuntimeError(detail[-1200:])
        return job.output_path or job.media_path

    results = queue.run(worker, on_result=lambda item: print(f"Batch {item.identifier}: {'ok' if item.success else item.error}"))
    return 0 if results and all(item.success for item in results) else (0 if not results else 2)


def cmd(args):
    if getattr(args, "batch_manifest", None):
        return _run_batch(args)
    return _run_single(args)
