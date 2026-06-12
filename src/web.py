import os

import logging
import threading
import collections
from functools import wraps

from flask import Flask, render_template, redirect, url_for, abort, request, flash, Response, jsonify, session

logger = logging.getLogger(__name__)


_trigger_lock = threading.Lock()
_trigger_running = False
_scheduler_paused = False
_scheduler = None  # set by start_web_server
_schedule_profile_name = ""  # runtime override for which profile the scheduler uses


class _LogCollector(logging.Handler):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._counter = 0
        self._lines = collections.deque(maxlen=300)
        self.setFormatter(logging.Formatter('%(name)s: %(message)s'))

    def emit(self, record):
        try:
            with self._lock:
                self._counter += 1
                self._lines.append({
                    "id": self._counter,
                    "level": record.levelname,
                    "text": self.format(record),
                })
        except Exception:
            pass

    def since(self, last_id: int) -> list:
        with self._lock:
            return [l for l in self._lines if l["id"] > last_id]

    def last_id(self) -> int:
        with self._lock:
            return self._lines[-1]["id"] if self._lines else 0


_log_collector = _LogCollector()


def _profile_form_data() -> dict:
    """Extract profile fields from a POST form."""
    return {
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip() or None,
        "active": request.form.get("active") == "1",
        "agent_company_name": request.form.get("agent_company_name", "").strip(),
        "agent_description": request.form.get("agent_description", "").strip(),
        "target_industries": request.form.get("target_industries", "").strip() or None,
        "target_cities": request.form.get("target_cities", "").strip() or None,
        "min_employees": _int_or_none(request.form.get("min_employees")),
        "max_employees": _int_or_none(request.form.get("max_employees")),
        "search_focus_terms": request.form.get("search_focus_terms", "").strip() or None,
        "outreach_tone": request.form.get("outreach_tone", "warm"),
        "target_roles": request.form.get("target_roles", "").strip() or None,
    }


def _int_or_none(val: str | None) -> int | None:
    if val and val.strip().isdigit():
        return int(val.strip())
    return None


def _setup_log_collector() -> None:
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _LogCollector):
            return
    root.addHandler(_log_collector)


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("authenticated"):
            return f(*args, **kwargs)
        return redirect(url_for("login", next=request.path))
    return decorated


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.environ.get("SECRET_KEY", "blest-web-secret")
    _setup_log_collector()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        from src.config import settings
        if request.method == "POST":
            if request.form.get("password") == settings.web_password:
                session.permanent = True
                session["authenticated"] = True
                return redirect(request.args.get("next") or url_for("index"))
            return render_template("login.html", error="Contraseña incorrecta.")
        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/schedule/update", methods=["POST"])
    @_require_auth
    def update_schedule():
        from apscheduler.triggers.cron import CronTrigger

        time_val = request.form.get("time", "08:00").strip()
        days = request.form.getlist("days")
        if not days:
            flash("Seleccioná al menos un día.", "error")
            return redirect(url_for("index"))
        try:
            hour, minute = time_val.split(":")
            int(hour); int(minute)
        except ValueError:
            flash("Hora inválida. Usá formato HH:MM.", "error")
            return redirect(url_for("index"))

        days_str = ",".join(days)
        profile_name = request.form.get("profile_name", "").strip()
        if _scheduler:
            from src.config import settings
            _scheduler.reschedule_job(
                "daily_discovery",
                trigger=CronTrigger(hour=int(hour), minute=int(minute), day_of_week=days_str, timezone=settings.scheduler_timezone),
            )
            logger.info(f"Schedule actualizado: {time_val} los días {days_str} — profile: {profile_name or 'Default'}")
            flash(f"Schedule actualizado: {time_val} — {days_str} — Profile: {profile_name or 'Default'}", "success")
        else:
            flash("Scheduler no disponible (modo local sin --web).", "warning")
        # Persist the profile name
        global _schedule_profile_name
        _schedule_profile_name = profile_name

        return redirect(url_for("index"))

    @app.route("/toggle-scheduler", methods=["POST"])
    @_require_auth
    def toggle_scheduler():
        global _scheduler_paused
        _scheduler_paused = not _scheduler_paused
        state = "pausado" if _scheduler_paused else "activo"
        logger.info(f"Scheduler {state} manualmente desde la web UI")
        return redirect(url_for("index"))

    @app.route("/logs")
    @_require_auth
    def logs():
        last_id = int(request.args.get("since", 0))
        return jsonify(lines=_log_collector.since(last_id), last_id=_log_collector.last_id())

    @app.route("/")
    @_require_auth
    def index():
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport, Profile

        with get_session() as session:
            profile_filter = request.args.get("profile_id", "")
            query = session.query(DiscoveryRun)
            if profile_filter and profile_filter.isdigit():
                query = query.filter_by(profile_id=int(profile_filter))
            rows = query.order_by(DiscoveryRun.run_date.desc()).all()

            profiles = session.query(Profile).filter_by(active=True).all()
            profile_options = [{"id": p.id, "name": p.name} for p in profiles]

            runs = []
            for r in rows:
                report = session.query(DailyReport).filter_by(run_id=r.id).first()
                quick_wins = len(report.quick_wins or []) if report else 0
                strategic = len(report.strategic_opportunities or []) if report else 0
                profile_name = "Default"
                if r.profile_id:
                    p = session.get(Profile, r.profile_id)
                    if p:
                        profile_name = p.name
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
                    "profile_name": profile_name,
                    "profile_id": r.profile_id,
                })
        from src.config import settings
        current_time = settings.schedule_time
        current_days = settings.schedule_days
        current_profile_name = _schedule_profile_name or settings.schedule_profile_name or "Default"
        if _scheduler:
            job = _scheduler.get_job("daily_discovery")
            if job and job.trigger:
                try:
                    fields = {f.name: str(f) for f in job.trigger.fields}
                    current_time = f"{fields.get('hour', '8'):0>2}:{fields.get('minute', '0'):0>2}"
                    current_days = fields.get("day_of_week", settings.schedule_days)
                except Exception:
                    pass

        return render_template(
            "runs.html",
            runs=runs,
            scheduler_paused=_scheduler_paused,
            schedule_time=current_time,
            schedule_days=current_days,
            schedule_profile_name=current_profile_name,
            profiles=profile_options,
            default_profile_name=profile_options[0]["name"] if profile_options else "None",
            selected_profile_id=profile_filter,
        )

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

        # Get optional profile_id from form
        profile_id_str = request.form.get("profile_id", "")
        profile_id = int(profile_id_str) if profile_id_str and profile_id_str.isdigit() else None

        with _trigger_lock:
            if _trigger_running:
                flash("Ya hay un run en progreso.", "warning")
                return redirect(url_for("index"))
            _trigger_running = True

        def _run():
            global _trigger_running
            try:
                run_workflow_once(profile_id=profile_id)
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

    @app.route("/run/<int:run_id>/delete", methods=["POST"])
    @_require_auth
    def delete_run(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if report:
                session.delete(report)
            session.delete(run)
        flash("Run eliminado.", "success")
        return redirect(url_for("index"))

    @app.route("/run/<int:run_id>/export/<fmt>")
    @_require_auth
    def export_run(run_id, fmt):
        import os
        import tempfile
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport
        from src.dashboard import _enrich_drafts_from_db
        from src.export import export_csv, export_markdown

        if fmt not in ("csv", "md"):
            abort(404)

        with get_session() as db:
            run = db.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = db.query(DailyReport).filter_by(run_id=run_id).first()
            if not report or not report.report_json:
                abort(404)
            report_data = _enrich_drafts_from_db(db, dict(report.report_json))

        run_date = report_data.get("run_date", str(run_id))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}")
        tmp.close()
        try:
            if fmt == "csv":
                export_csv(report_data, tmp.name)
                mimetype, filename = "text/csv", f"blest-leads-{run_date}.csv"
            else:
                export_markdown(report_data, tmp.name)
                mimetype, filename = "text/markdown", f"blest-report-{run_date}.md"
            with open(tmp.name, "rb") as f:
                content = f.read()
        finally:
            os.unlink(tmp.name)

        return Response(
            content,
            mimetype=mimetype,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

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
            from src.dashboard import _enrich_drafts_from_db
            raw = dict(report.report_json) if report and report.report_json else {}
            report_data = _enrich_drafts_from_db(session, raw)

            all_opps = report_data.get("quick_wins", []) + report_data.get("strategic_opportunities", [])
            company_names = [o.get("company_name") for o in all_opps if o.get("company_name")]
            companies = session.query(Company).filter(Company.name.in_(company_names)).all()
            company_id_map = {c.name: c.id for c in companies}
            statuses = session.query(ContactStatus).filter(
                ContactStatus.company_id.in_(company_id_map.values())
            ).all()
            contacted_map = {s.company_id: str(s.contacted_at)[:16] for s in statuses}
            feedback_map = {s.company_id: s for s in statuses}
            contact_info = {
                name: {
                    "company_id": cid,
                    "contacted": cid in contacted_map,
                    "contacted_at": contacted_map.get(cid),
                    "has_comment": bool(feedback_map.get(cid) and feedback_map[cid].comment),
                    "has_feedback": bool(feedback_map.get(cid) and feedback_map[cid].icp_feedback),
                }
                for name, cid in company_id_map.items()
            }

            report_has_professional = False
            if report and report.report_markdown:
                md = report.report_markdown
                report_has_professional = bool(
                    md and md not in ("__generating__",) and not md.startswith("__error__:")
                )

        from src.integrations.zoho_mail import is_configured as zoho_is_configured
        return render_template(
            "run.html", run=run_data, report=report_data,
            contact_info=contact_info, report_has_professional=report_has_professional,
            zoho_configured=zoho_is_configured(),
        )

    # ── Professional Report ──────────────────────────────────────────────────

    @app.route("/run/<int:run_id>/professional-report")
    @_require_auth
    def professional_report(run_id):
        import json
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            run_data = {"id": run.id, "run_date": str(run.run_date)}
            markdown_content = report.report_markdown if report else None

        if not markdown_content:
            return render_template(
                "professional_report.html", run=run_data,
                markdown_content=None, generating=False, error=None,
            )
        if markdown_content == "__generating__":
            return render_template(
                "professional_report.html", run=run_data,
                markdown_content=None, generating=True, error=None,
            )
        if markdown_content.startswith("__error__:"):
            return render_template(
                "professional_report.html", run=run_data,
                markdown_content=None, generating=False,
                error=markdown_content[len("__error__:"):],
            )

        return render_template(
            "professional_report.html", run=run_data,
            markdown_content=markdown_content, generating=False, error=None,
        )

    @app.route("/run/<int:run_id>/professional-report/generate", methods=["POST"])
    @_require_auth
    def generate_professional_report(run_id):
        import json
        import threading
        import anthropic as anthropic_lib
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport
        from src.dashboard import _enrich_drafts_from_db
        from src.prompts.professional_report import PROFESSIONAL_REPORT_PROMPT
        from src.config import get_settings

        cfg = get_settings()

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if not report:
                flash("No hay datos de reporte para este run.", "error")
                return redirect(url_for("run_detail", run_id=run_id))

            report_data = _enrich_drafts_from_db(session, dict(report.report_json or {}))
            all_opps = sorted(
                report_data.get("quick_wins", []) + report_data.get("strategic_opportunities", []),
                key=lambda x: x.get("score", 0), reverse=True,
            )
            drafts_by_company: dict[str, dict] = {}
            for d in report_data.get("outreach_drafts", []):
                nm = d.get("company_name", "")
                if nm not in drafts_by_company:
                    drafts_by_company[nm] = d

            prompt = PROFESSIONAL_REPORT_PROMPT.format(
                run_date=str(run.run_date),
                total_companies=run.companies_found or 0,
                search_queries=", ".join(run.search_queries_used or []),
                scored_json=json.dumps(all_opps, ensure_ascii=False, indent=2),
                contacts_json=json.dumps(report_data.get("all_contacts", []), ensure_ascii=False, indent=2),
                insights_json=json.dumps(report_data.get("top_insights", []), ensure_ascii=False, indent=2),
                drafts_summary=json.dumps(list(drafts_by_company.values()), ensure_ascii=False, indent=2),
            )
            report.report_markdown = "__generating__"

        def _generate(rid: int, p: str) -> None:
            try:
                client = anthropic_lib.Anthropic(api_key=cfg.anthropic_api_key)
                msg = client.messages.create(
                    model=cfg.reasoning_model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": p}],
                )
                result = msg.content[0].text
            except Exception as exc:
                logger.error(f"Professional report generation failed for run {rid}: {exc}", exc_info=True)
                result = f"__error__:{exc}"
            with get_session() as s:
                r = s.query(DailyReport).filter_by(run_id=rid).first()
                if r:
                    r.report_markdown = result

        threading.Thread(target=_generate, args=(run_id, prompt), daemon=True).start()
        return redirect(url_for("professional_report", run_id=run_id))

    @app.route("/run/<int:run_id>/professional-report/download")
    @_require_auth
    def professional_report_download(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if not report:
                abort(404)
            md = report.report_markdown or ""
            if not md or md == "__generating__" or md.startswith("__error__:"):
                abort(404)
            content = md
            run_date = str(run.run_date)

        return Response(
            content.encode("utf-8"),
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=blest-professional-report-{run_date}.md"},
        )

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

    @app.route("/company/<int:company_id>/feedback", methods=["GET"])
    @_require_auth
    def get_feedback(company_id):
        from src.database.session import get_session
        from src.database.models import ContactStatus

        with get_session() as session:
            status = session.get(ContactStatus, company_id)
            if not status:
                return jsonify({"exists": False})

            return jsonify({
                "exists": True,
                "company_id": status.company_id,
                "contacted_at": str(status.contacted_at)[:16] if status.contacted_at else None,
                "comment": status.comment or "",
                "contact_method": status.contact_method or "",
                "response_received": status.response_received or "",
                "follow_up_date": str(status.follow_up_date) if status.follow_up_date else "",
                "icp_feedback": status.icp_feedback or {},
            })

    # ── Profile Management ───────────────────────────────────────────────────

    @app.route("/profiles")
    @_require_auth
    def profile_list():
        from src.database.session import get_session
        from src.database.models import Profile

        with get_session() as session:
            profiles = session.query(Profile).order_by(Profile.name).all()
            enriched = []
            for p in profiles:
                ind_count = len(p.target_industries.split(",")) if p.target_industries else 0
                city_count = len(p.target_cities.split(",")) if p.target_cities else 0
                emp_range = f"{p.min_employees or '?'}–{p.max_employees or '?'}"
                enriched.append({
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "active": p.active,
                    "target_industries_count": ind_count,
                    "target_cities_count": city_count,
                    "employee_range": emp_range,
                })

        return render_template("profiles.html", profiles=enriched)

    @app.route("/profiles/new", methods=["GET", "POST"])
    @_require_auth
    def profile_new():
        from src.database.session import get_session
        from src.database.models import Profile

        if request.method == "POST":
            data = _profile_form_data()
            with get_session() as session:
                existing = session.query(Profile).filter_by(name=data["name"]).first()
                if existing:
                    flash(f"A profile named '{data['name']}' already exists.", "error")
                    return render_template("profile_form.html", profile=None, action="/profiles/new")
                profile = Profile(**data)
                session.add(profile)
                session.flush()
            flash(f"Profile '{data['name']}' created.", "success")
            return redirect(url_for("profile_list"))

        return render_template("profile_form.html", profile=None, action="/profiles/new")

    @app.route("/profiles/<int:profile_id>/edit", methods=["GET", "POST"])
    @_require_auth
    def profile_edit(profile_id):
        from src.database.session import get_session
        from src.database.models import Profile

        with get_session() as session:
            profile = session.get(Profile, profile_id)
            if not profile:
                abort(404)

            if request.method == "POST":
                data = _profile_form_data()
                # Check name uniqueness
                dup = session.query(Profile).filter(
                    Profile.name == data["name"], Profile.id != profile_id
                ).first()
                if dup:
                    flash(f"A profile named '{data['name']}' already exists.", "error")
                    return render_template("profile_form.html", profile=profile, action=f"/profiles/{profile_id}/edit")

                for key, val in data.items():
                    setattr(profile, key, val)
                flash(f"Profile '{data['name']}' updated.", "success")
                return redirect(url_for("profile_list"))

            return render_template("profile_form.html", profile=profile, action=f"/profiles/{profile_id}/edit")

    @app.route("/company/<int:company_id>/feedback", methods=["POST"])
    @_require_auth
    def save_feedback(company_id):
        import datetime
        from src.database.session import get_session
        from src.database.models import ContactStatus

        with get_session() as session:
            status = session.get(ContactStatus, company_id)
            if not status:
                status = ContactStatus(
                    company_id=company_id,
                    contacted_at=datetime.datetime.utcnow(),
                )
                session.add(status)
                session.flush()

            status.comment = request.form.get("comment", "").strip() or None
            status.contact_method = request.form.get("contact_method", "").strip() or None
            status.response_received = request.form.get("response_received", "").strip() or None

            follow_up = request.form.get("follow_up_date", "").strip()
            status.follow_up_date = datetime.date.fromisoformat(follow_up) if follow_up else None

            icp_feedback = {}
            for key in request.form:
                if key.startswith("icp_"):
                    icp_feedback[key] = request.form[key]
            other_text = request.form.get("icp_other_text", "").strip()
            if other_text:
                icp_feedback["icp_other_text"] = other_text
            status.icp_feedback = icp_feedback if icp_feedback else None

        flash("Comentario guardado correctamente.", "success")
        return redirect(request.referrer or url_for("index"))

    # ── Zoho Mail Drafts ─────────────────────────────────────────────────────

    @app.route("/run/<int:run_id>/zoho-drafts", methods=["POST"])
    @_require_auth
    def create_zoho_drafts(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, DailyReport
        from src.dashboard import _enrich_drafts_from_db
        from src.integrations.zoho_mail import create_draft, is_configured

        if not is_configured():
            return jsonify({"error": "Zoho Mail not configured"}), 503

        with get_session() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                abort(404)
            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if not report or not report.report_json:
                return jsonify({"error": "no report data"}), 404
            report_data = _enrich_drafts_from_db(session, dict(report.report_json))

        # Build one draft per company: prefer email channel, fall back to first draft
        all_drafts = report_data.get("outreach_drafts", [])
        companies_seen: dict[str, dict] = {}
        for d in all_drafts:
            company = d.get("company_name", "")
            if not company:
                continue
            if company not in companies_seen:
                companies_seen[company] = d
            elif d.get("channel") == "email":
                # Prefer email channel over LinkedIn
                companies_seen[company] = d

        created = 0
        skipped = 0
        errors = []
        for company_name, draft in companies_seen.items():
            to_address = draft.get("contact_email")
            if not to_address:
                skipped += 1
                continue
            subject = draft.get("subject_line") or f"Outreach — {company_name}"
            body = draft.get("body", "")
            try:
                create_draft(to_address=to_address, subject=subject, content=body)
                created += 1
            except Exception as e:
                logger.warning(f"Zoho draft failed for {company_name}: {e}")
                errors.append(f"{company_name}: {e}")

        return jsonify({"created": created, "skipped": skipped, "errors": errors})

    @app.route("/contact/<int:contact_id>/zoho-draft", methods=["POST"])
    @_require_auth
    def contact_zoho_draft(contact_id):
        from src.database.session import get_session
        from src.database.models import Contact, Company, DailyReport
        from src.dashboard import _enrich_drafts_from_db
        from src.integrations.zoho_mail import create_draft, is_configured

        if not is_configured():
            return jsonify({"error": "Zoho Mail no configurado"}), 503

        data = request.get_json(silent=True) or {}
        run_id = data.get("run_id")
        if not run_id:
            return jsonify({"error": "run_id requerido"}), 400

        with get_session() as session:
            contact = session.get(Contact, contact_id)
            if not contact or not contact.email:
                return jsonify({"error": "Contacto sin email"}), 404

            company = session.get(Company, contact.company_id)
            if not company:
                return jsonify({"error": "Empresa no encontrada"}), 404

            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if not report or not report.report_json:
                return jsonify({"error": "Sin datos de reporte para este run"}), 404

            report_data = _enrich_drafts_from_db(session, dict(report.report_json))

        # Find the email-channel draft for this company
        all_drafts = report_data.get("outreach_drafts", [])
        company_drafts = [d for d in all_drafts if d.get("company_name") == company.name]
        draft = next((d for d in company_drafts if d.get("channel") == "email"), None)
        if not draft and company_drafts:
            draft = company_drafts[0]
        if not draft:
            return jsonify({"error": f"Sin draft para {company.name}"}), 404

        subject = draft.get("subject_line") or f"Outreach — {company.name}"
        body = draft.get("body", "")
        try:
            create_draft(to_address=contact.email, subject=subject, content=body)
            return jsonify({"ok": True})
        except Exception as e:
            logger.warning(f"Zoho single draft failed for contact {contact_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ── Contact Enrichment ───────────────────────────────────────────────────

    # Per-run: track in-progress bulk enrichment {run_id: {"done": int, "total": int}}
    _enrich_progress: dict[int, dict] = {}

    @app.route("/contact/<int:contact_id>/enrich", methods=["POST"])
    @_require_auth
    def enrich_contact_route(contact_id):
        from src.enrichment.pipeline import enrich_contact

        result = enrich_contact(contact_id)
        return jsonify({
            "contact_id": contact_id,
            "email": result.email,
            "email_status": result.email_status,
            "email_source": result.email_source,
            "phone_whatsapp": result.phone_whatsapp,
            "enrichment_log": result.log,
        })

    @app.route("/run/<int:run_id>/enrich-all", methods=["POST"])
    @_require_auth
    def enrich_run_all(run_id):
        from src.database.session import get_session
        from src.database.models import Contact, Company, Opportunity
        from src.enrichment.pipeline import enrich_contact

        with get_session() as session:
            opp_company_ids = [
                o.company_id for o in
                session.query(Opportunity).filter_by(run_id=run_id).all()
            ]
            if not opp_company_ids:
                return jsonify({"error": "no opportunities for this run"}), 404
            contact_ids = [
                c.id for c in
                session.query(Contact).filter(Contact.company_id.in_(opp_company_ids)).all()
            ]

        if not contact_ids:
            return jsonify({"error": "no contacts found"}), 404

        _enrich_progress[run_id] = {"done": 0, "total": len(contact_ids)}

        def _bulk(ids: list[int]) -> None:
            for cid in ids:
                try:
                    enrich_contact(cid)
                except Exception as e:
                    logger.warning(f"Bulk enrich failed for contact {cid}: {e}")
                _enrich_progress[run_id]["done"] += 1

        threading.Thread(target=_bulk, args=(contact_ids,), daemon=True).start()
        return jsonify({"started": True, "total": len(contact_ids)}), 202

    @app.route("/run/<int:run_id>/enrich-status")
    @_require_auth
    def enrich_status(run_id):
        progress = _enrich_progress.get(run_id, {})
        return jsonify(progress)

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
    def _scheduled_run():
        global _schedule_profile_name
        if _scheduler_paused:
            logger.info("Scheduler pausado — saltando run de hoy")
            return
        from src.database.session import get_session
        from src.database.models import Profile
        profile_id = None
        effective = _schedule_profile_name or settings.schedule_profile_name
        if effective:
            with get_session() as session:
                p = session.query(Profile).filter_by(name=effective).first()
                if p:
                    profile_id = p.id
        logger.info(f"Running scheduled discovery for profile: {effective or 'Default'}")
        run_workflow_once(profile_id=profile_id)

    scheduler.add_job(
        _scheduled_run,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), day_of_week=settings.schedule_days),
        id="daily_discovery",
        name="Blest Daily Lead Discovery",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    global _scheduler
    _scheduler = scheduler
    logger.info(
        f"Background scheduler started — daily at {settings.schedule_time} ({settings.scheduler_timezone})"
    )

    port = int(os.environ.get("PORT", 8080))
    app = create_app()
    print(f"\n✅ Web server running at http://0.0.0.0:{port}")
    print(f"   Daily discovery scheduled at {settings.schedule_time} {settings.scheduler_timezone}\n")
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
