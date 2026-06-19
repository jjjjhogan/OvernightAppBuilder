from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from .backlog import (
    delete_task,
    get_task,
    kanban_column,
    load_backlog,
    normalize_status,
    update_task_status,
)
from .config import AppConfig
from .tasks_log import append_completion

DEFAULT_QUEUE_DIR = "logs/worker-queue"


def queue_prompt_path(project_root: Path, task_id: str, queue_dir: str = DEFAULT_QUEUE_DIR) -> Path:
    return project_root / queue_dir / f"{task_id}.prompt.txt"


def remove_queue_prompt(project_root: Path, task_id: str, queue_dir: str = DEFAULT_QUEUE_DIR) -> bool:
    path = queue_prompt_path(project_root, task_id, queue_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def task_to_view(task: dict[str, Any], *, project_root: Path, queue_dir: str = DEFAULT_QUEUE_DIR) -> dict[str, Any]:
    task_id = str(task.get("id", ""))
    status = normalize_status(str(task.get("status", "todo")))
    prompt_path = queue_prompt_path(project_root, task_id, queue_dir)
    return {
        "id": task_id,
        "title": str(task.get("title", "")),
        "description": str(task.get("description", task.get("title", ""))),
        "status": status,
        "column": kanban_column(status),
        "owner": str(task.get("owner", "main")),
        "artifact": str(task.get("artifact", task.get("output_dir", ""))),
        "output_dir": str(task.get("output_dir", "")),
        "phase": str(task.get("phase", "")),
        "created_at": str(task.get("created_at", "")),
        "prompt_path": str(prompt_path.relative_to(project_root).as_posix()) if prompt_path.exists() else "",
        "has_prompt": prompt_path.exists(),
    }


def list_task_views(
    config: AppConfig,
    *,
    status_filter: str | None = None,
    queue_dir: str = DEFAULT_QUEUE_DIR,
) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    normalized_filter = normalize_status(status_filter) if status_filter else None
    for task in load_backlog(config.backlog_file):
        view = task_to_view(task, project_root=config.project_root, queue_dir=queue_dir)
        if normalized_filter and view["status"] != normalized_filter:
            continue
        views.append(view)
    return views


def show_task(config: AppConfig, task_id: str, *, queue_dir: str = DEFAULT_QUEUE_DIR) -> dict[str, Any] | None:
    task = get_task(config.backlog_file, task_id)
    if not task:
        return None
    return task_to_view(task, project_root=config.project_root, queue_dir=queue_dir)


def cancel_task(
    config: AppConfig,
    task_id: str,
    *,
    remove_prompt: bool = True,
    queue_dir: str = DEFAULT_QUEUE_DIR,
) -> tuple[bool, str]:
    if not get_task(config.backlog_file, task_id):
        return False, f"Task {task_id} not found."
    update_task_status(config.backlog_file, task_id, "cancelled")
    removed = False
    if remove_prompt:
        removed = remove_queue_prompt(config.project_root, task_id, queue_dir)
    detail = f"Cancelled {task_id}."
    if remove_prompt and removed:
        detail += " Removed queue prompt file."
    return True, detail


def delete_task_entry(
    config: AppConfig,
    task_id: str,
    *,
    remove_prompt: bool = True,
    queue_dir: str = DEFAULT_QUEUE_DIR,
) -> tuple[bool, str]:
    if not get_task(config.backlog_file, task_id):
        return False, f"Task {task_id} not found."
    delete_task(config.backlog_file, task_id)
    removed = False
    if remove_prompt:
        removed = remove_queue_prompt(config.project_root, task_id, queue_dir)
    detail = f"Deleted {task_id} from backlog."
    if remove_prompt and removed:
        detail += " Removed queue prompt file."
    return True, detail


def complete_task(
    config: AppConfig,
    task_id: str,
    *,
    remove_prompt: bool = False,
    queue_dir: str = DEFAULT_QUEUE_DIR,
) -> tuple[bool, str]:
    task = get_task(config.backlog_file, task_id)
    if not task:
        return False, f"Task {task_id} not found."
    title = str(task.get("title", task_id))
    update_task_status(config.backlog_file, task_id, "done")
    append_completion(config.tasks_log_file, task_id, title)
    removed = False
    if remove_prompt:
        removed = remove_queue_prompt(config.project_root, task_id, queue_dir)
    detail = f"Marked {task_id} done and appended to {config.tasks_log_file.name}."
    if remove_prompt and removed:
        detail += " Removed queue prompt file."
    return True, detail


def read_prompt_text(config: AppConfig, task_id: str, *, queue_dir: str = DEFAULT_QUEUE_DIR) -> str | None:
    path = queue_prompt_path(config.project_root, task_id, queue_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def build_openclaw_commands(
    config: AppConfig,
    task_id: str,
    *,
    queue_dir: str = DEFAULT_QUEUE_DIR,
) -> dict[str, str] | None:
    prompt = read_prompt_text(config, task_id, queue_dir=queue_dir)
    if prompt is None:
        task = get_task(config.backlog_file, task_id)
        if not task:
            return None
        worker_prompt = str(task.get("worker_prompt", "")).strip()
        if not worker_prompt:
            return None
        prompt = worker_prompt

    session_key = f"overnight-{task_id.lower()}"
    agent = config.openclaw_agent_id
    base = ["openclaw", "agent", "--agent", agent, "--session-key", session_key, "--message"]
    posix = " ".join(base + [shlex.quote(prompt)])
    powershell = (
        f'openclaw agent --agent {agent} --session-key {session_key} '
        f'--message "$(Get-Content {queue_prompt_path(config.project_root, task_id, queue_dir).as_posix()} -Raw)"'
    )
    return {
        "bash": posix,
        "powershell": powershell,
        "session_key": session_key,
        "prompt_preview": prompt[:200] + ("..." if len(prompt) > 200 else ""),
    }


def format_task_list(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "[info] No tasks match the filter."
    lines = ["ID        STATUS       PROMPT  TITLE", "--------  -----------  ------  -----"]
    for task in tasks:
        prompt_flag = "yes" if task.get("has_prompt") else "no"
        lines.append(
            f"{task['id']:<8}  {task['status']:<11}  {prompt_flag:<6}  {task['title']}"
        )
    return "\n".join(lines)


def format_task_detail(task: dict[str, Any]) -> str:
    lines = [
        f"ID:          {task['id']}",
        f"Title:       {task['title']}",
        f"Status:      {task['status']}",
        f"Column:      {task['column']}",
        f"Phase:       {task.get('phase') or '-'}",
        f"Artifact:    {task.get('artifact') or '-'}",
        f"Prompt file: {task.get('prompt_path') or '(none)'}",
    ]
    return "\n".join(lines)


def board_payload(config: AppConfig, *, queue_dir: str = DEFAULT_QUEUE_DIR) -> dict[str, Any]:
    views = list_task_views(config, queue_dir=queue_dir)
    columns: dict[str, list[dict[str, Any]]] = {
        "todo": [],
        "queued": [],
        "in_progress": [],
        "done": [],
        "failed": [],
        "cancelled": [],
    }
    for view in views:
        column = view["column"]
        if column not in columns:
            column = "todo"
        columns[column].append(view)
    return {
        "project_root": str(config.project_root),
        "backlog_file": str(config.backlog_file.relative_to(config.project_root)),
        "columns": columns,
        "total": len(views),
    }


def dumps_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
