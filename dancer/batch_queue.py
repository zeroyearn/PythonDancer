"""Threaded batch generation/render queue for PythonDancer 3.0."""
from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class BatchJob:
    identifier: str
    media_path: str
    output_path: str = ""
    options: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self):
        return {
            "identifier": self.identifier,
            "media_path": self.media_path,
            "output_path": self.output_path,
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, payload: Mapping):
        return cls(
            identifier=str(payload.get("identifier", payload.get("media_path", "job"))),
            media_path=str(payload.get("media_path", "")),
            output_path=str(payload.get("output_path", "")),
            options=dict(payload.get("options") or {}),
        )


@dataclass(frozen=True)
class BatchResult:
    identifier: str
    success: bool
    output: object = None
    error: str = ""

    def to_dict(self):
        return {"identifier": self.identifier, "success": self.success, "output": self.output, "error": self.error}


class BatchQueue:
    def __init__(self, jobs: Sequence[BatchJob] = (), *, workers: int = 2):
        self.jobs = list(jobs)
        self.workers = max(1, min(int(workers), 16))
        self.results: list[BatchResult] = []
        self.cancelled = False

    def add(self, job: BatchJob):
        self.jobs.append(job)

    def cancel(self):
        self.cancelled = True

    def run(self, worker: Callable[[BatchJob], object], *, on_result: Callable[[BatchResult], None] | None = None):
        self.results = []
        self.cancelled = False
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="pythondancer-batch") as executor:
            futures = {executor.submit(worker, job): job for job in self.jobs}
            for future in as_completed(futures):
                job = futures[future]
                if self.cancelled:
                    for pending in futures:
                        pending.cancel()
                    break
                try:
                    output = future.result()
                    result = BatchResult(job.identifier, True, output)
                except Exception as exc:
                    result = BatchResult(job.identifier, False, None, str(exc))
                self.results.append(result)
                if on_result:
                    on_result(result)
        return tuple(self.results)

    def to_dict(self):
        return {
            "version": "1.0",
            "workers": self.workers,
            "jobs": [job.to_dict() for job in self.jobs],
            "results": [result.to_dict() for result in self.results],
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None):
        payload = payload or {}
        queue = cls([BatchJob.from_dict(item) for item in payload.get("jobs", ())], workers=int(payload.get("workers", 2)))
        return queue


def load_batch_manifest(path: str | Path) -> BatchQueue:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("batch manifest must contain a JSON object")
    return BatchQueue.from_dict(payload)
