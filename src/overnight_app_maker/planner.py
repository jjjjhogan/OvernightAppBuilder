from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedTask:
    id: str
    title: str
    description: str
    output_dir: str


def plan_daily_tasks(goals: str, max_tasks: int = 5) -> list[PlannedTask]:
    """Create starter task proposals from a goals document.

    This is intentionally simple for the scaffold. Replace this with an LLM-backed
    planner that reads user goals, constraints, and previous task history.
    """
    task_templates = [
        ("Research one opportunity from the goals file", "research"),
        ("Draft one useful artifact that advances a stated goal", "reports"),
        ("Identify one workflow that could be automated", "reports"),
        ("Design a small overnight app MVP idea", "apps"),
        ("Prepare the implementation brief for the highest-impact task", "reports"),
    ]

    planned: list[PlannedTask] = []
    goal_hint = goals.splitlines()[0] if goals else "No goals supplied"
    for index, (title, output_dir) in enumerate(task_templates[:max_tasks], start=1):
        planned.append(
            PlannedTask(
                id=f"TASK-{index:03d}",
                title=title,
                description=f"Use the goals context starting with: {goal_hint}",
                output_dir=output_dir,
            )
        )
    return planned
