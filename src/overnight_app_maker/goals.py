from __future__ import annotations

from pathlib import Path


def load_goals(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Goals file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
