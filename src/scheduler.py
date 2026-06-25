import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def load_profile(profile_id: int | None = None) -> tuple[int | None, dict | None]:
    """Load a profile from the database by ID, or the first active profile."""
    from src.database.session import get_session
    from src.database.models import Profile as ProfileModel

    with get_session() as session:
        if profile_id:
            profile = session.get(ProfileModel, profile_id)
        else:
            profile = (
                session.query(ProfileModel).filter_by(active=True, is_default=True).first()
                or session.query(ProfileModel).filter_by(active=True).first()
            )

        if not profile:
            return None, None

        return profile.id, {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "agent_company_name": profile.agent_company_name,
            "agent_description": profile.agent_description,
            "target_industries": profile.target_industries,
            "target_cities": profile.target_cities,
            "min_employees": profile.min_employees,
            "max_employees": profile.max_employees,
            "search_focus_terms": profile.search_focus_terms,
            "scoring_rubric": profile.scoring_rubric,
            "outreach_tone": profile.outreach_tone,
            "outreach_language": profile.outreach_language,
            "outreach_instructions": profile.outreach_instructions,
            "target_roles": profile.target_roles,
        }


def run_workflow_once(profile_id: int | None = None) -> dict | None:
    from src.config import settings
    from src.database.models import DiscoveryRun
    from src.database.session import get_session
    from src.graph.state import AgentState
    from src.graph.workflow import build_workflow
    from src.dashboard import render_report_from_data

    graph = build_workflow()

    # Load profile
    pid, profile = load_profile(profile_id)
    profile_name = profile.get("name", "Default") if profile else "Default"

    with get_session() as session:
        run = DiscoveryRun(
            run_date=datetime.date.today(),
            started_at=datetime.datetime.utcnow(),
            status="running",
            profile_id=pid,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    logger.info(f"Starting discovery run {run_id} for profile '{profile_name}' on {datetime.date.today()}")

    initial_state: AgentState = {
        "run_id": run_id,
        "run_date": datetime.date.today().isoformat(),
        "profile_id": pid,
        "profile": profile,
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
        return final_state
    except Exception as e:
        logger.error(f"Run {run_id} failed with unhandled exception: {e}", exc_info=True)
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
