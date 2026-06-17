from overnight_app_maker.planner import plan_daily_tasks


def test_plan_daily_tasks_limits_count() -> None:
    tasks = plan_daily_tasks("# Goals\n\nBuild useful tools.", max_tasks=2)

    assert len(tasks) == 2
    assert tasks[0].id == "TASK-001"
    assert tasks[1].output_dir
