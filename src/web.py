import concurrent.futures
import logging
import os
import threading
import time
import collections
from functools import wraps

from flask import Flask, render_template, redirect, url_for, abort, request, flash, Response, jsonify, session

logger = logging.getLogger(__name__)


_trigger_lock = threading.Lock()
_trigger_running = False
_scheduler_paused = False
_scheduler = None  # set by start_web_server
_schedule_profile_name = ""  # runtime override for which profile the scheduler uses
_quick_run_state: dict[int, dict] = {}  # run_id → {phase, enrich, error}


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
        "outreach_language": request.form.get("outreach_language", "es"),
        "outreach_instructions": request.form.get("outreach_instructions", "").strip() or None,
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


def _do_quick_run(run_id: int, pid: int | None, profile: dict | None) -> None:
    """Background: run discovery workflow then auto-enrich all contacts."""
    import datetime as _dt
    from src.database.session import get_session
    from src.database.models import Contact, Opportunity
    from src.graph.workflow import build_workflow
    from src.graph.state import AgentState
    from src.enrichment.pipeline import enrich_contact

    state = _quick_run_state[run_id]
    graph = build_workflow()

    initial_state: AgentState = {
        "run_id": run_id,
        "run_date": _dt.date.today().isoformat(),
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
        graph.invoke(initial_state)
    except Exception as e:
        logger.error(f"Quick run {run_id} workflow failed: {e}", exc_info=True)
        state["phase"] = "error"
        state["error"] = str(e)
        return

    # Phase 2: auto-enrich all contacts found in this run
    state["phase"] = "enriching"
    try:
        with get_session() as db:
            opp_company_ids = [
                o.company_id for o in db.query(Opportunity).filter_by(run_id=run_id).all()
            ]
            contacts = (
                db.query(Contact)
                .filter(Contact.company_id.in_(opp_company_ids))
                .filter(Contact.enriched_at.is_(None))
                .all()
            ) if opp_company_ids else []
            contact_ids = [c.id for c in contacts]
            contact_names = {c.id: c.name or "" for c in contacts}

        ep: dict = {"done": 0, "total": len(contact_ids), "failed": 0, "running": True, "current_name": None}
        state["enrich"] = ep
        state["fresh_contact_ids"] = set(contact_ids)  # IDs new/unenriched at run start

        for i, cid in enumerate(contact_ids):
            ep["current_name"] = contact_names.get(cid, "")
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(enrich_contact, cid).result(timeout=180)
            except concurrent.futures.TimeoutError:
                logger.warning(f"Quick run enrich timeout contact {cid}")
                ep["failed"] += 1
            except Exception as exc:
                logger.warning(f"Quick run enrich failed contact {cid}: {exc}")
                ep["failed"] += 1
            ep["done"] += 1
            if i < len(contact_ids) - 1:
                time.sleep(2)

        ep["running"] = False
        ep["current_name"] = None
    except Exception as e:
        logger.error(f"Quick run {run_id} enrichment failed: {e}", exc_info=True)
        if "enrich" in state:
            state["enrich"]["running"] = False

    state["phase"] = "done"


def _search_companies_data(db, q: str, limit: int | None = None, offset: int = 0,
                           desc_len: int = 120) -> tuple[list[dict], int]:
    """Company listing for the /search page.

    With a query, filters by name/domain/industry/location; without one, returns
    the full catalogue. Returns (rows, total_count). Pass limit=None to fetch all
    matching rows (used by the CSV/MD export).
    """
    from src.database.models import Company, Opportunity, ContactStatus
    from sqlalchemy import or_

    base = db.query(Company)
    if q:
        like = f"%{q}%"
        base = base.filter(or_(
            Company.name.ilike(like),
            Company.domain.ilike(like),
            Company.industry.ilike(like),
            Company.location.ilike(like),
        ))

    total = base.count()
    rows_q = base.order_by(Company.name)
    if offset:
        rows_q = rows_q.offset(offset)
    if limit is not None:
        rows_q = rows_q.limit(limit)
    co_rows = rows_q.all()
    co_ids = [c.id for c in co_rows]

    best_scores: dict = {}
    best_run_id: dict = {}
    if co_ids:
        for cid, score, run_id in (
            db.query(Opportunity.company_id, Opportunity.score, Opportunity.run_id)
            .filter(Opportunity.company_id.in_(co_ids))
            .order_by(Opportunity.score.desc())
            .all()
        ):
            if cid not in best_scores:
                best_scores[cid] = score
                best_run_id[cid] = run_id

    contacted_ids: set = set()
    if co_ids:
        contacted_ids = {
            r[0] for r in
            db.query(ContactStatus.company_id).filter(ContactStatus.company_id.in_(co_ids)).all()
        }

    companies = []
    for c in co_rows:
        companies.append({
            "id": c.id,
            "name": c.name,
            "domain": c.domain or "",
            "industry": c.industry or "",
            "location": c.location or "",
            "description": (c.description or "")[:desc_len],
            "website_url": c.website_url or "",
            "score": best_scores.get(c.id),
            "run_id": best_run_id.get(c.id),
            "contacted": c.id in contacted_ids,
        })
    return companies, total


def _search_contacts_data(db, q: str, limit: int = 40) -> list[dict]:
    """Contact search for the /search page (only used when a query is present)."""
    from src.database.models import Contact, Company
    from sqlalchemy import or_

    like = f"%{q}%"
    ct_rows = (
        db.query(Contact, Company)
        .join(Company, Contact.company_id == Company.id)
        .filter(or_(
            Contact.name.ilike(like),
            Contact.email.ilike(like),
            Contact.role.ilike(like),
        ))
        .order_by(Contact.name)
        .limit(limit)
        .all()
    )
    contacts = []
    for ct, co in ct_rows:
        contacts.append({
            "id": ct.id,
            "name": ct.name or "",
            "role": ct.role or "",
            "email": ct.email or "",
            "email_status": ct.email_status or "",
            "linkedin_url": ct.linkedin_url or "",
            "phone_whatsapp": ct.phone_whatsapp or "",
            "company_id": co.id,
            "company_name": co.name,
            "company_domain": co.domain or "",
        })
    return contacts


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

    @app.route("/company/<int:company_id>/details", methods=["GET"])
    @_require_auth
    def get_company_details(company_id):
        from src.database.session import get_session
        from src.database.models import Company, Contact

        with get_session() as session:
            company = session.get(Company, company_id)
            if not company:
                return jsonify({"error": "Not found"}), 404

            # Fetch all contacts for this company
            contacts = session.query(Contact).filter_by(company_id=company_id).all()
            contacts_data = [
                {
                    "id": c.id,
                    "name": c.name,
                    "email": c.email,
                    "role": c.role,
                    "linkedin_url": c.linkedin_url,
                    "email_source": c.email_source,
                    "is_primary": bool(c.is_primary),
                }
                for c in contacts
            ]

            return jsonify({
                "id": company.id,
                "name": company.name,
                "domain": company.domain,
                "industry": company.industry,
                "size_estimate": company.size_estimate,
                "location": company.location,
                "description": company.description,
                "website_url": company.website_url,
                "linkedin_url": company.linkedin_url,
                "source": company.source,
                "source_url": company.source_url,
                "first_seen_at": str(company.first_seen_at)[:10] if company.first_seen_at else None,
                "last_updated_at": str(company.last_updated_at)[:10] if company.last_updated_at else None,
                "contacts": contacts_data,
            })

    @app.route("/company/<int:company_id>/update", methods=["POST"])
    @_require_auth
    def update_company(company_id):
        from src.database.session import get_session
        from src.database.models import Company

        with get_session() as session:
            company = session.get(Company, company_id)
            if not company:
                return jsonify({"error": "Not found"}), 404

            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            editable_fields = ['industry', 'size_estimate', 'location', 'description', 'website_url', 'linkedin_url']
            for field in editable_fields:
                if field in data:
                    setattr(company, field, data[field] or None)

            session.commit()
            return jsonify({"success": True, "message": "Company updated"})

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

    # ── Email bounce detection (reads Zoho inbox) ────────────────────────────

    @app.route("/bounces/scan")
    @_require_auth
    def bounces_scan():
        """Preview: scan the Zoho inbox for bounces and match them to DB contacts.
        Read-only — does not mark anything."""
        from src.integrations.zoho_mail import is_configured
        from src.tools.bounces import scan_and_match

        if not is_configured():
            return jsonify({"error": "Zoho Mail no está configurado."}), 503
        try:
            summary = scan_and_match()
        except Exception as e:
            logger.error(f"Bounce scan failed: {e}", exc_info=True)
            return jsonify({"error": f"No se pudo leer Zoho (¿falta el scope de lectura?): {e}"}), 502

        summary.pop("addresses", None)  # internal; not needed by the UI
        return jsonify(summary)

    @app.route("/bounces/apply", methods=["POST"])
    @_require_auth
    def bounces_apply():
        """Mark matched bounced contacts: sets Contact.email_status = 'bounced'."""
        from src.integrations.zoho_mail import is_configured
        from src.tools.bounces import apply_bounces

        if not is_configured():
            return jsonify({"error": "Zoho Mail no está configurado."}), 503
        try:
            return jsonify(apply_bounces())
        except Exception as e:
            logger.error(f"Bounce apply failed: {e}", exc_info=True)
            return jsonify({"error": f"No se pudo leer Zoho: {e}"}), 502

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

        # Build company_name → primary contact email mapping for this run
        from src.database.models import Company, Opportunity, Contact
        primary_emails: dict[str, str] = {}
        with get_session() as session:
            run_company_ids = [
                o.company_id for o in
                session.query(Opportunity).filter_by(run_id=run_id).all()
            ]
            run_companies = session.query(Company).filter(Company.id.in_(run_company_ids)).all()
            company_name_by_id = {c.id: c.name for c in run_companies}
            primary_contacts = (
                session.query(Contact)
                .filter(Contact.company_id.in_(run_company_ids))
                .filter(Contact.is_primary.is_(True))
                .filter(Contact.email.isnot(None))
                .all()
            )
            for ct in primary_contacts:
                cname = company_name_by_id.get(ct.company_id)
                if cname:
                    primary_emails[cname] = ct.email

        created = 0
        skipped = 0
        errors = []
        pushed_company_names: list[str] = []
        for company_name, draft in companies_seen.items():
            to_address = primary_emails.get(company_name) or draft.get("contact_email")
            if not to_address:
                skipped += 1
                continue
            subject = draft.get("subject_line") or f"Outreach — {company_name}"
            body = draft.get("body", "")
            try:
                create_draft(to_address=to_address, subject=subject, content=body)
                created += 1
                pushed_company_names.append(company_name)
            except Exception as e:
                logger.warning(f"Zoho draft failed for {company_name}: {e}")
                errors.append(f"{company_name}: {e}")

        # Mark successfully-pushed companies as contacted so they appear on the
        # follow-up page. Resolve names → company_id within this run's opportunities.
        if pushed_company_names:
            from src.database.models import Company, Opportunity
            from src.tools.db_tools import mark_company_contacted
            with get_session() as session:
                run_companies = (
                    session.query(Company)
                    .join(Opportunity, Opportunity.company_id == Company.id)
                    .filter(Opportunity.run_id == run_id)
                    .all()
                )
                by_name = {c.name: c.id for c in run_companies}
                for name in pushed_company_names:
                    cid = by_name.get(name)
                    if cid:
                        mark_company_contacted(session, cid, method="email")

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

            company_name = company.name
            company_id = company.id

            report = session.query(DailyReport).filter_by(run_id=run_id).first()
            if not report or not report.report_json:
                return jsonify({"error": "Sin datos de reporte para este run"}), 404

            report_data = _enrich_drafts_from_db(session, dict(report.report_json))

            # Find the email-channel draft for this company
            all_drafts = report_data.get("outreach_drafts", [])
            company_drafts = [d for d in all_drafts if d.get("company_name") == company_name]
            draft = next((d for d in company_drafts if d.get("channel") == "email"), None)
            if not draft and company_drafts:
                draft = company_drafts[0]
            if not draft:
                return jsonify({"error": f"Sin draft para {company_name}"}), 404

            subject = draft.get("subject_line") or f"Outreach — {company_name}"
            body = draft.get("body", "")
            contact_email = contact.email

            try:
                create_draft(to_address=contact_email, subject=subject, content=body)
                from src.tools.db_tools import mark_company_contacted
                mark_company_contacted(session, company_id, method="email")
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

    @app.route("/contact/<int:contact_id>/set-email", methods=["POST"])
    @_require_auth
    def set_contact_email(contact_id):
        """Manually assign a verified email to a contact."""
        from src.database.session import get_session
        from src.database.models import Contact
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "email inválido"}), 400
        with get_session() as db:
            c = db.get(Contact, contact_id)
            if not c:
                return jsonify({"error": "contacto no encontrado"}), 404
            c.email = email
            c.email_status = "verified"
            c.email_source = "manual"
        return jsonify({"ok": True, "email": email})

    @app.route("/contact/<int:contact_id>/set-primary", methods=["POST"])
    @_require_auth
    def set_primary_contact(contact_id):
        """Mark this contact as the primary recipient for its company's drafts."""
        from src.database.session import get_session
        from src.database.models import Contact
        with get_session() as db:
            c = db.get(Contact, contact_id)
            if not c:
                return jsonify({"error": "contacto no encontrado"}), 404
            db.query(Contact).filter_by(company_id=c.company_id).update({"is_primary": False})
            c.is_primary = True
        return jsonify({"ok": True})

    @app.route("/company/<int:company_id>/add-email", methods=["POST"])
    @_require_auth
    def add_company_email(company_id):
        """Add a manual email address for a company (creates a minimal Contact row)."""
        from src.database.session import get_session
        from src.database.models import Company, Contact
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "email inválido"}), 400
        with get_session() as db:
            company = db.get(Company, company_id)
            if not company:
                return jsonify({"error": "empresa no encontrada"}), 404
            contact = Contact(
                company_id=company_id,
                email=email,
                email_status="verified",
                email_source="manual",
                is_primary=False,
            )
            db.add(contact)
            db.flush()
            contact_id_new = contact.id
        return jsonify({"ok": True, "contact": {"id": contact_id_new, "email": email}})

    @app.route("/company/<int:company_id>/create-manual-draft", methods=["POST"])
    @_require_auth
    def create_manual_draft(company_id):
        """Create a Zoho draft for a manually-added email using an existing outreach draft or IA."""
        from src.database.session import get_session
        from src.database.models import Company, Contact, Opportunity
        from src.integrations.zoho_mail import create_draft, is_configured

        if not is_configured():
            return jsonify({"error": "Zoho Mail no configurado"}), 503

        data = request.get_json(silent=True) or {}
        contact_id = data.get("contact_id")
        action = data.get("action")  # "use_existing", "empty", "ai", "manual"
        manual_content = data.get("content")
        manual_subject = data.get("subject")

        if not contact_id:
            return jsonify({"error": "contact_id requerido"}), 400

        with get_session() as db:
            company = db.get(Company, company_id)
            if not company:
                return jsonify({"error": "Empresa no encontrada"}), 404

            contact = db.get(Contact, contact_id)
            if not contact or not contact.email:
                return jsonify({"error": "Contacto sin email"}), 404

            opp = (
                db.query(Opportunity)
                .filter_by(company_id=company_id)
                .filter(Opportunity.outreach_draft.isnot(None))
                .filter(Opportunity.outreach_subject.isnot(None))
                .first()
            )

            # If no action specified, check if existing draft available
            if not action:
                if opp:
                    return jsonify({"ok": True, "has_existing": True, "subject": opp.outreach_subject, "body": opp.outreach_draft})
                else:
                    return jsonify({"ok": False, "no_draft": True, "company_name": company.name})

            # Handle requested action
            subject = None
            body = None

            if action == "use_existing":
                if not opp:
                    return jsonify({"error": "No hay draft existente"}), 404
                subject = opp.outreach_subject
                body = opp.outreach_draft

            elif action == "empty":
                subject = f"Outreach — {company.name}"
                body = ""

            elif action == "manual":
                if not manual_subject or not manual_content:
                    return jsonify({"error": "Asunto y contenido requeridos"}), 400
                subject = manual_subject
                body = manual_content

            elif action == "ai":
                from src.database.models import Profile
                from src.config import get_settings
                import json
                import anthropic
                import instructor
                from src.prompts.outreach import build_outreach_prompt
                from src.schemas.outputs import CompanyOutreach

                profile = db.query(Profile).filter_by(active=True).first()
                po = {
                    "agent_company_name": profile.agent_company_name if profile else "Blest",
                    "agent_description": profile.agent_description if profile else "",
                    "search_focus_terms": profile.search_focus_terms if profile else "",
                    "outreach_instructions": profile.outreach_instructions if profile else "",
                    "outreach_tone": profile.outreach_tone if profile else "warm",
                    "outreach_language": profile.outreach_language if profile else "es",
                }

                payload = {
                    "company_name": company.name,
                    "website": company.website_url,
                    "industry": company.industry,
                    "size": company.size_estimate,
                    "location": company.location,
                    "description": company.description,
                    "signals": [],
                }

                try:
                    cfg = get_settings()
                    client = instructor.from_anthropic(anthropic.Anthropic(api_key=cfg.anthropic_api_key))

                    custom = (po.get("outreach_instructions") or "").strip()
                    custom_block = (
                        f"\nWHAT {po['agent_company_name'].upper()} OFFERS & HOW TO PITCH "
                        f"(use only what is relevant; never contradict COMPANY DATA):\n{custom}\n"
                        if custom else ""
                    )

                    result = client.messages.create(
                        model=cfg.outreach_model,
                        max_tokens=1024,
                        messages=[{
                            "role": "user",
                            "content": build_outreach_prompt(
                                agent_name=po["agent_company_name"],
                                agent_description=po["agent_description"],
                                outreach_service_description=po.get("search_focus_terms") or "improve their business",
                                outreach_tone=po.get("outreach_tone", "warm"),
                                company_and_insight_json=json.dumps(payload, ensure_ascii=False, indent=2),
                                custom_instructions_block=custom_block,
                                outreach_language=po.get("outreach_language", "es"),
                            ),
                        }],
                        response_model=CompanyOutreach,
                    )
                    if result.drafts:
                        subject = result.drafts[0].subject_line or f"Outreach — {company.name}"
                        body = result.drafts[0].body or ""
                    else:
                        subject = f"Outreach — {company.name}"
                        body = ""
                except Exception as e:
                    logger.warning(f"IA draft generation failed: {e}")
                    return jsonify({"error": f"Error generando con IA: {str(e)}"}), 500

            if not subject or body is None:
                return jsonify({"error": "No se pudo determinar asunto/contenido"}), 400

            try:
                create_draft(to_address=contact.email, subject=subject, content=body)
                from src.tools.db_tools import mark_company_contacted
                mark_company_contacted(db, company_id, method="email")
                return jsonify({"ok": True})
            except Exception as e:
                logger.warning(f"Manual draft creation failed for contact {contact_id}: {e}")
                return jsonify({"error": str(e)}), 500

    @app.route("/contact/<int:contact_id>/delete-manual", methods=["POST"])
    @_require_auth
    def delete_manual_contact(contact_id):
        """Delete a manually-added contact (email_source='manual', never enriched)."""
        from src.database.session import get_session
        from src.database.models import Contact
        with get_session() as db:
            c = db.get(Contact, contact_id)
            if not c:
                return jsonify({"error": "contacto no encontrado"}), 404
            if c.email_source != "manual" or c.enriched_at is not None:
                return jsonify({"error": "solo se pueden eliminar contactos agregados manualmente"}), 400
            db.delete(c)
        return jsonify({"ok": True})

    @app.route("/run/<int:run_id>/enrich-all", methods=["POST"])
    @_require_auth
    def enrich_run_all(run_id):
        from src.database.session import get_session
        from src.database.models import Contact, Opportunity
        from src.enrichment.pipeline import enrich_contact

        # Block double-runs: return current progress if already active
        existing = _enrich_progress.get(run_id, {})
        if existing.get("running"):
            return jsonify({"error": "already_running", "progress": existing}), 409

        with get_session() as db:
            from src.database.models import Company
            opp_company_ids = [
                o.company_id for o in
                db.query(Opportunity).filter_by(run_id=run_id).all()
            ]
            if not opp_company_ids:
                return jsonify({"error": "no opportunities for this run"}), 404
            company_names = {
                c.id: c.name for c in
                db.query(Company).filter(Company.id.in_(opp_company_ids)).all()
            }
            # Only enrich contacts that haven't been enriched yet
            contacts = (
                db.query(Contact)
                .filter(Contact.company_id.in_(opp_company_ids))
                .filter(Contact.enriched_at.is_(None))
                .all()
            )
            contact_ids = [c.id for c in contacts]
            contact_names = {
                c.id: c.name or company_names.get(c.company_id, f"#{c.id}")
                for c in contacts
            }

        if not contact_ids:
            return jsonify({"error": "no unenriched contacts found"}), 404

        _enrich_progress[run_id] = {
            "done": 0, "total": len(contact_ids), "failed": 0,
            "running": True, "current_name": None,
        }

        def _bulk(ids: list[int], names: dict) -> None:
            for i, cid in enumerate(ids):
                _enrich_progress[run_id]["current_name"] = names.get(cid, "")
                try:
                    # Hard 3-minute cap per contact so a hung scrape/SMTP call
                    # can't freeze the entire queue indefinitely.
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(enrich_contact, cid).result(timeout=180)
                except concurrent.futures.TimeoutError:
                    logger.warning(f"Bulk enrich timed out for contact {cid} (>180s)")
                    _enrich_progress[run_id]["failed"] += 1
                except Exception as e:
                    logger.warning(f"Bulk enrich failed for contact {cid}: {e}")
                    _enrich_progress[run_id]["failed"] += 1
                _enrich_progress[run_id]["done"] += 1
                if i < len(ids) - 1:
                    time.sleep(2)
            _enrich_progress[run_id]["running"] = False
            _enrich_progress[run_id]["current_name"] = None

        threading.Thread(target=_bulk, args=(contact_ids, contact_names), daemon=True).start()
        return jsonify({"started": True, "total": len(contact_ids)}), 202

    @app.route("/run/<int:run_id>/enrich-status")
    @_require_auth
    def enrich_status(run_id):
        progress = _enrich_progress.get(run_id, {})
        return jsonify(progress)

    # ── Quick Run ─────────────────────────────────────────────────────────────

    @app.route("/quick-run", methods=["GET", "POST"])
    @_require_auth
    def quick_run_page():
        import datetime as _dt
        from src.database.session import get_session
        from src.database.models import Profile, DiscoveryRun
        from src.scheduler import load_profile
        from src.integrations.zoho_mail import is_configured as _zoho_ok

        if request.method == "GET":
            with get_session() as db:
                from src.database.models import Profile as _Prof
                profs = db.query(Profile).filter_by(active=True).order_by(Profile.id).all()
                profiles_data = [{"id": p.id, "name": p.name} for p in profs]
                # Recent runs (last 15, completed or running) for the history list
                recent_runs_q = (
                    db.query(DiscoveryRun, Profile)
                    .outerjoin(Profile, DiscoveryRun.profile_id == Profile.id)
                    .order_by(DiscoveryRun.id.desc())
                    .limit(15)
                    .all()
                )
                recent_runs = [
                    {
                        "run_id": r.id,
                        "run_date": r.run_date.isoformat() if r.run_date else "",
                        "status": r.status,
                        "profile_name": p.name if p else "Default",
                        "companies_found": r.companies_found or 0,
                    }
                    for r, p in recent_runs_q
                ]
            return render_template("quick_run.html", profiles=profiles_data, run_id=None,
                                   phase=None, enrich={}, contacts_data=[], error="",
                                   zoho_configured=_zoho_ok(), profile_name="",
                                   recent_runs=recent_runs)

        profile_id_str = request.form.get("profile_id", "")
        profile_id = int(profile_id_str) if profile_id_str.isdigit() else None
        pid, profile = load_profile(profile_id)

        with get_session() as db:
            run = DiscoveryRun(
                run_date=_dt.date.today(),
                started_at=_dt.datetime.utcnow(),
                status="running",
                profile_id=pid,
            )
            db.add(run)
            db.flush()
            run_id = run.id

        _quick_run_state[run_id] = {"phase": "discovering", "enrich": {}, "error": ""}
        threading.Thread(target=_do_quick_run, args=(run_id, pid, profile), daemon=True).start()
        return redirect(f"/quick-run/{run_id}")

    @app.route("/quick-run/<int:run_id>")
    @_require_auth
    def quick_run_results(run_id):
        from src.database.session import get_session
        from src.database.models import DiscoveryRun, Company, Contact, Opportunity, DailyReport, Profile as ProfileModel
        from src.integrations.zoho_mail import is_configured as _zoho_ok

        state = _quick_run_state.get(run_id, {})
        phase = state.get("phase", "")
        enrich = state.get("enrich", {})

        if not phase:
            with get_session() as db:
                run = db.get(DiscoveryRun, run_id)
                if not run:
                    abort(404)
                phase = {"completed": "done", "failed": "error"}.get(run.status, "discovering")

        contacts_data = []
        profile_name = ""

        if phase in ("enriching", "done"):
            with get_session() as db:
                run = db.get(DiscoveryRun, run_id)
                if run and run.profile_id:
                    p = db.get(ProfileModel, run.profile_id)
                    profile_name = p.name if p else ""

                opps_cos = (
                    db.query(Opportunity, Company)
                    .join(Company, Opportunity.company_id == Company.id)
                    .filter(Opportunity.run_id == run_id)
                    .order_by(Opportunity.score.desc())
                    .all()
                )
                company_ids = [co.id for _, co in opps_cos]
                all_contacts = (
                    db.query(Contact)
                    .filter(Contact.company_id.in_(company_ids))
                    .order_by(Contact.confidence_score.desc())
                    .all()
                ) if company_ids else []
                ctcs_by_co: dict[int, list] = {}
                for c in all_contacts:
                    ctcs_by_co.setdefault(c.company_id, []).append(c)

                report = db.query(DailyReport).filter_by(run_id=run_id).first()
                drafts_raw = (report.report_json or {}).get("outreach_drafts", []) if report else []
                email_drafts: dict[str, dict] = {}
                for d in drafts_raw:
                    cn = d.get("company_name", "")
                    if cn and d.get("channel") == "email" and cn not in email_drafts:
                        email_drafts[cn] = d

                # ContactStatus for all companies in this run
                from src.database.models import ContactStatus
                contact_statuses = {
                    s.company_id: s for s in
                    db.query(ContactStatus).filter(ContactStatus.company_id.in_(company_ids)).all()
                }

                fresh_ids = state.get("fresh_contact_ids")  # None if old run / state lost after restart

                for opp, co in opps_cos:
                    draft = email_drafts.get(co.name, {})
                    desc = (co.description or "").strip()
                    if len(desc) > 90:
                        desc = desc[:90] + "…"
                    cs = contact_statuses.get(co.id)
                    is_pushed = opp.zoho_pushed_at is not None
                    for ct in ctcs_by_co.get(co.id, []):
                        # Skip contacts from previous runs (only show new ones from this run)
                        if fresh_ids is not None and ct.id not in fresh_ids:
                            continue
                        # Eligibility for a safe push: real verified/probable email, a draft,
                        # and the company isn't already contacted or pushed.
                        has_body = bool(draft.get("body"))
                        eligible = bool(
                            ct.email
                            and ct.email_status in ("verified", "probable")
                            and has_body and cs is None and not is_pushed
                        )
                        if eligible:
                            reason = ""
                        elif cs is not None:
                            reason = "ya contactado"
                        elif is_pushed:
                            reason = "ya pusheado"
                        elif not ct.email:
                            reason = "sin email"
                        elif ct.email_status not in ("verified", "probable"):
                            reason = "email rebotó / sin verificar"
                        else:
                            reason = "sin draft"
                        contacts_data.append({
                            "company_name": co.name,
                            "company_id": co.id,
                            "location": co.location or "",
                            "description": desc,
                            "score": opp.score or 0,
                            "contact_id": ct.id,
                            "contact_name": ct.name or "",
                            "contact_role": ct.role or "",
                            "email": ct.email or "",
                            "email_status": ct.email_status or "",
                            "linkedin_url": ct.linkedin_url or "",
                            "enriched": ct.enriched_at is not None,
                            "subject": draft.get("subject_line", ""),
                            "body": draft.get("body", ""),
                            "is_contacted": cs is not None,
                            "is_pushed": is_pushed,
                            "eligible": eligible,
                            "reason": reason,
                            "contacted_at": str(cs.contacted_at)[:10] if cs and cs.contacted_at else "",
                        })

        return render_template(
            "quick_run.html",
            run_id=run_id,
            phase=phase,
            enrich=enrich,
            contacts_data=contacts_data,
            profile_name=profile_name,
            zoho_configured=_zoho_ok(),
            error=state.get("error", ""),
            profiles=[],
            recent_runs=[],
        )

    @app.route("/quick-run/<int:run_id>/status")
    @_require_auth
    def quick_run_status(run_id):
        state = _quick_run_state.get(run_id, {})
        if not state:
            from src.database.session import get_session
            from src.database.models import DiscoveryRun
            with get_session() as db:
                run = db.get(DiscoveryRun, run_id)
                if run:
                    phase = {"completed": "done", "failed": "error"}.get(run.status, "discovering")
                    return jsonify({"phase": phase})
        return jsonify(state)

    def _quick_push_eligible(run_id, only_contact_ids=None):
        """Push Zoho drafts for a Quick Run, applying the same safety guards as the worker:
        only verified/probable emails with a draft, skipping companies already contacted
        or pushed, and at most one contact per company per batch. If `only_contact_ids` is
        given, restrict to those contacts (still filtered for eligibility).
        Returns (created, skipped, skipped_reasons, errors)."""
        from src.database.session import get_session
        from src.database.models import Company, Contact, Opportunity, DailyReport, ContactStatus
        from src.integrations.zoho_mail import create_draft
        from src.tools.db_tools import mark_company_contacted
        from datetime import datetime, timezone

        only = set(only_contact_ids) if only_contact_ids is not None else None
        created, skipped, errors = 0, 0, []
        skipped_reasons: dict[str, int] = {}

        with get_session() as db:
            opps = {o.company_id: o for o in db.query(Opportunity).filter_by(run_id=run_id).all()}
            if not opps:
                return 0, 0, {}, ["sin oportunidades"]
            company_ids = list(opps.keys())

            statuses = {
                s.company_id for s in
                db.query(ContactStatus.company_id).filter(ContactStatus.company_id.in_(company_ids)).all()
            }
            report = db.query(DailyReport).filter_by(run_id=run_id).first()
            drafts_raw = (report.report_json or {}).get("outreach_drafts", []) if report else []
            email_drafts: dict[str, dict] = {}
            for d in drafts_raw:
                cn = d.get("company_name", "")
                if cn and d.get("channel") == "email" and cn not in email_drafts:
                    email_drafts[cn] = d

            contacts = (
                db.query(Contact, Company)
                .join(Company, Contact.company_id == Company.id)
                .filter(Contact.company_id.in_(company_ids))
                .order_by(Contact.is_primary.desc().nullslast(), Contact.confidence_score.desc().nullslast())
                .all()
            )

            def _bump(reason):
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

            done_companies: set[int] = set()
            for ct, co in contacts:
                if only is not None and ct.id not in only:
                    continue
                opp = opps.get(co.id)
                draft = email_drafts.get(co.name, {})
                body = draft.get("body", "")
                # Eligibility (same guards as the worker push)
                if co.id in statuses:
                    skipped += 1; _bump("ya contactado"); continue
                if opp is None or opp.zoho_pushed_at is not None:
                    skipped += 1; _bump("ya pusheado"); continue
                if not ct.email or ct.email_status not in ("verified", "probable"):
                    skipped += 1; _bump("email rebotó / sin verificar"); continue
                if not body:
                    skipped += 1; _bump("sin draft"); continue
                if co.id in done_companies:
                    skipped += 1; _bump("otro contacto de la empresa ya pusheado"); continue

                subject = draft.get("subject_line") or f"Outreach — {co.name}"
                try:
                    create_draft(to_address=ct.email, subject=subject, content=body)
                    opp.zoho_pushed_at = datetime.now(timezone.utc)
                    mark_company_contacted(db, co.id, method="email")
                    db.flush()
                    created += 1
                    done_companies.add(co.id)
                except Exception as e:
                    errors.append(f"{co.name}: {e}")

        return created, skipped, skipped_reasons, errors

    @app.route("/quick-run/<int:run_id>/push-all-zoho", methods=["POST"])
    @_require_auth
    def quick_run_push_all_zoho(run_id):
        """Push every ELIGIBLE contact (verified/probable, not yet contacted/pushed)."""
        from src.integrations.zoho_mail import is_configured
        if not is_configured():
            return jsonify({"error": "Zoho no configurado"}), 503
        created, skipped, reasons, errors = _quick_push_eligible(run_id)
        return jsonify({"created": created, "skipped": skipped,
                        "skipped_reasons": reasons, "errors": errors})

    @app.route("/quick-run/<int:run_id>/push-selected-zoho", methods=["POST"])
    @_require_auth
    def quick_run_push_selected_zoho(run_id):
        """Push only the selected contacts (still filtered for eligibility)."""
        from src.integrations.zoho_mail import is_configured
        if not is_configured():
            return jsonify({"error": "Zoho no configurado"}), 503
        data = request.get_json(silent=True) or {}
        ids = data.get("contact_ids") or []
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return jsonify({"error": "contact_ids inválido"}), 400
        if not ids:
            return jsonify({"error": "nada seleccionado"}), 400
        created, skipped, reasons, errors = _quick_push_eligible(run_id, only_contact_ids=ids)
        return jsonify({"created": created, "skipped": skipped,
                        "skipped_reasons": reasons, "errors": errors})

    @app.route("/quick-run/<int:run_id>/push-one-zoho", methods=["POST"])
    @_require_auth
    def quick_run_push_one_zoho(run_id):
        from src.integrations.zoho_mail import create_draft, is_configured
        if not is_configured():
            return jsonify({"error": "Zoho no configurado"}), 503
        data = request.get_json(silent=True) or {}
        email = data.get("email", "").strip()
        if not email:
            return jsonify({"error": "email requerido"}), 400
        company_id = data.get("company_id")
        try:
            create_draft(
                to_address=email,
                subject=data.get("subject", "").strip() or "Outreach",
                content=data.get("body", "").strip(),
            )
            if company_id:
                from src.database.session import get_session
                from src.tools.db_tools import mark_company_contacted
                with get_session() as db:
                    mark_company_contacted(db, int(company_id), method="email")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Contacted Companies Report ───────────────────────────────────────────

    @app.route("/contacts-report")
    @_require_auth
    def contacts_report():
        from src.database.session import get_session
        from src.database.models import Company, ContactStatus, Contact, Opportunity, DiscoveryRun, Profile
        from datetime import date

        today = date.today()

        with get_session() as db:
            pairs = (
                db.query(Company, ContactStatus)
                .join(ContactStatus, Company.id == ContactStatus.company_id)
                .order_by(Company.name.asc())
                .all()
            )

            if not pairs:
                return render_template(
                    "contacts_report.html",
                    by_profile={}, profiles_order=[], total=0, needs_follow_up=0, overdue=0,
                    bounced_count=0, success_count=0,
                )

            company_ids = [c.id for c, _ in pairs]

            # Contacts per company — single bulk query
            contacts_rows = (
                db.query(Contact)
                .filter(Contact.company_id.in_(company_ids))
                .order_by(Contact.confidence_score.desc())
                .all()
            )
            contacts_by_company: dict = {}
            for c in contacts_rows:
                contacts_by_company.setdefault(c.company_id, []).append({
                    "id": c.id,
                    "name": c.name or "",
                    "role": c.role or "",
                    "email": c.email or "",
                    "email_status": c.email_status or "",
                    "email_source": c.email_source or "",
                    "linkedin_url": c.linkedin_url or "",
                    "phone_whatsapp": c.phone_whatsapp or "",
                })

            # Best opportunity per company — single bulk query
            opp_rows = (
                db.query(Opportunity, DiscoveryRun, Profile)
                .join(DiscoveryRun, Opportunity.run_id == DiscoveryRun.id)
                .outerjoin(Profile, DiscoveryRun.profile_id == Profile.id)
                .filter(Opportunity.company_id.in_(company_ids))
                .order_by(DiscoveryRun.run_date.desc(), Opportunity.score.desc())
                .all()
            )
            best_opp: dict = {}
            opp_profile: dict = {}
            for opp, run, profile in opp_rows:
                if opp.company_id not in best_opp:
                    best_opp[opp.company_id] = opp
                    opp_profile[opp.company_id] = profile

            # ── Deduplicate companies that point to the same real business ──
            # The same company can exist as multiple rows (name variants, missing
            # domain on one run). Group by domain or normalized name so it shows
            # once and feedback targets a single canonical record.
            from src.tools.db_tools import normalize_company_name

            def _dedup_key(c) -> str:
                if c.domain:
                    return "d:" + c.domain.lower().strip()
                norm = normalize_company_name(c.name)
                return "n:" + norm if norm else f"id:{c.id}"

            def _feedback_weight(s) -> int:
                w = 0
                if s.response_received:
                    w += 4
                if s.follow_up_date:
                    w += 2
                if s.comment or s.contact_method:
                    w += 1
                return w

            groups: dict = {}          # key → list of (company, status)
            group_order: list = []
            for company, status in pairs:   # already ordered by contacted_at desc
                key = _dedup_key(company)
                if key not in groups:
                    groups[key] = []
                    group_order.append(key)
                groups[key].append((company, status))

            # Serialize all data to plain dicts while session is open
            companies_data = []
            for key in group_order:
                members = groups[key]
                # Canonical = richest feedback, tie-break = most recent (list order)
                company, status = max(
                    members,
                    key=lambda m: (_feedback_weight(m[1]), -members.index(m)),
                )
                # Merge contacts from every duplicate row, de-duped by email/name
                merged_contacts: list = []
                seen_ct: set = set()
                for m_company, _ in members:
                    for ct in contacts_by_company.get(m_company.id, []):
                        sig = (ct.get("email") or "").lower() or (ct.get("name") or "").lower()
                        if sig and sig in seen_ct:
                            continue
                        if sig:
                            seen_ct.add(sig)
                        merged_contacts.append(ct)

                # Best opportunity across all duplicate rows
                opp = None
                profile = None
                for m_company, _ in members:
                    m_opp = best_opp.get(m_company.id)
                    if m_opp and (opp is None or (m_opp.score or 0) > (opp.score or 0)):
                        opp = m_opp
                        profile = opp_profile.get(m_company.id)
                if profile is None:
                    profile = opp_profile.get(company.id)

                desc = company.description or ""
                words = desc.split()
                if len(words) > 40:
                    desc = " ".join(words[:40]) + "…"

                notable = None
                if opp and opp.insights:
                    for line in opp.insights.splitlines():
                        cleaned = line.strip().lstrip("•-* ").strip()
                        if cleaned:
                            notable = cleaned[:150]
                            break
                if not notable and opp and opp.score_explanation:
                    notable = opp.score_explanation.split(".")[0].strip()[:150]

                follow_up_date = status.follow_up_date
                follow_up_overdue = bool(follow_up_date and follow_up_date < today)
                follow_up_today = bool(follow_up_date and follow_up_date == today)
                needs_followup = bool(follow_up_date)

                website = company.website_url or ""
                domain = company.domain or ""
                display_url = domain or website.replace("https://", "").replace("http://", "").split("/")[0]

                companies_data.append({
                    "id": company.id,
                    "name": company.name or "",
                    "website_url": website,
                    "display_url": display_url[:35],
                    "location": company.location or "",
                    "description": desc,
                    "notable": notable,
                    "profile_name": profile.name if profile else "Default",
                    "score": opp.score if opp else None,
                    "contacts": merged_contacts,
                    "contacted_at": status.contacted_at.strftime("%d/%m/%Y") if status.contacted_at else "",
                    "contact_method": status.contact_method or "",
                    "response": status.response_received or "",
                    "comment": status.comment or "",
                    "follow_up_date": str(follow_up_date) if follow_up_date else "",
                    "follow_up_date_display": follow_up_date.strftime("%d/%m/%Y") if follow_up_date else "",
                    "follow_up_overdue": follow_up_overdue,
                    "follow_up_today": follow_up_today,
                    "needs_followup": needs_followup,
                    "has_bounced": any(c.get("email_status") == "bounced" for c in merged_contacts),
                    "is_success": (status.response_received or "") in
                                  ("replied", "interested", "meeting_scheduled"),
                })

            profiles_order: list = []
            by_profile: dict = {}
            for d in companies_data:
                pname = d["profile_name"]
                if pname not in by_profile:
                    by_profile[pname] = []
                    profiles_order.append(pname)
                by_profile[pname].append(d)

            for companies in by_profile.values():
                companies.sort(key=lambda x: x["name"].lower())

            total = len(companies_data)
            needs_follow_up = sum(1 for d in companies_data if d["needs_followup"])
            overdue = sum(1 for d in companies_data if d["follow_up_overdue"])
            bounced_count = sum(1 for d in companies_data if d["has_bounced"])
            success_count = sum(1 for d in companies_data if d["is_success"])

        return render_template(
            "contacts_report.html",
            by_profile=by_profile,
            profiles_order=profiles_order,
            total=total,
            needs_follow_up=needs_follow_up,
            overdue=overdue,
            bounced_count=bounced_count,
            success_count=success_count,
        )

    @app.route("/follow-ups")
    @_require_auth
    def follow_ups():
        from sqlalchemy import func
        from src.database.session import get_session
        from src.database.models import Company, Contact, Opportunity, DiscoveryRun, Profile, ContactStatus
        from src.tools.followups import (
            select_followup_candidates, select_upcoming_followups, _aware,
            FOLLOWUP_FIRST_DAYS, FOLLOWUP_SECOND_DAYS,
        )
        from datetime import datetime, timezone, timedelta

        try:
            within_days = max(1, min(30, int(request.args.get("within", 7))))
        except (TypeError, ValueError):
            within_days = 7

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        replied_window = now - timedelta(days=30)

        def _disp_url(company) -> str:
            d = company.domain or ""
            w = (company.website_url or "")
            return (d or w.replace("https://", "").replace("http://", "").split("/")[0])[:35]

        with get_session() as db:
            # ── Due / pending (reuse the worker's eligibility logic) ──
            due = []
            for opp, company, contact, profile in select_followup_candidates(db):
                count = opp.followup_count or 0
                if count == 0:
                    base = _aware(opp.zoho_pushed_at)
                    target = FOLLOWUP_FIRST_DAYS
                else:
                    base = _aware(opp.last_followup_at)
                    target = FOLLOWUP_SECOND_DAYS - FOLLOWUP_FIRST_DAYS
                days_since = (now - base).days if base else 0
                due.append({
                    "company_id": opp.company_id,
                    "company": company.name or "",
                    "display_url": _disp_url(company),
                    "website_url": company.website_url or "",
                    "location": company.location or "",
                    "score": opp.score,
                    "profile_name": profile.name if profile else "Default",
                    "contact_name": contact.name or "",
                    "contact_role": contact.role or "",
                    "contact_email": contact.email or "",
                    "email_status": contact.email_status or "",
                    "stage": count + 1,
                    "days_since": days_since,
                    "overdue": days_since >= target + 3,
                })

            # ── Upcoming (eligible but cadence not yet due) ──
            upcoming = []
            for opp, company, contact, profile, due_date in select_upcoming_followups(db, within_days):
                days_until = max(0, (due_date - now).days)
                upcoming.append({
                    "company_id": opp.company_id,
                    "company": company.name or "",
                    "display_url": _disp_url(company),
                    "website_url": company.website_url or "",
                    "profile_name": profile.name if profile else "Default",
                    "contact_name": contact.name or "",
                    "contact_role": contact.role or "",
                    "contact_email": contact.email or "",
                    "email_status": contact.email_status or "",
                    "stage": (opp.followup_count or 0) + 1,
                    "days_until": days_until,
                    "due_display": due_date.strftime("%d/%m"),
                })

            # ── Drafted this week (weekly summary) ──
            drafted_rows = (
                db.query(Opportunity, Company, Profile)
                .join(Company, Opportunity.company_id == Company.id)
                .join(DiscoveryRun, Opportunity.run_id == DiscoveryRun.id)
                .outerjoin(Profile, DiscoveryRun.profile_id == Profile.id)
                .filter(Opportunity.last_followup_at.isnot(None))
                .filter(Opportunity.last_followup_at >= week_ago.replace(tzinfo=None))
                .order_by(Opportunity.last_followup_at.desc())
                .all()
            )
            drafted = [{
                "company_id": opp.company_id,
                "company": company.name or "",
                "display_url": _disp_url(company),
                "profile_name": profile.name if profile else "Default",
                "subject": opp.followup_subject or "",
                "stage": opp.followup_count or 0,
                "when": opp.last_followup_at.strftime("%d/%m %H:%M") if opp.last_followup_at else "",
            } for opp, company, profile in drafted_rows]

            # ── Replied (excluded going forward) ──
            replied_rows = (
                db.query(Contact, Company)
                .join(Company, Contact.company_id == Company.id)
                .filter(Contact.replied_at.isnot(None))
                .filter(Contact.replied_at >= replied_window.replace(tzinfo=None))
                .order_by(Contact.replied_at.desc())
                .all()
            )
            replied = [{
                "company_id": company.id,
                "contact_id": contact.id,
                "company": company.name or "",
                "contact_name": contact.name or "",
                "contact_email": contact.email or "",
                "when": contact.replied_at.strftime("%d/%m/%Y") if contact.replied_at else "",
            } for contact, company in replied_rows]

            # ── Stats: contacted & waiting for a response ──
            replied_sq = db.query(Contact.company_id).filter(Contact.replied_at.isnot(None))
            responded_sq = (
                db.query(ContactStatus.company_id)
                .filter(ContactStatus.response_received.isnot(None))
            )
            waiting = (
                db.query(func.count(func.distinct(Opportunity.company_id)))
                .filter(Opportunity.zoho_pushed_at.isnot(None))
                .filter(~Opportunity.company_id.in_(replied_sq))
                .filter(~Opportunity.company_id.in_(responded_sq))
                .scalar()
            ) or 0

            stats = {
                "waiting": waiting,
                "due": len(due),
                "upcoming": len(upcoming),
                "drafted_week": len(drafted),
                "replied": len(replied),
            }

            due.sort(key=lambda x: x["company"].lower())
            upcoming.sort(key=lambda x: x["company"].lower())
            drafted.sort(key=lambda x: x["company"].lower())
            replied.sort(key=lambda x: x["company"].lower())

        return render_template(
            "follow_ups.html",
            due=due, upcoming=upcoming, drafted=drafted, replied=replied,
            stats=stats, within_days=within_days,
        )

    @app.route("/follow-ups/push-now", methods=["POST"])
    @_require_auth
    def follow_ups_push_now():
        from src.database.session import get_session
        from src.tools.followups import push_followup_now

        try:
            company_id = int(request.form.get("company_id", ""))
        except (TypeError, ValueError):
            flash("Empresa inválida.", "error")
            return redirect(url_for("follow_ups"))

        with get_session() as db:
            res = push_followup_now(db, company_id)
        flash(res["message"], "success" if res["ok"] else "error")
        return redirect(url_for("follow_ups"))

    @app.route("/contact/<int:contact_id>/clear-replied", methods=["POST"])
    @_require_auth
    def contact_clear_replied(contact_id: int):
        from src.database.session import get_session
        from src.database.models import Contact, ContactStatus
        with get_session() as db:
            c = db.query(Contact).filter_by(id=contact_id).first()
            if not c:
                flash("Contacto no encontrado.", "error")
                return redirect(url_for("follow_ups"))
            c.replied_at = None
            # Clear auto-set response_received only if it was set to "replied"
            # (leave manually-set values like "interested" or "meeting_scheduled" untouched)
            cs = db.query(ContactStatus).filter_by(company_id=c.company_id).first()
            if cs and cs.response_received == "replied":
                cs.response_received = None
            db.commit()
        flash("Respuesta borrada — la empresa vuelve al circuito de follow-ups.", "success")
        return redirect(url_for("follow_ups"))

    @app.route("/search")
    @_require_auth
    def search():
        import math
        from src.database.session import get_session

        PAGE_SIZE = 25
        q = request.args.get("q", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except (TypeError, ValueError):
            page = 1

        contacts = []
        with get_session() as db:
            companies, total_companies = _search_companies_data(
                db, q, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
            )
            total_pages = max(1, math.ceil(total_companies / PAGE_SIZE)) if total_companies else 1
            if page > total_pages:
                page = total_pages
                companies, total_companies = _search_companies_data(
                    db, q, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
                )
            if q:
                contacts = _search_contacts_data(db, q)

        return render_template(
            "search.html",
            q=q,
            companies=companies,
            contacts=contacts,
            page=page,
            total_pages=total_pages,
            total_companies=total_companies,
            page_size=PAGE_SIZE,
        )

    @app.route("/search/export/<fmt>")
    @_require_auth
    def export_search(fmt):
        import os
        import tempfile
        from src.database.session import get_session
        from src.export import export_companies_csv, export_companies_markdown

        if fmt not in ("csv", "md"):
            abort(404)

        q = request.args.get("q", "").strip()
        with get_session() as db:
            companies, _ = _search_companies_data(db, q, limit=5000, offset=0, desc_len=1000)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}")
        tmp.close()
        try:
            if fmt == "csv":
                export_companies_csv(companies, tmp.name)
                mimetype, filename = "text/csv", "blest-empresas.csv"
            else:
                export_companies_markdown(companies, tmp.name, query=q)
                mimetype, filename = "text/markdown", "blest-empresas.md"
            with open(tmp.name, "rb") as f:
                content = f.read()
        finally:
            os.unlink(tmp.name)

        return Response(
            content,
            mimetype=mimetype,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

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
