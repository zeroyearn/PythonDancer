import json
import time
from types import SimpleNamespace

import numpy as np

from dancer.batch_queue import BatchJob, BatchQueue
from dancer.cli_v30 import add_cli_arguments
from dancer.control_surface import ControlMapping, LinkClock
from dancer.copilot import compile_instruction
from dancer.device_feedback import DeviceDynamicsProfile, TelemetrySample, estimate_feedback, simulate_dynamic_load
from dancer.device_twin import DeviceTwinProfile
from dancer.motion_grammar import MotionPrimitive, MotionProgram, blend_motion_program, compile_motion_program
from dancer.motion_pack import MotionPack, MotionPackManifest, load_motion_pack, save_motion_pack
from dancer.plugin_api import PluginDescriptor, PluginRegistry
from dancer.preferences import PreferenceEvent, PreferenceModel
from dancer.project import PROJECT_SCHEMA, ProjectDocument
from dancer.quality import QualityReport
from dancer.reference_retrieval import ReferenceSection, ReferenceSectionIndex
from dancer.util import cli_args
from dancer.versioning import ProjectVersionGraph


AXES = ("L0", "L1", "L2", "R0", "R1", "R2")


def simple_plan():
    return {
        "L0": [(0.0, 25.0), (1.0, 75.0), (2.0, 25.0)],
        "L1": [(0.0, 50.0), (2.0, 62.0)],
        "L2": [(0.0, 50.0), (2.0, 44.0)],
        "R0": [(0.0, 45.0), (1.0, 68.0), (2.0, 45.0)],
        "R1": [(0.0, 50.0), (2.0, 56.0)],
        "R2": [(0.0, 50.0), (2.0, 47.0)],
    }


def report(overall, rhythm, safety):
    metrics = {
        "rhythm_alignment": rhythm,
        "phrase_alignment": 80.0,
        "smoothness": 80.0,
        "axis_diversity": 80.0,
        "cross_axis_coherence": 80.0,
        "repetition": 80.0,
        "mechanical_safety": safety,
        "jerk_comfort": 80.0,
        "stem_responsiveness": 80.0,
    }
    return QualityReport(overall, metrics)


def test_motion_grammar_is_deterministic_bounded_and_zero_blend_is_identity():
    program = MotionProgram((MotionPrimitive("wave", 0.0, 2.0, amount=.8, cycles=2.0),), sample_hz=12.0)
    first = compile_motion_program(program)
    second = compile_motion_program(program)
    assert first == second
    assert set(first) == set(AXES)
    assert all(0.0 <= value <= 100.0 for rows in first.values() for _, value in rows)

    base = simple_plan()
    identity = blend_motion_program(base, MotionProgram(program.primitives, blend=0.0, sample_hz=20.0), duration=2.0)
    # Identity is numerical at the sampled output surface.
    assert identity["L0"][0][1] == 25.0
    assert identity["L0"][-1][1] == 25.0


def test_copilot_compiles_chinese_section_style_lock_density_and_primitive():
    sections = [
        SimpleNamespace(start=0.0, end=8.0, label="verse"),
        SimpleNamespace(start=8.0, end=16.0, label="chorus"),
    ]
    plan = compile_instruction("副歌更激进一点，锁住 L0，R1 少一点，加 wave", sections=sections, duration=16.0)
    assert "L0" in plan.axis_locks
    assert plan.axis_density["R1"] < 1.0
    assert any(item.kind == "wave" and item.start == 8.0 and item.end == 16.0 for item in plan.motion_program.primitives)
    assert any(item.action == "style" and item.target == "aggressive" and item.start == 8.0 for item in plan.operations)


def test_preference_learning_changes_existing_quality_weights_and_round_trips():
    model = PreferenceModel()
    before = dict(model.quality_weights)
    selected = report(91.0, 96.0, 94.0)
    rejected = report(82.0, 65.0, 70.0)
    model.record_reports("A", selected, "B", rejected, section="drop")
    assert model.observations == 1
    assert model.quality_weights != before
    restored = PreferenceModel.from_dict(model.to_dict())
    assert restored.observations == 1
    assert restored.personalized_score(selected) > restored.personalized_score(rejected)


def test_preference_event_can_update_style_traits():
    model = PreferenceModel()
    model.update(PreferenceEvent(
        "A", "B",
        {"rotation": .9, "flow": .8, "complexity": .7},
        {"rotation": .2, "flow": .3, "complexity": .4},
    ))
    assert model.trait_weights["rotation"] > model.trait_weights["symmetry"]


def test_reference_retrieval_ranks_closest_section():
    index = ReferenceSectionIndex([
        ReferenceSection("fast-drop", "drop", {"bpm": 140, "energy": .95, "bass": .9, "duration": 8, "rotation": .8}),
        ReferenceSection("slow-verse", "verse", {"bpm": 82, "energy": .35, "bass": .25, "duration": 16, "rotation": .2}),
    ])
    matches = index.query({"bpm": 138, "energy": .9, "bass": .88, "duration": 8, "rotation": .75}, top_k=2)
    assert matches[0].reference.identifier == "fast-drop"
    assert matches[0].similarity >= matches[1].similarity


def test_plugin_registry_registers_and_invokes_without_core_coupling():
    registry = PluginRegistry()
    registry.register(PluginDescriptor("double", "planner", "1.0"), lambda value: value * 2)
    assert registry.invoke("planner", "double", 7) == 14
    assert registry.descriptors("planner")[0].name == "double"


def test_control_mapping_and_link_fallback_are_bounded():
    mapping = ControlMapping("midi", "cc1", "energy", .5, 1.5)
    assert mapping.map_value(0) == .5
    assert mapping.map_value(127) == 1.5
    clock = LinkClock(128.0)
    clock.start()
    time.sleep(.005)
    state = clock.snapshot()
    assert 0.0 <= state.beat_phase < 1.0
    assert state.bpm == 128.0
    clock.stop()


def test_feedback_calibration_device_twin_v2_and_dynamic_load_are_finite():
    samples = []
    for index in range(30):
        command = 30.0 + index * 1.2
        samples.append(TelemetrySample(
            timestamp=index * .05,
            commanded={axis: command for axis in AXES},
            actual={axis: command * .96 + 1.8 for axis in AXES},
        ))
    feedback = estimate_feedback(samples)
    assert feedback.enabled is True
    assert feedback.samples == 30
    assert all(np.isfinite(value) for value in feedback.rms_error.values())

    twin = DeviceTwinProfile(feedback=feedback, dynamics=DeviceDynamicsProfile(velocity_derate=.9))
    restored = DeviceTwinProfile.from_dict(twin.to_dict())
    assert restored.to_dict()["version"] == "2.0"
    assert restored.feedback.enabled is True
    output, diagnostics = restored.output_plan(simple_plan())
    assert set(output) == set(AXES)
    assert "dynamic_load" in diagnostics
    load = simulate_dynamic_load(simple_plan(), restored.dynamics)
    assert np.isfinite(load.peak_temperature_c)
    assert load.peak_load >= 0.0


def test_project_schema_5_defaults_intelligence_and_preserves_old_state_shape():
    assert PROJECT_SCHEMA == 5
    project = ProjectDocument(intelligence={"version": "3.0", "motion_program": {"version": "1.0"}})
    payload = project.to_dict()
    assert payload["schema"] == 5
    restored = ProjectDocument.from_dict(payload)
    assert restored.intelligence["version"] == "3.0"


def test_project_version_graph_commit_branch_checkout_and_section_merge():
    graph = ProjectVersionGraph()
    first = graph.commit(simple_plan(), "base")
    graph.create_branch("aggressive", from_snapshot=first.identifier)
    changed = simple_plan()
    changed["R0"] = [(0.0, 10.0), (1.0, 90.0), (2.0, 10.0)]
    second = graph.commit(changed, "strong rotation")
    assert graph.checkout(second.identifier)["R0"][1][1] == 90.0
    history = graph.history("aggressive")
    assert [item.message for item in history][:2] == ["strong rotation", "base"]
    merged = graph.merge_sections(first.identifier, second.identifier, [SimpleNamespace(start=0.0, end=2.0, label="drop")])
    assert merged["R0"] != simple_plan()["R0"]


def test_motion_pack_round_trip(tmp_path):
    program = MotionProgram((MotionPrimitive("spiral", 0.0, 2.0),), name="spiral-pack")
    pack = MotionPack(
        MotionPackManifest("Test Pack", version="3.0"),
        motion_programs={"spiral": program.to_dict()},
        preference_profiles={"personal": PreferenceModel().to_dict()},
    )
    path = save_motion_pack(tmp_path / "test.pdmotion", pack)
    restored = load_motion_pack(path)
    assert restored.manifest.name == "Test Pack"
    assert "spiral" in restored.motion_programs


def test_batch_queue_core_handles_success_and_failure():
    queue = BatchQueue([
        BatchJob("a", "a.mp3"),
        BatchJob("b", "b.mp3"),
    ], workers=2)

    def worker(job):
        if job.identifier == "b":
            raise RuntimeError("expected failure")
        return job.identifier

    results = queue.run(worker)
    by_id = {item.identifier: item for item in results}
    assert by_id["a"].success is True
    assert by_id["b"].success is False
    assert "expected failure" in by_id["b"].error


def test_cli_parser_exposes_full_intelligence_surface():
    parser = add_cli_arguments(cli_args())
    args = parser.parse_args([
        "song.mp3", "--cli", "--multiaxis",
        "--copilot", "drop wave",
        "--motion-program", "program.json",
        "--preference-profile", "prefs.json",
        "--reference-index", "index.json",
        "--telemetry-log", "telemetry.json",
        "--discover-plugins",
        "--batch-workers", "3",
    ])
    assert args.copilot_instruction == "drop wave"
    assert args.motion_program == "program.json"
    assert args.preference_profile == "prefs.json"
    assert args.reference_index == "index.json"
    assert args.telemetry_log == "telemetry.json"
    assert args.discover_plugins is True
    assert args.batch_workers == 3


def test_3_0_release_modules_import():
    import dancer.cli_v30  # noqa: F401
    import dancer.copilot  # noqa: F401
    import dancer.motion_grammar  # noqa: F401
    import dancer.preferences  # noqa: F401
    import dancer.reference_retrieval  # noqa: F401
    import dancer.device_feedback  # noqa: F401
    import dancer.plugin_api  # noqa: F401
    import dancer.control_surface  # noqa: F401
    import dancer.versioning  # noqa: F401
    import dancer.motion_pack  # noqa: F401
    import dancer.workstation_ui_v30  # noqa: F401
