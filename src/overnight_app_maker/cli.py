from __future__ import annotations

import argparse
from pathlib import Path

from .goals import load_goals
from .planner import plan_daily_tasks
from .runner import run_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and run autonomous daily tasks from a goals file.")
    parser.add_argument("--goals", default="goals/GOALS.example.md", help="Path to the goals markdown file.")
    parser.add_argument("--max-tasks", type=int, default=5, help="Maximum number of tasks to plan.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned tasks without executing them.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    goals_path = Path(args.goals)
    goals = load_goals(goals_path)
    tasks = plan_daily_tasks(goals, max_tasks=args.max_tasks)
    run_tasks(tasks, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
