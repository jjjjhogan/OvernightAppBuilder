# Architecture

OvernightAppMaker is split into four responsibilities:

1. Goal loading from `goals/`
2. Daily planning into structured tasks
3. Autonomous execution through a runner adapter
4. Progress tracking through a small control file plus append-only logs

## Data Flow

`goals/*.md` -> planner -> `backlog/tasks.yml` -> runner -> artifacts -> `memory/tasks-log.md`

## Concurrency Rule

The coordinator owns `AUTONOMOUS.md` and `backlog/tasks.yml`. Workers append to `memory/tasks-log.md` and write task artifacts only.
