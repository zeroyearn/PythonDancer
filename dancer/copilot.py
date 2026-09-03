"""Natural-language choreography intent compiler for PythonDancer 3.0.

This module intentionally compiles text into deterministic DAW operations and
Motion Grammar primitives. The text parser never writes raw device commands or
bypasses the normal optimizer / Device Twin safety chain.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Mapping, Sequence

import numpy as np

from .automation import AutomationPoint, AutomationSet, StyleKeyframe, StyleMorphTimeline
from .intent import MotionIntent
from .motion_grammar import MotionPrimitive, MotionProgram
from .multiaxis import AXIS_ORDER


STYLE_INTENTS = {
    "smooth": MotionIntent(intensity=.52, aggression=.20, flow=.90, complexity=.38, symmetry=.76, rotation_bias=.55, translation_bias=.48, accent_density=.28),
    "expressive": MotionIntent(intensity=.76, aggression=.46, flow=.78, complexity=.68, symmetry=.50, rotation_bias=.72, translation_bias=.62, accent_density=.58),
    "aggressive": MotionIntent(intensity=.92, aggression=.92, flow=.30, complexity=.72, symmetry=.30, rotation_bias=.62, translation_bias=.86, accent_density=.94),
    "rotation": MotionIntent(intensity=.70, aggression=.48, flow=.72, complexity=.70, symmetry=.42, rotation_bias=.96, translation_bias=.26, accent_density=.58),
    "minimal": MotionIntent(intensity=.34, aggression=.18, flow=.74, complexity=.18, symmetry=.82, rotation_bias=.36, translation_bias=.38, accent_density=.16),
}

STYLE_ALIASES = {
    "smooth": ("smooth", "smoother", "平滑", "柔和", "顺滑"),
    "expressive": ("expressive", "表现力", "丰富", "更有表现"),
    "aggressive": ("aggressive", "hard", "harder", "激进", "猛烈", "更猛", "更强烈"),
    "rotation": ("rotation", "rotational", "旋转", "转动"),
    "minimal": ("minimal", "simple", "极简", "简洁", "克制"),
}

SECTION_ALIASES = {
    "intro": ("intro", "前奏"),
    "verse": ("verse", "主歌"),
    "build": ("build", "build-up", "铺垫", "过渡"),
    "chorus": ("chorus", "副歌"),
    "drop": ("drop", "高潮", "爆发"),
    "breakdown": ("breakdown", "间奏", "缓冲"),
    "outro": ("outro", "尾奏", "结尾"),
}

PRIMITIVE_ALIASES = {
    "wave": ("wave", "波浪", "波动"),
    "spiral": ("spiral", "螺旋"),
    "orbit": ("orbit", "环绕", "绕圈"),
    "pulse": ("pulse", "脉冲", "脉动"),
    "rock": ("rock", "摇摆", "左右摇"),
    "sweep": ("sweep", "扫动", "扫过"),
    "twist": ("twist", "扭转", "旋扭"),
    "accent": ("accent", "重击", "强调", "重拍"),
    "recoil": ("recoil", "回弹", "反冲"),
    "drift": ("drift", "漂移", "缓慢移动"),
    "hold": ("hold", "保持", "停住"),
}


@dataclass(frozen=True)
class ChoreographyOperation:
    action: str
    target: str
    value: object
    start: float = 0.0
    end: float = 0.0

    def to_dict(self):
        return {"action": self.action, "target": self.target, "value": self.value, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class CopilotPlan:
    instruction: str
    operations: tuple[ChoreographyOperation, ...] = ()
    axis_locks: tuple[str, ...] = ()
    axis_density: Mapping[str, float] = field(default_factory=dict)
    motion_program: MotionProgram = field(default_factory=MotionProgram)
    summary: str = ""

    def to_dict(self):
        return {
            "version": "1.0",
            "instruction": self.instruction,
            "operations": [item.to_dict() for item in self.operations],
            "axis_locks": list(self.axis_locks),
            "axis_density": dict(self.axis_density),
            "motion_program": self.motion_program.to_dict(),
            "summary": self.summary,
        }


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_any(text: str, values: Sequence[str]) -> bool:
    return any(value.lower() in text for value in values)


def _section_ranges(sections: Sequence | None, text: str, duration: float) -> list[tuple[float, float, str]]:
    normalized = _normalized(text)
    found = []
    for index, section in enumerate(sections or ()):
        if isinstance(section, Mapping):
            start, end, label = float(section.get("start", 0.0)), float(section.get("end", duration)), str(section.get("label", f"section-{index+1}"))
        else:
            start, end, label = float(section.start), float(section.end), str(getattr(section, "label", f"section-{index+1}"))
        label_lower = label.lower()
        aliases = SECTION_ALIASES.get(label_lower, (label_lower,))
        if label_lower in normalized or _contains_any(normalized, aliases):
            found.append((start, end, label))
    if found:
        return found
    for canonical, aliases in SECTION_ALIASES.items():
        if _contains_any(normalized, aliases):
            matches = []
            for section in sections or ():
                if isinstance(section, Mapping):
                    label = str(section.get("label", "")).lower()
                    start, end = float(section.get("start", 0.0)), float(section.get("end", duration))
                else:
                    label = str(getattr(section, "label", "")).lower()
                    start, end = float(section.start), float(section.end)
                if label == canonical or label in aliases:
                    matches.append((start, end, canonical))
            if matches:
                return matches
    return [(0.0, max(duration, .1), "all")]


def _intensity_multiplier(text: str) -> float:
    value = 1.0
    if _contains_any(text, ("slightly", "a little", "一点", "稍微", "轻微")):
        value = 1.08
    if _contains_any(text, ("more", "stronger", "更强", "更多", "加强")):
        value = max(value, 1.18)
    if _contains_any(text, ("much more", "very", "明显", "大幅", "很强")):
        value = max(value, 1.32)
    if _contains_any(text, ("less", "reduce", "降低", "减少", "弱一点")):
        value = .82
    if _contains_any(text, ("much less", "minimal", "大幅降低", "少很多")):
        value = .65
    return value


def _axis_lock_requested(text: str, token: str) -> bool:
    patterns = (
        rf"\b(lock|keep|preserve)\s*{token}\b",
        rf"\b{token}\s*(lock|locked|keep|preserve)\b",
        rf"(锁住|锁定|保持|保留)\s*{token}\b",
        rf"\b{token}\s*(锁住|锁定|保持|保留)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _axis_density_request(text: str, token: str) -> float | None:
    less = r"less|reduce|lower|降低|减少|少一点|弱一点|不要太频繁|别太频繁"
    more = r"more|increase|higher|增加|加强|更频繁|多一点"
    separator = r"[^,，。;；]{0,16}"
    if re.search(rf"\b{token}\b{separator}({less})", text) or re.search(rf"({less}){separator}\b{token}\b", text):
        return .72
    if re.search(rf"\b{token}\b{separator}({more})", text) or re.search(rf"({more}){separator}\b{token}\b", text):
        return 1.25
    return None


def compile_instruction(
    instruction: str,
    *,
    sections: Sequence | None = None,
    duration: float = 0.0,
) -> CopilotPlan:
    text = _normalized(instruction)
    duration = max(float(duration), max((float(getattr(s, "end", 0.0)) if not isinstance(s, Mapping) else float(s.get("end", 0.0)) for s in sections or ()), default=0.0), .1)
    ranges = _section_ranges(sections, text, duration)
    multiplier = _intensity_multiplier(text)
    operations: list[ChoreographyOperation] = []
    primitives: list[MotionPrimitive] = []

    style_name = None
    for canonical, aliases in STYLE_ALIASES.items():
        if _contains_any(text, aliases):
            style_name = canonical
            break
    if style_name:
        for start, end, _ in ranges:
            operations.append(ChoreographyOperation("style", style_name, min(1.5, max(.25, multiplier)), start, end))

    lane_keywords = {
        "energy": ("energy", "能量", "力度", "强度"),
        "stroke_depth": ("stroke", "stroke depth", "行程", "深度"),
        "rotation_mix": ("rotation", "rotation mix", "旋转量", "转动量"),
        "gesture_density": ("density", "gesture density", "动作密度", "频繁"),
        "complexity": ("complexity", "复杂度", "复杂"),
        "smoothing": ("smoothness", "smoothing", "平滑度"),
        "safety_aggressiveness": ("safety", "safe", "安全", "保守"),
    }
    for lane, aliases in lane_keywords.items():
        if _contains_any(text, aliases):
            lane_value = multiplier
            if lane == "safety_aggressiveness" and _contains_any(text, ("safer", "more safe", "更安全", "保守")):
                lane_value = .72
            for start, end, _ in ranges:
                operations.append(ChoreographyOperation("automation", lane, lane_value, start, end))

    for kind, aliases in PRIMITIVE_ALIASES.items():
        if _contains_any(text, aliases):
            for start, end, _ in ranges:
                length = max(end - start, .1)
                cycles = max(1.0, length / 2.0)
                primitives.append(MotionPrimitive(kind, start, end, amount=min(1.6, multiplier), cycles=cycles))

    axis_locks = []
    density: dict[str, float] = {}
    for axis in AXIS_ORDER:
        token = axis.lower()
        if _axis_lock_requested(text, token):
            axis_locks.append(axis)
        requested_density = _axis_density_request(text, token)
        if requested_density is not None:
            density[axis] = requested_density

    if not operations and not primitives and not axis_locks and not density:
        start, end, _ = ranges[0]
        operations.append(ChoreographyOperation("automation", "energy", multiplier, start, end))
        operations.append(ChoreographyOperation("style", "expressive", .55, start, end))

    program = MotionProgram(tuple(primitives), blend=.45 if primitives else 0.0, name="copilot")
    parts = []
    if style_name:
        parts.append(f"style={style_name}")
    if operations:
        parts.append(f"operations={len(operations)}")
    if primitives:
        parts.append("motion=" + ",".join(item.kind for item in primitives))
    if axis_locks:
        parts.append("lock=" + ",".join(axis_locks))
    if density:
        parts.append("axis-density=" + ",".join(f"{k}:{v:.2f}" for k, v in density.items()))
    return CopilotPlan(instruction, tuple(operations), tuple(axis_locks), density, program, " · ".join(parts))


def apply_copilot_plan(
    plan: CopilotPlan,
    automation: AutomationSet | None = None,
    styles: StyleMorphTimeline | None = None,
):
    """Apply Copilot operations to editable DAW objects and return copies."""
    automation = deepcopy(automation or AutomationSet())
    styles = deepcopy(styles or StyleMorphTimeline())
    for operation in plan.operations:
        if operation.action == "automation" and operation.target in automation.lanes:
            lane = automation.lanes[operation.target]
            lane.points = [point for point in lane.points if abs(point.time - operation.start) > 1e-6 and abs(point.time - operation.end) > 1e-6]
            lane.points.extend((
                AutomationPoint(operation.start, float(operation.value), "smoothstep"),
                AutomationPoint(operation.end, float(operation.value), "smoothstep"),
            ))
            lane.points.sort(key=lambda item: item.time)
        elif operation.action == "style" and operation.target in STYLE_INTENTS:
            styles.keyframes = [item for item in styles.keyframes if abs(item.time - operation.start) > 1e-6]
            styles.keyframes.append(StyleKeyframe(
                operation.start,
                operation.target.title(),
                STYLE_INTENTS[operation.target],
                float(np.clip(operation.value, 0.0, 2.0)),
            ))
            styles.keyframes.sort(key=lambda item: item.time)
    return automation, styles
