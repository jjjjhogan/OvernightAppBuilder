from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedTask:
    id: str
    title: str
    description: str
    output_dir: str
    worker_prompt: str = ""
