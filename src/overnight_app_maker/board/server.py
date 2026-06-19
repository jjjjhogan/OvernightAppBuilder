from __future__ import annotations

import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..config import AppConfig
from .. import __version__
from ..task_manager import (
    archive_done_tasks,
    board_payload,
    build_openclaw_commands,
    cancel_task,
    complete_task,
    confirm_plan_tasks,
    delete_task_entry,
    diagnose_planning_readiness,
    export_diagnose_json,
    fresh_lab_session,
    open_task_output_folder,
    plan_tasks_for_board,
    preview_plan_tasks,
    preview_task_prompt,
    queue_task,
    read_goals,
    read_tasks_log_for_board,
    show_task,
    uncomplete_task,
    update_task_details,
    write_goals,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
TASK_ID_PATTERN = re.compile(r"^TASK-\d+$", re.IGNORECASE)
OPEN_FOLDER_ACTIONS = {"open-folder", "folder", "openfolder"}


class BoardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], config: AppConfig):
        self.config = config
        super().__init__(server_address, handler_cls)


class BoardHandler(BaseHTTPRequestHandler):
    server: BoardServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def config(self) -> AppConfig:
        return self.server.config

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _handle_save_goals(self, body: dict[str, Any]) -> None:
        content = body.get("content")
        if content is None or not isinstance(content, str):
            return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing goals content."})
        _ok, detail = write_goals(self.config, content)
        return self._send_json(
            HTTPStatus.OK,
            {"ok": True, "detail": detail, "goals": read_goals(self.config)},
        )

    def _handle_open_folder(self, task_id: str) -> None:
        ok, detail, folder_path = open_task_output_folder(self.config, task_id)
        if not ok:
            return self._send_json(HTTPStatus.BAD_REQUEST, {"error": detail})
        return self._send_json(
            HTTPStatus.OK,
            {"ok": True, "detail": detail, "folder_path": folder_path},
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in {"", "/"}:
            return self._serve_static("index.html", "text/html; charset=utf-8")

        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            return self._serve_static(rel)

        if path == "/api/board":
            query = parsed.query or ""
            include_archived = "include_archived=1" in query or "include_archived=true" in query
            return self._send_json(HTTPStatus.OK, board_payload(self.config, include_archived=include_archived))

        if path == "/api/tasks-log":
            return self._send_json(HTTPStatus.OK, read_tasks_log_for_board(self.config))

        if path == "/api/export/diagnose":
            return self._send_json(
                HTTPStatus.OK,
                export_diagnose_json(self.config, goals_content=None),
            )

        if path == "/api/goals":
            return self._send_json(HTTPStatus.OK, read_goals(self.config))

        if path == "/api/meta":
            return self._send_json(
                HTTPStatus.OK,
                {
                    "version": __version__,
                    "features": {
                        "open_folder": True,
                        "run_modal_complete": True,
                    },
                },
            )

        if path.startswith("/api/tasks/"):
            task_id = path.removeprefix("/api/tasks/").split("/", 1)[0].upper()
            if not TASK_ID_PATTERN.match(task_id):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid task id."})
            suffix = path.split("/")[-1].lower()
            if suffix in OPEN_FOLDER_ACTIONS:
                return self._handle_open_folder(task_id)
            if path.endswith("/command"):
                commands = build_openclaw_commands(self.config, task_id)
                if not commands:
                    return self._send_json(HTTPStatus.NOT_FOUND, {"error": f"No prompt for {task_id}."})
                if commands.get("error") and not commands.get("bash"):
                    return self._send_json(HTTPStatus.BAD_REQUEST, {"error": commands["error"], **commands})
                return self._send_json(HTTPStatus.OK, {"task_id": task_id, **commands})
            task = show_task(self.config, task_id)
            if not task:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Task {task_id} not found."})
            return self._send_json(HTTPStatus.OK, task)

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/goals":
            return self._handle_save_goals(self._read_json_body())

        if path.startswith("/api/tasks/"):
            task_id = path.removeprefix("/api/tasks/").split("/", 1)[0].upper()
            if not TASK_ID_PATTERN.match(task_id):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid task id."})
            body = self._read_json_body()
            ok, detail = update_task_details(
                self.config,
                task_id,
                title=body.get("title"),
                description=body.get("description"),
            )
            if not ok:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": detail})
            task = show_task(self.config, task_id)
            return self._send_json(HTTPStatus.OK, {"ok": True, "detail": detail, "task": task})

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json_body()

        if path in {"/api/goals", "/api/goals/save"}:
            return self._handle_save_goals(body)

        if path == "/api/plan":
            result = plan_tasks_for_board(
                self.config,
                goals_content=body.get("goals_content"),
                allow_repeat=bool(body.get("allow_repeat", False)),
                goals_only=bool(body.get("goals_only", False)),
            )
            if not result.get("ok"):
                return self._send_json(HTTPStatus.BAD_REQUEST, result)
            return self._send_json(HTTPStatus.OK, result)

        if path == "/api/plan/preview":
            result = preview_plan_tasks(
                self.config,
                goals_content=body.get("goals_content"),
                allow_repeat=bool(body.get("allow_repeat", False)),
                goals_only=bool(body.get("goals_only", False)),
            )
            if not result.get("ok"):
                return self._send_json(HTTPStatus.BAD_REQUEST, result)
            return self._send_json(HTTPStatus.OK, result)

        if path == "/api/plan/confirm":
            selected = body.get("selected_titles")
            if selected is not None and not isinstance(selected, list):
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "selected_titles must be a list."})
            result = confirm_plan_tasks(
                self.config,
                goals_content=body.get("goals_content"),
                allow_repeat=bool(body.get("allow_repeat", False)),
                goals_only=bool(body.get("goals_only", False)),
                selected_titles=selected,
            )
            if not result.get("ok"):
                return self._send_json(HTTPStatus.BAD_REQUEST, result)
            return self._send_json(HTTPStatus.OK, result)

        if path == "/api/plan/diagnose":
            result = diagnose_planning_readiness(
                self.config,
                goals_content=body.get("goals_content"),
            )
            if not result.get("ok"):
                return self._send_json(HTTPStatus.BAD_REQUEST, result)
            return self._send_json(HTTPStatus.OK, result)

        if path == "/api/board/archive-done":
            count, detail = archive_done_tasks(self.config)
            return self._send_json(HTTPStatus.OK, {"ok": True, "archived_count": count, "detail": detail})

        if path == "/api/board/fresh-start":
            result = fresh_lab_session(self.config)
            return self._send_json(HTTPStatus.OK, result)

        if path == "/api/export/diagnose":
            result = export_diagnose_json(
                self.config,
                goals_content=body.get("goals_content"),
            )
            if not result.get("ok"):
                return self._send_json(HTTPStatus.BAD_REQUEST, result)
            return self._send_json(HTTPStatus.OK, result)

        if not path.startswith("/api/tasks/"):
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

        remainder = path.removeprefix("/api/tasks/")
        parts = remainder.split("/")
        if not parts or not TASK_ID_PATTERN.match(parts[0].upper()):
            return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid task id."})

        task_id = parts[0].upper()
        action = parts[1].lower() if len(parts) > 1 else ""
        goals_content = body.get("goals_content")
        remove_prompt = bool(body.get("remove_prompt", True))

        if action == "preview":
            ok, detail, prompt_text = preview_task_prompt(
                self.config,
                task_id,
                goals_content=goals_content,
            )
            if not ok:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": detail})
            return self._send_json(
                HTTPStatus.OK,
                {"ok": True, "detail": detail, "task_id": task_id, "prompt_text": prompt_text},
            )

        if action == "queue" or action == "requeue":
            ok, detail = queue_task(self.config, task_id, goals_content=goals_content)
            if not ok:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": detail})
            task = show_task(self.config, task_id)
            commands = build_openclaw_commands(self.config, task_id) or {}
            return self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "detail": detail,
                    "task": task,
                    "prompt_text": commands.get("prompt_text", ""),
                },
            )

        if action == "uncomplete":
            ok, detail = uncomplete_task(self.config, task_id)
            if not ok:
                return self._send_json(HTTPStatus.BAD_REQUEST, {"error": detail})
            task = show_task(self.config, task_id)
            return self._send_json(HTTPStatus.OK, {"ok": True, "detail": detail, "task": task})

        if action in OPEN_FOLDER_ACTIONS:
            return self._handle_open_folder(task_id)

        if action == "complete":
            ok, detail = complete_task(self.config, task_id, remove_prompt=remove_prompt)
        elif action == "cancel":
            ok, detail = cancel_task(self.config, task_id, remove_prompt=remove_prompt)
        else:
            return self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": f"Unknown action '{action}'. Restart the board after git pull "
                    "(Ctrl+C, then python -m overnight_app_maker board).",
                },
            )

        if not ok:
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": detail})
        task = show_task(self.config, task_id)
        return self._send_json(HTTPStatus.OK, {"ok": True, "detail": detail, "task": task})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not path.startswith("/api/tasks/"):
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

        task_id = path.removeprefix("/api/tasks/").split("/", 1)[0].upper()
        if not TASK_ID_PATTERN.match(task_id):
            return self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid task id."})

        body = self._read_json_body()
        remove_prompt = bool(body.get("remove_prompt", True))
        ok, detail = delete_task_entry(self.config, task_id, remove_prompt=remove_prompt)
        if not ok:
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": detail})
        return self._send_json(HTTPStatus.OK, {"ok": True, "detail": detail})

    def _serve_static(self, rel_path: str, content_type: str | None = None) -> None:
        target = (STATIC_DIR / rel_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return self._send_json(HTTPStatus.FORBIDDEN, {"error": "Forbidden."})
        if not target.exists() or not target.is_file():
            return self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
        guessed = content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guessed)
        if target.name == "index.html":
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_board_server(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = BoardServer((host, port), BoardHandler, config)
    url = f"http://{host}:{port}/"
    print(f"[info] Kanban board at {url}")
    print(f"[info] Backlog: {config.backlog_file}")
    print(f"[info] Goals: {config.goals_file}")
    print("[info] After git pull, restart this server so new board buttons work.")
    print("[info] Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[info] Board stopped.")
    finally:
        server.server_close()
