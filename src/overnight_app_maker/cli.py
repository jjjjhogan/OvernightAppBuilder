from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from .backlog import merge_planned_tasks
from .board import run_board_server
from .config import load_config
from .goals import load_goals
from .planner import explain_planning_blockers, plan_daily_tasks
from .runner import run_tasks
from .task_manager import (
    archive_done_tasks,
    build_openclaw_commands,
    cancel_task,
    complete_task,
    delete_task_entry,
    diagnose_planning_readiness,
    dumps_json,
    format_task_detail,
    format_task_list,
    list_task_views,
    queue_task,
    read_goals,
    show_task,
    uncomplete_task,
    write_goals,
)


def _add_shared_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to settings YAML (defaults to config/settings.yml or example).")
    parser.add_argument("--project-root", help="Project root directory (defaults to current working directory).")


def _resolve_config(args: argparse.Namespace) -> "AppConfig":
    from .config import AppConfig

    project_root = Path(args.project_root).resolve() if args.project_root else Path.cwd().resolve()
    config_path = Path(args.config).resolve() if args.config else None
    goals_override = Path(args.goals).resolve() if getattr(args, "goals", None) else None
    return load_config(project_root=project_root, config_path=config_path, goals_override=goals_override)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan and run autonomous daily tasks from a goals file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    plan_parser = subparsers.add_parser("plan", help="Plan and run tasks from a goals file (default).")
    plan_parser.add_argument("--goals", help="Path to the goals markdown file.")
    _add_shared_config_args(plan_parser)
    plan_parser.add_argument("--max-tasks", type=int, help="Maximum number of tasks to plan.")
    plan_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned tasks without executing them or writing backlog updates.",
    )
    plan_parser.add_argument(
        "--no-write-backlog",
        action="store_true",
        help="Skip writing newly planned tasks to backlog/tasks.yml.",
    )
    plan_parser.add_argument(
        "--mode",
        choices=["queue", "openclaw"],
        help="Execution mode override (queue writes prompt files; openclaw runs workers).",
    )
    plan_parser.add_argument(
        "--allow-repeat",
        action="store_true",
        help="Allow replanning task titles already listed in memory/tasks-log.md.",
    )
    plan_parser.add_argument(
        "--goals-only",
        action="store_true",
        help="Plan only from goal bullets; skip generic fallback tasks.",
    )

    board_parser = subparsers.add_parser("board", help="Start the local Kanban board UI.")
    _add_shared_config_args(board_parser)
    board_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1).")
    board_parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765).")
    board_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser tab automatically.",
    )

    tasks_parser = subparsers.add_parser("tasks", help="Manage backlog tasks from the CLI.")
    _add_shared_config_args(tasks_parser)
    tasks_sub = tasks_parser.add_subparsers(dest="tasks_command", required=True)

    list_parser = tasks_sub.add_parser("list", help="List backlog tasks.")
    list_parser.add_argument("--status", help="Filter by status (todo, queued, done, cancelled, etc.).")

    show_parser = tasks_sub.add_parser("show", help="Show one task by id.")
    show_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")

    cancel_parser = tasks_sub.add_parser("cancel", help="Mark a task cancelled and optionally remove its prompt file.")
    cancel_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")
    cancel_parser.add_argument(
        "--keep-prompt",
        action="store_true",
        help="Keep the queued prompt file on disk.",
    )

    delete_parser = tasks_sub.add_parser("delete", help="Remove a task from the backlog.")
    delete_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")
    delete_parser.add_argument(
        "--keep-prompt",
        action="store_true",
        help="Keep the queued prompt file on disk.",
    )

    complete_parser = tasks_sub.add_parser("complete", help="Mark a task done and append memory/tasks-log.md.")
    complete_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")
    complete_parser.add_argument(
        "--remove-prompt",
        action="store_true",
        help="Delete the queued prompt file after marking complete.",
    )

    command_parser = tasks_sub.add_parser("command", help="Print manual openclaw agent command for a queued task.")
    command_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")

    queue_parser = tasks_sub.add_parser("queue", help="Write worker prompt and mark task queued (single-task queue mode).")
    queue_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")

    diagnose_parser = tasks_sub.add_parser("diagnose", help="Show planning readiness diagnostics as JSON.")
    diagnose_parser.add_argument("--goals", help="Path to goals markdown (defaults to configured goals file).")

    archive_parser = tasks_sub.add_parser("archive-done", help="Archive all done tasks (hide from board).")

    uncomplete_parser = tasks_sub.add_parser("uncomplete", help="Move a done task back to todo and remove tasks-log line.")
    uncomplete_parser.add_argument("task_id", help="Task id, e.g. TASK-002.")

    goals_parser = subparsers.add_parser("goals", help="View or edit the goals file.")
    _add_shared_config_args(goals_parser)
    goals_parser.add_argument("--goals", help="Path to the goals markdown file.")
    goals_sub = goals_parser.add_subparsers(dest="goals_command", required=True)
    goals_sub.add_parser("show", help="Print the current goals file.")
    goals_save = goals_sub.add_parser("save", help="Save goals from a markdown file or stdin.")
    goals_save.add_argument("file", nargs="?", help="Markdown file to write as goals (defaults to stdin).")

    return parser


def _run_plan(args: argparse.Namespace) -> None:
    config = _resolve_config(args)
    if args.max_tasks is not None:
        config = replace(config, max_daily_tasks=args.max_tasks)
    if args.mode is not None:
        config = replace(config, execution_mode=args.mode)

    print(f"[info] project_root={config.project_root}")
    print(f"[info] goals_file={config.goals_file}")

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
        allow_repeat=args.allow_repeat,
        goals_only=args.goals_only,
    )

    print(f"[info] planned {len(tasks)} task(s).")
    if len(tasks) == 0:
        for line in explain_planning_blockers(
            goals,
            tasks_log_path=config.tasks_log_file,
            backlog_path=config.backlog_file,
            project_root=config.project_root,
        ):
            print(line)

    if not args.dry_run and not args.no_write_backlog:
        added = merge_planned_tasks(config.backlog_file, tasks)
        if added:
            print(f"[info] added {len(added)} task(s) to {config.backlog_file}.")

    lines = run_tasks(
        tasks,
        config=config,
        goals=goals,
        dry_run=args.dry_run,
        write_backlog=not args.no_write_backlog,
    )
    for line in lines:
        print(line)


def _run_board(args: argparse.Namespace) -> None:
    config = _resolve_config(args)
    run_board_server(
        config,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


def _run_tasks(args: argparse.Namespace) -> None:
    config = _resolve_config(args)
    cmd = args.tasks_command

    if cmd == "list":
        views = list_task_views(config, status_filter=args.status)
        print(format_task_list(views))
        return

    task_id = args.task_id.upper()

    if cmd == "show":
        task = show_task(config, task_id)
        if not task:
            print(f"[error] Task {task_id} not found.", file=sys.stderr)
            raise SystemExit(1)
        print(format_task_detail(task))
        return

    if cmd == "cancel":
        ok, detail = cancel_task(config, task_id, remove_prompt=not args.keep_prompt)
        if not ok:
            print(f"[error] {detail}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[ok] {detail}")
        return

    if cmd == "delete":
        ok, detail = delete_task_entry(config, task_id, remove_prompt=not args.keep_prompt)
        if not ok:
            print(f"[error] {detail}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[ok] {detail}")
        return

    if cmd == "complete":
        ok, detail = complete_task(config, task_id, remove_prompt=args.remove_prompt)
        if not ok:
            print(f"[error] {detail}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[ok] {detail}")
        return

    if cmd == "command":
        commands = build_openclaw_commands(config, task_id)
        if not commands:
            print(f"[error] No prompt found for {task_id}. Queue the task first.", file=sys.stderr)
            raise SystemExit(1)
        if commands.get("error") and not commands.get("bash"):
            print(f"[error] {commands['error']}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[info] session_key={commands['session_key']}")
        if commands.get("prompt_path"):
            print(f"[info] prompt_path={commands['prompt_path']}")
        print("\n# Bash / Mac")
        print(commands["bash"])
        print("\n# PowerShell / Windows")
        print(commands["powershell"])
        return

    if cmd == "queue":
        ok, detail = queue_task(config, task_id)
        if not ok:
            print(f"[error] {detail}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[ok] {detail}")
        return

    if cmd == "diagnose":
        goals_content = None
        if args.goals:
            goals_content = Path(args.goals).read_text(encoding="utf-8")
        result = diagnose_planning_readiness(config, goals_content=goals_content)
        print(dumps_json(result))
        if not result.get("ok"):
            raise SystemExit(1)
        return

    if cmd == "archive-done":
        count, detail = archive_done_tasks(config)
        print(f"[ok] {detail}")
        if count == 0:
            print("[info] No done tasks to archive.")
        return

    if cmd == "uncomplete":
        ok, detail = uncomplete_task(config, task_id)
        if not ok:
            print(f"[error] {detail}", file=sys.stderr)
            raise SystemExit(1)
        print(f"[ok] {detail}")
        return

    print(f"[error] Unknown tasks command: {cmd}", file=sys.stderr)
    raise SystemExit(1)


def _run_goals(args: argparse.Namespace) -> None:
    config = _resolve_config(args)
    cmd = args.goals_command

    if cmd == "show":
        data = read_goals(config)
        if not data["exists"]:
            print(f"[warn] Goals file not found: {data['path']}", file=sys.stderr)
        print(data["content"])
        return

    if cmd == "save":
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        else:
            content = sys.stdin.read()
        ok, detail = write_goals(config, content)
        print(f"[ok] {detail}")
        return

    print(f"[error] Unknown goals command: {cmd}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv or argv[0].startswith("-"):
        argv = ["plan", *argv]

    args = parser.parse_args(argv)

    if args.command == "plan":
        _run_plan(args)
    elif args.command == "board":
        _run_board(args)
    elif args.command == "tasks":
        _run_tasks(args)
    elif args.command == "goals":
        _run_goals(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
