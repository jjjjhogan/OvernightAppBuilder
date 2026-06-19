from __future__ import annotations

import json
from pathlib import Path

from overnight_app_maker.cli import main


def _scaffold_project(tmp_path: Path) -> None:
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir(parents=True)
    goals = goals_dir / "GOALS.example.md"
    goals.write_text("# Goals\n\n## Personal\n\n- Learn guitar.\n", encoding="utf-8")
    instructions = tmp_path / "docs" / "worker-instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("Complete the task.\n", encoding="utf-8")
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")


def test_cli_tasks_diagnose_without_task_id(tmp_path: Path, capsys) -> None:
    _scaffold_project(tmp_path)
    main(["tasks", "--project-root", str(tmp_path), "diagnose"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["goals_diagnosis"]["eligible_count"] == 1


def test_cli_tasks_archive_done_without_task_id(tmp_path: Path, capsys) -> None:
    _scaffold_project(tmp_path)
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.write_text(
        "tasks:\n  - id: TASK-001\n    title: Done task\n    status: done\n",
        encoding="utf-8",
    )
    main(["tasks", "--project-root", str(tmp_path), "archive-done"])
    captured = capsys.readouterr()
    assert "Archived 1 done task(s)" in captured.out
