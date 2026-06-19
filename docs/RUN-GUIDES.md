# Run Guides

Quick setup for lab sessions, plus an extensive CLI cheat sheet for the Kanban board and backlog.

---

## Setup

Run these **every session** from your project root (where `backlog/` and `goals/` live).

### Mac — Michael

```bash
cd ~/.openclaw/workspace/projects/OvernightAppBuilder
source .venv/bin/activate
git pull origin main
pip install -e .
python3 -m overnight_app_maker board
```

### Windows — Alex

```powershell
cd C:\Users\garyj\.openclaw\workspace\OvernightAppBuilder
.\.venv\Scripts\Activate.ps1
git pull origin main
pip install -e .
python -m overnight_app_maker board
```

### After every `git pull`

1. `pip install -e .` — picks up new Python code
2. **Stop the old board** (Ctrl+C in the terminal running it)
3. Start the board again
4. Hard-refresh the browser tab (Ctrl+F5)

If buttons fail with **Unknown action**, the board server is almost always still running old code.

**Board URL:** http://127.0.0.1:8765

---

## CLI cheat sheet

### Quick reference

| What you want | Command |
|---|---|
| Start Kanban board | `python -m overnight_app_maker board` |
| List all tasks | `python -m overnight_app_maker tasks list` |
| Why did planning fail? | `python -m overnight_app_maker tasks diagnose` |
| Queue one task (CLI) | `python -m overnight_app_maker tasks queue TASK-003` |
| Get OpenClaw run command | `python -m overnight_app_maker tasks command TASK-003` |
| Mark task done | `python -m overnight_app_maker tasks complete TASK-003` |
| Hide finished tasks from board | `python -m overnight_app_maker tasks archive-done` |
| Show goals file | `python -m overnight_app_maker goals show` |

**Mac:** use `python3` instead of `python` if needed.

---

### Global options

Most subcommands accept:

| Flag | Purpose |
|---|---|
| `--project-root PATH` | Use a different project folder (default: current directory) |
| `--config PATH` | Custom settings YAML (default: `config/settings.yml`) |

Example:

```bash
python -m overnight_app_maker tasks list --project-root /path/to/project
```

---

### `board` — Kanban UI

```bash
python -m overnight_app_maker board
python -m overnight_app_maker board --no-browser      # don't auto-open tab
python -m overnight_app_maker board --port 9000       # different port
python -m overnight_app_maker board --host 127.0.0.1
```

**Board workflow:** Save goals → Check goals → Plan tasks → Queue → Run command → Complete

**Tips:**

- **Esc** closes any modal
- **Folder** opens `research/` / `reports/` in Explorer or Finder
- **Complete** in the run-command modal marks the task done without hunting the card
- **Export diagnose** downloads JSON for troubleshooting (paste in chat)

---

### `goals` — view / save goals

```bash
# Print current goals (same file the board uses)
python -m overnight_app_maker goals show

# Save from a file
python -m overnight_app_maker goals save my-goals.md

# Save from stdin (Mac)
cat my-goals.md | python3 -m overnight_app_maker goals save

# Custom goals path
python -m overnight_app_maker goals show --goals goals/GOALS.example.md
```

**Goals formatting (planner ignores bad lines):**

- Good: `- eat healthier` (dash, space, then text)
- Bad: `-eat healthier`, `eat healthier`, lines starting with `Example:`

**Sections that generate tasks:** Career, Personal, Business, Automation Targets, Overnight App Ideas

---

### `tasks` — backlog management

#### List and inspect

```bash
python -m overnight_app_maker tasks list
python -m overnight_app_maker tasks list --status todo
python -m overnight_app_maker tasks list --status queued
python -m overnight_app_maker tasks list --status done
python -m overnight_app_maker tasks list --status cancelled

python -m overnight_app_maker tasks show TASK-003
```

Statuses: `todo`, `queued`, `in_progress`, `done`, `failed`, `cancelled`, `archived`

#### Queue and run (CLI — same as board)

```bash
# Write worker prompt file + mark queued
python -m overnight_app_maker tasks queue TASK-003

# Print copy-paste OpenClaw command
python -m overnight_app_maker tasks command TASK-003
```

- **Windows (PowerShell):** command uses `Get-Content` on the prompt file
- **Mac (Bash):** command uses `$(cat logs/worker-queue/TASK-003.prompt.txt)`

Prompt files: `logs/worker-queue/TASK-XXX.prompt.txt`

#### Complete, undo, cancel, delete

```bash
python -m overnight_app_maker tasks complete TASK-003
python -m overnight_app_maker tasks complete TASK-003 --remove-prompt

python -m overnight_app_maker tasks uncomplete TASK-003

python -m overnight_app_maker tasks cancel TASK-003
python -m overnight_app_maker tasks cancel TASK-003 --keep-prompt

python -m overnight_app_maker tasks delete TASK-003
python -m overnight_app_maker tasks delete TASK-003 --keep-prompt
```

#### Diagnostics and cleanup

```bash
# Full planning health check — paste output when asking for help
python -m overnight_app_maker tasks diagnose

# Diagnose a specific goals file
python -m overnight_app_maker tasks diagnose --goals path/to/goals.md

# Hide all done tasks from the board (archived in backlog)
python -m overnight_app_maker tasks archive-done
```

Board equivalents: **Check goals**, **Export diagnose**, **Archive done**, **Fresh lab**

---

### `plan` — CLI planner (board is usually easier)

If you omit a subcommand, `plan` runs by default:

```bash
python -m overnight_app_maker plan
```

Useful flags:

```bash
python -m overnight_app_maker plan --dry-run              # preview only
python -m overnight_app_maker plan --no-write-backlog     # don't write backlog
python -m overnight_app_maker plan --goals-only           # skip generic fallback tasks
python -m overnight_app_maker plan --allow-repeat       # ignore tasks-log history
python -m overnight_app_maker plan --mode queue           # write prompt files only
python -m overnight_app_maker plan --max-tasks 3
```

When stuck:

```bash
python -m overnight_app_maker plan --dry-run --allow-repeat --goals-only
```

---

## Common workflows

### A. Normal lab session (board-first)

1. Start `board` → edit goals → **Save goals**
2. **Check goals** (fix bullets if eligible count is 0)
3. **Plan tasks** → select tasks → **Add selected**
4. **Queue** → **Run command** → paste in terminal
5. When OpenClaw finishes → **Complete** (run modal or card)

### B. Queue and run one task from CLI only

```bash
python -m overnight_app_maker tasks list --status todo
python -m overnight_app_maker tasks queue TASK-005
python -m overnight_app_maker tasks command TASK-005
# run the printed command in another terminal
python -m overnight_app_maker tasks complete TASK-005
```

### C. Planning blocked / zero tasks

```bash
python -m overnight_app_maker tasks diagnose
```

Typical fixes:

- Add `- ` bullets to goals (dash **then space**)
- Enable **Allow repeat** on the board (or `--allow-repeat` in CLI)
- Cancel or delete open duplicate tasks
- Use **Goals only** to skip generic scaffold tasks
- **Archive done** or **Fresh lab** to clear clutter

### D. Fresh board for a new demo

Use **Fresh lab** on the board (archives done + cancelled), or:

```bash
python -m overnight_app_maker tasks archive-done
```

### E. Reset goals

Edit `goals/GOALS.example.md` or use the board **Template** button, then **Save goals**.

---

## Important files and folders

| Path | Purpose |
|---|---|
| `goals/GOALS.example.md` | Your goals (planner reads this) |
| `backlog/tasks.yml` | Kanban backlog and task statuses |
| `memory/tasks-log.md` | Completed task history (can block replanning) |
| `logs/worker-queue/TASK-XXX.prompt.txt` | Full OpenClaw worker brief |
| `research/` | Research task outputs |
| `reports/` | Planning briefs |
| `apps/` | Build-phase static web apps |
| `config/settings.yml` | Optional project settings |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Folder button → Unknown action | `git pull`, `pip install -e .`, restart board, Ctrl+F5 |
| Planned 0 tasks | Run `tasks diagnose`; fix `- ` bullets; try Allow repeat |
| Queue fails on build task | Need a planning brief in `reports/` first |
| Broken OpenClaw command | Queue first; command must read from prompt **file** |
| Wrong task marked complete | Use run modal (shows TASK-XXX in title) |
| Board shows old UI | Ctrl+F5; restart board after pull |

**When asking for help**, run and paste:

```bash
python -m overnight_app_maker tasks diagnose
```

Or use board → **Export diagnose**.

---

## Help

```bash
python -m overnight_app_maker --help
python -m overnight_app_maker board --help
python -m overnight_app_maker tasks --help
python -m overnight_app_maker goals --help
python -m overnight_app_maker plan --help
```

---

## Tests (optional)

```bash
pip install pytest
python -m pytest tests/ -q
```
