"""Bounce detection: scan the Zoho inbox, match failed addresses to contacts,
and mark them. Shared by the web routes (/bounces/scan, /bounces/apply) and the
`python run.py --check-bounces` CLI so the logic lives in one place.
"""
import logging

from sqlalchemy import func

from src.database.models import Contact
from src.database.session import get_session
from src.integrations.zoho_mail import scan_bounced_addresses

logger = logging.getLogger(__name__)


def scan_and_match(max_messages: int = 200) -> dict:
    """Scan Zoho for bounces and match the failed addresses to DB contacts.

    Read-only (marks nothing). Returns a summary dict including `addresses`
    (so a caller can mark without re-scanning) and `matched` rows.
    """
    res = scan_bounced_addresses(max_messages=max_messages)
    addrs = res["addresses"]
    matched: list[dict] = []
    if addrs:
        with get_session() as session:
            rows = (
                session.query(Contact.id, Contact.name, Contact.email, Contact.email_status)
                .filter(func.lower(Contact.email).in_(addrs))
                .all()
            )
            for cid, name, email, status in rows:
                matched.append({
                    "contact_id": cid, "name": name or "", "email": email,
                    "already": (status == "bounced"),
                })
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


def mark_bounced(addresses: list[str]) -> int:
    """Set Contact.email_status='bounced' for contacts whose email is in `addresses`
    (skips ones already marked). Returns how many were newly marked."""
    if not addresses:
        return 0
    addrs = [a.lower() for a in addresses]
    marked = 0
    with get_session() as session:
        contacts = session.query(Contact).filter(func.lower(Contact.email).in_(addrs)).all()
        for c in contacts:
            if c.email_status != "bounced":
                c.email_status = "bounced"
                marked += 1
    return marked


def apply_bounces(max_messages: int = 200) -> dict:
    """One-shot: scan + mark. Returns {marked, matched, bounce_messages}."""
    summary = scan_and_match(max_messages=max_messages)
    marked = mark_bounced(summary["addresses"])
    return {
        "marked": marked,
        "matched": summary["addresses_found"],
        "bounce_messages": summary["bounce_messages"],
    }
