"""Lightweight choreography version control for .pdance projects."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Mapping

from .multiaxis import AXIS_ORDER


def _canonical_plan(plan):
    return {
        axis: [[round(float(t), 6), round(float(p), 5)] for t, p in plan.get(axis, ())]
        for axis in AXIS_ORDER
    }


def _snapshot_id(plan, metadata) -> str:
    payload = json.dumps({"plan": _canonical_plan(plan), "metadata": metadata}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class VersionSnapshot:
    identifier: str
    parent: str | None
    branch: str
    message: str
    created_at: str
    plan: Mapping[str, list]
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self):
        return {
            "identifier": self.identifier,
            "parent": self.parent,
            "branch": self.branch,
            "message": self.message,
            "created_at": self.created_at,
            "plan": deepcopy(dict(self.plan)),
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            identifier=str(payload.get("identifier", "")),
            parent=payload.get("parent"),
            branch=str(payload.get("branch", "main")),
            message=str(payload.get("message", "")),
            created_at=str(payload.get("created_at", "")),
            plan=deepcopy(payload.get("plan") or {}),
            metadata=deepcopy(payload.get("metadata") or {}),
        )


@dataclass
class ProjectVersionGraph:
    snapshots: dict[str, VersionSnapshot] = field(default_factory=dict)
    branches: dict[str, str] = field(default_factory=dict)
    current_branch: str = "main"

    def commit(self, plan, message: str, *, metadata: Mapping | None = None, branch: str | None = None) -> VersionSnapshot:
        branch = branch or self.current_branch
        parent = self.branches.get(branch)
        meta = deepcopy(dict(metadata or {}))
        identifier = _snapshot_id(plan, {"parent": parent, "branch": branch, "message": message, **meta})
        snapshot = VersionSnapshot(
            identifier=identifier,
            parent=parent,
            branch=branch,
            message=str(message),
            created_at=datetime.now(timezone.utc).isoformat(),
            plan=_canonical_plan(plan),
            metadata=meta,
        )
        self.snapshots[identifier] = snapshot
        self.branches[branch] = identifier
        self.current_branch = branch
        return snapshot

    def create_branch(self, name: str, *, from_snapshot: str | None = None):
        name = str(name).strip()
        if not name:
            raise ValueError("branch name is required")
        if from_snapshot is None:
            from_snapshot = self.branches.get(self.current_branch)
        if from_snapshot is not None and from_snapshot not in self.snapshots:
            raise KeyError(f"snapshot not found: {from_snapshot}")
        self.branches[name] = from_snapshot or ""
        self.current_branch = name

    def checkout(self, ref: str):
        identifier = self.branches.get(ref, ref)
        if not identifier or identifier not in self.snapshots:
            raise KeyError(f"version not found: {ref}")
        snapshot = self.snapshots[identifier]
        if ref in self.branches:
            self.current_branch = ref
        return {
            axis: [(float(t), float(p)) for t, p in snapshot.plan.get(axis, ())]
            for axis in AXIS_ORDER
        }

    def history(self, ref: str | None = None) -> tuple[VersionSnapshot, ...]:
        identifier = self.branches.get(ref or self.current_branch, ref or "")
        result = []
        seen = set()
        while identifier and identifier in self.snapshots and identifier not in seen:
            seen.add(identifier)
            snapshot = self.snapshots[identifier]
            result.append(snapshot)
            identifier = snapshot.parent
        return tuple(result)

    def merge_sections(self, base_ref: str, incoming_ref: str, sections, *, selected_indices=()):
        base = self.checkout(base_ref)
        incoming = self.checkout(incoming_ref)
        selected = set(int(index) for index in selected_indices)
        if not selected:
            selected = set(range(len(sections)))
        from .workspace import splice_plan
        merged = base
        for index, section in enumerate(sections):
            if index not in selected:
                continue
            if isinstance(section, Mapping):
                start, end = float(section.get("start", 0.0)), float(section.get("end", 0.0))
            else:
                start, end = float(section.start), float(section.end)
            if end > start:
                merged = splice_plan(merged, incoming, start, end, blend=.30)
        return merged

    def to_dict(self):
        return {
            "version": "1.0",
            "current_branch": self.current_branch,
            "branches": dict(self.branches),
            "snapshots": [item.to_dict() for item in self.snapshots.values()],
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        snapshots = [VersionSnapshot.from_dict(item) for item in payload.get("snapshots", ())]
        return cls(
            snapshots={item.identifier: item for item in snapshots},
            branches={str(k): str(v) for k, v in dict(payload.get("branches") or {}).items()},
            current_branch=str(payload.get("current_branch", "main")),
        )
