"""Section-aware Candidate Composer for PythonDancer 2.8."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .candidates import CandidateResult
from .multiaxis import AXIS_ORDER
from .workspace import copy_plan, splice_plan


@dataclass(frozen=True)
class SectionAssignment:
    section_index: int
    candidate_name: str

    def to_dict(self):
        return {"section_index": int(self.section_index), "candidate_name": self.candidate_name}

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(int(payload.get("section_index", 0)), str(payload.get("candidate_name", "")))


@dataclass
class CandidateComposition:
    assignments: dict[int, str] = field(default_factory=dict)
    blend_seconds: float = .30

    def __post_init__(self):
        self.assignments = {int(index): str(name) for index, name in dict(self.assignments).items()}
        self.blend_seconds = max(0.0, float(self.blend_seconds))

    def assign(self, section_index: int, candidate_name: str):
        self.assignments[int(section_index)] = str(candidate_name)

    def clear(self, section_index: int):
        self.assignments.pop(int(section_index), None)

    def to_dict(self):
        return {
            "version": "1.0",
            "blend_seconds": self.blend_seconds,
            "assignments": [SectionAssignment(index, name).to_dict() for index, name in sorted(self.assignments.items())],
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        assignments = {
            item.section_index: item.candidate_name
            for item in (SectionAssignment.from_dict(row) for row in payload.get("assignments", []))
        }
        return cls(assignments, float(payload.get("blend_seconds", .30)))


def _section_bounds(section):
    if isinstance(section, Mapping):
        return float(section.get("start", 0.0)), float(section.get("end", 0.0)), str(section.get("label", "section"))
    return float(section.start), float(section.end), str(getattr(section, "label", "section"))


def compose_candidates(
    candidates: Sequence[CandidateResult],
    sections: Sequence,
    composition: CandidateComposition,
    *,
    base_plan=None,
    locked_axes: Sequence[str] = (),
):
    """Compose raw candidate plans section by section.

    Candidate plans remain raw editable base plans. Workspace/curve/safety effects
    are deliberately applied by the caller after composition, which avoids
    double-applying gestures or safety shaping.
    """
    if not candidates:
        raise ValueError("at least one candidate is required")
    by_name = {candidate.name: candidate for candidate in candidates}
    output = copy_plan(base_plan if base_plan is not None else candidates[0].plan)
    choices: dict[int, str] = {}
    for index, section in enumerate(sections):
        name = composition.assignments.get(index)
        if not name:
            continue
        candidate = by_name.get(name)
        if candidate is None:
            raise ValueError(f"candidate not found: {name}")
        start, end, _ = _section_bounds(section)
        if end <= start:
            continue
        output = splice_plan(
            output,
            candidate.plan,
            start,
            end,
            locked_axes=tuple(axis for axis in locked_axes if axis in AXIS_ORDER),
            blend=composition.blend_seconds,
        )
        choices[index] = name
    return output, choices


def auto_assign_by_section_scores(candidates: Sequence[CandidateResult], sections: Sequence) -> CandidateComposition:
    """Create a manual-editable composition from existing per-candidate windows.

    When exact section-window scores are not available, use the candidate's
    overall score as a deterministic fallback. The GUI can then override any
    section assignment before composing.
    """
    if not candidates:
        return CandidateComposition()
    assignments: dict[int, str] = {}
    for index, section in enumerate(sections):
        start, end, _ = _section_bounds(section)
        best = None
        best_score = float("-inf")
        for candidate in candidates:
            window_score = None
            for window in getattr(candidate.quality, "weak_ranges", ()) or ():
                if float(getattr(window, "start", -1)) <= start and float(getattr(window, "end", -1)) >= end:
                    window_score = float(getattr(window, "score", candidate.quality.overall))
                    break
            score = float(candidate.quality.overall if window_score is None else window_score)
            if best is None or score > best_score or (score == best_score and candidate.name < best.name):
                best = candidate
                best_score = score
        assignments[index] = best.name
    return CandidateComposition(assignments)
