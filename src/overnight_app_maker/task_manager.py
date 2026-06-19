from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .backlog import (
    delete_task,
    get_task,
    kanban_column,
    load_backlog,
    normalize_status,
    planned_task_from_backlog,
    update_task_fields,
    update_task_status,
)
from .backlog import merge_planned_tasks
from .config import AppConfig
from .goals import goals_view, load_goals, save_goals
from .models import PlannedTask
from .openclaw_adapter import queue_worker_prompt
from .planner import _find_latest_planning_artifact, build_worker_prompt, explain_planning_blockers, plan_daily_tasks
from .tasks_log import append_completion

DEFAULT_QUEUE_DIR = "logs/worker-queue"


def queue_dir_for_config(config: AppConfig) -> str:
    if config.output_dirs:
        return f"{config.output_dirs[-1]}/worker-queue"
    return DEFAULT_QUEUE_DIR


def queue_prompt_path(project_root: Path, task_id: str, queue_dir: str = DEFAULT_QUEUE_DIR) -> Path:
    return project_root / queue_dir / f"{task_id}.prompt.txt"


def remove_queue_prompt(project_root: Path, task_id: str, queue_dir: str = DEFAULT_QUEUE_DIR) -> bool:
    path = queue_prompt_path(project_root, task_id, queue_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


def _load_worker_instructions(path: Path) -> str:
    if not path.exists():
        return (
            "Complete the assigned task using the project goals and task brief.\n"
            "Write artifacts into the requested output folder.\n"
            "When done, append a completed task line to memory/tasks-log.md.\n"
            "Never edit AUTONOMOUS.md directly."
        )
    return path.read_text(encoding="utf-8")


def resolve_worker_prompt(
    *,
    task: PlannedTask,
    goals: str,
    worker_instructions: str,
    project_root: Path,
) -> str:
    if task.worker_prompt.strip():
        return task.worker_prompt
    artifact = _find_latest_planning_artifact(project_root) if task.phase == "build" else None
    return build_worker_prompt(
        task=task,
        goals=goals,
        worker_instructions=worker_instructions,
        project_root=project_root,
        planning_artifact=artifact,
    )


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
    queue_dir: str | None = None,
) -> list[dict[str, Any]]:
    queue_dir = queue_dir or queue_dir_for_config(config)
    views: list[dict[str, Any]] = []
    normalized_filter = normalize_status(status_filter) if status_filter else None
    for task in load_backlog(config.backlog_file):
        view = task_to_view(task, project_root=config.project_root, queue_dir=queue_dir)
        if normalized_filter and view["status"] != normalized_filter:
            continue
        views.append(view)
    return views


def show_task(
    config: AppConfig,
    task_id: str,
    *,
    queue_dir: str | None = None,
) -> dict[str, Any] | None:
    queue_dir = queue_dir or queue_dir_for_config(config)
    task = get_task(config.backlog_file, task_id)
    if not task:
        return None
    return task_to_view(task, project_root=config.project_root, queue_dir=queue_dir)


def cancel_task(
    config: AppConfig,
    task_id: str,
    *,
    remove_prompt: bool = True,
    queue_dir: str | None = None,
) -> tuple[bool, str]:
    queue_dir = queue_dir or queue_dir_for_config(config)
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
    queue_dir: str | None = None,
) -> tuple[bool, str]:
    queue_dir = queue_dir or queue_dir_for_config(config)
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
    queue_dir: str | None = None,
) -> tuple[bool, str]:
    queue_dir = queue_dir or queue_dir_for_config(config)
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


def _resolve_goals_text(config: AppConfig, goals_content: str | None = None) -> str:
    if goals_content is not None:
        save_goals(config.goals_file, goals_content)
        return goals_content.strip()
    return load_goals(config.goals_file)


def _build_prompt_for_task(
    config: AppConfig,
    task_dict: dict[str, Any],
    *,
    goals_content: str | None = None,
) -> str:
    goals = _resolve_goals_text(config, goals_content)
    planned = planned_task_from_backlog(task_dict)
    worker_instructions = _load_worker_instructions(config.worker_instructions_file)
    return resolve_worker_prompt(
        task=planned,
        goals=goals,
        worker_instructions=worker_instructions,
        project_root=config.project_root,
    )


def preview_task_prompt(
    config: AppConfig,
    task_id: str,
    *,
    goals_content: str | None = None,
) -> tuple[bool, str, str]:
    task_dict = get_task(config.backlog_file, task_id)
    if not task_dict:
        return False, f"Task {task_id} not found.", ""
    status = normalize_status(str(task_dict.get("status", "todo")))
    if status in {"done", "cancelled"}:
        return False, f"Cannot preview {task_id} with status {status}.", ""
    try:
        prompt = _build_prompt_for_task(config, task_dict, goals_content=goals_content)
    except FileNotFoundError as exc:
        return False, str(exc), ""
    return True, f"Preview ready for {task_id}.", prompt


def plan_tasks_for_board(
    config: AppConfig,
    *,
    goals_content: str | None = None,
    allow_repeat: bool = False,
) -> dict[str, Any]:
    try:
        goals = _resolve_goals_text(config, goals_content)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "added_count": 0, "planned_count": 0, "blockers": []}

    worker_instructions = _load_worker_instructions(config.worker_instructions_file)
    tasks = plan_daily_tasks(
        goals,
        max_tasks=config.max_daily_tasks,
        tasks_log_path=config.tasks_log_file,
        backlog_path=config.backlog_file,
        worker_instructions=worker_instructions,
        project_root=config.project_root,
        allow_repeat=allow_repeat,
    )
    added = merge_planned_tasks(config.backlog_file, tasks) if tasks else []
    blockers: list[str] = []
    if len(tasks) == 0:
        blockers = explain_planning_blockers(
            goals,
            tasks_log_path=config.tasks_log_file,
            backlog_path=config.backlog_file,
            project_root=config.project_root,
        )
    return {
        "ok": True,
        "planned_count": len(tasks),
        "added_count": len(added),
        "added_titles": [task.title for task in added],
        "blockers": blockers,
    }


def queue_task(
    config: AppConfig,
    task_id: str,
    *,
    goals_content: str | None = None,
) -> tuple[bool, str]:
    """Write worker prompt file and mark backlog task as queued (same as --mode queue for one task)."""
    queue_dir = queue_dir_for_config(config)
    task_dict = get_task(config.backlog_file, task_id)
    if not task_dict:
        return False, f"Task {task_id} not found."

    status = normalize_status(str(task_dict.get("status", "todo")))
    if status in {"done", "cancelled"}:
        return False, f"Cannot queue {task_id} with status {status}."

    try:
        prompt = _build_prompt_for_task(config, task_dict, goals_content=goals_content)
    except FileNotFoundError as exc:
        return False, str(exc)

    planned = planned_task_from_backlog(task_dict)
    output_path = config.project_root / planned.output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    result = queue_worker_prompt(
        task_id=task_id,
        prompt=prompt,
        project_root=config.project_root,
        queue_dir=queue_dir,
    )
    update_task_fields(
        config.backlog_file,
        task_id,
        status="queued",
        worker_prompt=prompt,
        output_dir=planned.output_dir,
    )
    rel_path = queue_prompt_path(config.project_root, task_id, queue_dir).relative_to(config.project_root).as_posix()
    saved_note = " Goals saved." if goals_content is not None else ""
    return True, f"Queued {task_id}. Prompt written to {rel_path}.{saved_note} ({result.detail})"


def update_task_details(
    config: AppConfig,
    task_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
) -> tuple[bool, str]:
    if not get_task(config.backlog_file, task_id):
        return False, f"Task {task_id} not found."
    fields: dict[str, Any] = {}
    if title is not None and title.strip():
        fields["title"] = title.strip()
    if description is not None:
        fields["description"] = description.strip()
    if not fields:
        return False, "No fields to update."
    update_task_fields(config.backlog_file, task_id, **fields)
    return True, f"Updated {task_id}."


def read_goals(config: AppConfig) -> dict[str, Any]:
    data = goals_view(config.goals_file, config.project_root)
    return {
        "path": data["path"],
        "absolute_path": str(config.goals_file.resolve()),
        "content": data["content"],
        "exists": data["exists"] == "true",
    }


def write_goals(config: AppConfig, content: str) -> tuple[bool, str]:
    save_goals(config.goals_file, content)
    rel = config.goals_file.relative_to(config.project_root).as_posix()
    return True, f"Saved goals to {rel}."


def read_prompt_text(
    config: AppConfig,
    task_id: str,
    *,
    queue_dir: str | None = None,
) -> str | None:
    queue_dir = queue_dir or queue_dir_for_config(config)
    path = queue_prompt_path(config.project_root, task_id, queue_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def build_openclaw_commands(
    config: AppConfig,
    task_id: str,
    *,
    queue_dir: str | None = None,
) -> dict[str, str] | None:
    queue_dir = queue_dir or queue_dir_for_config(config)
    prompt_path = queue_prompt_path(config.project_root, task_id, queue_dir)
    rel_prompt = prompt_path.relative_to(config.project_root).as_posix()
    session_key = f"overnight-{task_id.lower()}"
    agent = config.openclaw_agent_id

    prompt_text = ""
    if prompt_path.exists():
        prompt_text = prompt_path.read_text(encoding="utf-8")
    else:
        task = get_task(config.backlog_file, task_id)
        if task:
            prompt_text = str(task.get("worker_prompt", "")).strip()

    if prompt_path.exists():
        bash = (
            f'openclaw agent --agent {agent} --session-key {session_key} '
            f'--message "$(cat {rel_prompt})"'
        )
        ps_path = rel_prompt.replace("/", "\\") if rel_prompt else rel_prompt
        powershell = (
            f'openclaw agent --agent {agent} --session-key {session_key} '
            f'--message "$(Get-Content {ps_path} -Raw)"'
        )
        return {
            "bash": bash,
            "powershell": powershell,
            "session_key": session_key,
            "prompt_path": rel_prompt,
            "prompt_text": prompt_text,
        }

    if not prompt_text:
        task = get_task(config.backlog_file, task_id)
        if not task:
            return None
        return {
            "bash": "",
            "powershell": "",
            "session_key": session_key,
            "prompt_path": "",
            "prompt_text": "",
            "error": f"No prompt file at {rel_prompt}. Click Queue on the board first.",
        }

    return {
        "bash": "",
        "powershell": "",
        "session_key": session_key,
        "prompt_path": "",
        "prompt_text": prompt_text,
        "error": f"No prompt file at {rel_prompt}. Click Queue on the board first.",
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


def board_payload(config: AppConfig, *, queue_dir: str | None = None) -> dict[str, Any]:
    queue_dir = queue_dir or queue_dir_for_config(config)
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
    goals = read_goals(config)
    return {
        "project_root": str(config.project_root),
        "backlog_file": str(config.backlog_file.relative_to(config.project_root)),
        "goals_file": goals["path"],
        "columns": columns,
        "total": len(views),
    }


def dumps_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
