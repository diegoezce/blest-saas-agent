import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.database.session import get_session
from src.database.models import Contact, Company
from src.enrichment.scraper import scrape_domain
from src.enrichment.patterns import (
    generate_candidates,
    infer_pattern_from_emails,
    prioritize_candidates,
)
from src.enrichment.providers.million_verifier import MillionVerifierProvider
from src.enrichment.providers.hunter import HunterProvider

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    contact_id: int
    email: str | None = None
    email_status: str | None = None   # verified | probable | catch_all | not_found
    email_source: str | None = None   # site_scrape | pattern_verified | hunter
    phone_whatsapp: str | None = None
    log: dict = field(default_factory=dict)


def _split_name(full_name: str) -> tuple[str, str]:
    """Return (first, last) from a full name. Best-effort."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def enrich_contact(contact_id: int) -> EnrichmentResult:
    result = EnrichmentResult(contact_id=contact_id)

    with get_session() as session:
        contact = session.get(Contact, contact_id)
        if not contact:
            result.log["error"] = "contact not found"
            return result

        company = session.get(Company, contact.company_id)
        domain = company.domain if company else None

        if not domain:
            result.log["error"] = "no domain for company"
            _persist(session, contact, result)
            return result

        contact_name = contact.name or ""
        first, last = _split_name(contact_name)
        result.log["name"] = contact_name
        result.log["domain"] = domain

        # ── Layer 1: site scrape ───────────────────────────────────────────
        layer1: dict = {}
        try:
            scrape = scrape_domain(domain)
            layer1["pages_checked"] = scrape.pages_checked
            layer1["emails_found"] = scrape.emails
            layer1["phones_found"] = scrape.phones
            layer1["blocked_by_robots"] = scrape.blocked_by_robots
            if scrape.error:
                layer1["error"] = scrape.error

            # Phone: store first found
            if scrape.phones:
                result.phone_whatsapp = scrape.phones[0]

            # If a person's email at this domain is found (not generic),
            # record as site_scrape hit
            domain_emails = [e for e in scrape.emails if e.endswith(f"@{domain}")]
            generic_prefixes = {"info", "hola", "hello", "contact", "contacto",
                                 "ventas", "sales", "admin", "support", "ayuda"}
            person_emails = [
                e for e in domain_emails
                if e.split("@")[0] not in generic_prefixes
            ]
            if person_emails and first and last:
                # Check if any matches the contact's name directly
                f_slug = first.lower()
                l_slug = last.lower()
                matched = next(
                    (e for e in person_emails
                     if f_slug in e or l_slug in e),
                    None,
                )
                if matched:
                    result.email = matched
                    result.email_status = "verified"
                    result.email_source = "site_scrape"
                    layer1["matched"] = matched
        except Exception as e:
            layer1["exception"] = str(e)
            logger.warning(f"Layer 1 failed for contact {contact_id}: {e}")

        result.log["layer1"] = layer1

        if result.email_status == "verified":
            _persist(session, contact, result)
            return result

        # ── Layer 2: pattern generation + SMTP verification ────────────────
        layer2: dict = {}
        if first and last:
            try:
                scrape_emails = layer1.get("emails_found", [])
                domain_emails = [e for e in scrape_emails if e.endswith(f"@{domain}")]
                inferred = infer_pattern_from_emails(domain_emails, domain)
                layer2["inferred_pattern"] = inferred

                candidates = generate_candidates(first, last, domain)
                candidates = prioritize_candidates(candidates, inferred, first, last, domain)
                layer2["candidates"] = candidates

                verifier = MillionVerifierProvider()
                for candidate in candidates:
                    time.sleep(1)  # global rate limit
                    vr = verifier.verify(candidate)
                    layer2.setdefault("verifications", []).append({
                        "email": candidate,
                        "status": vr.status,
                        "confidence": vr.confidence,
                    })
                    if vr.status == "valid":
                        result.email = candidate
                        result.email_status = "verified"
                        result.email_source = "pattern_verified"
                        break
                    if vr.status == "catch_all":
                        # Store as probable but keep searching for valid
                        if not result.email:
                            result.email = candidate
                            result.email_status = "probable"
                            result.email_source = "pattern_verified"
                        # don't break — continue looking for something valid
            except Exception as e:
                layer2["exception"] = str(e)
                logger.warning(f"Layer 2 failed for contact {contact_id}: {e}")

        result.log["layer2"] = layer2

        if result.email_status == "verified":
            _persist(session, contact, result)
            return result

        # ── Layer 3: Hunter.io fallback ────────────────────────────────────
        layer3: dict = {}
        if first and last:
            try:
                hunter = HunterProvider()
                found = hunter.find_email(domain, first, last)
                if found:
                    layer3["hunter_email"] = found["email"]
                    layer3["hunter_score"] = found["score"]
                    score = found["score"]
                    if score >= 90:
                        result.email = found["email"]
                        result.email_status = "verified"
                        result.email_source = "hunter"
                    elif score >= 50:
                        if result.email_status != "verified":
                            result.email = found["email"]
                            result.email_status = "probable"
                            result.email_source = "hunter"
                else:
                    layer3["hunter_email"] = None
            except Exception as e:
                layer3["exception"] = str(e)
                logger.warning(f"Layer 3 failed for contact {contact_id}: {e}")

        result.log["layer3"] = layer3

        # If nothing found at all
        if not result.email_status:
            result.email_status = "not_found"

        _persist(session, contact, result)
        return result


def _persist(session, contact: Contact, result: EnrichmentResult) -> None:
    if result.email:
        contact.email = result.email
    if result.email_status:
        contact.email_status = result.email_status
    if result.email_source:
        contact.email_source = result.email_source
    if result.phone_whatsapp:
        contact.phone_whatsapp = result.phone_whatsapp
    contact.enriched_at = datetime.now(timezone.utc)
    contact.enrichment_log = result.log
