from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkerRunResult:
    task_id: str
    session_key: str
    status: str
    detail: str
    stdout: str = ""
    stderr: str = ""


def openclaw_available() -> bool:
    return shutil.which("openclaw") is not None


def build_session_key(agent_id: str, task_id: str) -> str:
    slug = task_id.lower().replace("_", "-")
    return f"overnight-{slug}"


def spawn_worker(
    *,
    task_id: str,
    prompt: str,
    project_root: Path,
    agent_id: str = "main",
    timeout_seconds: int = 600,
    use_local: bool = False,
) -> WorkerRunResult:
    session_key = build_session_key(agent_id, task_id)
    command = [
        "openclaw",
        "agent",
        f"--agent={agent_id}",
        f"--session-key={session_key}",
        f"--message={prompt}",
        "--json",
    ]
    if use_local:
        command.insert(2, "--local")

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return WorkerRunResult(
            task_id=task_id,
            session_key=session_key,
            status="timed_out",
            detail=f"OpenClaw worker exceeded {timeout_seconds}s",
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )
    except OSError as exc:
        return WorkerRunResult(
            task_id=task_id,
            session_key=session_key,
            status="failed",
            detail=str(exc),
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return WorkerRunResult(
            task_id=task_id,
            session_key=session_key,
            status="failed",
            detail=stderr or stdout or f"openclaw exited with code {completed.returncode}",
            stdout=stdout,
            stderr=stderr,
        )

    detail = "Worker run finished"
    if stdout:
        try:
            payload = json.loads(stdout)
            payloads = payload.get("payloads") or []
            if payloads and isinstance(payloads[0], dict):
                text = payloads[0].get("text")
                if text:
                    detail = str(text).strip()[:500]
        except json.JSONDecodeError:
            detail = stdout[:500]

    return WorkerRunResult(
        task_id=task_id,
        session_key=session_key,
        status="completed",
        detail=detail,
        stdout=stdout,
        stderr=stderr,
    )


def queue_worker_prompt(
    *,
    task_id: str,
    prompt: str,
    project_root: Path,
    queue_dir: str = "logs/worker-queue",
) -> WorkerRunResult:
    queue_root = project_root / queue_dir
    queue_root.mkdir(parents=True, exist_ok=True)
    prompt_path = queue_root / f"{task_id}.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    return WorkerRunResult(
        task_id=task_id,
        session_key=f"queued:{task_id}",
        status="queued",
        detail=f"Worker prompt written to {prompt_path.relative_to(project_root).as_posix()}",
    )
