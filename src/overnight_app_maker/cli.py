from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .backlog import merge_planned_tasks
from .config import load_config
from .goals import load_goals
from .planner import plan_daily_tasks
from .runner import run_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and run autonomous daily tasks from a goals file.")
    parser.add_argument("--goals", help="Path to the goals markdown file.")
    parser.add_argument("--config", help="Path to settings YAML (defaults to config/settings.yml or example).")
    parser.add_argument("--project-root", help="Project root directory (defaults to current working directory).")
    parser.add_argument("--max-tasks", type=int, help="Maximum number of tasks to plan.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned tasks without executing them or writing backlog updates.",
    )
    parser.add_argument(
        "--no-write-backlog",
        action="store_true",
        help="Skip writing newly planned tasks to backlog/tasks.yml.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd().resolve()
    config_path = Path(args.config).resolve() if args.config else None
    goals_override = Path(args.goals).resolve() if args.goals else None

    config = load_config(project_root=project_root, config_path=config_path, goals_override=goals_override)
    if args.max_tasks is not None:
        config = replace(config, max_daily_tasks=args.max_tasks)

    goals = load_goals(config.goals_file)
    worker_instructions = ""
    if config.worker_instructions_file.exists():
        worker_instructions = config.worker_instructions_file.read_text(encoding="utf-8")

    tasks = plan_daily_tasks(
        goals,
        max_tasks=config.max_daily_tasks,
        tasks_log_path=config.tasks_log_file,
        backlog_path=config.backlog_file,
        worker_instructions=worker_instructions,
        project_root=config.project_root,
    )

    if not args.dry_run and not args.no_write_backlog:
        merge_planned_tasks(config.backlog_file, tasks)

    lines = run_tasks(
        tasks,
        config=config,
        goals=goals,
        dry_run=args.dry_run,
    )
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
