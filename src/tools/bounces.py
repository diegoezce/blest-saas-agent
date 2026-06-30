"""Bounce detection: scan the Zoho inbox, match failed addresses to contacts,
and mark them. Shared by the web routes (/bounces/scan, /bounces/apply) and the
`python run.py --check-bounces` CLI so the logic lives in one place.
"""
import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from src.database.models import Contact, Company
from src.database.session import get_session
from src.integrations.zoho_mail import scan_bounced_addresses

logger = logging.getLogger(__name__)


def _email_domain(addr: str) -> str:
    """Return the domain part of an email address, lowercased."""
    return addr.split("@")[-1].lower() if "@" in addr else ""


def _domain_matches(company_domain: str, email_domain: str) -> bool:
    """True if company_domain equals email_domain or is a parent domain of it.

    e.g. company_domain='luxoft.com', email_domain='career.luxoft.com' → True
    """
    if not company_domain or not email_domain:
        return False
    cd = company_domain.lower().lstrip("www.")
    return cd == email_domain or email_domain.endswith("." + cd)


def scan_and_match(max_messages: int = 200) -> dict:
    """Scan Zoho for bounces and match the failed addresses to DB contacts.

    Read-only (marks nothing). Returns a summary dict including `addresses`
    (so a caller can mark without re-scanning) and `matched` rows.

    Matching is three-pass:
    1. Direct: Contact.email == bounced address
    2. Fallback: bounced address appears in Contact.enrichment_log["bad_emails"]
       (covers cases where enrichment already replaced the address before the
       bounce notification arrived)
    3. Domain fallback: company domain matches the email domain (incl. subdomains),
       restricted to contacts whose name prefix matches the email local part
    """
    res = scan_bounced_addresses(max_messages=max_messages)
    addrs = res["addresses"]
    matched: list[dict] = []
    seen_ids: set[int] = set()

    if addrs:
        addrs_set = set(addrs)
        with get_session() as session:
            # Pass 1: direct email match
            rows = (
                session.query(Contact.id, Contact.name, Contact.email, Contact.email_status)
                .filter(func.lower(Contact.email).in_(addrs))
                .all()
            )
            for cid, name, email, status in rows:
                matched.append({
                    "contact_id": cid, "name": name or "", "email": email,
                    "already": (status == "bounced"),
                    "matched_via": "email",
                })
                seen_ids.add(cid)

            # Pass 2: address in enrichment_log["bad_emails"] (replaced before bounce arrived)
            candidates = (
                session.query(Contact)
                .filter(Contact.enrichment_log.isnot(None))
                .filter(Contact.id.notin_(seen_ids) if seen_ids else True)
                .all()
            )
            for c in candidates:
                bad = {e.lower() for e in (c.enrichment_log or {}).get("bad_emails", []) if e}
                if bad & addrs_set:
                    matched.append({
                        "contact_id": c.id, "name": c.name or "", "email": c.email,
                        "already": (c.email_status == "bounced"),
                        "matched_via": "bad_emails",
                    })
                    seen_ids.add(c.id)

            # Pass 3: domain-based match (handles subdomain variants like career.luxoft.com vs luxoft.com)
            bounced_domains = {_email_domain(a) for a in addrs_set}
            all_contacts = (
                session.query(Contact)
                .options(joinedload(Contact.company))
                .filter(Contact.id.notin_(seen_ids) if seen_ids else True)
                .all()
            )
            for c in all_contacts:
                if not c.company or not c.company.domain:
                    continue
                for addr in addrs_set:
                    if not _domain_matches(c.company.domain, _email_domain(addr)):
                        continue
                    # Narrow by first name: local part of bounced addr must contain
                    # the contact's first name (case-insensitive) to avoid false positives.
                    # Skip contacts with no name or no email — can't confirm identity.
                    if not c.name or not c.email:
                        continue
                    local = addr.split("@")[0].lower()
                    first = c.name.split()[0].lower()
                    if first not in local:
                        continue
                    matched.append({
                        "contact_id": c.id, "name": c.name or "", "email": c.email,
                        "already": (c.email_status == "bounced"),
                        "matched_via": "domain",
                        "bounced_addr": addr,
                    })
                    seen_ids.add(c.id)
                    break

    new_count = sum(1 for m in matched if not m["already"])
    return {
        "checked": res["checked"],
        "bounce_messages": res["bounce_messages"],
        "addresses_found": len(addrs),
        "addresses": addrs,
        "matched": matched,
        "matched_count": len(matched),
        "new_count": new_count,
        "already_count": len(matched) - new_count,
    }


def mark_bounced(addresses: list[str], extra_contact_ids: list[int] | None = None) -> dict:
    """Set Contact.email_status='bounced' for matched contacts.

    Matches by email address OR by explicit contact IDs (for contacts matched
    via enrichment_log["bad_emails"] whose current email differs from the bounced one).
    """
    if not addresses and not extra_contact_ids:
        return {"marked": 0, "companies": 0}
    from src.tools.db_tools import mark_company_contacted

    addrs = [a.lower() for a in addresses]
    marked = 0
    company_ids: set[int] = set()
    with get_session() as session:
        contacts: list[Contact] = []
        if addrs:
            contacts += session.query(Contact).filter(func.lower(Contact.email).in_(addrs)).all()
        if extra_contact_ids:
            already_ids = {c.id for c in contacts}
            extra = session.query(Contact).filter(
                Contact.id.in_([i for i in extra_contact_ids if i not in already_ids])
            ).all()
            contacts += extra

        for c in contacts:
            if c.email_status != "bounced":
                c.email_status = "bounced"
                marked += 1
            # A bounce means we DID send this company an email → make sure it's
            # recorded as contacted so it shows on /contacts-report (idempotent).
            if c.company_id:
                mark_company_contacted(session, c.company_id, method="email")
                company_ids.add(c.company_id)
    return {"marked": marked, "companies": len(company_ids)}


def apply_bounces(max_messages: int = 200) -> dict:
    """One-shot: scan + mark. Returns {marked, companies, matched, bounce_messages}."""
    summary = scan_and_match(max_messages=max_messages)
    extra_ids = [
        m["contact_id"] for m in summary["matched"]
        if m.get("matched_via") in ("bad_emails", "domain")
    ]
    res = mark_bounced(summary["addresses"], extra_contact_ids=extra_ids or None)
    return {
        "marked": res["marked"],
        "companies": res["companies"],
        "matched": summary["addresses_found"],
        "bounce_messages": summary["bounce_messages"],
    }
