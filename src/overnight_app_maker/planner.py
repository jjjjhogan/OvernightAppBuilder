from __future__ import annotations

import re
from pathlib import Path

from .backlog import load_backlog, next_task_id, open_backlog_tasks
from .models import PlannedTask
from .tasks_log import is_recently_completed, load_tasks_log

GOAL_BULLET = re.compile(r"^\s*-\s+(.+)$")
PLANNING_SECTIONS = {
    "career",
    "personal",
    "business",
    "automation targets",
    "overnight app ideas",
}
SECTION_OUTPUT_DIRS = {
    "career": "research",
    "personal": "reports",
    "business": "research",
    "automation targets": "apps",
    "constraints": "reports",
    "overnight app ideas": "apps",
}

FALLBACK_TASKS = [
    (
        "Research one opportunity from the goals file",
        "research",
        "Review the goals file and produce a short research note on the highest-impact opportunity.",
    ),
    (
        "Draft one useful artifact that advances a stated goal",
        "reports",
        "Create a concise report that moves one stated goal forward.",
    ),
    (
        "Identify one workflow that could be automated",
        "reports",
        "Document one repetitive workflow from the goals file and outline an automation approach.",
    ),
    (
        "Design a small overnight app MVP idea",
        "apps",
        "Draft a lightweight MVP concept with scope, user story, and first implementation steps.",
    ),
    (
        "Prepare the implementation brief for the highest-impact task",
        "reports",
        "Write an implementation brief for the most valuable next task implied by the goals file.",
    ),
]


def _extract_worker_instructions_block(markdown: str) -> str:
    match = re.search(r"```(?:text)?\n([\s\S]*?)```", markdown)
    if match:
        return match.group(1).strip()
    return markdown.strip()


def build_worker_prompt(
    *,
    task: PlannedTask,
    goals: str,
    worker_instructions: str,
    project_root: Path,
) -> str:
    instructions = _extract_worker_instructions_block(worker_instructions)
    goals_excerpt = "\n".join(goals.splitlines()[:40]).strip()
    root = project_root.as_posix()
    return (
        f"{instructions}\n\n"
        f"## Assigned Task\n"
        f"- ID: {task.id}\n"
        f"- Title: {task.title}\n"
        f"- Description: {task.description}\n"
        f"- Output directory: {task.output_dir}/\n"
        f"- Project root: {root}\n\n"
        f"## Goals Context\n"
        f"{goals_excerpt}\n\n"
        f"## Completion\n"
        f"When finished, append this exact line to memory/tasks-log.md:\n"
        f"- {task.id}: {task.title}\n"
        f"Do not edit AUTONOMOUS.md or backlog/tasks.yml."
    )


def _parse_goal_bullets(goals: str) -> list[tuple[str, str]]:
    bullets: list[tuple[str, str]] = []
    current_section = "general"
    for line in goals.splitlines():
        heading = re.match(r"^##\s+(.+)$", line.strip())
        if heading:
            current_section = heading.group(1).strip().lower()
            continue
        if current_section not in PLANNING_SECTIONS:
            continue
        match = GOAL_BULLET.match(line)
        if not match:
            continue
        text = match.group(1).strip()
        if not text or text.lower().startswith("example:"):
            continue
        if text.lower().startswith("example "):
            continue
        bullets.append((current_section, text))
    return bullets


def _title_for_goal(section: str, goal_text: str) -> str:
    short_goal = goal_text if len(goal_text) <= 72 else goal_text[:69] + "..."
    if section == "overnight app ideas":
        return f"Design overnight app MVP for: {short_goal}"
    if section == "automation targets":
        return f"Automate or prototype: {short_goal}"
    if section in {"career", "business"}:
        return f"Research progress path for: {short_goal}"
    return f"Advance goal: {short_goal}"


def _description_for_goal(section: str, goal_text: str) -> str:
    output_hint = SECTION_OUTPUT_DIRS.get(section, "reports")
    return (
        f"Use the goals file to work on this {section} goal: {goal_text}. "
        f"Produce a useful artifact under {output_hint}/."
    )


def _proposal_from_goal(section: str, goal_text: str) -> tuple[str, str, str]:
    output_dir = SECTION_OUTPUT_DIRS.get(section, "reports")
    title = _title_for_goal(section, goal_text)
    description = _description_for_goal(section, goal_text)
    return title, description, output_dir


def _is_duplicate_open_task(title: str, open_tasks: list[dict]) -> bool:
    normalized = title.strip().lower()
    for task in open_tasks:
        existing = str(task.get("title", "")).strip().lower()
        if not existing:
            continue
        if normalized == existing or normalized in existing or existing in normalized:
            return True
    return False


def plan_daily_tasks(
    goals: str,
    *,
    max_tasks: int = 5,
    tasks_log_path: Path | None = None,
    backlog_path: Path | None = None,
    worker_instructions: str = "",
    project_root: Path | None = None,
) -> list[PlannedTask]:
    """Plan daily tasks from goals, recent history, and the existing backlog."""
    root = (project_root or Path.cwd()).resolve()
    tasks_log = load_tasks_log(tasks_log_path) if tasks_log_path else ""
    backlog = load_backlog(backlog_path) if backlog_path else []
    open_tasks = open_backlog_tasks(backlog)

    planned: list[PlannedTask] = []
    seen_titles: set[str] = set()

    for section, goal_text in _parse_goal_bullets(goals):
        title, description, output_dir = _proposal_from_goal(section, goal_text)
        normalized = title.strip().lower()
        if normalized in seen_titles:
            continue
        if is_recently_completed(title, tasks_log):
            continue
        if _is_duplicate_open_task(title, open_tasks):
            continue
        seen_titles.add(normalized)
        planned.append(
            PlannedTask(
                id="",
                title=title,
                description=description,
                output_dir=output_dir,
            )
        )
        if len(planned) >= max_tasks:
            break

    for title, output_dir, description in FALLBACK_TASKS:
        if len(planned) >= max_tasks:
            break
        normalized = title.strip().lower()
        if normalized in seen_titles:
            continue
        if is_recently_completed(title, tasks_log):
            continue
        if _is_duplicate_open_task(title, open_tasks):
            continue
        seen_titles.add(normalized)
        planned.append(
            PlannedTask(
                id="",
                title=title,
                description=description,
                output_dir=output_dir,
            )
        )

    next_id_number = next_task_id(backlog)
    finalized: list[PlannedTask] = []
    current_number = int(next_id_number.split("-")[1])
    for task in planned[:max_tasks]:
        task_id = f"TASK-{current_number:03d}"
        current_number += 1
        worker_prompt = ""
        if worker_instructions:
            worker_prompt = build_worker_prompt(
                task=PlannedTask(
                    id=task_id,
                    title=task.title,
                    description=task.description,
                    output_dir=task.output_dir,
                ),
                goals=goals,
                worker_instructions=worker_instructions,
                project_root=root,
            )
        finalized.append(
            PlannedTask(
                id=task_id,
                title=task.title,
                description=task.description,
                output_dir=task.output_dir,
                worker_prompt=worker_prompt,
            )
        )

    return finalized
