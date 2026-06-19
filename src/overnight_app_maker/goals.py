from __future__ import annotations

from pathlib import Path


def load_goals(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Goals file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def save_goals(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")


def goals_view(path: Path, project_root: Path) -> dict[str, str]:
    try:
        rel = path.relative_to(project_root).as_posix()
    except ValueError:
        rel = str(path)
    if not path.exists():
        return {"path": rel, "content": "", "exists": "false"}
    return {"path": rel, "content": path.read_text(encoding="utf-8"), "exists": "true"}
