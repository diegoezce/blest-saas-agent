import os
import logging
import threading
from base64 import b64decode
from functools import wraps

from flask import Flask, render_template, redirect, url_for, abort, request, flash, Response

logger = logging.getLogger(__name__)


_trigger_lock = threading.Lock()
_trigger_running = False


def _check_auth(username: str, password: str) -> bool:
    from src.config import settings
    return username == "blest" and password == settings.web_password


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                credentials = b64decode(auth[6:]).decode("utf-8")
                username, password = credentials.split(":", 1)
                if _check_auth(username, password):
                    return f(*args, **kwargs)
            except Exception:
                pass
        return Response(
            "Acceso restringido.",
            401,
            {"WWW-Authenticate": 'Basic realm="Blest Lead Discovery"'},
        )
    return decorated


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.environ.get("SECRET_KEY", "blest-web-secret")

    @app.route("/")
    @_require_auth
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

    @app.route("/trigger", methods=["POST"])
    @_require_auth
    def trigger():
        global _trigger_running
        from src.config import settings
        from src.scheduler import run_workflow_once

        password = request.form.get("password", "")
        if password != settings.trigger_password:
            flash("Contraseña incorrecta.", "error")
            return redirect(url_for("index"))

        with _trigger_lock:
            if _trigger_running:
                flash("Ya hay un run en progreso.", "warning")
                return redirect(url_for("index"))
            _trigger_running = True

        def _run():
            global _trigger_running
            try:
                run_workflow_once()
            finally:
                _trigger_running = False

        threading.Thread(target=_run, daemon=True).start()
        flash("Run iniciado. Actualizá la página en unos minutos.", "success")
        return redirect(url_for("index"))

    @app.route("/run/latest")
    @_require_auth
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
    @_require_auth
    def run_detail(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport, Company, ContactStatus

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

            all_opps = report_data.get("quick_wins", []) + report_data.get("strategic_opportunities", [])
            company_names = [o.get("company_name") for o in all_opps if o.get("company_name")]
            companies = session.query(Company).filter(Company.name.in_(company_names)).all()
            company_id_map = {c.name: c.id for c in companies}
            statuses = session.query(ContactStatus).filter(
                ContactStatus.company_id.in_(company_id_map.values())
            ).all()
            contacted_map = {s.company_id: str(s.contacted_at)[:16] for s in statuses}
            contact_info = {
                name: {
                    "company_id": cid,
                    "contacted": cid in contacted_map,
                    "contacted_at": contacted_map.get(cid),
                }
                for name, cid in company_id_map.items()
            }

        return render_template("run.html", run=run_data, report=report_data, contact_info=contact_info)

    @app.route("/company/<int:company_id>/toggle-contact", methods=["POST"])
    @_require_auth
    def toggle_contact(company_id):
        import datetime
        from src.database.session import get_session
        from src.database.models import ContactStatus

        with get_session() as session:
            status = session.get(ContactStatus, company_id)
            if status:
                session.delete(status)
            else:
                session.add(ContactStatus(
                    company_id=company_id,
                    contacted_at=datetime.datetime.utcnow(),
                ))

        return redirect(request.referrer or url_for("index"))

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
        trigger=CronTrigger(hour=int(hour), minute=int(minute), day_of_week=settings.schedule_days),
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
