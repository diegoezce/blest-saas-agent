"""Follow-up agent: detect replies in the Zoho inbox, pick leads that were already
contacted but haven't answered, generate a second/third-touch draft and push it to
Zoho. Mirrors the structure of `src/tools/bounces.py` (scan + match + act) so the
logic lives in one place, shared by the worker phase and the CLI flags
(`--detect-replies`, `--follow-ups`).

Cadence assumes the first-touch draft is *sent the same day it is pushed* — the clock
runs from `Opportunity.zoho_pushed_at`. There is no separate "sent_at" in v1.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import func

from src.database.models import Contact, Opportunity, Company, DiscoveryRun, Profile, ContactStatus
from src.database.session import get_session
from src.integrations.zoho_mail import scan_inbox_senders, create_draft as zoho_create_draft

logger = logging.getLogger(__name__)

# Cadence (days). Touch #1 ~day 4, touch #2 ~day 10, max 2 follow-ups.
FOLLOWUP_FIRST_DAYS = 4
FOLLOWUP_SECOND_DAYS = 10
FOLLOWUP_MAX = 2


def _aware(dt: datetime | None) -> datetime | None:
    """Treat naive DB timestamps as UTC so deltas don't raise."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Reply detection (read Zoho inbox) — mirror of bounces.scan_and_match ──────

def detect_replies(max_messages: int = 200) -> dict:
    """Scan the inbox, match senders to contacts and mark `Contact.replied_at`.

    Only counts a message as a reply if it arrived *after* the first-touch push to
    that contact's company (avoids marking unrelated prior mail). Also reflects the
    reply in `ContactStatus.response_received` when no manual feedback exists yet,
    so `/contacts-report` shows it. Returns {checked, senders, matched, newly_marked, ooo_verified}.
    """
    res = scan_inbox_senders(max_messages=max_messages)
    senders: dict[str, int] = res["senders"]
    ooo_senders: set[str] = res.get("ooo_senders", set())
    addrs = list(senders.keys())
    matched = 0
    newly = 0
    ooo_verified = 0
    if addrs:
        with get_session() as session:
            rows = (
                session.query(Contact)
                .filter(func.lower(Contact.email).in_(addrs))
                .all()
            )
            for c in rows:
                matched += 1
                em = (c.email or "").lower()
                reply_ms = senders.get(em)
                if not reply_ms:
                    continue
                reply_dt = datetime.fromtimestamp(reply_ms / 1000, tz=timezone.utc)

                pushed = (
                    session.query(func.min(Opportunity.zoho_pushed_at))
                    .filter(Opportunity.company_id == c.company_id)
                    .filter(Opportunity.zoho_pushed_at.isnot(None))
                    .scalar()
                )
                if not pushed:
                    continue  # we never contacted them → not a reply to us
                if reply_dt < _aware(pushed):
                    continue  # mail predates our outreach

                # OOO auto-reply: confirms the address is valid and resets the cadence
                # clock so we don't follow up while they're away.
                if em in ooo_senders:
                    # Don't override a confirmed bounce — bounce from the mail server
                    # is stronger evidence than an OOO (which may have been sent before
                    # the mailbox was deleted/disabled).
                    if c.email_status not in ("verified", "bounced"):
                        c.email_status = "verified"
                        c.email_source = "ooo_confirmed"
                        ooo_verified += 1
                    log = c.enrichment_log or {}
                    if not log.get("ooo_confirmed_at"):
                        log["ooo_confirmed_at"] = reply_dt.isoformat()
                        c.enrichment_log = log
                        logger.info("OOO from %s — email confirmed valid, cadence paused", c.email)
                        # Reset the follow-up cadence clock for this company.
                        opp_to_reset = (
                            session.query(Opportunity)
                            .filter(Opportunity.company_id == c.company_id)
                            .filter(Opportunity.zoho_pushed_at.isnot(None))
                            .order_by(Opportunity.score.desc())
                            .first()
                        )
                        if opp_to_reset:
                            opp_to_reset.last_followup_at = reply_dt
                    continue  # not a real reply → skip replied_at

                if c.replied_at is not None:
                    continue

                c.replied_at = reply_dt
                newly += 1

                cs = session.query(ContactStatus).filter_by(company_id=c.company_id).first()
                if cs is None:
                    session.add(ContactStatus(
                        company_id=c.company_id,
                        contacted_at=_aware(pushed),
                        contact_method="email",
                        response_received="replied",
                    ))
                elif not cs.response_received:
                    cs.response_received = "replied"

    return {
        "checked": res["checked"],
        "senders": len(addrs),
        "matched": matched,
        "newly_marked": newly,
        "ooo_verified": ooo_verified,
    }


# ── Candidate selection ───────────────────────────────────────────────────────

def _followup_due_date(opp) -> datetime | None:
    """When this opportunity becomes due for its next follow-up (UTC), or None.

    count 0 → FIRST_DAYS after the first-touch push;
    count 1 → (SECOND-FIRST) days after the last follow-up.
    """
    count = opp.followup_count or 0
    if count == 0:
        base = _aware(opp.zoho_pushed_at)
        if not base:
            return None
        # If last_followup_at is set at count=0, it means an OOO was received and
        # reset the cadence clock — use whichever is later.
        if opp.last_followup_at:
            base = max(base, _aware(opp.last_followup_at))
        return base + timedelta(days=FOLLOWUP_FIRST_DAYS)
    if count == 1:
        base = _aware(opp.last_followup_at)
        if not base:
            return None
        return base + timedelta(days=(FOLLOWUP_SECOND_DAYS - FOLLOWUP_FIRST_DAYS))
    return None


def _best_followup_contact(session, company_id):
    """Best verified/probable, non-replied contact for a company, or None."""
    return (
        session.query(Contact)
        .filter(Contact.company_id == company_id)
        .filter(Contact.email.isnot(None))
        .filter(Contact.email_status.in_(["verified", "probable"]))
        .filter(Contact.replied_at.is_(None))
        .order_by(Contact.confidence_score.desc().nullslast())
        .first()
    )


def _eligible_followup_opps(session) -> list:
    """All opportunities eligible for a follow-up *regardless of cadence timing*.

    Returns [(opp, company, contact, profile)], one per company (highest score),
    filtered by: first touch pushed, `followup_count` < MAX, no reply, no manual
    response, and a verified/probable non-replied contact. Cadence timing is left to
    the caller via `_followup_due_date(opp)`.
    """
    replied_sq = session.query(Contact.company_id).filter(Contact.replied_at.isnot(None))
    responded_sq = (
        session.query(ContactStatus.company_id)
        .filter(ContactStatus.response_received.isnot(None))
    )

    opps = (
        session.query(Opportunity, Company, Profile)
        .join(Company, Opportunity.company_id == Company.id)
        .join(DiscoveryRun, Opportunity.run_id == DiscoveryRun.id)
        .outerjoin(Profile, DiscoveryRun.profile_id == Profile.id)
        .filter(Opportunity.zoho_pushed_at.isnot(None))
        .filter(func.coalesce(Opportunity.followup_count, 0) < FOLLOWUP_MAX)
        .filter(~Opportunity.company_id.in_(replied_sq))
        .filter(~Opportunity.company_id.in_(responded_sq))
        .order_by(Opportunity.score.desc())
        .all()
    )

    out: list = []
    seen_company: set = set()
    for opp, company, profile in opps:
        if opp.company_id in seen_company:
            continue
        contact = _best_followup_contact(session, opp.company_id)
        if not contact:
            continue
        seen_company.add(opp.company_id)
        out.append((opp, company, contact, profile))
    return out


def select_followup_candidates(session) -> list:
    """Opportunities **due now** for a follow-up. Returns [(opp, company, contact, profile)].

    Eligibility per `_eligible_followup_opps`; due when `_followup_due_date(opp) <= now`.
    """
    now = datetime.now(timezone.utc)
    out: list = []
    for opp, company, contact, profile in _eligible_followup_opps(session):
        due = _followup_due_date(opp)
        if due and due <= now:
            out.append((opp, company, contact, profile))
    return out


def select_upcoming_followups(session, within_days: int = 7) -> list:
    """Eligible follow-ups **not yet due** but coming up within `within_days`.

    Returns [(opp, company, contact, profile, due_date)], soonest first.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=within_days)
    out: list = []
    for opp, company, contact, profile in _eligible_followup_opps(session):
        due = _followup_due_date(opp)
        if due and now < due <= horizon:
            out.append((opp, company, contact, profile, due))
    out.sort(key=lambda t: t[4])
    return out


# ── Draft generation — mirror of worker._generate_draft ───────────────────────

def generate_followup(company, contact, opp, profile) -> tuple[str, str]:
    """Generate a follow-up draft via Claude Haiku. Returns (subject, body)."""
    import anthropic
    import instructor
    from src.prompts.followup import build_followup_prompt
    from src.schemas.outputs import FollowUpEmail

    agent_name = (profile.agent_company_name if profile else "Blest")
    agent_desc = (profile.agent_description if profile else "a corporate English training provider")
    language = (getattr(profile, "outreach_language", None) if profile else None) or "es"
    custom = ((profile.outreach_instructions if profile else "") or "").strip()
    instructions_block = (
        f"\nWHAT {agent_name.upper()} OFFERS & HOW TO PITCH "
        f"(use only what is relevant; never contradict COMPANY DATA):\n{custom}\n"
        if custom else ""
    )

    days_since = 0
    if opp and opp.last_followup_at:
        days_since = max(0, (datetime.now(timezone.utc) - _aware(opp.last_followup_at)).days)
    elif opp and opp.zoho_pushed_at:
        days_since = max(0, (datetime.now(timezone.utc) - _aware(opp.zoho_pushed_at)).days)

    payload = {
        "company_name": company.name,
        "website": company.website_url,
        "industry": company.industry,
        "size": company.size_estimate,
        "location": company.location,
        "description": company.description,
        "contact_name": contact.name,
        "contact_role": contact.role,
    }

    client = instructor.from_anthropic(anthropic.Anthropic())
    result = client.messages.create(
        # Customer-facing draft → use the quality model (Sonnet) by default.
        model=os.getenv("OUTREACH_MODEL", "claude-sonnet-4-6"),
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": build_followup_prompt(
                agent_name=agent_name,
                agent_description=agent_desc,
                outreach_instructions_block=instructions_block,
                original_email=(opp.outreach_draft if opp else "") or "",
                days_since_contact=days_since,
                company_context_json=json.dumps(payload, ensure_ascii=False, indent=2),
                followup_number=(opp.followup_count or 0) + 1 if opp else 1,
                outreach_language=language,
            ),
        }],
        response_model=FollowUpEmail,
    )

    original_subject = (opp.outreach_subject if opp else None) or f"Para {contact.name or company.name}"
    subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"
    return subject, result.body


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_followups(session, batch: int = 15, delay: float = 1.0) -> dict:
    """Detect replies, select due candidates, generate + push follow-up drafts.

    `session` is used for selection + persistence; reply detection opens its own
    session (and commits) first, so candidate selection sees freshly-marked replies.
    Returns {replies_detected, candidates, drafted}.
    """
    rep = detect_replies()

    candidates = select_followup_candidates(session)[:batch]
    if not candidates:
        logger.info("Follow-ups: nothing due")
        return {"replies_detected": rep["newly_marked"], "ooo_verified": rep.get("ooo_verified", 0), "candidates": 0, "drafted": 0}

    logger.info(
        f"Follow-ups: {len(candidates)} due "
        f"(replies: {rep['newly_marked']}, OOO confirmed: {rep.get('ooo_verified', 0)})"
    )
    drafted = 0
    for opp, company, contact, profile in candidates:
        label = f"{company.name} → {contact.email} (#{(opp.followup_count or 0) + 1})"
        try:
            subject, body = generate_followup(company, contact, opp, profile)
            zoho_create_draft(to_address=contact.email, subject=subject, content=body)
            opp.followup_count = (opp.followup_count or 0) + 1
            opp.last_followup_at = datetime.now(timezone.utc)
            opp.followup_subject = subject
            opp.followup_draft = body
            session.flush()
            drafted += 1
            logger.info(f"  📨 {label} — follow-up draft pushed")
        except Exception as exc:
            logger.error(f"  ❌ {label} — {exc}")
        time.sleep(delay)

    session.commit()
    logger.info(f"Follow-ups done: {drafted} drafts pushed")
    return {"replies_detected": rep["newly_marked"], "ooo_verified": rep.get("ooo_verified", 0), "candidates": len(candidates), "drafted": drafted}


def push_followup_now(session, company_id: int) -> dict:
    """Generate + push a follow-up draft for one company **right now**, bypassing the
    cadence wait (manual "do it today" / bring-forward action).

    The company must still be eligible (pushed, no reply, no manual response,
    `followup_count` < MAX, with a verified/probable contact). Returns
    {ok, message, stage}.
    """
    match = next(
        (t for t in _eligible_followup_opps(session) if t[0].company_id == company_id),
        None,
    )
    if match is None:
        return {"ok": False, "message": "Empresa no elegible para follow-up", "stage": None}

    opp, company, contact, profile = match
    stage = (opp.followup_count or 0) + 1
    try:
        subject, body = generate_followup(company, contact, opp, profile)
        zoho_create_draft(to_address=contact.email, subject=subject, content=body)
        opp.followup_count = (opp.followup_count or 0) + 1
        opp.last_followup_at = datetime.now(timezone.utc)
        opp.followup_subject = subject
        opp.followup_draft = body
        session.commit()
        logger.info(f"Follow-up #{stage} adelantado: {company.name} → {contact.email}")
        return {"ok": True, "message": f"Follow-up #{stage} drafteado para {company.name}", "stage": stage}
    except Exception as exc:
        session.rollback()
        logger.error(f"Follow-up adelantado falló ({company.name}): {exc}")
        return {"ok": False, "message": f"Error: {exc}", "stage": stage}
