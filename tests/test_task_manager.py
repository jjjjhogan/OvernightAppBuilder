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
    list_task_views,
    queue_prompt_path,
    remove_queue_prompt,
    show_task,
)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        project_root=tmp_path,
        goals_file=tmp_path / "goals.md",
        backlog_file=tmp_path / "backlog" / "tasks.yml",
        tasks_log_file=tmp_path / "memory" / "tasks-log.md",
        worker_instructions_file=tmp_path / "docs" / "worker-instructions.md",
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
    prompt = queue_prompt_path(config.project_root, "TASK-003")
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


def test_build_openclaw_commands_from_prompt_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_backlog(config.backlog_file, [{"id": "TASK-006", "title": "Run me", "status": "queued"}])
    prompt = queue_prompt_path(config.project_root, "TASK-006")
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Do the work", encoding="utf-8")

    commands = build_openclaw_commands(config, "TASK-006")
    assert commands is not None
    assert "openclaw agent" in commands["bash"]
    assert "Do the work" in commands["bash"]
    assert "overnight-task-006" in commands["session_key"]


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


def test_remove_queue_prompt_missing_is_false(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert remove_queue_prompt(config.project_root, "TASK-999") is False
