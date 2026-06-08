def record_run_event(
    run_id: int | None,
    message: str,
    *,
    level: str = "info",
    step: str | None = None,
) -> None:
    """Persist user-facing run progress without interrupting the workflow."""
    if not run_id:
        return

    try:
        from src.database.models import RunEvent
        from src.database.session import get_session

        with get_session() as session:
            session.add(RunEvent(
                run_id=run_id,
                level=level.lower(),
                step=step,
                message=message,
            ))
    except Exception:
        # Progress reporting must never make a discovery run fail.
        pass
