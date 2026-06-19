from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import yaml

from overnight_app_maker.board.server import BoardServer, BoardHandler
from overnight_app_maker.config import AppConfig


def _config(tmp_path: Path) -> AppConfig:
    goals = tmp_path / "goals.md"
    goals.write_text("# Goals\n\n- Ship a feature.\n", encoding="utf-8")
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


def test_board_api_queue_and_command(tmp_path: Path) -> None:
    config = _config(tmp_path)
    server = BoardServer(("127.0.0.1", 0), BoardHandler, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, data = _request(port, "POST", "/api/tasks/TASK-001/queue", {})
        assert status == 200
        assert data["ok"] is True
        assert data["task"]["status"] == "queued"

        status, cmd = _request(port, "GET", "/api/tasks/TASK-001/command")
        assert status == 200
        assert "openclaw agent" in cmd["bash"]
        assert "logs/worker-queue/TASK-001.prompt.txt" in cmd["bash"]
        assert len(cmd["bash"]) < 500

        status, goals = _request(port, "PUT", "/api/goals", {"content": "# Goals\n\n- Updated goal\n"})
        assert status == 200
        assert "Updated goal" in goals["goals"]["content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
