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

    # Default: run once
    from src.scheduler import run_workflow_once
    run_workflow_once()


if __name__ == "__main__":
    main()
