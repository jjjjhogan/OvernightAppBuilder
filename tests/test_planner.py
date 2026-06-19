from __future__ import annotations

from pathlib import Path

import json
import yaml

from overnight_app_maker.backlog import ensure_backlog_task, load_backlog, merge_planned_tasks, next_task_id, update_task_status
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


def test_build_worker_prompt_includes_web_app_requirements(tmp_path: Path) -> None:
    brief = tmp_path / "reports" / "TASK-005-implementation-brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# Brief\n", encoding="utf-8")
    task = PlannedTask(
        id="TASK-006",
        title="Build minimal web app from latest planning brief",
        description="Implement the brief.",
        output_dir="apps",
        phase="build",
    )
    prompt = build_worker_prompt(
        task=task,
        goals="# Goals",
        worker_instructions="Follow the brief.",
        project_root=tmp_path,
        planning_artifact=brief,
    )

    assert "index.html" in prompt
    assert "Build Requirements" in prompt
    assert brief.name in prompt


def test_plan_daily_tasks_includes_build_after_planning_artifacts(tmp_path: Path) -> None:
    brief = tmp_path / "reports" / "TASK-005-implementation-brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# Brief\n", encoding="utf-8")
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")

    tasks = plan_daily_tasks(
        "# Goals\n\n## Overnight App Ideas\n\n- Habit tracker for students.\n",
        max_tasks=4,
        backlog_path=backlog,
        project_root=tmp_path,
    )

    phases = [task.phase for task in tasks]
    assert "plan" in phases
    assert "build" in phases
    assert phases.index("plan") < phases.index("build")


def test_plan_daily_tasks_no_build_without_planning_artifacts(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")

    tasks = plan_daily_tasks(
        "# Goals\n\n## Overnight App Ideas\n\n- Habit tracker for students.\n",
        max_tasks=4,
        backlog_path=backlog,
        project_root=tmp_path,
    )

    assert all(task.phase == "plan" for task in tasks)


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


def test_merge_planned_tasks_allows_repeat_after_done(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump(
            {"tasks": [{"id": "TASK-001", "title": "First task", "status": "done"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    planned = [
        PlannedTask(
            id="TASK-002",
            title="First task",
            description="Do one thing again",
            output_dir="reports",
        )
    ]

    added = merge_planned_tasks(backlog, planned)
    assert len(added) == 1
    assert len(load_backlog(backlog)) == 2


def test_diagnose_goals_flags_non_bullet_lines() -> None:
    from overnight_app_maker.planner import diagnose_goals

    goals = "## Personal\n\neat healthier\n\n- Learn guitar\n"
    diagnosis = diagnose_goals(goals)
    assert diagnosis["eligible_count"] == 1
    assert diagnosis["eligible_bullets"][0]["text"] == "Learn guitar"
    assert len(diagnosis["ignored_lines"]) == 1
    assert diagnosis["ignored_lines"][0]["line"] == "eat healthier"


def test_plan_daily_tasks_allow_repeat_ignores_tasks_log(tmp_path: Path) -> None:
    tasks_log = tmp_path / "memory" / "tasks-log.md"
    tasks_log.parent.mkdir(parents=True)
    tasks_log.write_text(
        "# Completed Tasks\n\n## 2026-06-18\n\n"
        "- TASK-001: Research one opportunity from the goals file\n",
        encoding="utf-8",
    )
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("tasks: []\n", encoding="utf-8")

    blocked = plan_daily_tasks(
        "# Goals\n\n## Career\n\n- Example: ignored.\n",
        max_tasks=1,
        tasks_log_path=tasks_log,
        backlog_path=backlog,
        project_root=tmp_path,
        allow_repeat=False,
    )
    allowed = plan_daily_tasks(
        "# Goals\n\n## Career\n\n- Example: ignored.\n",
        max_tasks=1,
        tasks_log_path=tasks_log,
        backlog_path=backlog,
        project_root=tmp_path,
        allow_repeat=True,
    )

    assert all(task.title != "Research one opportunity from the goals file" for task in blocked)
    assert len(allowed) == 1
    assert allowed[0].title == "Research one opportunity from the goals file"


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


def test_update_task_status_normalizes_in_progress(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump({"tasks": [{"id": "TASK-001", "title": "One", "status": "todo"}]}, sort_keys=False),
        encoding="utf-8",
    )

    update_task_status(backlog, "TASK-001", "in progress")
    tasks = load_backlog(backlog)
    assert tasks[0]["status"] == "in_progress"


def test_ensure_backlog_task_reuses_existing_title(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog" / "tasks.yml"
    backlog.parent.mkdir(parents=True)
    backlog.write_text(
        yaml.safe_dump(
            {"tasks": [{"id": "TASK-004", "title": "Existing title", "status": "in progress"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    planned = PlannedTask(
        id="TASK-009",
        title="Existing title",
        description="Same work",
        output_dir="reports",
    )

    resolved_id = ensure_backlog_task(backlog, planned)
    assert resolved_id == "TASK-004"
    assert len(load_backlog(backlog)) == 1


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


def test_runner_no_write_backlog_skips_backlog_status_updates(tmp_path: Path) -> None:
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
            title="Queue without backlog writes",
            description="Only queue prompt",
            output_dir="reports",
        )
    ]

    lines = run_tasks(tasks, config=config, goals="# Goals", write_backlog=False)

    assert load_backlog(backlog) == []
    assert not any("[warn]" in line for line in lines)
    assert any("[queued] TASK-001:" in line for line in lines)
    assert (tmp_path / "logs" / "worker-queue" / "TASK-001.prompt.txt").exists()


def test_runner_reports_when_no_tasks_planned(tmp_path: Path) -> None:
    from overnight_app_maker.config import AppConfig

    config = AppConfig(
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

    lines = run_tasks([], config=config, goals="# Goals", dry_run=False)
    assert any("No new tasks to run" in line for line in lines)


def test_next_task_id(tmp_path: Path) -> None:
    backlog = tmp_path / "tasks.yml"
    backlog.write_text(
        yaml.safe_dump({"tasks": [{"id": "TASK-009", "title": "Nine"}]}, sort_keys=False),
        encoding="utf-8",
    )
    assert next_task_id(load_backlog(backlog)) == "TASK-010"


def test_resolve_spawn_message_prefers_inline_prompt(tmp_path: Path) -> None:
    from overnight_app_maker.openclaw_adapter import resolve_spawn_message

    prompt_path = tmp_path / "logs" / "worker-queue" / "TASK-001.prompt.txt"
    prompt_path.parent.mkdir(parents=True)
    prompt = "Complete TASK-001 and write reports/output.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    message = resolve_spawn_message(prompt=prompt, prompt_path=prompt_path, project_root=tmp_path)
    assert message == prompt


def test_resolve_spawn_message_file_fallback_avoids_drive_colon_label(tmp_path: Path) -> None:
    from overnight_app_maker.openclaw_adapter import resolve_spawn_message

    prompt_path = tmp_path / "logs" / "worker-queue" / "TASK-001.prompt.txt"
    prompt_path.parent.mkdir(parents=True)
    prompt = "x" * 8000
    prompt_path.write_text(prompt, encoding="utf-8")

    message = resolve_spawn_message(prompt=prompt, prompt_path=prompt_path, project_root=tmp_path)
    assert "BRIEF_PATH" in message
    assert "absolute path, then execute" not in message


def test_build_spawn_message_uses_prompt_file(tmp_path: Path) -> None:
    from overnight_app_maker.openclaw_adapter import resolve_spawn_message

    prompt_path = tmp_path / "logs" / "worker-queue" / "TASK-002.prompt.txt"
    prompt_path.parent.mkdir(parents=True)
    prompt = "brief"
    prompt_path.write_text(prompt, encoding="utf-8")

    message = resolve_spawn_message(prompt=prompt, prompt_path=prompt_path, project_root=tmp_path)
    assert message == "brief"


def test_extract_agent_reply_reads_nested_payload() -> None:
    from overnight_app_maker.openclaw_adapter import extract_agent_reply

    stdout = json.dumps({"result": {"payloads": [{"text": "Finished report."}]}})
    assert extract_agent_reply(stdout) == "Finished report."


def test_looks_like_deferred_reply() -> None:
    from overnight_app_maker.openclaw_adapter import looks_like_deferred_reply

    assert looks_like_deferred_reply("Please provide the specific details of the task.")
    assert looks_like_deferred_reply("I don't see an absolute path after the colon.")
    assert not looks_like_deferred_reply("Wrote reports/TASK-002.md successfully.")


def test_normalize_output_handles_none() -> None:
    from overnight_app_maker.openclaw_adapter import _normalize_output

    assert _normalize_output(None) == ""
    assert _normalize_output("  ok  ") == "ok"


def test_resolve_openclaw_executable_prefers_cmd_on_windows(monkeypatch) -> None:
    from overnight_app_maker import openclaw_adapter

    monkeypatch.setattr(openclaw_adapter.shutil, "which", lambda name: {
        "openclaw": None,
        "openclaw.cmd": r"C:\Users\garyj\AppData\Roaming\npm\openclaw.cmd",
        "openclaw.exe": None,
    }.get(name))
    monkeypatch.delenv("OVERNIGHT_APP_MAKER_OPENCLAW", raising=False)

    assert openclaw_adapter.resolve_openclaw_executable() == r"C:\Users\garyj\AppData\Roaming\npm\openclaw.cmd"
    command = openclaw_adapter.build_openclaw_command("agent", "--message=test")
    assert command[0] == r"C:\Users\garyj\AppData\Roaming\npm\openclaw.cmd"


def test_plan_daily_tasks_goals_only_skips_fallbacks(tmp_path: Path) -> None:
    goals = "# Goals\n\n## Personal\n\n- Learn guitar.\n"
    all_tasks = plan_daily_tasks(goals, max_tasks=5, project_root=tmp_path)
    goals_only = plan_daily_tasks(goals, max_tasks=5, project_root=tmp_path, goals_only=True)

    assert len(all_tasks) >= len(goals_only)
    assert all("Learn guitar" in t.title or "Plan and brief" in t.title for t in goals_only)
    assert not any(t.title == "Draft one useful artifact that advances a stated goal" for t in goals_only)
