"""Layer 4: Find emails via Tavily web search — replicates manual "company email" lookups.

Only invoked for dubious cases (email_status != "verified") to minimize API cost.
Queries are built from contact name + company + role, extracts emails from snippets,
filters by domain/reputation, and scores by name match.
"""
import logging
import re
from dataclasses import dataclass

from src.tools.search import search
from src.tools.db_tools import _normalize_domain

logger = logging.getLogger(__name__)

# Hosts that are never a company's own domain.
_BLOCKED_HOSTS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "crunchbase.com",
    "bloomberg.com", "glassdoor.com", "glassdoor.com.ar", "indeed.com",
    "bumeran.com.ar", "bumeran.com", "computrabajo.com.ar", "computrabajo.com",
    "zonajobs.com.ar", "paginasamarillas.com.ar", "guiatelefonica.com.ar",
    "cylex.com.ar", "cylex.com", "clutch.co", "g2.com", "google.com",
    "medium.com", "wordpress.com", "blogspot.com", "github.com", "apollo.io",
    "zoominfo.com", "infobae.com", "lanacion.com.ar", "cronista.com",
    "clarin.com", "ambito.com", "elempleo.com", "trabajando.com",
}

# Generic mailbox prefixes that signal a company inbox (no named person).
GENERIC_PREFIXES = (
    "contacto", "contact", "info", "informes", "hola", "hello", "consultas",
    "ventas", "sales", "recepcion", "secretaria", "ayuda", "soporte",
    "support", "admin", "administracion", "comercial", "marketing",
    "capacitacion", "formacion", "rrhh", "recursoshumanos",
)


@dataclass
class WebEmailCandidateResult:
    email: str | None = None
    source: str | None = None  # "web_search" | "web_search_generic"
    confidence: str = "low"  # "high" (named match) | "medium" (consensus) | "low" (generic only)
    log: dict | None = None


def _host_blocked(domain: str) -> bool:
    """True if domain is a social network, job board, aggregator, etc."""
    return any(domain == h or domain.endswith("." + h) for h in _BLOCKED_HOSTS)


def _is_generic_inbox(local_part: str) -> bool:
    """True if the email is a shared mailbox (info@, contacto@, etc.)."""
    return any(local_part.lower().startswith(p) for p in GENERIC_PREFIXES)


def _extract_emails_from_text(text: str) -> set[str]:
    """Extract email addresses from text using regex."""
    pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    return set(re.findall(pattern, text))


def _name_matches_local(first: str, last: str, local_part: str) -> bool:
    """True if the email local part contains the contact's first or last name."""
    if not (first or last):
        return False
    local_lower = local_part.lower()
    first_norm = first.lower().replace(" ", "")
    last_norm = last.lower().replace(" ", "")
    return bool(first_norm and first_norm in local_lower) or bool(last_norm and last_norm in local_lower)


def find_emails_via_web_search(
    first_name: str,
    last_name: str,
    company_name: str,
    domain: str,
    role: str | None = None,
    bad_emails: set[str] | None = None,
) -> WebEmailCandidateResult:
    """
    Search the web for emails matching a contact at a company.

    Returns the best candidate email with source and confidence, or None if nothing found.

    Args:
        first_name: Contact first name
        last_name: Contact last name
        company_name: Company legal name
        domain: Company official domain (e.g., "acme.com.ar")
        role: Job title/role (optional, used in secondary queries)
        bad_emails: Set of addresses known to bounce (never propose these)

    Returns:
        WebEmailCandidateResult with email, source, confidence, and debug log.
    """
    bad_emails = bad_emails or set()
    log = {}

    if not domain or not company_name:
        log["error"] = "missing domain or company_name"
        return WebEmailCandidateResult(log=log)

    # Build search queries (4 variants, ordered by specificity).
    queries = []
    if first_name and last_name:
        queries.append(f'"{first_name} {last_name}" "{company_name}" email')
        queries.append(f'"{first_name} {last_name}" {domain} correo')
    if role:
        queries.append(f'"{company_name}" {role} contacto email')
    queries.append(f'"{company_name}" contacto email')

    log["queries"] = queries

    # Collect candidates with metadata.
    candidates: dict[str, dict] = {}  # email -> {domain, is_generic, matches_name, query}

    for query in queries:
        try:
            results = search(query, max_results=5)
            log.setdefault("search_results", []).append({
                "query": query,
                "count": len(results),
            })

            for r in results:
                # Extract emails from title and content (snippet).
                emails = _extract_emails_from_text(r.get("title", ""))
                emails.update(_extract_emails_from_text(r.get("content", "")))

                for em in emails:
                    if em in bad_emails or em in candidates:
                        continue

                    em_lower = em.lower()
                    local, at_domain = em_lower.rsplit("@", 1) if "@" in em_lower else (em_lower, "")
                    at_domain_norm = _normalize_domain(at_domain) if at_domain else None

                    # Reject if domain is blocked or doesn't match company domain.
                    if not at_domain_norm or _host_blocked(at_domain_norm):
                        continue
                    if at_domain_norm != _normalize_domain(domain):
                        # Allow close matches (subdomains), but only if explicitly the company domain.
                        if not (at_domain_norm.endswith("." + _normalize_domain(domain))):
                            continue

                    is_generic = _is_generic_inbox(local)
                    matches_name = _name_matches_local(first_name, last_name, local)

                    candidates[em] = {
                        "domain": at_domain_norm,
                        "is_generic": is_generic,
                        "matches_name": matches_name,
                        "query": query,
                    }

        except Exception as e:
            logger.warning(f"Web search failed for query '{query}': {e}")
            log.setdefault("exceptions", []).append(str(e))

    if not candidates:
        log["result"] = "no candidates found"
        return WebEmailCandidateResult(log=log)

    log["candidates_found"] = len(candidates)

    # Rank candidates: named match > generic only.
    named = [em for em, meta in candidates.items() if meta["matches_name"] and not meta["is_generic"]]
    generics = [em for em, meta in candidates.items() if meta["is_generic"]]

    if named:
        best = named[0]
        return WebEmailCandidateResult(
            email=best,
            source="web_search",
            confidence="high",
            log={**log, "best_email": best, "strategy": "named_match"},
        )

    if generics:
        best = generics[0]
        return WebEmailCandidateResult(
            email=best,
            source="web_search_generic",
            confidence="medium",
            log={**log, "best_email": best, "strategy": "generic_inbox"},
        )

    # Should not reach here (candidates is non-empty), but for safety.
    log["result"] = "no rankable candidates"
    return WebEmailCandidateResult(log=log)
