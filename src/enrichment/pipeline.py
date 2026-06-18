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
from src.enrichment.providers import get_verifier
from src.enrichment.providers.hunter import HunterProvider

logger = logging.getLogger(__name__)

# Generic/shared inboxes worth using as an outreach fallback when no named email is
# found. Ordered by outreach preference (most appropriate first) — a real published
# address here beats any invented pattern guess and won't bounce.
GENERIC_PREFIXES: tuple[str, ...] = (
    "contacto", "contact", "info", "hola", "hello", "consultas",
    "ventas", "sales", "recepcion", "secretaria", "ayuda", "soporte",
    "support", "admin", "administracion",
)
# Never adopt these — non-deliverable / system mailboxes.
NEVER_EMAIL_PREFIXES: frozenset[str] = frozenset({
    "noreply", "no-reply", "postmaster", "webmaster", "mailer-daemon",
})


@dataclass
class EnrichmentResult:
    contact_id: int
    email: str | None = None
    email_status: str | None = None   # verified | probable | catch_all | not_found
    email_source: str | None = None   # site_scrape | site_scrape_generic | pattern_verified | hunter
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

        # Carry forward an attempt counter so the worker can bound retries.
        prev_log = contact.enrichment_log if isinstance(contact.enrichment_log, dict) else {}
        result.log["attempts"] = prev_log.get("attempts", 0) + 1

        # Known-bad addresses (e.g. ones that bounced) — never re-propose these.
        bad_emails = {e.lower() for e in prev_log.get("bad_emails", []) if e}
        if bad_emails:
            result.log["bad_emails"] = sorted(bad_emails)

        company = session.get(Company, contact.company_id)
        domain = company.domain if company else None

        # If discovery never captured a domain, try to resolve one before
        # giving up — otherwise every contact at this company instant-fails.
        if not domain and company:
            from src.enrichment.domain_resolver import resolve_company_domain
            existing_emails = [
                e for (e,) in session.query(Contact.email)
                .filter(Contact.company_id == company.id, Contact.email.isnot(None))
                .all()
            ]
            resolved = resolve_company_domain(company.name, company.location, existing_emails)
            if resolved:
                domain = resolved
                result.log["domain_resolved"] = resolved
                logger.info(f"[Enrich #{contact_id}] resolved missing domain → {resolved}")
                # Persist back only if no other company already owns this domain
                # (domain column is unique).
                clash = (
                    session.query(Company.id)
                    .filter(Company.domain == resolved, Company.id != company.id)
                    .first()
                )
                if not clash:
                    company.domain = resolved

        if not domain:
            result.log["error"] = "no domain for company"
            _persist(session, contact, result)
            return result

        contact_name = contact.name or ""
        first, last = _split_name(contact_name)
        result.log["name"] = contact_name
        result.log["domain"] = domain

        label = f"[Enrich #{contact_id}] {contact_name or '?'} @ {domain}"

        # ── Layer 1: site scrape ───────────────────────────────────────────
        layer1: dict = {}
        generic_emails: list[str] = []  # real published inboxes; fallback at end
        logger.info(f"{label} — Layer 1: scraping site")
        try:
            scrape = scrape_domain(domain)
            layer1["pages_checked"] = scrape.pages_checked
            layer1["emails_found"] = scrape.emails
            layer1["phones_found"] = scrape.phones
            layer1["blocked_by_robots"] = scrape.blocked_by_robots
            if scrape.error:
                layer1["error"] = scrape.error

            robots_note = " (robots.txt blocked)" if scrape.blocked_by_robots else ""
            logger.info(
                f"{label} — Layer 1 done: {scrape.pages_checked} pages, "
                f"{len(scrape.emails)} emails found{robots_note}"
            )

            # Phone: store first found
            if scrape.phones:
                result.phone_whatsapp = scrape.phones[0]
                logger.info(f"{label} — phone found: {scrape.phones[0]}")

            # If a person's email at this domain is found (not generic),
            # record as site_scrape hit
            domain_emails = [e for e in scrape.emails if e.endswith(f"@{domain}")]
            generic_prefixes = set(GENERIC_PREFIXES) | NEVER_EMAIL_PREFIXES
            person_emails = [
                e for e in domain_emails
                if e.split("@")[0].lower() not in generic_prefixes
            ]
            # Real published generic inboxes (info@, contacto@, …), deduped + ordered by
            # outreach preference, minus anything already known-bad. Used as a fallback
            # later only if no verified *named* email is found.
            generic_seen: set[str] = set()
            for pref in GENERIC_PREFIXES:
                for e in domain_emails:
                    el = e.lower()
                    if (el.split("@")[0] == pref and el not in bad_emails
                            and el not in generic_seen):
                        generic_seen.add(el)
                        generic_emails.append(e)
            layer1["generic_emails"] = generic_emails
            if person_emails and first:
                # Check if any matches the contact's name (first or last)
                f_slug = first.lower()
                l_slug = last.lower() if last else None
                matched = next(
                    (e for e in person_emails
                     if (f_slug in e or (l_slug and l_slug in e))
                     and e.lower() not in bad_emails),
                    None,
                )
                if matched:
                    result.email = matched
                    result.email_status = "verified"
                    result.email_source = "site_scrape"
                    layer1["matched"] = matched
                    logger.info(f"{label} — ✅ site scrape match: {matched}")
        except Exception as e:
            layer1["exception"] = str(e)
            logger.warning(f"Layer 1 failed for contact {contact_id}: {e}")

        result.log["layer1"] = layer1

        if result.email_status == "verified":
            _persist(session, contact, result)
            return result

        # ── Layer 2: pattern generation + SMTP verification ────────────────
        layer2: dict = {}
        if first:
            logger.info(f"{label} — Layer 2: SMTP pattern verification")
            try:
                scrape_emails = layer1.get("emails_found", [])
                domain_emails = [e for e in scrape_emails if e.endswith(f"@{domain}")]
                inferred = infer_pattern_from_emails(domain_emails, domain)
                layer2["inferred_pattern"] = inferred
                if inferred:
                    logger.info(f"{label} — inferred pattern: {inferred}")

                candidates = generate_candidates(first, last, domain)
                candidates = prioritize_candidates(candidates, inferred, first, last, domain)
                if bad_emails:
                    candidates = [c for c in candidates if c.lower() not in bad_emails]
                layer2["candidates"] = candidates
                logger.info(f"{label} — checking {len(candidates)} candidates: {', '.join(candidates)}")

                verifier = get_verifier()
                layer2["verifier"] = type(verifier).__name__
                unknown_fallback: str | None = None
                for candidate in candidates:
                    time.sleep(1)  # global rate limit
                    vr = verifier.verify(candidate)
                    layer2.setdefault("verifications", []).append({
                        "email": candidate,
                        "status": vr.status,
                        "confidence": vr.confidence,
                    })
                    logger.info(f"{label} — {candidate} → {vr.status}")
                    if vr.status == "valid":
                        result.email = candidate
                        result.email_status = "verified"
                        result.email_source = "pattern_verified"
                        logger.info(f"{label} — ✅ SMTP verified: {candidate}")
                        break
                    if vr.status == "catch_all":
                        # Store as probable but keep searching for valid
                        if not result.email:
                            result.email = candidate
                            result.email_status = "probable"
                            result.email_source = "pattern_verified"
                        # don't break — continue looking for something valid
                    elif vr.status == "unknown" and unknown_fallback is None:
                        unknown_fallback = candidate  # SMTP unreachable; save best guess

                # If every candidate was unverifiable (SMTP timeout / no response),
                # store the top-ranked candidate as probable rather than returning nothing
                if not result.email and unknown_fallback:
                    result.email = unknown_fallback
                    result.email_status = "probable"
                    result.email_source = "pattern_unverified"
                    layer2["unknown_fallback"] = unknown_fallback
                    logger.info(f"{label} — 🟡 unverifiable, storing best guess: {unknown_fallback}")
            except Exception as e:
                layer2["exception"] = str(e)
                logger.warning(f"Layer 2 failed for contact {contact_id}: {e}")
        else:
            logger.info(f"{label} — Layer 2 skipped (no first name)")

        result.log["layer2"] = layer2

        if result.email_status == "verified":
            _persist(session, contact, result)
            return result

        # ── Layer 3: Hunter.io fallback ────────────────────────────────────
        layer3: dict = {}
        if first:
            logger.info(f"{label} — Layer 3: Hunter.io lookup")
            try:
                hunter = HunterProvider()
                found = hunter.find_email(domain, first, last or "")
                if found and found.get("email", "").lower() in bad_emails:
                    layer3["skipped_bad_email"] = found["email"]
                    found = None
                if found:
                    layer3["hunter_email"] = found["email"]
                    layer3["hunter_score"] = found["score"]
                    score = found["score"]
                    logger.info(f"{label} — Hunter: {found['email']} (score {score})")
                    if score >= 90:
                        result.email = found["email"]
                        result.email_status = "verified"
                        result.email_source = "hunter"
                        logger.info(f"{label} — ✅ Hunter verified: {found['email']}")
                    elif score >= 50:
                        if result.email_status != "verified":
                            result.email = found["email"]
                            result.email_status = "probable"
                            result.email_source = "hunter"
                else:
                    layer3["hunter_email"] = None
                    logger.info(f"{label} — Hunter: no result")
            except Exception as e:
                layer3["exception"] = str(e)
                logger.warning(f"Layer 3 failed for contact {contact_id}: {e}")
        else:
            logger.info(f"{label} — Layer 3 skipped (no first name)")

        result.log["layer3"] = layer3

        # ── Fallback: real published generic inbox ─────────────────────────
        # A generic address scraped off the site (info@, contacto@, …) is real and
        # deliverable, so it beats any invented/unverified pattern guess. Only a
        # SMTP-verified *named* email (set above) outranks it.
        if result.email_status != "verified" and generic_emails:
            chosen = generic_emails[0]
            result.email = chosen
            result.email_status = "verified"   # published site address = deliverable
            result.email_source = "site_scrape_generic"
            result.log["generic_fallback"] = chosen
            logger.info(f"{label} — ✅ using published generic inbox: {chosen}")

        # If nothing found at all
        if not result.email_status:
            result.email_status = "not_found"
            logger.info(f"{label} — 🔴 not found after all 3 layers")

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
