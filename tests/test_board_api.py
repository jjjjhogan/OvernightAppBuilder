from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import yaml

from overnight_app_maker.board.server import BoardServer, BoardHandler
from overnight_app_maker.config import AppConfig


def _config(tmp_path: Path) -> AppConfig:
    goals = tmp_path / "goals" / "GOALS.example.md"
    goals.parent.mkdir(parents=True)
    goals.write_text(
        "# Goals\n\n## Personal\n\n- Build a study planner app.\n",
        encoding="utf-8",
    )
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "Research one opportunity from the goals file",
                        "description": "Write a report.",
                        "output_dir": "reports",
                        "status": "todo",
                        "phase": "plan",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    instructions = tmp_path / "docs" / "worker-instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("Complete the task.\n", encoding="utf-8")
    return AppConfig(
        project_root=tmp_path,
        goals_file=goals,
        backlog_file=backlog,
        tasks_log_file=tmp_path / "memory" / "tasks-log.md",
        worker_instructions_file=instructions,
        max_daily_tasks=5,
        execution_mode="queue",
        openclaw_agent_id="main",
        openclaw_timeout_seconds=30,
        openclaw_use_local=False,
        output_dirs=("apps", "research", "reports", "logs"),
    )


def _request(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read().decode("utf-8")
    conn.close()
    return response.status, json.loads(raw) if raw else {}


def test_board_api_goals_save_post(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, goals = _request(
            port,
            "POST",
            "/api/goals/save",
            {"content": "# Goals\n\n## Personal\n\n- Updated goal line\n"},
        )
        assert status == 200
        assert goals["ok"] is True
        assert "Updated goal line" in goals["goals"]["content"]
        assert config.goals_file.read_text(encoding="utf-8").count("Updated goal line") == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_board_api_preview_queue_and_command(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, preview = _request(
            port,
            "POST",
            "/api/tasks/TASK-001/preview",
            {"goals_content": "# Goals\n\n## Personal\n\n- Build a study planner app.\n"},
        )
        assert status == 200
        assert preview["prompt_text"]
        assert "TASK-001" in preview["prompt_text"]

        status, data = _request(
            port,
            "POST",
            "/api/tasks/TASK-001/queue",
            {"goals_content": "# Goals\n\n## Personal\n\n- Build a study planner app.\n"},
        )
        assert status == 200
        assert data["task"]["status"] == "queued"
        assert data["prompt_text"]

        status, cmd = _request(port, "GET", "/api/tasks/TASK-001/command")
        assert status == 200
        assert cmd["prompt_text"]
        assert "openclaw agent" in cmd["bash"]
        assert len(cmd["bash"]) < 500
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_board_api_plan_tasks(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.backlog_file.write_text("tasks: []\n", encoding="utf-8")
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, result = _request(
            port,
            "POST",
            "/api/plan",
            {
                "goals_content": (
                    "# Goals\n\n## Personal\n\n- Build a study planner app.\n\n"
                    "## Overnight App Ideas\n\n- Habit tracker demo.\n"
                ),
            },
        )
        assert status == 200
        assert result["added_count"] >= 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_board_api_plan_preview_and_confirm(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.backlog_file.write_text("tasks: []\n", encoding="utf-8")
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    goals_body = {
        "goals_content": "# Goals\n\n## Personal\n\n- Build a study planner app.\n",
        "goals_only": True,
    }

    try:
        status, preview = _request(port, "POST", "/api/plan/preview", goals_body)
        assert status == 200
        assert preview["candidates"]
        title = preview["candidates"][0]["title"]

        status, confirm = _request(
            port,
            "POST",
            "/api/plan/confirm",
            {**goals_body, "selected_titles": [title]},
        )
        assert status == 200
        assert confirm["added_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_board_api_archive_and_tasks_log(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, _ = _request(port, "POST", "/api/tasks/TASK-001/complete", {})
        assert status == 200

        status, archive = _request(port, "POST", "/api/board/archive-done", {})
        assert status == 200
        assert archive["archived_count"] == 1

        status, log = _request(port, "GET", "/api/tasks-log")
        assert status == 200
        assert "TASK-001" in log["content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
