from __future__ import annotations

from pathlib import Path

import yaml

from overnight_app_maker.backlog import load_backlog, merge_planned_tasks, next_task_id, update_task_status
from overnight_app_maker.models import PlannedTask
from overnight_app_maker.planner import build_worker_prompt, plan_daily_tasks
from overnight_app_maker.runner import run_tasks
from overnight_app_maker.tasks_log import append_completion, is_recently_completed, load_tasks_log


def test_plan_daily_tasks_limits_count(tmp_path: Path) -> None:
    goals = "# Goals\n\n## Career\n\n- Launch a SaaS product by Q3.\n"
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")

    tasks = plan_daily_tasks(
        goals,
        max_tasks=2,
        backlog_path=backlog,
        project_root=tmp_path,
    )

    assert len(tasks) == 2
    assert tasks[0].id == "TASK-001"
    assert tasks[0].output_dir
    assert tasks[0].worker_prompt == ""


def test_plan_daily_tasks_skips_recent_completions(tmp_path: Path) -> None:
    goals = "# Goals\n\n## Career\n\n- Launch a SaaS product by Q3.\n"
    tasks_log = tmp_path / "memory" / "tasks-log.md"
    tasks_log.parent.mkdir(parents=True)
    tasks_log.write_text(
        "# Completed Tasks\n\n## 2026-06-18\n\n- TASK-010: Research progress path for: Launch a SaaS product by Q3.\n",
        encoding="utf-8",
    )

    tasks = plan_daily_tasks(
        goals,
        max_tasks=3,
        tasks_log_path=tasks_log,
        project_root=tmp_path,
    )

    assert all("Launch a SaaS product by Q3" not in task.title for task in tasks)


def test_plan_daily_tasks_allocates_ids_after_existing_backlog(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {"id": "TASK-003", "title": "Existing", "status": "todo"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    tasks = plan_daily_tasks(
        "# Goals\n\n## Personal\n\n- Learn Spanish.\n",
        max_tasks=1,
        backlog_path=backlog,
        project_root=tmp_path,
    )

    assert tasks[0].id == "TASK-004"


def test_build_worker_prompt_includes_task_and_rules(tmp_path: Path) -> None:
    task = PlannedTask(
        id="TASK-004",
        title="Advance goal: Learn Spanish",
        description="Produce a useful artifact.",
        output_dir="reports",
    )
    prompt = build_worker_prompt(
        task=task,
        goals="# Goals\n\n- Learn Spanish",
        worker_instructions="Never edit AUTONOMOUS.md.",
        project_root=tmp_path,
    )

    assert "TASK-004" in prompt
    assert "reports/" in prompt
    assert "Never edit AUTONOMOUS.md" in prompt
    assert "memory/tasks-log.md" in prompt


def test_merge_planned_tasks_appends_without_duplicates(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")

    planned = [
        PlannedTask(
            id="TASK-001",
            title="First task",
            description="Do one thing",
            output_dir="reports",
        )
    ]
    added = merge_planned_tasks(backlog, planned)
    assert len(added) == 1

    added_again = merge_planned_tasks(backlog, planned)
    assert added_again == []
    assert len(load_backlog(backlog)) == 1


def test_update_task_status(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump({"tasks": [{"id": "TASK-001", "title": "One", "status": "todo"}]}, sort_keys=False),
        encoding="utf-8",
    )

    update_task_status(backlog, "TASK-001", "running")
    tasks = load_backlog(backlog)
    assert tasks[0]["status"] == "running"


def test_append_completion_adds_dated_line(tmp_path: Path) -> None:
    tasks_log = tmp_path / "memory" / "tasks-log.md"
    append_completion(tasks_log, "TASK-007", "Write summary")
    content = load_tasks_log(tasks_log)
    assert "TASK-007: Write summary" in content
    assert is_recently_completed("Write summary", content)


def test_runner_dry_run_does_not_touch_backlog(tmp_path: Path) -> None:
    from overnight_app_maker.config import AppConfig

    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")
    config = AppConfig(
        project_root=tmp_path,
        goals_file=tmp_path / "goals.md",
        backlog_file=backlog,
        tasks_log_file=tmp_path / "memory" / "tasks-log.md",
        worker_instructions_file=tmp_path / "docs" / "worker-instructions.md",
        max_daily_tasks=5,
        execution_mode="queue",
        openclaw_agent_id="main",
        openclaw_timeout_seconds=30,
        openclaw_use_local=False,
        output_dirs=("apps", "research", "reports", "logs"),
    )
    tasks = [
        PlannedTask(
            id="TASK-001",
            title="Dry run task",
            description="Only print",
            output_dir="reports",
        )
    ]

    lines = run_tasks(tasks, config=config, goals="# Goals", dry_run=True)
    assert lines == ["[dry-run] TASK-001: Dry run task -> reports/"]
    assert load_backlog(backlog) == []


def test_next_task_id(tmp_path: Path) -> None:
    backlog = tmp_path / "tasks.yml"
    backlog.write_text(
        yaml.safe_dump({"tasks": [{"id": "TASK-009", "title": "Nine"}]}, sort_keys=False),
        encoding="utf-8",
    )
    assert next_task_id(load_backlog(backlog)) == "TASK-010"
