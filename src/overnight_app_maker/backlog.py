from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import PlannedTask

TASK_ID_PATTERN = re.compile(r"^TASK-(\d+)$", re.IGNORECASE)
OPEN_STATUSES = {"todo", "in_progress", "queued", "running"}
STATUS_ALIASES = {
    "in progress": "in_progress",
    "in-progress": "in_progress",
    "inprogress": "in_progress",
    "to do": "todo",
    "to-do": "todo",
    "done": "done",
    "complete": "done",
    "completed": "done",
    "failed": "failed",
    "error": "failed",
}


def normalize_status(status: str) -> str:
    cleaned = status.strip().lower().replace("_", " ")
    cleaned = " ".join(cleaned.split())
    return STATUS_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_backlog(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    tasks = data.get("tasks", [])
    return tasks if isinstance(tasks, list) else []


def save_backlog(path: Path, tasks: list[dict[str, Any]]) -> None:
    _ensure_parent(path)
    payload = {"tasks": tasks}
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, default_flow_style=False)


def parse_task_number(task_id: str) -> int | None:
    match = TASK_ID_PATTERN.match(task_id.strip())
    if not match:
        return None
    return int(match.group(1))


def next_task_id(tasks: list[dict[str, Any]]) -> str:
    highest = 0
    for task in tasks:
        task_id = str(task.get("id", ""))
        number = parse_task_number(task_id)
        if number is not None:
            highest = max(highest, number)
    return f"TASK-{highest + 1:03d}"


def open_backlog_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        task
        for task in tasks
        if normalize_status(str(task.get("status", "todo"))) in OPEN_STATUSES
    ]


def planned_task_from_backlog(task: dict[str, Any]) -> PlannedTask:
    return PlannedTask(
        id=str(task["id"]),
        title=str(task.get("title", "")),
        description=str(task.get("description", task.get("title", ""))),
        output_dir=str(task.get("output_dir", "reports")),
        worker_prompt=str(task.get("worker_prompt", "")),
    )


def backlog_entry_from_planned(task: PlannedTask, *, owner: str = "main") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "output_dir": task.output_dir,
        "status": "todo",
        "owner": owner,
        "artifact": f"{task.output_dir}/",
        "created_at": date.today().isoformat(),
    }
    if task.worker_prompt:
        entry["worker_prompt"] = task.worker_prompt
    return entry


def merge_planned_tasks(path: Path, planned: list[PlannedTask], *, owner: str = "main") -> list[PlannedTask]:
    existing = load_backlog(path)
    existing_ids = {str(task.get("id")) for task in existing}
    existing_titles = {str(task.get("title", "")).strip().lower() for task in existing}

    merged = list(existing)
    added: list[PlannedTask] = []
    for task in planned:
        if task.id in existing_ids:
            continue
        if task.title.strip().lower() in existing_titles:
            continue
        merged.append(backlog_entry_from_planned(task, owner=owner))
        added.append(task)

    if added:
        save_backlog(path, merged)
    return added


def ensure_backlog_task(path: Path, task: PlannedTask, *, owner: str = "main") -> str:
    """Ensure the task exists in backlog and return the id to use for updates."""
    tasks = load_backlog(path)
    normalized_title = task.title.strip().lower()

    for existing in tasks:
        if str(existing.get("id")) == task.id:
            return task.id
        if str(existing.get("title", "")).strip().lower() == normalized_title:
            return str(existing["id"])

    tasks.append(backlog_entry_from_planned(task, owner=owner))
    save_backlog(path, tasks)
    return task.id


def update_task_status(path: Path, task_id: str, status: str) -> bool:
    tasks = load_backlog(path)
    normalized_status = normalize_status(status)
    updated = False
    for task in tasks:
        if str(task.get("id")) == task_id:
            task["status"] = normalized_status
            updated = True
            break
    if updated:
        save_backlog(path, tasks)
    return updated
