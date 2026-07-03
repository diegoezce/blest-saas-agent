"""
Weekly PostgreSQL backup → Cloudflare R2.

Runs as a standalone script (separate Task Scheduler entry, weekly).
Does NOT touch the worker phases — purely backup.

Steps:
  1. pg_dump the Railway database (plain SQL, gzip compressed)
  2. Upload to R2 under backups/blest/YYYY-MM-DD_HH-MM.sql.gz
  3. Prune backups older than RETENTION_DAYS

Required env vars (add to worker/.env):
  DATABASE_URL          — postgresql+psycopg2://... (same as worker)
  R2_ACCESS_KEY_ID      — Cloudflare R2 access key
  R2_SECRET_ACCESS_KEY  — Cloudflare R2 secret key
  R2_ENDPOINT_URL       — https://<account_id>.r2.cloudflarestorage.com
  R2_BUCKET_NAME        — bucket name

Optional:
  BACKUP_PREFIX         — object key prefix (default: backups/blest/)
  BACKUP_RETENTION_DAYS — days to keep (default: 30)
  PG_DUMP_PATH          — path to pg_dump.exe if not on PATH
                          e.g. C:\\Program Files\\PostgreSQL\\16\\bin\\pg_dump.exe

Run:
  py -3.11 worker/backup_db.py

Schedule (admin shell, weekly on Sunday at 03:00):
  schtasks /Create /TN "BlestBackup" /TR "C:\\path\\to\\worker\\run_backup.bat" /SC WEEKLY /D SUN /ST 03:00 /F
"""

import gzip
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env from worker directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

def _setup_logging() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(__file__).parent / "backup_task.log", encoding="utf-8"),
        ],
    )

_setup_logging()
logger = logging.getLogger(__name__)

BACKUP_PREFIX = os.getenv("BACKUP_PREFIX", "backups/blest/")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def _parse_db_url(url: str) -> dict:
    """Extract host, port, dbname, user, password from a psycopg2 DATABASE_URL."""
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    m = re.match(
        r"postgresql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:/]+):(?P<port>\d+)/(?P<dbname>.+)",
        url,
    )
    if not m:
        logger.error("Cannot parse DATABASE_URL: %s", url[:40] + "...")
        sys.exit(1)
    return m.groupdict()


def _find_pg_dump() -> str:
    custom = os.getenv("PG_DUMP_PATH")
    if custom and Path(custom).exists():
        return custom
    found = shutil.which("pg_dump")
    if found:
        return found
    # Common Windows install paths
    for ver in ("18", "17", "16", "15", "14"):
        candidate = Path(f"C:/Program Files/PostgreSQL/{ver}/bin/pg_dump.exe")
        if candidate.exists():
            return str(candidate)
    logger.error(
        "pg_dump not found. Install PostgreSQL client tools or set PG_DUMP_PATH."
    )
    sys.exit(1)


def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def run_backup() -> None:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("=" * 60)
    logger.info("BACKUP START — %s", run_ts)
    logger.info("=" * 60)

    _require_env("DATABASE_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                 "R2_ENDPOINT_URL", "R2_BUCKET_NAME")

    db = _parse_db_url(os.environ["DATABASE_URL"])
    pg_dump = _find_pg_dump()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    object_key = f"{BACKUP_PREFIX}{timestamp}.sql.gz"

    logger.info("Starting backup → %s", object_key)
    logger.info("pg_dump: %s", pg_dump)

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Dump to plain SQL then gzip on the fly
        cmd = [
            pg_dump,
            "--host", db["host"],
            "--port", db["port"],
            "--username", db["user"],
            "--dbname", db["dbname"],
            "--format", "plain",
            "--no-password",
            "--encoding", "UTF8",
        ]

        logger.info("Running pg_dump...")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error("pg_dump failed (exit %d): %s", result.returncode,
                         result.stderr.decode("utf-8", errors="replace")[:500])
            sys.exit(1)

        raw_bytes = result.stdout
        logger.info("Dump complete: %s bytes raw SQL", f"{len(raw_bytes):,}")

        with gzip.open(tmp_path, "wb", compresslevel=6) as gz:
            gz.write(raw_bytes)

        compressed_size = Path(tmp_path).stat().st_size
        logger.info("Compressed to %s bytes (%.1f%%)", f"{compressed_size:,}",
                    100 * compressed_size / max(len(raw_bytes), 1))

        # Upload to R2
        bucket = os.environ["R2_BUCKET_NAME"]
        logger.info("Uploading to R2 bucket '%s'...", bucket)
        _s3_client().upload_file(tmp_path, bucket, object_key)
        logger.info("Backup uploaded OK: %s", object_key)

        _prune_old_backups()
        logger.info("=" * 60)
        logger.info("BACKUP DONE  -- %s", run_ts)
        logger.info("=" * 60)

    finally:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink()


def _prune_old_backups() -> None:
    from botocore.exceptions import BotoCoreError, ClientError
    bucket = os.environ["R2_BUCKET_NAME"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    client = _s3_client()

    try:
        paginator = client.get_paginator("list_objects_v2")
        to_delete = []
        for page in paginator.paginate(Bucket=bucket, Prefix=BACKUP_PREFIX):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < cutoff:
                    to_delete.append({"Key": obj["Key"]})

        if to_delete:
            client.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
            logger.info("Pruned %d old backup(s) (older than %d days)",
                        len(to_delete), RETENTION_DAYS)
        else:
            logger.info("No old backups to prune.")
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Pruning failed (non-fatal): %s", exc)


if __name__ == "__main__":
    run_backup()
