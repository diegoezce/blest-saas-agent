import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def create_discovery_run() -> int:
    from src.database.models import DiscoveryRun
    from src.database.session import get_session

    with get_session() as session:
        run = DiscoveryRun(
            run_date=datetime.date.today(),
            started_at=datetime.datetime.utcnow(),
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    return run_id


def run_workflow_once(run_id: int | None = None) -> None:
    from src.graph.state import AgentState
    from src.graph.workflow import build_workflow
    from src.dashboard import render_report_from_data
    from src.tools.run_events import record_run_event

    if run_id is None:
        run_id = create_discovery_run()

    graph = build_workflow()
    logger.info(f"Starting discovery run {run_id} for {datetime.date.today()}")
    record_run_event(run_id, "Run started.", step="run")

    initial_state: AgentState = {
        "run_id": run_id,
        "run_date": datetime.date.today().isoformat(),
        "search_queries": [],
        "raw_search_results": [],
        "companies": [],
        "scored_opportunities": [],
        "contacts": [],
        "insights": [],
        "outreach_drafts": [],
        "report": {},
        "errors": [],
        "completed": False,
    }

    try:
        final_state = graph.invoke(initial_state)
        render_report_from_data(final_state.get("report", {}))
        if final_state.get("errors"):
            logger.warning(f"Run {run_id} completed with {len(final_state['errors'])} non-fatal error(s):")
            for err in final_state["errors"]:
                logger.warning(f"  • {err}")
        else:
            logger.info(f"Run {run_id} completed successfully")
        record_run_event(run_id, "Run completed.", step="run")
        return final_state
    except Exception as e:
        logger.error(f"Run {run_id} failed with unhandled exception: {e}", exc_info=True)
        record_run_event(run_id, f"Run failed: {e}", level="error", step="run")
        try:
            with get_session() as session:
                run = session.get(DiscoveryRun, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = str(e)
                    run.completed_at = datetime.datetime.utcnow()
        except Exception:
            pass
        raise


def start_scheduler() -> None:
    from src.config import settings

    hour, minute = settings.schedule_time.split(":")
    scheduler = BlockingScheduler(timezone=settings.scheduler_timezone)
    scheduler.add_job(
        run_workflow_once,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), day_of_week=settings.schedule_days),
        id="daily_discovery",
        name="Blest Daily Lead Discovery",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    next_run = scheduler.get_job("daily_discovery").next_run_time
    logger.info(
        f"Scheduler started — daily run at {settings.schedule_time} "
        f"({settings.scheduler_timezone}). Next: {next_run}"
    )
    print(f"\n✅ Scheduler running. Daily discovery at {settings.schedule_time} {settings.scheduler_timezone}")
    print(f"   Next run: {next_run}")
    print("   Press Ctrl+C to stop.\n")
    scheduler.start()
