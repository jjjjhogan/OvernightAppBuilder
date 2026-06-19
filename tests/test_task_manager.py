from __future__ import annotations

from pathlib import Path

import yaml

from overnight_app_maker.config import AppConfig
from overnight_app_maker.task_manager import (
    board_payload,
    build_openclaw_commands,
    cancel_task,
    complete_task,
    delete_task_entry,
    diagnose_planning_readiness,
    list_task_views,
    plan_tasks_for_board,
    preview_task_prompt,
    queue_prompt_path,
    queue_task,
    read_goals,
    remove_queue_prompt,
    show_task,
    write_goals,
)


def _config(tmp_path: Path) -> AppConfig:
    goals = tmp_path / "goals.md"
    goals.write_text("# Goals\n\n- Build something useful.\n", encoding="utf-8")
    instructions = tmp_path / "docs" / "worker-instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("Follow the task brief.\n", encoding="utf-8")
    return AppConfig(
        project_root=tmp_path,
        goals_file=goals,
        backlog_file=tmp_path / "backlog" / "tasks.yml",
        tasks_log_file=tmp_path / "memory" / "tasks-log.md",
        worker_instructions_file=instructions,
        max_daily_tasks=5,
        execution_mode="queue",
        openclaw_agent_id="main",
        openclaw_timeout_seconds=30,
        openclaw_use_local=False,
        output_dirs=("apps", "research", "reports", "logs"),
    )


def _write_backlog(path: Path, tasks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"tasks": tasks}, sort_keys=False), encoding="utf-8")


def test_list_task_views(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [
            {"id": "TASK-001", "title": "Alpha", "status": "todo"},
            {"id": "TASK-002", "title": "Beta", "status": "queued"},
        ],
    )
    views = list_task_views(config)
    assert len(views) == 2
    assert views[1]["column"] == "queued"


def test_cancel_task_removes_prompt_by_default(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(config.backlog_file, [{"id": "TASK-003", "title": "Cancel me", "status": "queued"}])
    prompt = queue_prompt_path(config.project_root, "TASK-003", "logs/worker-queue")
    prompt.parent.mkdir(parents=True)
    prompt.write_text("prompt body", encoding="utf-8")

    ok, detail = cancel_task(config, "TASK-003")
    assert ok
    assert "Cancelled" in detail
    task = show_task(config, "TASK-003")
    assert task is not None
    assert task["status"] == "cancelled"
    assert not prompt.exists()


def test_delete_task_removes_backlog_entry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(config.backlog_file, [{"id": "TASK-004", "title": "Delete me", "status": "todo"}])

    ok, _ = delete_task_entry(config, "TASK-004")
    assert ok
    assert show_task(config, "TASK-004") is None


def test_complete_task_updates_log(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(config.backlog_file, [{"id": "TASK-005", "title": "Finish me", "status": "queued"}])

    ok, detail = complete_task(config, "TASK-005")
    assert ok
    assert "done" in detail
    task = show_task(config, "TASK-005")
    assert task is not None
    assert task["status"] == "done"
    assert "TASK-005: Finish me" in config.tasks_log_file.read_text(encoding="utf-8")


def test_build_openclaw_commands_uses_prompt_file_not_inline(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(config.backlog_file, [{"id": "TASK-006", "title": "Run me", "status": "queued"}])
    prompt = queue_prompt_path(config.project_root, "TASK-006", "logs/worker-queue")
    prompt.parent.mkdir(parents=True)
    long_prompt = "Do the work. " * 500
    prompt.write_text(long_prompt, encoding="utf-8")

    commands = build_openclaw_commands(config, "TASK-006")
    assert commands is not None
    assert "openclaw agent" in commands["bash"]
    assert "logs/worker-queue/TASK-006.prompt.txt" in commands["bash"]
    assert "$(cat logs/worker-queue/TASK-006.prompt.txt)" in commands["bash"]
    assert long_prompt not in commands["bash"]
    assert "Get-Content" in commands["powershell"]
    assert "overnight-task-006" in commands["session_key"]
    assert "Do the work" in commands["prompt_text"]
    assert len(commands["prompt_text"]) > 20


def test_preview_task_prompt_uses_editor_goals(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [
            {
                "id": "TASK-008",
                "title": "Advance goal: My custom goal",
                "description": "Work on it.",
                "output_dir": "reports",
                "status": "todo",
                "phase": "plan",
            }
        ],
    )
    ok, _, prompt = preview_task_prompt(
        config,
        "TASK-008",
        goals_content="# Goals\n\n## Personal\n\n- My custom goal for class.\n",
    )
    assert ok
    assert "My custom goal" in prompt
    assert config.goals_file.read_text(encoding="utf-8").startswith("# Goals")


def test_plan_tasks_for_board_adds_todo_items(tmp_path: Path) -> None:
    config = _config(tmp_path)
    goals = (
        "# Goals\n\n## Personal\n\n- Build a habit tracker for students.\n\n"
        "## Overnight App Ideas\n\n- Morning routine checklist app.\n"
    )
    result = plan_tasks_for_board(config, goals_content=goals)
    assert result["ok"] is True
    assert result["added_count"] >= 1
    views = list_task_views(config, status_filter="todo")
    assert len(views) >= 1


def test_queue_task_writes_prompt_and_updates_status(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [
            {
                "id": "TASK-007",
                "title": "Research one opportunity from the goals file",
                "description": "Produce a report.",
                "output_dir": "reports",
                "status": "todo",
                "phase": "plan",
            }
        ],
    )

    ok, detail = queue_task(config, "TASK-007")
    assert ok
    assert "Queued TASK-007" in detail

    task = show_task(config, "TASK-007")
    assert task is not None
    assert task["status"] == "queued"
    assert task["has_prompt"]

    prompt = queue_prompt_path(config.project_root, "TASK-007", "logs/worker-queue")
    assert prompt.exists()
    assert "TASK-007" in prompt.read_text(encoding="utf-8")


def test_write_and_read_goals(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ok, detail = write_goals(config, "# Goals\n\n- New bullet\n")
    assert ok
    data = read_goals(config)
    assert "New bullet" in data["content"]
    assert data["exists"] is True


def test_board_payload_groups_columns(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [
            {"id": "TASK-001", "title": "Todo one", "status": "todo"},
            {"id": "TASK-002", "title": "Queued one", "status": "queued"},
            {"id": "TASK-003", "title": "Done one", "status": "done"},
        ],
    )
    payload = board_payload(config)
    assert payload["total"] == 3
    assert len(payload["columns"]["todo"]) == 1
    assert len(payload["columns"]["queued"]) == 1
    assert len(payload["columns"]["done"]) == 1
    assert payload["goals_file"]


def test_diagnose_planning_readiness_reports_open_backlog(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [{"id": "TASK-001", "title": "Open task", "status": "todo"}],
    )
    diagnosis = diagnose_planning_readiness(
        config,
        goals_content="# Goals\n\n## Personal\n\n- eat healthier\n",
    )
    assert diagnosis["ok"] is True
    assert diagnosis["goals_diagnosis"]["eligible_count"] == 1
    assert diagnosis["open_backlog_count"] == 1


def test_plan_tasks_for_board_zero_when_no_bullets_and_blocked(tmp_path: Path) -> None:
    from overnight_app_maker.planner import PLANNING_FALLBACK_TASKS
    from overnight_app_maker.tasks_log import append_completion

    config = _config(tmp_path)
    _write_backlog(
        config.backlog_file,
        [
            {
                "id": f"TASK-{index:03d}",
                "title": title,
                "status": "todo",
                "output_dir": output_dir,
                "phase": "plan",
            }
            for index, (title, output_dir, _description) in enumerate(PLANNING_FALLBACK_TASKS, start=1)
        ],
    )
    for index, (title, _output_dir, _description) in enumerate(PLANNING_FALLBACK_TASKS, start=1):
        append_completion(config.tasks_log_file, f"TASK-{index:03d}", title)

    result = plan_tasks_for_board(
        config,
        goals_content="## Personal\n\neat healthier\n",
        allow_repeat=False,
    )
    assert result["planned_count"] == 0
    assert result["added_count"] == 0
    assert result["blockers"]


def test_remove_queue_prompt_missing_is_false(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert remove_queue_prompt(config.project_root, "TASK-999", "logs/worker-queue") is False
