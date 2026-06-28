"""Resolve a company's official web domain when discovery didn't capture one.

Used by the enrichment pipeline before it would otherwise instant-fail on a
company with no domain. Reuses the Tavily search tool and the domain
normalizer already in the codebase — no new infrastructure.
"""
import logging
import re

from src.tools.search import search
from src.tools.db_tools import _normalize_domain, normalize_company_name

logger = logging.getLogger(__name__)

# Hosts that are never a company's own official site (social, directories,
# job boards, data aggregators). A domain matching one of these is rejected.
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

# Tokens that aren't useful for matching a domain to a company name.
_STOP_TOKENS = {
    "grupo", "group", "argentina", "sociedad", "anonima", "company",
    "compania", "compañia", "srl", "sas", "saic", "the", "and",
    "servicios", "services", "consultora", "consulting",
}


def _host_blocked(domain: str) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in _BLOCKED_HOSTS)


def _name_tokens(name: str | None) -> list[str]:
    s = re.sub(r"[^\w\s]", " ", (name or "").lower())
    return [t for t in s.split() if len(t) >= 4 and t not in _STOP_TOKENS]


def _domain_matches_name(domain: str, tokens: list[str]) -> bool:
    root = domain.split(".")[0]
    return any(t in root or root in t for t in tokens)


def _title_mentions_name(title: str, tokens: list[str]) -> bool:
    """True if a search result title contains a company-name token.

    Used to gate the fallback domain: a result whose title names the company is
    far more likely to be the company's own site than an unrelated investor/news
    page that merely mentions it.
    """
    if not tokens:
        return False
    title_lower = (title or "").lower()
    return any(t in title_lower for t in tokens)


def resolve_company_domain(
    name: str | None,
    location: str | None = None,
    existing_emails: list[str] | None = None,
) -> str | None:
    """Best-effort resolution of a company's official domain.

    1. Derive from an existing contact email at the company.
    2. Web-search for the official site and pick the best non-blocked domain,
       preferring one whose root matches a token of the company name.

    Returns a normalized domain (e.g. "acme.com.ar") or None.
    """
    # 1. Derive from an existing contact's email
    for em in existing_emails or []:
        if em and "@" in em:
            d = em.split("@", 1)[1].strip().lower()
            d = _normalize_domain(d)
            if d and not _host_blocked(d):
                logger.info(f"Domain resolved from existing email: {d}")
                return d

    if not name:
        return None

    # 2. Web search for the official site
    tokens = _name_tokens(name)
    loc = f" {location}" if location else ""
    fallback: str | None = None
    for query in (f"{name}{loc} sitio web oficial", f"{name} official website"):
        for r in search(query, max_results=5):
            d = _normalize_domain(r.get("url"))
            if not d or _host_blocked(d):
                continue
            if _domain_matches_name(d, tokens):
                logger.info(f"Domain resolved for '{name}': {d} (name match)")
                return d
            # Only consider a non-matching domain as fallback when the result's
            # title actually mentions the company. This rejects investor/news/
            # partner domains (e.g. "Technisys" → kaszek.com, its VC) that share
            # a page with the company but aren't its site — those generate
            # bouncing first.last@wrong-domain emails. Acronym domains whose
            # title names the company (e.g. bacp.com.ar) still pass.
            if fallback is None and _title_mentions_name(r.get("title", ""), tokens):
                fallback = d
        if fallback:
            break

    if fallback:
        logger.info(f"Domain resolved for '{name}': {fallback} (fallback, title match)")
    else:
        logger.info(f"Domain resolution for '{name}': no confident match, returning None")
    return fallback
