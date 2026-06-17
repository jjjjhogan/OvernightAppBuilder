from __future__ import annotations

from .planner import PlannedTask


def run_tasks(tasks: list[PlannedTask], dry_run: bool = False) -> None:
    for task in tasks:
        if dry_run:
            print(f"[dry-run] {task.id}: {task.title} -> {task.output_dir}")
            continue

        print(f"[queued] {task.id}: {task.title}")
        print("Execution adapter not implemented yet. Wire this to OpenClaw sessions_spawn/sessions_send.")
