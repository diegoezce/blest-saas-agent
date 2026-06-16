#!/usr/bin/env python3
"""
Blest Lead Discovery Agent

Usage:
  python run.py                        Run discovery once and show dashboard
  python run.py --schedule             Start daily scheduler daemon
  python run.py --web                  Start web UI + embedded daily scheduler
  python run.py --report               Show last run's dashboard
  python run.py --report --date DATE   Show report for DATE (YYYY-MM-DD)
  python run.py --setup                Initialize database tables only
  python run.py --enrich-run <ID>      Enrich all contacts for a run
  python run.py --zoho-auth <TOKEN>    Store Zoho Mail OAuth credentials
  python run.py --check-bounces        Scan Zoho inbox for bounces, mark matched contacts
  python run.py --detect-replies       Scan Zoho inbox for replies, mark answered contacts
  python run.py --follow-ups           Generate + push follow-up drafts for unanswered leads
"""
import argparse
import logging
import pathlib
import sys


def setup_logging() -> None:
    from logging.handlers import RotatingFileHandler
    from src.config import settings

    log_path = pathlib.Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(settings.report_output_dir).mkdir(parents=True, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=handlers,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Blest Lead Discovery Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup", action="store_true", help="Initialize database and exit")
    parser.add_argument("--schedule", action="store_true", help="Start daily scheduler daemon")
    parser.add_argument("--web", action="store_true", help="Start web UI + embedded daily scheduler")
    parser.add_argument("--report", action="store_true", help="Show last (or dated) report")
    parser.add_argument("--date", type=str, help="Date for --report (YYYY-MM-DD)", default=None)
    parser.add_argument("--profile", type=int, default=None, help="Profile ID to use for the run")
    parser.add_argument("--enrich-run", type=int, default=None, metavar="RUN_ID",
                        help="Enrich all contacts for a given run ID")
    parser.add_argument("--zoho-auth", type=str, default=None, metavar="GRANT_TOKEN",
                        help="Exchange a Zoho self-client grant token for stored OAuth credentials")
    parser.add_argument("--check-bounces", action="store_true",
                        help="Scan the Zoho inbox for bounces and mark matched contacts as bounced")
    parser.add_argument("--detect-replies", action="store_true",
                        help="Scan the Zoho inbox for replies and mark answered contacts (replied_at)")
    parser.add_argument("--follow-ups", action="store_true",
                        help="Generate and push follow-up drafts for contacted leads that haven't replied")
    args = parser.parse_args()

    setup_logging()

    from src.database.session import init_db
    init_db()

    if args.setup:
        print("✅ Database initialized.")
        return

    if args.report:
        from src.dashboard import render_last_run
        target = None
        if args.date:
            import datetime
            try:
                target = datetime.date.fromisoformat(args.date)
            except ValueError:
                print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
                sys.exit(1)
        report_data = render_last_run(target_date=target)
        if report_data:
            from src.export import export_markdown, export_csv
            run_date = report_data.get("run_date", "unknown")
            pathlib.Path("reports").mkdir(exist_ok=True)
            export_markdown(report_data, f"reports/{run_date}.md")
            export_csv(report_data, f"reports/{run_date}.csv")
            print(f"Guardado: reports/{run_date}.md + .csv")
        return

    if args.schedule:
        from src.scheduler import start_scheduler
        start_scheduler()
        return

    if args.web:
        from src.web import start_web_server
        start_web_server()
        return

    if args.enrich_run:
        from src.database.session import get_session
        from src.database.models import Contact, Opportunity
        from src.enrichment.pipeline import enrich_contact

        run_id = args.enrich_run
        with get_session() as session:
            opp_company_ids = [
                o.company_id for o in
                session.query(Opportunity).filter_by(run_id=run_id).all()
            ]
            contact_ids = [
                c.id for c in
                session.query(Contact).filter(Contact.company_id.in_(opp_company_ids)).all()
            ] if opp_company_ids else []

        if not contact_ids:
            print(f"No contacts found for run {run_id}.")
            return

        print(f"Enriching {len(contact_ids)} contacts for run {run_id}...")
        for i, cid in enumerate(contact_ids, 1):
            result = enrich_contact(cid)
            status = result.email_status or "skipped"
            email = result.email or "(none)"
            print(f"  [{i}/{len(contact_ids)}] contact {cid}: {status} — {email}")
        print("Done.")
        return

    if args.zoho_auth:
        from src.integrations.zoho_mail import exchange_grant_token
        try:
            exchange_grant_token(args.zoho_auth)
            print("OK: Zoho Mail configured. Token stored in .zoho_tokens.json")
        except Exception as e:
            print(f"ERROR: Zoho auth failed: {e}")
            sys.exit(1)
        return

    if args.check_bounces:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        from src.integrations.zoho_mail import is_configured
        from src.tools.bounces import scan_and_match, mark_bounced

        if not is_configured():
            print("Zoho no configurado. Corre: python run.py --zoho-auth <grant_token>")
            sys.exit(1)
        try:
            summary = scan_and_match()
        except Exception as e:
            print(f"ERROR: no se pudo leer Zoho (falta el scope de lectura?): {e}")
            sys.exit(1)

        print(f"Revisados {summary['checked']} mensajes | {summary['bounce_messages']} rebotes | "
              f"{summary['matched_count']} matchean contactos "
              f"({summary['new_count']} nuevos, {summary['already_count']} ya marcados)")
        for m in summary["matched"]:
            print(f"  - {m['email']} ({m['name']}){' [ya]' if m['already'] else ''}")
        if summary["new_count"]:
            marked = mark_bounced(summary["addresses"])
            print(f"Marcados {marked} contactos como rebotados (email_status=bounced).")
        else:
            print("Nada nuevo para marcar.")
        return

    if args.detect_replies:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        from src.integrations.zoho_mail import is_configured
        from src.tools.followups import detect_replies

        if not is_configured():
            print("Zoho no configurado. Corre: python run.py --zoho-auth <grant_token>")
            sys.exit(1)
        try:
            res = detect_replies()
        except Exception as e:
            print(f"ERROR: no se pudo leer Zoho (falta el scope de lectura?): {e}")
            sys.exit(1)
        print(f"Revisados {res['checked']} mensajes | {res['senders']} remitentes | "
              f"{res['matched']} matchean contactos | {res['newly_marked']} marcados como respondieron")
        return

    if args.follow_ups:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        from src.integrations.zoho_mail import is_configured
        from src.tools.followups import run_followups
        from src.database.session import get_session

        if not is_configured():
            print("Zoho no configurado. Corre: python run.py --zoho-auth <grant_token>")
            sys.exit(1)
        try:
            with get_session() as db:
                res = run_followups(db, batch=50, delay=1.0)
        except Exception as e:
            print(f"ERROR: no se pudieron generar follow-ups: {e}")
            sys.exit(1)
        print(f"Respuestas marcadas: {res['replies_detected']} | "
              f"Candidatos: {res['candidates']} | Drafts creados: {res['drafted']}")
        return

    # Default: run once (optionally with a specific profile)
    from src.scheduler import run_workflow_once
    run_workflow_once(profile_id=args.profile)


if __name__ == "__main__":
    main()
