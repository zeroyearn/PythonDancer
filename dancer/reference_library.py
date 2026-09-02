"""Multi-reference motion style learning for PythonDancer 2.6."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .style import ChoreographyProfile, learn_profile_from_bundle

PROFILE_VECTOR_FIELDS = (
    ("axis", "L1"), ("axis", "L2"), ("axis", "R0"), ("axis", "R1"), ("axis", "R2"),
    ("gesture", "pulse"), ("gesture", "sway"), ("gesture", "rock"), ("gesture", "circle"),
    ("gesture", "spiral"), ("gesture", "wave"), ("gesture", "accent"),
    ("coupling", "sway_roll"), ("coupling", "surge_pitch"), ("coupling", "stroke_twist"),
)


def profile_vector(profile: ChoreographyProfile) -> np.ndarray:
    values: list[float] = []
    for kind, name in PROFILE_VECTOR_FIELDS:
        if kind == "axis":
            values.append(profile.axis_multiplier(name))
        elif kind == "gesture":
            values.append(profile.gesture_multiplier(name))
        else:
            values.append(profile.coupling_multiplier(name))
    values.extend((profile.reactive_mix, profile.smoothing, profile.stem_influence))
    return np.asarray(values, dtype=np.float64)


def blend_profiles(
    profiles: Sequence[ChoreographyProfile],
    weights: Sequence[float] | None = None,
    *,
    name: str = "reference-blend",
) -> ChoreographyProfile:
    if not profiles:
        raise ValueError("at least one choreography profile is required")
    if weights is None:
        weights = [1.0] * len(profiles)
    if len(weights) != len(profiles):
        raise ValueError("weights must match profiles")
    weight = np.asarray(weights, dtype=np.float64)
    if np.any(~np.isfinite(weight)) or np.any(weight < 0) or float(np.sum(weight)) <= 0:
        raise ValueError("profile weights must be finite, non-negative, and have positive sum")
    weight /= float(np.sum(weight))

    def average(getter):
        return float(sum(float(w) * float(getter(profile)) for w, profile in zip(weight, profiles)))

    axes = ("L1", "L2", "R0", "R1", "R2")
    gestures = ("pulse", "sway", "rock", "circle", "spiral", "wave", "accent")
    couplings = ("sway_roll", "surge_pitch", "stroke_twist", "stroke_bass_l1")
    sections = ("intro", "verse", "build", "chorus", "drop", "breakdown", "outro")
    return ChoreographyProfile(
        name=name,
        axis_scale={axis: average(lambda profile, axis=axis: profile.axis_multiplier(axis)) for axis in axes},
        gesture_gain={gesture: average(lambda profile, gesture=gesture: profile.gesture_multiplier(gesture)) for gesture in gestures},
        section_gain={section: average(lambda profile, section=section: profile.section_multiplier(section)) for section in sections},
        coupling_gain={key: average(lambda profile, key=key: profile.coupling_multiplier(key)) for key in couplings},
        reactive_mix=average(lambda profile: profile.reactive_mix),
        smoothing=average(lambda profile: profile.smoothing),
        stem_influence=average(lambda profile: profile.stem_influence),
        metadata={
            "learner": "PythonDancer multi-reference style v2",
            "sources": [dict(profile.metadata).get("source_bundle", profile.name) for profile in profiles],
            "weights": [float(value) for value in weight],
        },
    )


def learn_profile_from_bundles(
    bundles: Iterable[str | Path],
    *,
    weights: Sequence[float] | None = None,
    name: str = "learned-library",
) -> ChoreographyProfile:
    bundle_list = [Path(value) for value in bundles]
    if not bundle_list:
        raise ValueError("reference bundle list is empty")
    profiles = [learn_profile_from_bundle(path, name=f"reference:{path.stem}") for path in bundle_list]
    return blend_profiles(profiles, weights, name=name)


@dataclass(frozen=True)
class StyleCluster:
    name: str
    member_indices: tuple[int, ...]
    centroid: tuple[float, ...]
    profile: ChoreographyProfile

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "member_indices": list(self.member_indices),
            "centroid": list(self.centroid),
            "profile": self.profile.to_dict(),
        }


def _cluster_label(profile: ChoreographyProfile) -> str:
    vector = {
        "Smooth Flow": profile.gesture_multiplier("wave") + profile.gesture_multiplier("circle") + (1.0 - profile.reactive_mix),
        "Rhythm Heavy": profile.gesture_multiplier("pulse") + profile.gesture_multiplier("accent") + profile.reactive_mix,
        "Rotation Heavy": profile.axis_multiplier("R0") + profile.axis_multiplier("R1") + profile.axis_multiplier("R2"),
        "Translation Heavy": profile.axis_multiplier("L1") + profile.axis_multiplier("L2"),
    }
    return max(vector, key=vector.get)


def cluster_profiles(profiles: Sequence[ChoreographyProfile], clusters: int = 3, *, iterations: int = 20) -> tuple[StyleCluster, ...]:
    if not profiles:
        return ()
    k = max(1, min(int(clusters), len(profiles)))
    matrix = np.vstack([profile_vector(profile) for profile in profiles])
    # Deterministic farthest-point initialization avoids an RNG dependency.
    centers = [0]
    while len(centers) < k:
        distance = np.min(np.stack([np.sum((matrix - matrix[index]) ** 2, axis=1) for index in centers]), axis=0)
        centers.append(int(np.argmax(distance)))
    centroid = matrix[centers].copy()
    labels = np.zeros(len(profiles), dtype=np.int64)
    for _ in range(max(1, int(iterations))):
        distances = np.stack([np.sum((matrix - center) ** 2, axis=1) for center in centroid], axis=1)
        new_labels = np.argmin(distances, axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            break
        labels = new_labels
        for index in range(k):
            members = matrix[labels == index]
            if members.size:
                centroid[index] = np.mean(members, axis=0)

    result: list[StyleCluster] = []
    used_names: dict[str, int] = {}
    for index in range(k):
        members = np.flatnonzero(labels == index)
        member_profiles = [profiles[int(item)] for item in members]
        if not member_profiles:
            continue
        profile = blend_profiles(member_profiles, name=f"cluster-{index + 1}")
        base = _cluster_label(profile)
        used_names[base] = used_names.get(base, 0) + 1
        label = base if used_names[base] == 1 else f"{base} {used_names[base]}"
        result.append(StyleCluster(label, tuple(int(item) for item in members), tuple(float(value) for value in centroid[index]), profile))
    return tuple(result)
