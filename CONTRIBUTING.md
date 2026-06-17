# Contributing

This project is designed for handoff to other implementers.

## Guidelines

- Keep `AUTONOMOUS.md` small and focused on active control state.
- Put completed work in `memory/tasks-log.md`.
- Put generated applications in `apps/`.
- Put research in `research/`.
- Put analysis and written deliverables in `reports/`.
- Add tests when changing planner or runner behavior.

## Before Opening a PR

```powershell
python -m pytest
python -m overnight_app_maker --goals goals/GOALS.example.md --dry-run
```
