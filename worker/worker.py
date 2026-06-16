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

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    log_file = Path(__file__).parent / "worker.log"
    # On Windows, stdout defaults to cp1252 which can't encode the emoji used in
    # log messages (⏭ ✍ 📧 →). run_worker.bat redirects stdout into
    # worker_task.log, so without this every emoji line raises UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

# ── Config ───────────────────────────────────────────────────────────────────
ENRICH_BATCH   = int(os.getenv("WORKER_ENRICH_BATCH", "15"))
PUSH_BATCH     = int(os.getenv("WORKER_PUSH_BATCH", "15"))
ENRICH_DELAY_S = float(os.getenv("WORKER_ENRICH_DELAY", "3"))   # between contacts
PUSH_DELAY_S   = float(os.getenv("WORKER_PUSH_DELAY", "1"))     # between Zoho calls
RETRY_FAILED   = os.getenv("WORKER_RETRY_FAILED", "true").lower() in ("1", "true", "yes")
MAX_ATTEMPTS   = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))     # incl. first pass
CHECK_BOUNCES  = os.getenv("WORKER_CHECK_BOUNCES", "true").lower() in ("1", "true", "yes")


# ── Draft generation (only called when Opportunity.outreach_draft is NULL) ──

def _generate_draft(company, contact, opportunity, profile) -> tuple[str, str]:
    """
    Generate an outreach draft via Claude Haiku.
    Returns (subject_line, body).
    """
    import anthropic
    import instructor
    from src.prompts.outreach import build_outreach_prompt
    from src.schemas.outputs import CompanyOutreach

    po = {
        "agent_company_name":  (profile.agent_company_name if profile else "Blest"),
        "agent_description":   (profile.agent_description  if profile else "a corporate English training provider"),
        "outreach_tone":       (profile.outreach_tone       if profile else "warm"),
        "outreach_language":   (getattr(profile, "outreach_language", None) if profile else None) or "es",
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
            "content": build_outreach_prompt(
                agent_name=po["agent_company_name"],
                agent_description=po["agent_description"],
                outreach_service_description=(
                    po["search_focus_terms"] or "improve business communication"
                ),
                outreach_tone=po["outreach_tone"],
                company_and_insight_json=json.dumps(payload, ensure_ascii=False, indent=2),
                custom_instructions_block=custom_block,
                outreach_language=po["outreach_language"],
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
    """Enrich up to ENRICH_BATCH contacts that have no email yet.

    Picks never-enriched contacts first; if room remains and WORKER_RETRY_FAILED
    is on, also retries previously-failed *named* contacts (no email yet) up to
    MAX_ATTEMPTS — these can now succeed because the pipeline resolves missing
    company domains.
    """
    from src.database.models import Contact

    unenriched = (
        db.query(Contact)
        .filter(Contact.enriched_at.is_(None))
        .filter(Contact.company_id.isnot(None))
        .order_by(Contact.created_at.asc())
        .limit(ENRICH_BATCH)
        .all()
    )

    batch = list(unenriched)

    if RETRY_FAILED and len(batch) < ENRICH_BATCH:
        remaining = ENRICH_BATCH - len(batch)
        retry_candidates = (
            db.query(Contact)
            .filter(Contact.enriched_at.isnot(None))
            .filter(Contact.company_id.isnot(None))
            .filter(Contact.email.is_(None))
            .filter(Contact.name.isnot(None))
            .filter(Contact.name != "")
            .order_by(Contact.enriched_at.asc())
            .limit(remaining * 5)  # over-fetch; filter by attempts below
            .all()
        )
        for ct in retry_candidates:
            attempts = ct.enrichment_log.get("attempts", 1) if isinstance(ct.enrichment_log, dict) else 1
            if attempts < MAX_ATTEMPTS:
                batch.append(ct)
            if len(batch) >= ENRICH_BATCH:
                break

    if not batch:
        logger.info("Enrichment: nothing to do (all contacts already enriched)")
        return []

    n_retry = len(batch) - len(unenriched)
    logger.info(f"Enrichment: processing {len(batch)} contacts ({len(unenriched)} new, {n_retry} retried)")
    ok_ids = []

    for contact in batch:
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
    from src.database.models import Contact, Company, Opportunity, DiscoveryRun, Profile, ContactStatus

    # Companies already engaged in ANY prior run — never push to them again.
    # (a) already recorded as contacted, or (b) already pushed to Zoho before.
    # Without this, each new run creates a fresh Opportunity with
    # zoho_pushed_at=NULL, so a company contacted before would get re-pushed.
    contacted_sq = db.query(ContactStatus.company_id)
    pushed_sq = (
        db.query(Opportunity.company_id)
        .filter(Opportunity.zoho_pushed_at.isnot(None))
    )

    # Best opportunity per company (highest score, not yet pushed)
    best_score_sq = (
        db.query(
            Opportunity.company_id,
            func.max(Opportunity.score).label("max_score"),
        )
        .filter(Opportunity.zoho_pushed_at.is_(None))
        .filter(~Opportunity.company_id.in_(contacted_sq))
        .filter(~Opportunity.company_id.in_(pushed_sq))
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
        .filter(~Opportunity.company_id.in_(contacted_sq))
        .filter(~Opportunity.company_id.in_(pushed_sq))
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


# ── Phase 3: Bounce check ────────────────────────────────────────────────────

def _run_bounce_phase() -> int:
    """Scan the Zoho inbox for bounces and mark matched contacts (email_status='bounced').
    Self-contained (own DB session). Failures are non-fatal (e.g. missing read scope)."""
    if not CHECK_BOUNCES:
        logger.info("Bounce check: disabled (WORKER_CHECK_BOUNCES=false)")
        return 0
    try:
        from src.tools.bounces import apply_bounces
        res = apply_bounces()
        logger.info(
            f"Bounce check: {res['bounce_messages']} bounce msg(s) in inbox, "
            f"{res['marked']} contact(s) newly marked as bounced"
        )
        return res["marked"]
    except Exception as exc:
        logger.warning(f"Bounce check skipped/failed (missing messages.READ/folders.READ scope?): {exc}")
        return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    _setup_logging()
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

    _run_bounce_phase()  # Phase 3 — mark bounced emails (reads Zoho inbox)

    logger.info("Worker finished.")


if __name__ == "__main__":
    main()
