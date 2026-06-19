# OvernightAppMaker

OvernightAppMaker is a scaffold for an OpenClaw-powered autonomous app maker. Users provide a goals file, then the system plans daily tasks, delegates autonomous execution, and records progress without rewriting shared state.

## What This Project Is For

- Accept a user's goals from a file in `goals/`
- Generate daily autonomous tasks from those goals
- Run those tasks through OpenClaw sessions or future worker integrations
- Track open work in `AUTONOMOUS.md`
- Track completed work in append-only logs under `memory/`
- Store generated apps, research, reports, and task outputs in predictable folders

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m overnight_app_maker plan --goals goals/GOALS.example.md --dry-run
```

Copy `goals/GOALS.example.md` to a new file, fill it with your own goals, then point the runner at that file.

## Kanban board and task CLI

After queue mode creates tasks, manage them in a local board or from the terminal:

```powershell
# Local Kanban UI (http://127.0.0.1:8765)
python -m overnight_app_maker board

# CLI backup if the board is unavailable
python -m overnight_app_maker tasks list
python -m overnight_app_maker tasks queue TASK-002
python -m overnight_app_maker tasks command TASK-002
python -m overnight_app_maker tasks complete TASK-002
python -m overnight_app_maker tasks cancel TASK-003
python -m overnight_app_maker tasks delete TASK-004
python -m overnight_app_maker goals show
```

The default command is still `plan` (same flags as before). Example:

```powershell
python -m overnight_app_maker --goals goals/GOALS.example.md --mode queue
```

## Core Files

- `AUTONOMOUS.md` - token-light control file with operating rules and open backlog only
- `goals/` - user-supplied goals and missions
- `memory/tasks-log.md` - append-only completed task log
- `backlog/tasks.yml` - structured backlog for planned tasks
- `src/overnight_app_maker/` - implementation package
- `scripts/` - setup and scheduled runner scripts
- `apps/` - generated app MVP outputs
- `research/` - research artifacts
- `reports/` - written summaries and analysis

## Agent Safety Pattern

Only the main coordinating session should edit `AUTONOMOUS.md`. Worker agents should append one completion line to `memory/tasks-log.md` and place artifacts in the relevant output directory.

This avoids race conditions where multiple agents edit the same control file at the same time.
