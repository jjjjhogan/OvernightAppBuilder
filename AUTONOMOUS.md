# OvernightAppMaker Autonomous Control

## Mission

Generate and complete useful daily tasks from a user's provided goals file, including surprise overnight mini-app MVPs when appropriate.

## Goal Input

- Primary goals live in `goals/`.
- Use `goals/GOALS.example.md` as the template.
- Do not store completed task history here.

## Daily Operating Loop

1. Read the selected goals file.
2. Generate 4-5 useful tasks for today.
3. Add open tasks to `backlog/tasks.yml`.
4. Spawn or run workers for tasks that can be completed autonomously.
5. Put artifacts in `apps/`, `research/`, `reports/`, or another appropriate output folder.
6. Append completed task lines to `memory/tasks-log.md`.

## Shared-File Rule

Only the main coordinator edits this file.

Worker instruction:

> When done, append a completed task line to `memory/tasks-log.md`. Never edit `AUTONOMOUS.md` directly.

## Open Backlog

- TASK-001: Implement the production planner that turns goal files into daily task proposals.
- TASK-002: Implement the OpenClaw session runner adapter.
- TASK-003: Build or connect a Kanban UI for `backlog/tasks.yml`.
