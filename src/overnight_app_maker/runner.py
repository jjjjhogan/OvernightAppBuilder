from __future__ import annotations

from pathlib import Path

from .backlog import ensure_backlog_task, update_task_status
from .config import AppConfig
from .openclaw_adapter import openclaw_available, queue_worker_prompt, spawn_worker
from .models import PlannedTask
from .planner import build_worker_prompt, _find_latest_planning_artifact
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
    artifact = _find_latest_planning_artifact(project_root) if task.phase == "build" else None
    return build_worker_prompt(
        task=task,
        goals=goals,
        worker_instructions=worker_instructions,
        project_root=project_root,
        planning_artifact=artifact,
    )


def resolve_execution_mode(config: AppConfig) -> tuple[str, list[str]]:
    """Return the effective execution mode and any advisory notes."""
    notes: list[str] = []
    requested = config.execution_mode.strip().lower()
    if requested not in {"openclaw", "queue"}:
        notes.append(
            f"[info] Unknown execution mode '{config.execution_mode}'; using openclaw when available, otherwise queue."
        )
        requested = "openclaw"

    if requested == "openclaw" and not openclaw_available():
        notes.append("[info] openclaw CLI not found on PATH; falling back to queue mode.")
        return "queue", notes

    if requested == "openclaw":
        notes.append("[info] execution_mode=openclaw (will call `openclaw agent` for each task).")
    else:
        notes.append(
            "[info] execution_mode=queue (writes prompts under logs/worker-queue/; does not run workers)."
        )
        notes.append(
            "[info] Queue mode is for planning/orchestration labs. Use --mode openclaw to run workers automatically."
        )

    return requested, notes


def run_tasks(
    tasks: list[PlannedTask],
    *,
    config: AppConfig,
    goals: str,
    dry_run: bool = False,
    write_backlog: bool = True,
) -> list[str]:
    """Execute or queue planned tasks and return human-readable status lines."""
    if dry_run:
        return [f"[dry-run] {task.id}: {task.title} -> {task.output_dir}/" for task in tasks]

    if not tasks:
        return [
            "[info] No new tasks to run.",
            "[info] The planner skipped everything already open or completed in backlog/tasks.yml.",
            "[info] Add new goal bullets, mark stale tasks done, or use a fresh goals file.",
        ]

    execution_mode, notes = resolve_execution_mode(config)
    status_lines = list(notes)
    _ensure_output_dirs(config.project_root, config.output_dirs)
    worker_instructions = _load_worker_instructions(config.worker_instructions_file)
    queue_dir = config.output_dirs[-1] + "/worker-queue"

    for task in tasks:
        backlog_id = task.id
        if write_backlog:
            backlog_id = ensure_backlog_task(config.backlog_file, task)

        prompt = _resolve_worker_prompt(
            task=PlannedTask(
                id=backlog_id,
                title=task.title,
                description=task.description,
                output_dir=task.output_dir,
                worker_prompt=task.worker_prompt,
                phase=task.phase,
            ),
            goals=goals,
            worker_instructions=worker_instructions,
            project_root=config.project_root,
        )
        output_path = config.project_root / task.output_dir
        output_path.mkdir(parents=True, exist_ok=True)

        if write_backlog:
            if not update_task_status(config.backlog_file, backlog_id, "queued"):
                status_lines.append(f"[warn] {backlog_id}: could not update backlog status to queued.")
        status_lines.append(f"[queued] {backlog_id}: {task.title} -> {task.output_dir}/")

        if execution_mode == "queue":
            result = queue_worker_prompt(
                task_id=backlog_id,
                prompt=prompt,
                project_root=config.project_root,
                queue_dir=queue_dir,
            )
            status_lines.append(f"[{result.status}] {backlog_id}: {result.detail}")
            continue

        if write_backlog:
            if not update_task_status(config.backlog_file, backlog_id, "running"):
                status_lines.append(f"[warn] {backlog_id}: could not update backlog status to running.")
        status_lines.append(f"[running] {backlog_id}: {task.title}")

        result = spawn_worker(
            task_id=backlog_id,
            prompt=prompt,
            project_root=config.project_root,
            agent_id=config.openclaw_agent_id,
            timeout_seconds=config.openclaw_timeout_seconds,
            use_local=config.openclaw_use_local,
            queue_dir=queue_dir,
        )

        if result.status == "completed":
            if write_backlog:
                update_task_status(config.backlog_file, backlog_id, "done")
            append_completion(config.tasks_log_file, backlog_id, task.title)
            status_lines.append(f"[completed] {backlog_id}: {result.detail}")
            continue

        if write_backlog:
            update_task_status(config.backlog_file, backlog_id, "failed")
        status_lines.append(f"[{result.status}] {backlog_id}: {result.detail}")
        fallback = queue_worker_prompt(
            task_id=backlog_id,
            prompt=prompt,
            project_root=config.project_root,
            queue_dir=queue_dir,
        )
        status_lines.append(
            f"[queued] {backlog_id}: OpenClaw failed; prompt saved to "
            f"{fallback.detail.rsplit(' ', 1)[-1]}"
        )

    return status_lines
