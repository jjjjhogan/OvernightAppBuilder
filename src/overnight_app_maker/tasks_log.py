from __future__ import annotations

import re
from datetime import date
from pathlib import Path

COMPLETION_LINE = re.compile(r"^\s*-\s*(?:\[[ xX]\]\s*)?(?:TASK-\d+\s*[:\-]\s*)?(.+)$")


def load_tasks_log(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def extract_completed_summaries(tasks_log: str) -> set[str]:
    summaries: set[str] = set()
    for line in tasks_log.splitlines():
        match = COMPLETION_LINE.match(line)
        if not match:
            continue
        summary = match.group(1).strip().lower()
        if summary:
            summaries.add(summary)
    return summaries


def normalize_summary(text: str) -> str:
    return " ".join(text.strip().lower().split())


def is_recently_completed(title: str, tasks_log: str) -> bool:
    normalized_title = normalize_summary(title)
    if not normalized_title:
        return False
    for summary in extract_completed_summaries(tasks_log):
        if normalized_title in summary or summary in normalized_title:
            return True
    return False


def append_completion(path: Path, task_id: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    line = f"- {task_id}: {title}\n"

    if not path.exists():
        content = f"# Completed Tasks\n\nAppend-only task history.\n\n## {today}\n\n{line}"
        path.write_text(content, encoding="utf-8")
        return

    content = path.read_text(encoding="utf-8")
    if f"- {task_id}:" in content:
        return

    if f"## {today}" in content:
        updated = content.rstrip() + "\n" + line
    else:
        updated = content.rstrip() + f"\n\n## {today}\n\n{line}"

    path.write_text(updated, encoding="utf-8")


def remove_completion(path: Path, task_id: str) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    marker = f"- {task_id}:"
    filtered = [line for line in lines if not line.lstrip().startswith(marker)]
    if len(filtered) == len(lines):
        return False
    path.write_text("".join(filtered), encoding="utf-8")
    return True
