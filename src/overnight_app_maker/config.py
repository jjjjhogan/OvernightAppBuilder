from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    goals_file: Path
    backlog_file: Path
    tasks_log_file: Path
    worker_instructions_file: Path
    max_daily_tasks: int
    execution_mode: str
    openclaw_agent_id: str
    openclaw_timeout_seconds: int
    openclaw_use_local: bool
    output_dirs: tuple[str, ...]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config(
    project_root: Path | None = None,
    config_path: Path | None = None,
    goals_override: Path | None = None,
) -> AppConfig:
    root = (project_root or Path.cwd()).resolve()
    settings_path = config_path or root / "config" / "settings.yml"
    if not settings_path.exists():
        example_path = root / "config" / "settings.example.yml"
        settings_path = example_path if example_path.exists() else settings_path

    settings: dict = {}
    if settings_path.exists():
        with settings_path.open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                settings = loaded

    goals_cfg = settings.get("goals", {})
    execution_cfg = settings.get("execution", {})
    outputs_cfg = settings.get("outputs", {})

    goals_default = goals_override or Path(
        os.environ.get(
            "OVERNIGHT_APP_MAKER_GOALS",
            goals_cfg.get("default_file", "goals/GOALS.example.md"),
        )
    )
    if not goals_default.is_absolute():
        goals_default = root / goals_default

    output_dirs = (
        outputs_cfg.get("apps_dir", "apps"),
        outputs_cfg.get("research_dir", "research"),
        outputs_cfg.get("reports_dir", "reports"),
        outputs_cfg.get("logs_dir", "logs"),
    )

    return AppConfig(
        project_root=root,
        goals_file=goals_default,
        backlog_file=root / "backlog" / "tasks.yml",
        tasks_log_file=root / "memory" / "tasks-log.md",
        worker_instructions_file=root / "docs" / "worker-instructions.md",
        max_daily_tasks=_env_int(
            "OVERNIGHT_APP_MAKER_MAX_TASKS",
            int(execution_cfg.get("max_daily_tasks", 5)),
        ),
        execution_mode=os.environ.get(
            "OVERNIGHT_APP_MAKER_MODE",
            execution_cfg.get("default_mode", "dry-run"),
        ),
        openclaw_agent_id=os.environ.get("OVERNIGHT_APP_MAKER_OPENCLAW_AGENT", "main"),
        openclaw_timeout_seconds=_env_int("OVERNIGHT_APP_MAKER_OPENCLAW_TIMEOUT", 600),
        openclaw_use_local=_env_bool("OVERNIGHT_APP_MAKER_OPENCLAW_LOCAL", False),
        output_dirs=tuple(output_dirs),
    )
