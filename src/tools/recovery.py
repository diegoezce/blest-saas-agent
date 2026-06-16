"""Bounced-email recovery: take contacts marked `email_status="bounced"` and try
to find a *different* working address — the bounce tells us the previous guess/pattern
was wrong, so we blocklist it and re-run the enrichment pipeline (which now skips
blocklisted addresses and tries the other patterns / Hunter).

Shared by the worker recovery phase and `python run.py --recover-bounced`.

Note: confirming the alternative address still needs a working verifier (NeverBounce /
MillionVerifier with credits). With no credits, recovery can only produce another
*unverified* guess — so keep a verifier funded for this to actually reduce bounces.
"""
import logging
import time

from src.database.session import get_session
from src.database.models import Contact
from src.enrichment.pipeline import enrich_contact, EnrichmentResult

logger = logging.getLogger(__name__)


def select_bounced_contacts(session, limit: int = 50) -> list[Contact]:
    """Named contacts whose email bounced — candidates to recover."""
    return (
        session.query(Contact)
        .filter(Contact.email_status == "bounced")
        .filter(Contact.name.isnot(None))
        .filter(Contact.name != "")
        .order_by(Contact.enriched_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )


def recover_contact(contact_id: int) -> EnrichmentResult | None:
    """Blocklist the bounced address, clear the email, and re-run enrichment.

    The pipeline reads `enrichment_log['bad_emails']` and never re-proposes them, so
    a fresh run targets the remaining patterns / Hunter result.
    """
    with get_session() as session:
        c = session.get(Contact, contact_id)
        if not c:
            return None
        # Copy the dict so the attribute reassignment is a NEW object — SQLAlchemy's
        # change detection ignores in-place mutation of a JSON column.
        log = dict(c.enrichment_log) if isinstance(c.enrichment_log, dict) else {}
        bad = {e.lower() for e in log.get("bad_emails", []) if e}
        if c.email:
            bad.add(c.email.lower())
        log["bad_emails"] = sorted(bad)
        c.enrichment_log = log
        # Clear the bounced address so the pipeline treats this as needing a new email.
        c.email = None
        c.email_status = None
        c.email_source = None
        session.commit()

    return enrich_contact(contact_id)


def run_recovery(limit: int = 15, delay: float = 2.0) -> dict:
    """Recover up to `limit` bounced contacts. Returns {processed, recovered, still_bad}."""
    with get_session() as session:
        ids = [c.id for c in select_bounced_contacts(session, limit)]

    if not ids:
        logger.info("Recovery: no bounced contacts to retry")
        return {"processed": 0, "recovered": 0, "still_bad": 0}

    logger.info(f"Recovery: retrying {len(ids)} bounced contact(s)")
    recovered = 0
    for cid in ids:
        try:
            res = recover_contact(cid)
            if res and res.email_status in ("verified", "probable"):
                recovered += 1
                logger.info(f"  ✅ contact #{cid} → {res.email} ({res.email_status})")
            else:
                status = res.email_status if res else "error"
                logger.info(f"  🔴 contact #{cid} → no new email ({status})")
        except Exception as exc:
            logger.error(f"  ❌ contact #{cid} recovery failed: {exc}")
        time.sleep(delay)

    logger.info(f"Recovery done: {recovered}/{len(ids)} found a new email")
    return {"processed": len(ids), "recovered": recovered, "still_bad": len(ids) - recovered}
