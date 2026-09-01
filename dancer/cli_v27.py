"""PythonDancer 2.7 Quality Intelligence CLI integration."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Mapping

import numpy as np

from . import cli_v26, cli_v26_release
from .candidates import generate_candidates
from .comparison import best_section_merge
from .geometry_profile import load_geometry_profile
from .improvement import ImprovementConfig, auto_improve
from .mechanical_safety import MechanicalProjectionConfig, trajectory_mechanical_risk
from .multiaxis import analyze_multiaxis
from .quality import score_plan
from .section_intent import overrides_from_dict, overrides_to_dict


def add_cli_arguments(parser):
    group = parser.add_argument_group("quality intelligence 2.7")
    group.add_argument("--quality_score", "--quality-score", dest="quality_score", action="store_true", help="Print the 2.7 Motion Quality score and metric breakdown")
    group.add_argument("--quality_candidates", "--quality-candidates", dest="quality_candidates", type=int, default=1, metavar="N", help="Generate N ranked choreography candidates (1..8)")
    group.add_argument("--keep_base_candidate", "--keep-base-candidate", dest="keep_base_candidate", action="store_true", help="Keep the original plan instead of automatically selecting the highest-scoring candidate")
    group.add_argument("--merge_best_sections", "--merge-best-sections", dest="merge_best_sections", action="store_true", help="Build one plan from the highest-scoring candidate in each detected section")
    group.add_argument("--auto_improve", "--auto-improve", dest="auto_improve", action="store_true", help="Iteratively regenerate and replace the weakest scoring time range")
    group.add_argument("--improve_iterations", "--improve-iterations", dest="improve_iterations", type=int, default=4, metavar="N", help="Maximum Auto Improvement passes")
    group.add_argument("--improve_target", "--improve-target", dest="improve_target", type=float, default=90.0, metavar="SCORE", help="Stop Auto Improvement after reaching this score")
    group.add_argument("--improve_min_gain", "--improve-min-gain", dest="improve_min_gain", type=float, default=.35, metavar="SCORE", help="Minimum score improvement required to accept a regenerated range")
    group.add_argument("--quality_report", "--quality-report", dest="quality_report", help="Write candidate/final Quality Intelligence diagnostics to JSON")
    group.add_argument("--section_intents", "--section-intents", dest="section_intents", help="JSON file containing section-level Motion Intent overrides")
    group.add_argument("--mechanical_projection", "--mechanical-projection", dest="mechanical_projection", action="store_true", default=True, help="Project generated SR6 poses into the mechanical safe set")
    group.add_argument("--no_mechanical_projection", "--no-mechanical-projection", dest="mechanical_projection", action="store_false", help="Disable nearest-safe SR6 pose projection")
    group.add_argument("--mechanical_max_risk", "--mechanical-max-risk", dest="mechanical_max_risk", type=float, default=.82, metavar="[0-1]", help="Maximum accepted mechanical/singularity risk")
    group.add_argument("--servo_limit_deg", "--servo-limit-deg", dest="servo_limit_deg", type=float, default=88.0, metavar="DEG", help="Diagnostic SR6 servo-angle safety limit")
    group.add_argument("--singularity_sensitivity", "--singularity-sensitivity", dest="singularity_sensitivity", type=float, default=2.5, metavar="DEG/UNIT", help="Linkage sensitivity level treated as singularity risk")
    group.add_argument("--sr6_geometry", "--sr6-geometry", dest="sr6_geometry", help="SR6 geometry-profile JSON for mechanical scoring/projection")
    return parser


def _load_section_overrides(path: str | None):
    if not path:
        return ()
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        payload = payload.get("section_intents", payload.get("sections", []))
    if not isinstance(payload, list):
        raise ValueError("section intent JSON must contain a list")
    return overrides_from_dict(payload)


def _section_ranges(data, analysis, duration: float):
    beats = np.asarray(data.get("beats", []), dtype=np.float64).reshape(-1)
    result = []
    for section in analysis.sections:
        start = float(beats[section.start_beat]) if 0 <= section.start_beat < beats.size else 0.0
        if 0 <= section.end_beat < beats.size:
            end = float(beats[section.end_beat])
        else:
            end = duration
        result.append({"start": start, "end": max(start, end), "label": section.label})
    return result


def _print_quality(report):
    print(f"Quality Intelligence: {report.overall:.1f}/100")
    for name, value in sorted(report.metrics.items()):
        print(f"  {name.replace('_', ' '):24s} {value:5.1f}")
    mechanical = report.mechanical
    if mechanical:
        print(
            "  mechanical: "
            f"risk mean={float(mechanical.get('mean_risk', 0.0)):.3f} "
            f"peak={float(mechanical.get('peak_risk', 0.0)):.3f} "
            f"unsafe={float(mechanical.get('unsafe_ratio', 0.0)) * 100.0:.1f}%"
        )
    if report.weak_ranges:
        print("  weak ranges:")
        for item in report.weak_ranges[:8]:
            print(f"    {item.start:7.2f}-{item.end:7.2f}s  {item.score:5.1f}  {item.weakest_metric}")


def cmd(args):
    if not 1 <= int(getattr(args, "quality_candidates", 1)) <= 8:
        print("--quality_candidates must be between 1 and 8.")
        return 2
    if not 0.0 <= float(getattr(args, "mechanical_max_risk", .82)) <= 1.0:
        print("--mechanical_max_risk must be within 0..1.")
        return 2
    if int(getattr(args, "improve_iterations", 4)) < 1:
        print("--improve_iterations must be at least 1.")
        return 2

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
        section_intents = _load_section_overrides(getattr(inner_args, "section_intents", None))
        return replace(config, section_intents=section_intents, mechanical=mechanical, geometry=geometry)

    def plan_multiaxis(data, config):
        base = original_plan(data, config)
        duration = max((float(t) for rows in base.values() for t, _ in rows), default=0.0)
        analysis = analyze_multiaxis(data, config)
        sections = _section_ranges(data, analysis, duration)
        final = base
        candidate_results = []
        count = int(getattr(args, "quality_candidates", 1))
        if count > 1 or getattr(args, "merge_best_sections", False) or getattr(args, "auto_improve", False):
            candidate_results = generate_candidates(data, config, count=max(count, 2), geometry=config.geometry, sections=sections)
            print("Quality candidates:")
            for rank, candidate in enumerate(candidate_results, 1):
                print(f"  {rank}. {candidate.name:18s} {candidate.quality.overall:5.1f}")
            if not getattr(args, "keep_base_candidate", False):
                final = {axis: list(rows) for axis, rows in candidate_results[0].plan.items()}
        if getattr(args, "merge_best_sections", False) and candidate_results and sections:
            final, choices, section_scores = best_section_merge(candidate_results, sections, data, geometry=config.geometry)
            print("Best-section merge:")
            for index, section in enumerate(sections):
                selected = choices.get(index, 0)
                print(f"  {section['label']:12s} -> {candidate_results[selected].name} ({section_scores[index][selected]:.1f})")
            state["section_choices"] = {str(k): int(v) for k, v in choices.items()}
        if getattr(args, "auto_improve", False):
            result = auto_improve(
                data,
                final,
                config,
                config=ImprovementConfig(
                    max_iterations=int(args.improve_iterations),
                    target_score=float(args.improve_target),
                    minimum_improvement=float(args.improve_min_gain),
                    candidates=max(2, count),
                ),
                geometry=config.geometry,
                sections=sections,
            )
            final = {axis: list(rows) for axis, rows in result.plan.items()}
            print(f"Auto Improvement: {result.quality.overall:.1f} · {result.stopped_reason}")
            for step in result.history:
                print(f"  #{step.iteration} {step.start:.2f}-{step.end:.2f}s {step.candidate}: {step.before:.1f} -> {step.after:.1f}")
            state["improvement"] = result.to_dict()
        report = score_plan(final, data, sections=sections, geometry=config.geometry, mechanical_config=config.mechanical)
        state["quality"] = report.to_dict()
        state["candidates"] = [item.to_dict(include_plan=False) for item in candidate_results]
        state["section_intents"] = overrides_to_dict(config.section_intents)
        state["mechanical"] = trajectory_mechanical_risk(final, config.geometry, config.mechanical)
        if getattr(args, "quality_score", False) or count > 1 or getattr(args, "auto_improve", False) or getattr(args, "merge_best_sections", False):
            _print_quality(report)
        return final

    def export_bundle(base_path, plan, *, metadata=None, manifest=True):
        payload = dict(metadata or {})
        if state:
            payload["quality_intelligence"] = dict(state)
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
        print(f"Quality report: {target}")
    return status
