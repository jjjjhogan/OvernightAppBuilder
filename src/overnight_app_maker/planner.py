from __future__ import annotations

import re
from pathlib import Path

from .backlog import load_backlog, next_task_id, open_backlog_tasks
from .models import PlannedTask
from .tasks_log import extract_completed_summaries, is_recently_completed, load_tasks_log

GOAL_BULLET = re.compile(r"^\s*-\s+(.+)$")
PLANNING_SECTIONS = {
    "career",
    "personal",
    "business",
    "automation targets",
    "overnight app ideas",
}
BUILD_GOAL_SECTIONS = {"automation targets", "overnight app ideas"}

PLANNING_FALLBACK_TASKS = [
    (
        "Research one opportunity from the goals file",
        "research",
        "Review the goals file and produce a short research note on the highest-impact opportunity.",
    ),
    (
        "Draft one useful artifact that advances a stated goal",
        "reports",
        "Create a concise markdown report that moves one stated goal forward.",
    ),
    (
        "Identify one workflow that could be automated",
        "reports",
        "Document one repetitive workflow from the goals file and outline an automation approach.",
    ),
    (
        "Design a small overnight app MVP idea",
        "reports",
        "Draft a lightweight MVP concept with scope, user story, and first implementation steps in reports/.",
    ),
    (
        "Prepare the implementation brief for the highest-impact task",
        "reports",
        "Write an implementation brief for the most valuable next task implied by the goals file.",
    ),
]

BUILD_WEB_APP_REQUIREMENTS = """\
## Build Requirements (web app task)
- Read the referenced planning brief from reports/ or research/ before coding.
- Create a minimal presentable static web app under the output directory in its own subfolder.
- Required files: index.html plus any CSS/JS assets the demo needs.
- The app must open directly in a browser with no backend or build step required.
- Use clean layout, readable typography, and a clear demo title suitable for class presentation.
- Do not only write another markdown plan; deliver runnable HTML/CSS/JS."""


def _extract_worker_instructions_block(markdown: str) -> str:
    match = re.search(r"```(?:text)?\n([\s\S]*?)```", markdown)
    if match:
        return match.group(1).strip()
    return markdown.strip()


def _slugify(text: str, *, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "demo-app"


def _find_latest_planning_artifact(project_root: Path) -> Path | None:
    candidates: list[Path] = []
    for folder in ("reports", "research"):
        folder_path = project_root / folder
        if folder_path.is_dir():
            candidates.extend(folder_path.glob("*.md"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _has_planning_artifacts(project_root: Path) -> bool:
    return _find_latest_planning_artifact(project_root) is not None


def build_worker_prompt(
    *,
    task: PlannedTask,
    goals: str,
    worker_instructions: str,
    project_root: Path,
    planning_artifact: Path | None = None,
) -> str:
    instructions = _extract_worker_instructions_block(worker_instructions)
    goals_excerpt = "\n".join(goals.splitlines()[:40]).strip()
    root = project_root.resolve().as_posix()
    output_path = (project_root / task.output_dir).resolve().as_posix()
    tasks_log_path = (project_root / "memory" / "tasks-log.md").resolve().as_posix()

    sections = [
        instructions,
        "",
        "## Assigned Task",
        f"- ID: {task.id}",
        f"- Phase: {task.phase}",
        f"- Title: {task.title}",
        f"- Description: {task.description}",
        f"- Output directory (absolute): {output_path}/",
        f"- Project root (absolute): {root}",
    ]

    if task.phase == "build" and planning_artifact is not None:
        sections.extend(
            [
                f"- Planning brief to implement (absolute): {planning_artifact.resolve().as_posix()}",
                "",
                BUILD_WEB_APP_REQUIREMENTS,
            ]
        )

    sections.extend(
        [
            "",
            "## Goals Context",
            goals_excerpt,
            "",
            "## Completion",
            f"When finished, append this exact line to {tasks_log_path}:",
            f"- {task.id}: {task.title}",
            "Do not edit AUTONOMOUS.md or backlog/tasks.yml.",
        ]
    )
    return "\n".join(sections)


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


def _short_goal(goal_text: str) -> str:
    return goal_text if len(goal_text) <= 72 else goal_text[:69] + "..."


def _planning_proposal_from_goal(section: str, goal_text: str) -> tuple[str, str, str]:
    short_goal = _short_goal(goal_text)
    if section in BUILD_GOAL_SECTIONS:
        return (
            f"Plan and brief: {short_goal}",
            f"Write a concise implementation brief in reports/ for this {section} goal: {goal_text}.",
            "reports",
        )
    if section in {"career", "business"}:
        return (
            f"Research progress path for: {short_goal}",
            f"Use the goals file to research progress paths for: {goal_text}. Produce a useful note under research/.",
            "research",
        )
    return (
        f"Advance goal: {short_goal}",
        f"Use the goals file to work on this {section} goal: {goal_text}. Produce a useful artifact under reports/.",
        "reports",
    )


def _build_proposal_from_goal(
    section: str,
    goal_text: str,
    *,
    planning_artifact: Path,
) -> tuple[str, str, str]:
    short_goal = _short_goal(goal_text)
    app_slug = _slugify(goal_text)
    artifact_name = planning_artifact.name
    return (
        f"Build minimal web app: {short_goal}",
        (
            f"Read {artifact_name} and the goals file. Build a presentable static web app under "
            f"apps/{app_slug}/ with index.html, basic styling, and a demo that reflects the brief."
        ),
        "apps",
    )


def _build_fallback_tasks(planning_artifact: Path) -> list[tuple[str, str, str]]:
    artifact_name = planning_artifact.name
    return [
        (
            "Build minimal web app from latest planning brief",
            "apps",
            (
                f"Read {artifact_name} from the planning folder and the goals file. Build a presentable "
                "static web app under apps/ in its own subfolder with index.html and basic CSS/JS."
            ),
        ),
        (
            "Build demo UI for highest-impact overnight app idea",
            "apps",
            (
                f"Use {artifact_name} plus the goals file to implement a minimal browser demo under apps/ "
                "with index.html. Focus on a presentable UI, not another markdown plan."
            ),
        ),
    ]


def _is_duplicate_open_task(title: str, open_tasks: list[dict]) -> bool:
    normalized = title.strip().lower()
    for task in open_tasks:
        existing = str(task.get("title", "")).strip().lower()
        if not existing:
            continue
        if normalized == existing or normalized in existing or existing in normalized:
            return True
    return False


def _append_candidate(
    planned: list[PlannedTask],
    *,
    seen_titles: set[str],
    title: str,
    description: str,
    output_dir: str,
    phase: str,
    tasks_log: str,
    open_tasks: list[dict],
    allow_repeat: bool = False,
) -> bool:
    normalized = title.strip().lower()
    if normalized in seen_titles:
        return False
    if not allow_repeat and is_recently_completed(title, tasks_log):
        return False
    if _is_duplicate_open_task(title, open_tasks):
        return False
    seen_titles.add(normalized)
    planned.append(
        PlannedTask(
            id="",
            title=title,
            description=description,
            output_dir=output_dir,
            phase=phase,
        )
    )
    return True


def explain_planning_blockers(
    goals: str,
    *,
    tasks_log_path: Path | None = None,
    backlog_path: Path | None = None,
    project_root: Path | None = None,
) -> list[str]:
    """Return human-readable reasons why planning may return zero tasks."""
    root = (project_root or Path.cwd()).resolve()
    tasks_log = load_tasks_log(tasks_log_path) if tasks_log_path else ""
    backlog = load_backlog(backlog_path) if backlog_path else []
    open_tasks = open_backlog_tasks(backlog)
    goal_bullets = _parse_goal_bullets(goals)

    lines = [
        f"[info] open backlog task(s): {len(open_tasks)}",
        f"[info] completed task log line(s): {len(extract_completed_summaries(tasks_log))}",
        f"[info] goal bullet(s) eligible for planning: {len(goal_bullets)}",
    ]
    if len(goal_bullets) == 0:
        lines.append(
            "[info] No eligible goal bullets found. Add bullets under Career/Personal/Business/"
            "Automation Targets/Overnight App Ideas without an Example: prefix."
        )
    if len(open_tasks) > 0:
        lines.append("[info] Open backlog titles blocking replans:")
        for task in open_tasks[:5]:
            lines.append(f"[info]   - {task.get('id')}: {task.get('title')} ({task.get('status')})")
    if extract_completed_summaries(tasks_log):
        lines.append(
            "[info] memory/tasks-log.md blocks repeat titles. Add new goal bullets or use --allow-repeat."
        )
    if _find_latest_planning_artifact(root):
        lines.append("[info] Planning brief(s) exist in reports/ or research/ (build tasks can be scheduled).")
    else:
        lines.append("[info] No reports/*.md or research/*.md yet (build tasks wait for a planning brief).")
    return lines


def plan_daily_tasks(
    goals: str,
    *,
    max_tasks: int = 5,
    tasks_log_path: Path | None = None,
    backlog_path: Path | None = None,
    worker_instructions: str = "",
    project_root: Path | None = None,
    allow_repeat: bool = False,
) -> list[PlannedTask]:
    """Plan daily tasks: planning artifacts first, then optional web-app build tasks."""
    root = (project_root or Path.cwd()).resolve()
    tasks_log = load_tasks_log(tasks_log_path) if tasks_log_path else ""
    backlog = load_backlog(backlog_path) if backlog_path else []
    open_tasks = open_backlog_tasks(backlog)
    planning_artifact = _find_latest_planning_artifact(root)
    has_planning = planning_artifact is not None

    planning_candidates: list[PlannedTask] = []
    build_candidates: list[PlannedTask] = []
    seen_titles: set[str] = set()

    for section, goal_text in _parse_goal_bullets(goals):
        title, description, output_dir = _planning_proposal_from_goal(section, goal_text)
        _append_candidate(
            planning_candidates,
            seen_titles=seen_titles,
            title=title,
            description=description,
            output_dir=output_dir,
            phase="plan",
            tasks_log=tasks_log,
            open_tasks=open_tasks,
            allow_repeat=allow_repeat,
        )
        if has_planning and section in BUILD_GOAL_SECTIONS and planning_artifact is not None:
            build_title, build_description, build_output = _build_proposal_from_goal(
                section,
                goal_text,
                planning_artifact=planning_artifact,
            )
            _append_candidate(
                build_candidates,
                seen_titles=seen_titles,
                title=build_title,
                description=build_description,
                output_dir=build_output,
                phase="build",
                tasks_log=tasks_log,
                open_tasks=open_tasks,
                allow_repeat=allow_repeat,
            )

    for title, output_dir, description in PLANNING_FALLBACK_TASKS:
        _append_candidate(
            planning_candidates,
            seen_titles=seen_titles,
            title=title,
            description=description,
            output_dir=output_dir,
            phase="plan",
            tasks_log=tasks_log,
            open_tasks=open_tasks,
            allow_repeat=allow_repeat,
        )

    if has_planning and planning_artifact is not None:
        for title, output_dir, description in _build_fallback_tasks(planning_artifact):
            _append_candidate(
                build_candidates,
                seen_titles=seen_titles,
                title=title,
                description=description,
                output_dir=output_dir,
                phase="build",
                tasks_log=tasks_log,
                open_tasks=open_tasks,
                allow_repeat=allow_repeat,
            )

    # Reserve at least one build slot when planning artifacts exist and max_tasks > 1.
    build_slots = 0
    if has_planning and max_tasks > 1 and build_candidates:
        build_slots = min(len(build_candidates), max(1, max_tasks // 2))
    plan_slots = max_tasks - build_slots

    planned = planning_candidates[:plan_slots] + build_candidates[:build_slots]
    if len(planned) < max_tasks:
        remaining = max_tasks - len(planned)
        planned.extend(planning_candidates[plan_slots : plan_slots + remaining])

    next_id_number = next_task_id(backlog)
    finalized: list[PlannedTask] = []
    current_number = int(next_id_number.split("-")[1])
    for task in planned[:max_tasks]:
        task_id = f"TASK-{current_number:03d}"
        current_number += 1
        artifact = planning_artifact if task.phase == "build" else None
        worker_prompt = ""
        if worker_instructions:
            worker_prompt = build_worker_prompt(
                task=PlannedTask(
                    id=task_id,
                    title=task.title,
                    description=task.description,
                    output_dir=task.output_dir,
                    phase=task.phase,
                ),
                goals=goals,
                worker_instructions=worker_instructions,
                project_root=root,
                planning_artifact=artifact,
            )
        finalized.append(
            PlannedTask(
                id=task_id,
                title=task.title,
                description=task.description,
                output_dir=task.output_dir,
                worker_prompt=worker_prompt,
                phase=task.phase,
            )
        )

    return finalized
