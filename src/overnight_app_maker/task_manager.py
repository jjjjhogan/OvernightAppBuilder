from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .backlog import (
    archive_tasks_with_status,
    delete_task,
    get_task,
    is_board_visible,
    kanban_column,
    load_backlog,
    merge_planned_tasks,
    normalize_status,
    open_backlog_tasks,
    planned_task_from_backlog,
    update_task_fields,
    update_task_status,
)
from .config import AppConfig
from .goals import goals_view, load_goals, save_goals
from .models import PlannedTask
from .openclaw_adapter import queue_worker_prompt
from .planner import (
    _find_latest_planning_artifact,
    build_worker_prompt,
    diagnose_goals,
    explain_planning_blockers,
    plan_daily_tasks,
)
from .tasks_log import append_completion, extract_completed_summaries, load_tasks_log, remove_completion

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


def _artifact_exists(project_root: Path, output_dir: str) -> bool:
    if not output_dir:
        return False
    base = project_root / output_dir
    if not base.exists():
        return False
    for pattern in ("*.md", "*.html", "index.html"):
        if list(base.glob(pattern)):
            return True
    return any(base.iterdir()) if base.is_dir() else False


def _build_ready(project_root: Path, task: dict[str, Any]) -> bool:
    phase = str(task.get("phase", "")).lower()
    if phase != "build":
        return True
    artifact = _find_latest_planning_artifact(project_root)
    return artifact is not None


def task_to_view(task: dict[str, Any], *, project_root: Path, queue_dir: str = DEFAULT_QUEUE_DIR) -> dict[str, Any]:
    task_id = str(task.get("id", ""))
    status = normalize_status(str(task.get("status", "todo")))
    prompt_path = queue_prompt_path(project_root, task_id, queue_dir)
    output_dir = str(task.get("output_dir", ""))
    return {
        "id": task_id,
        "title": str(task.get("title", "")),
        "description": str(task.get("description", task.get("title", ""))),
        "status": status,
        "column": kanban_column(status),
        "owner": str(task.get("owner", "main")),
        "artifact": str(task.get("artifact", output_dir)),
        "output_dir": output_dir,
        "phase": str(task.get("phase", "")),
        "created_at": str(task.get("created_at", "")),
        "prompt_path": str(prompt_path.relative_to(project_root).as_posix()) if prompt_path.exists() else "",
        "has_prompt": prompt_path.exists(),
        "has_artifact": _artifact_exists(project_root, output_dir),
        "build_ready": _build_ready(project_root, task),
    }


def list_task_views(
    config: AppConfig,
    *,
    status_filter: str | None = None,
    queue_dir: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    queue_dir = queue_dir or queue_dir_for_config(config)
    views: list[dict[str, Any]] = []
    normalized_filter = normalize_status(status_filter) if status_filter else None
    for task in load_backlog(config.backlog_file):
        if not include_archived and not is_board_visible(task):
            continue
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


def uncomplete_task(
    config: AppConfig,
    task_id: str,
) -> tuple[bool, str]:
    task = get_task(config.backlog_file, task_id)
    if not task:
        return False, f"Task {task_id} not found."
    status = normalize_status(str(task.get("status", "todo")))
    if status != "done":
        return False, f"Cannot uncomplete {task_id} with status {status}."
    remove_completion(config.tasks_log_file, task_id)
    update_task_status(config.backlog_file, task_id, "todo")
    return True, f"Moved {task_id} back to todo and removed tasks-log entry."


def archive_done_tasks(config: AppConfig) -> tuple[int, str]:
    count = archive_tasks_with_status(config.backlog_file, {"done"})
    return count, f"Archived {count} done task(s)."


def archive_cancelled_tasks(config: AppConfig) -> tuple[int, str]:
    count = archive_tasks_with_status(config.backlog_file, {"cancelled"})
    return count, f"Archived {count} cancelled task(s)."


def fresh_lab_session(config: AppConfig) -> dict[str, Any]:
    done_count = archive_tasks_with_status(config.backlog_file, {"done"})
    cancelled_count = archive_tasks_with_status(config.backlog_file, {"cancelled"})
    return {
        "ok": True,
        "archived_done": done_count,
        "archived_cancelled": cancelled_count,
        "detail": (
            f"Fresh lab session: archived {done_count} done and {cancelled_count} cancelled task(s). "
            "Enable Allow repeat if you want to replan similar titles from memory/tasks-log.md."
        ),
    }


def read_tasks_log_for_board(config: AppConfig) -> dict[str, Any]:
    path = config.tasks_log_file
    content = load_tasks_log(path) if path.exists() else ""
    return {
        "path": path.relative_to(config.project_root).as_posix() if path.exists() else str(path.name),
        "content": content,
        "exists": path.exists(),
        "completed_count": len(extract_completed_summaries(content)),
    }


def _plan_tasks_internal(
    config: AppConfig,
    *,
    goals_content: str | None = None,
    allow_repeat: bool = False,
    goals_only: bool = False,
) -> tuple[str, list[PlannedTask], dict[str, Any]]:
    goals = _resolve_goals_text(config, goals_content)
    goals_diagnosis = diagnose_goals(goals)
    worker_instructions = _load_worker_instructions(config.worker_instructions_file)
    tasks = plan_daily_tasks(
        goals,
        max_tasks=config.max_daily_tasks,
        tasks_log_path=config.tasks_log_file,
        backlog_path=config.backlog_file,
        worker_instructions=worker_instructions,
        project_root=config.project_root,
        allow_repeat=allow_repeat,
        goals_only=goals_only,
    )
    return goals, tasks, goals_diagnosis


def preview_plan_tasks(
    config: AppConfig,
    *,
    goals_content: str | None = None,
    allow_repeat: bool = False,
    goals_only: bool = False,
) -> dict[str, Any]:
    try:
        _goals, tasks, goals_diagnosis = _plan_tasks_internal(
            config,
            goals_content=goals_content,
            allow_repeat=allow_repeat,
            goals_only=goals_only,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "candidates": []}

    candidates = [
        {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "phase": task.phase,
            "output_dir": task.output_dir,
        }
        for task in tasks
    ]
    blockers: list[str] = []
    if not candidates:
        blockers = explain_planning_blockers(
            _goals,
            tasks_log_path=config.tasks_log_file,
            backlog_path=config.backlog_file,
            project_root=config.project_root,
        )
        if goals_only:
            blockers.append("[info] Goals-only mode skips generic fallback tasks.")
        elif not allow_repeat:
            blockers.append(
                "[info] Try Allow repeat or Goals only to change what gets planned."
            )

    return {
        "ok": True,
        "candidates": candidates,
        "planned_count": len(candidates),
        "blockers": blockers,
        "goals_diagnosis": goals_diagnosis,
        "allow_repeat": allow_repeat,
        "goals_only": goals_only,
    }


def confirm_plan_tasks(
    config: AppConfig,
    *,
    goals_content: str | None = None,
    allow_repeat: bool = False,
    goals_only: bool = False,
    selected_titles: list[str] | None = None,
) -> dict[str, Any]:
    try:
        goals, tasks, goals_diagnosis = _plan_tasks_internal(
            config,
            goals_content=goals_content,
            allow_repeat=allow_repeat,
            goals_only=goals_only,
        )
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "added_count": 0, "planned_count": 0, "blockers": []}

    title_set = set(selected_titles) if selected_titles is not None else None
    added = merge_planned_tasks(config.backlog_file, tasks, selected_titles=title_set) if tasks else []
    blockers: list[str] = []
    if len(tasks) == 0:
        blockers = explain_planning_blockers(
            goals,
            tasks_log_path=config.tasks_log_file,
            backlog_path=config.backlog_file,
            project_root=config.project_root,
        )
    elif len(added) == 0:
        blockers = [
            "[info] Selected tasks were not added — open backlog items with the same title may already exist.",
        ]

    return {
        "ok": True,
        "planned_count": len(tasks),
        "added_count": len(added),
        "added_titles": [task.title for task in added],
        "blockers": blockers,
        "goals_diagnosis": goals_diagnosis,
        "allow_repeat": allow_repeat,
        "goals_only": goals_only,
    }


def export_diagnose_json(
    config: AppConfig,
    *,
    goals_content: str | None = None,
) -> dict[str, Any]:
    diagnosis = diagnose_planning_readiness(config, goals_content=goals_content)
    diagnosis["project_root"] = str(config.project_root)
    diagnosis["backlog_file"] = str(config.backlog_file.relative_to(config.project_root))
    diagnosis["tasks_log"] = read_tasks_log_for_board(config)
    return diagnosis


def plan_tasks_for_board(
    config: AppConfig,
    *,
    goals_content: str | None = None,
    allow_repeat: bool = False,
    goals_only: bool = False,
) -> dict[str, Any]:
    return confirm_plan_tasks(
        config,
        goals_content=goals_content,
        allow_repeat=allow_repeat,
        goals_only=goals_only,
        selected_titles=None,
    )


def diagnose_planning_readiness(
    config: AppConfig,
    *,
    goals_content: str | None = None,
) -> dict[str, Any]:
    try:
        goals = goals_content if goals_content is not None else load_goals(config.goals_file)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}

    goals_diagnosis = diagnose_goals(goals)
    backlog = load_backlog(config.backlog_file)
    open_tasks = open_backlog_tasks(backlog)
    tasks_log = load_tasks_log(config.tasks_log_file) if config.tasks_log_file.exists() else ""
    completed_count = len(extract_completed_summaries(tasks_log))

    open_preview = [
        {
            "id": str(task.get("id", "")),
            "title": str(task.get("title", "")),
            "status": normalize_status(str(task.get("status", "todo"))),
        }
        for task in open_tasks[:8]
    ]

    recommendations: list[str] = list(goals_diagnosis.get("hints", []))
    if goals_diagnosis["eligible_count"] == 0:
        recommendations.append(
            "Without eligible goal bullets, planning only uses generic fallback tasks — "
            "and those may already be done or still open in your backlog."
        )
    if open_tasks:
        recommendations.append(
            f"You have {len(open_tasks)} open backlog task(s). Finish, cancel, or delete them "
            "if you want fresh plans from new goals."
        )
    if completed_count > 0:
        recommendations.append(
            f"memory/tasks-log.md has {completed_count} completed title(s). "
            "Enable Allow repeat to plan similar tasks again."
        )

    return {
        "ok": True,
        "goals_diagnosis": goals_diagnosis,
        "open_backlog_count": len(open_tasks),
        "open_backlog_preview": open_preview,
        "completed_log_count": completed_count,
        "recommendations": recommendations,
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


def board_payload(
    config: AppConfig,
    *,
    queue_dir: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    queue_dir = queue_dir or queue_dir_for_config(config)
    views = list_task_views(config, queue_dir=queue_dir, include_archived=include_archived)
    columns: dict[str, list[dict[str, Any]]] = {
        "todo": [],
        "queued": [],
        "in_progress": [],
        "done": [],
        "failed": [],
        "cancelled": [],
        "archived": [],
    }
    for view in views:
        column = view["column"]
        if column not in columns:
            column = "todo"
        columns[column].append(view)
    goals = read_goals(config)
    all_tasks = load_backlog(config.backlog_file)
    archived_count = sum(
        1 for task in all_tasks if normalize_status(str(task.get("status", "todo"))) == "archived"
    )
    return {
        "project_root": str(config.project_root),
        "backlog_file": str(config.backlog_file.relative_to(config.project_root)),
        "goals_file": goals["path"],
        "columns": columns,
        "total": len(views),
        "archived_count": archived_count,
        "include_archived": include_archived,
        "tasks_log_path": read_tasks_log_for_board(config)["path"],
    }


def dumps_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
