from __future__ import annotations

from pathlib import Path

from .backlog import update_task_status
from .config import AppConfig
from .openclaw_adapter import openclaw_available, queue_worker_prompt, spawn_worker
from .models import PlannedTask
from .planner import build_worker_prompt
from .tasks_log import append_completion


def _ensure_output_dirs(project_root: Path, output_dirs: tuple[str, ...]) -> None:
    for name in output_dirs:
        (project_root / name).mkdir(parents=True, exist_ok=True)


def _load_worker_instructions(path: Path) -> str:
    if not path.exists():
        return (
            "Complete the assigned task using the project goals and task brief.\n"
            "Write artifacts into the requested output folder.\n"
            "When done, append a completed task line to memory/tasks-log.md.\n"
            "Never edit AUTONOMOUS.md directly."
        )
    return path.read_text(encoding="utf-8")


def _resolve_worker_prompt(
    *,
    task: PlannedTask,
    goals: str,
    worker_instructions: str,
    project_root: Path,
) -> str:
    if task.worker_prompt.strip():
        return task.worker_prompt
    return build_worker_prompt(
        task=task,
        goals=goals,
        worker_instructions=worker_instructions,
        project_root=project_root,
    )


def run_tasks(
    tasks: list[PlannedTask],
    *,
    config: AppConfig,
    goals: str,
    dry_run: bool = False,
) -> list[str]:
    """Execute or queue planned tasks and return human-readable status lines."""
    if dry_run:
        return [f"[dry-run] {task.id}: {task.title} -> {task.output_dir}/" for task in tasks]

    _ensure_output_dirs(config.project_root, config.output_dirs)
    worker_instructions = _load_worker_instructions(config.worker_instructions_file)
    execution_mode = config.execution_mode if config.execution_mode in {"openclaw", "queue"} else "openclaw"
    if execution_mode == "openclaw" and not openclaw_available():
        execution_mode = "queue"

    status_lines: list[str] = []
    for task in tasks:
        prompt = _resolve_worker_prompt(
            task=task,
            goals=goals,
            worker_instructions=worker_instructions,
            project_root=config.project_root,
        )
        output_path = config.project_root / task.output_dir
        output_path.mkdir(parents=True, exist_ok=True)

        update_task_status(config.backlog_file, task.id, "queued")
        status_lines.append(f"[queued] {task.id}: {task.title} -> {task.output_dir}/")

        if execution_mode == "queue" or not openclaw_available():
            result = queue_worker_prompt(
                task_id=task.id,
                prompt=prompt,
                project_root=config.project_root,
                queue_dir=config.output_dirs[-1] + "/worker-queue",
            )
            status_lines.append(f"[{result.status}] {task.id}: {result.detail}")
            continue

        update_task_status(config.backlog_file, task.id, "running")
        status_lines.append(f"[running] {task.id}: {task.title}")

        result = spawn_worker(
            task_id=task.id,
            prompt=prompt,
            project_root=config.project_root,
            agent_id=config.openclaw_agent_id,
            timeout_seconds=config.openclaw_timeout_seconds,
            use_local=config.openclaw_use_local,
        )

        if result.status == "completed":
            update_task_status(config.backlog_file, task.id, "done")
            append_completion(config.tasks_log_file, task.id, task.title)
            status_lines.append(f"[completed] {task.id}: {result.detail}")
        else:
            update_task_status(config.backlog_file, task.id, "failed")
            status_lines.append(f"[{result.status}] {task.id}: {result.detail}")

    return status_lines
