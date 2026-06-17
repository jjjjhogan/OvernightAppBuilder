# Implementation Roadmap

## Phase 1 - Scaffold

- Establish project directories and conventions.
- Provide a goals template.
- Provide a dry-run planner CLI.

## Phase 2 - Real Planning

- Replace the template planner with an LLM-backed task planner.
- Include recent task history so the system does not repeat itself.
- Rank tasks by impact, effort, and autonomy.

## Phase 3 - Execution

- Add an OpenClaw runner adapter.
- Spawn isolated workers for independent tasks.
- Require workers to append completion lines to `memory/tasks-log.md`.

## Phase 4 - Visibility

- Build a Kanban UI backed by `backlog/tasks.yml`.
- Show To Do, In Progress, Done, artifact links, and run history.
- Add a scheduler for daily planning.
