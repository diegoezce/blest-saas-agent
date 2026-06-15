"""
Blest Lead Hunter Worker
Runs every 2 days via Windows Task Scheduler.

Phase 1 — Enrichment: finds emails for contacts that don't have one yet.
Phase 2 — Zoho push:  pushes outreach drafts for contacts that now have a
           verified/probable email and haven't been sent to Zoho yet.

Reads/writes directly to the Railway PostgreSQL database via DATABASE_URL.
All src/ modules are reused as-is; no code is duplicated.

Run from the project root:
    python worker/worker.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow importing from the project root (src/ package)
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ── Logging setup ────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "worker.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
ENRICH_BATCH   = int(os.getenv("WORKER_ENRICH_BATCH", "15"))
PUSH_BATCH     = int(os.getenv("WORKER_PUSH_BATCH", "15"))
ENRICH_DELAY_S = float(os.getenv("WORKER_ENRICH_DELAY", "3"))   # between contacts
PUSH_DELAY_S   = float(os.getenv("WORKER_PUSH_DELAY", "1"))     # between Zoho calls


# ── Draft generation (only called when Opportunity.outreach_draft is NULL) ──

def _generate_draft(company, contact, opportunity, profile) -> tuple[str, str]:
    """
    Generate an outreach draft via Claude Haiku.
    Returns (subject_line, body).
    """
    import anthropic
    import instructor
    from src.prompts.outreach import OUTREACH_PROMPT
    from src.schemas.outputs import CompanyOutreach

    po = {
        "agent_company_name":  (profile.agent_company_name if profile else "Blest"),
        "agent_description":   (profile.agent_description  if profile else "a corporate English training provider"),
        "outreach_tone":       (profile.outreach_tone       if profile else "warm"),
        "outreach_instructions": (profile.outreach_instructions if profile else "") or "",
        "search_focus_terms":  (profile.search_focus_terms  if profile else "") or "",
    }

    custom = po["outreach_instructions"].strip()
    custom_block = (
        f"\nWHAT {po['agent_company_name'].upper()} OFFERS & HOW TO PITCH "
        f"(use only what is relevant; never contradict COMPANY DATA):\n{custom}\n"
        if custom else ""
    )

    payload = {
        "company_name":  company.name,
        "website":       company.website_url,
        "industry":      company.industry,
        "size":          company.size_estimate,
        "location":      company.location,
        "description":   company.description,
        "score":         opportunity.score if opportunity else None,
        "contact_name":  contact.name,
        "contact_role":  contact.role,
        "contact_email": contact.email,
    }

    client = instructor.from_anthropic(anthropic.Anthropic())
    result = client.messages.create(
        model=os.getenv("FAST_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": OUTREACH_PROMPT.format(
                agent_name=po["agent_company_name"],
                agent_description=po["agent_description"],
                outreach_service_description=(
                    po["search_focus_terms"] or "improve business communication"
                ),
                outreach_tone=po["outreach_tone"],
                company_and_insight_json=json.dumps(payload, ensure_ascii=False, indent=2),
                custom_instructions_block=custom_block,
            ),
        }],
        response_model=CompanyOutreach,
    )

    email_draft = next(
        (d for d in result.drafts if d.channel == "email"),
        result.drafts[0] if result.drafts else None,
    )
    if not email_draft:
        raise ValueError("No draft returned by Claude")

    return email_draft.subject_line, email_draft.body


# ── Phase 1: Enrichment ──────────────────────────────────────────────────────

def _run_enrichment_phase(db) -> list[int]:
    """Enrich up to ENRICH_BATCH contacts that have no email yet."""
    from src.database.models import Contact

    unenriched = (
        db.query(Contact)
        .filter(Contact.enriched_at.is_(None))
        .filter(Contact.company_id.isnot(None))
        .order_by(Contact.created_at.asc())
        .limit(ENRICH_BATCH)
        .all()
    )

    if not unenriched:
        logger.info("Enrichment: nothing to do (all contacts already enriched)")
        return []

    logger.info(f"Enrichment: processing {len(unenriched)} contacts")
    ok_ids = []

    for contact in unenriched:
        label = f"{contact.name or '?'} @ company #{contact.company_id}"
        try:
            from src.enrichment.pipeline import enrich_contact
            result = enrich_contact(contact.id)
            if result.email_status in ("verified", "probable"):
                ok_ids.append(contact.id)
                logger.info(f"  ✅ {label} → {result.email} ({result.email_status})")
            else:
                logger.info(f"  🔴 {label} → not found")
        except Exception as exc:
            logger.error(f"  ❌ {label} error: {exc}")

        time.sleep(ENRICH_DELAY_S)

    logger.info(f"Enrichment done: {len(ok_ids)}/{len(unenriched)} found an email")
    return ok_ids


# ── Phase 2: Zoho push ───────────────────────────────────────────────────────

def _run_push_phase(db) -> int:
    """
    Push outreach drafts to Zoho for contacts with emails that haven't been sent yet.
    Picks the best opportunity (highest score) per company.
    """
    from sqlalchemy import func, and_
    from src.database.models import Contact, Company, Opportunity, DiscoveryRun, Profile

    # Best opportunity per company (highest score, not yet pushed)
    best_score_sq = (
        db.query(
            Opportunity.company_id,
            func.max(Opportunity.score).label("max_score"),
        )
        .filter(Opportunity.zoho_pushed_at.is_(None))
        .group_by(Opportunity.company_id)
        .subquery()
    )

    best_opps = (
        db.query(Opportunity, Company, DiscoveryRun, Profile)
        .join(best_score_sq, and_(
            Opportunity.company_id == best_score_sq.c.company_id,
            Opportunity.score == best_score_sq.c.max_score,
        ))
        .join(Company, Opportunity.company_id == Company.id)
        .join(DiscoveryRun, Opportunity.run_id == DiscoveryRun.id)
        .outerjoin(Profile, DiscoveryRun.profile_id == Profile.id)
        .filter(Opportunity.zoho_pushed_at.is_(None))
        .order_by(Opportunity.score.desc())
        .limit(PUSH_BATCH)
        .all()
    )

    if not best_opps:
        logger.info("Zoho push: nothing to do (no pending opportunities)")
        return 0

    # Best contact per company (highest confidence, must have verified/probable email)
    company_ids = [opp.company_id for opp, *_ in best_opps]
    contacts_raw = (
        db.query(Contact)
        .filter(Contact.company_id.in_(company_ids))
        .filter(Contact.email.isnot(None))
        .filter(Contact.email_status.in_(["verified", "probable"]))
        .order_by(Contact.confidence_score.desc())
        .all()
    )
    # One contact per company (best)
    best_contact: dict[int, Contact] = {}
    for ct in contacts_raw:
        if ct.company_id not in best_contact:
            best_contact[ct.company_id] = ct

    logger.info(
        f"Zoho push: {len(best_opps)} opportunities, "
        f"{len(best_contact)} have a contact email"
    )

    from src.integrations.zoho_mail import create_draft as zoho_create_draft
    pushed = 0

    for opp, company, run, profile in best_opps:
        contact = best_contact.get(opp.company_id)
        if not contact:
            logger.info(f"  ⏭  {company.name} — no verified/probable contact email, skipping")
            continue

        label = f"{company.name} → {contact.email}"
        try:
            subject = opp.outreach_subject
            body    = opp.outreach_draft

            if not body:
                logger.info(f"  ✍  {label} — generating draft (not in DB)")
                subject, body = _generate_draft(company, contact, opp, profile)
                # Persist generated draft so future runs don't regenerate
                opp.outreach_draft   = body
                opp.outreach_subject = subject
                db.flush()

            subject = subject or f"Para {contact.name or company.name}"

            zoho_create_draft(
                to_address=contact.email,
                subject=subject,
                content=body,
            )

            opp.zoho_pushed_at = datetime.now(timezone.utc)
            db.flush()
            pushed += 1
            logger.info(f"  📧 {label} — draft pushed")

        except Exception as exc:
            logger.error(f"  ❌ {label} — {exc}")

        time.sleep(PUSH_DELAY_S)

    db.commit()
    logger.info(f"Zoho push done: {pushed} drafts sent")
    return pushed


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Blest Worker starting")
    logger.info("=" * 60)

    from src.integrations.zoho_mail import is_configured
    if not is_configured():
        logger.error(
            "Zoho Mail not configured.\n"
            "Run from project root: python run.py --zoho-auth <grant_token>"
        )
        sys.exit(1)

    from src.database.session import init_db, get_session
    init_db()  # creates tables + runs all migrations (adds zoho_pushed_at if new)

    with get_session() as db:
        _run_enrichment_phase(db)
        _run_push_phase(db)

    logger.info("Worker finished.")


if __name__ == "__main__":
    main()
