"""Unsubscribe detection: scan the Zoho inbox for List-Unsubscribe requests,
match sender addresses to contacts, and mark them with unsubscribed_at.
Shared by the worker (phase 3b) and any future web route.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func

from src.database.models import Contact
from src.database.session import get_session
from src.integrations.zoho_mail import scan_unsubscribe_requests

logger = logging.getLogger(__name__)


def apply_unsubscribes(max_messages: int = 200) -> dict:
    """Scan inbox for unsubscribe requests and mark matched contacts.

    Returns {checked, unsubscribe_messages, matched, marked}.
    """
    res = scan_unsubscribe_requests(max_messages=max_messages)
    addrs = res["addresses"]
    marked = 0
    if addrs:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            contacts = (
                session.query(Contact)
                .filter(func.lower(Contact.email).in_(addrs))
                .filter(Contact.unsubscribed_at.is_(None))
                .all()
            )
            for c in contacts:
                c.unsubscribed_at = now
                marked += 1
                logger.info(f"Unsubscribed: {c.email} (contact_id={c.id})")

    return {
        "checked": res["checked"],
        "unsubscribe_messages": res["unsubscribe_messages"],
        "matched": len(addrs),
        "marked": marked,
    }
