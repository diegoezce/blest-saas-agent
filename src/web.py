import os
import logging

from flask import Flask, render_template, redirect, url_for, abort

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.route("/")
    def index():
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport

        with get_session() as session:
            rows = session.query(DiscoveryRun).order_by(DiscoveryRun.run_date.desc()).all()
            runs = []
            for r in rows:
                report = session.query(DailyReport).filter_by(run_id=r.id).first()
                quick_wins = len(report.quick_wins or []) if report else 0
                strategic = len(report.strategic_opportunities or []) if report else 0
                runs.append({
                    "id": r.id,
                    "run_date": str(r.run_date),
                    "status": r.status,
                    "companies_found": r.companies_found or 0,
                    "quick_wins": quick_wins,
                    "strategic": strategic,
                    "started_at": str(r.started_at) if r.started_at else None,
                    "completed_at": str(r.completed_at) if r.completed_at else None,
                    "error_message": r.error_message,
                })
        return render_template("runs.html", runs=runs)

    @app.route("/run/latest")
    def latest():
        from src.database.session import get_session
        from src.database.models import DiscoveryRun

        with get_session() as session:
            run = session.query(DiscoveryRun).order_by(DiscoveryRun.run_date.desc()).first()
            if not run:
                return redirect(url_for("index"))
            run_id = run.id
        return redirect(url_for("run_detail", run_id=run_id))

    @app.route("/run/<int:run_id>")
    def run_detail(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()

            run_data = {
                "id": run.id,
                "run_date": str(run.run_date),
                "status": run.status,
                "companies_found": run.companies_found or 0,
                "started_at": str(run.started_at) if run.started_at else None,
                "completed_at": str(run.completed_at) if run.completed_at else None,
                "error_message": run.error_message,
            }
            report_data = dict(report.report_json) if report and report.report_json else {}

        return render_template("run.html", run=run_data, report=report_data)

    return app


def start_web_server() -> None:
    from src.config import settings
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from src.scheduler import run_workflow_once
    from src.database.session import init_db

    init_db()

    hour, minute = settings.schedule_time.split(":")
    scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    scheduler.add_job(
        run_workflow_once,
        trigger=CronTrigger(hour=int(hour), minute=int(minute)),
        id="daily_discovery",
        name="Blest Daily Lead Discovery",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        f"Background scheduler started — daily at {settings.schedule_time} ({settings.scheduler_timezone})"
    )

    port = int(os.environ.get("PORT", 8080))
    app = create_app()
    print(f"\n✅ Web server running at http://0.0.0.0:{port}")
    print(f"   Daily discovery scheduled at {settings.schedule_time} {settings.scheduler_timezone}\n")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
