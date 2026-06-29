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
    # Email/contact-finding tools and data aggregators — a company is never these.
    # (These leaked in as wrong domains: Grupo MSA → prospeo.io.)
    "prospeo.io", "rocketreach.co", "lusha.com", "hunter.io", "snov.io",
    "signalhire.com", "contactout.com", "lead411.com", "datanyze.com",
    "kaspr.io", "uplead.com", "seamless.ai",
    # VC / investor sites — they share news pages with portfolio companies.
    # (Technisys → kaszek.com, its investor.)
    "kaszek.com", "sequoiacap.com", "ycombinator.com", "a16z.com",
    "softbank.com", "generalatlantic.com",
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

    # 2. Web search for the official site — ONLY accept a domain whose root matches
    # a company-name token. A non-matching domain is far more likely to be an
    # investor/news/data-tool page that merely mentions the company (Technisys →
    # kaszek.com; Grupo MSA → prospeo.io) than its real site. A wrong domain
    # generates bouncing or false-"verified" first.last@wrong emails, so it's
    # safer to return None (→ contact stays not_found) than to guess.
    tokens = _name_tokens(name)
    loc = f" {location}" if location else ""
    for query in (f"{name}{loc} sitio web oficial", f"{name} official website"):
        for r in search(query, max_results=5):
            d = _normalize_domain(r.get("url"))
            if not d or _host_blocked(d):
                continue
            if _domain_matches_name(d, tokens):
                logger.info(f"Domain resolved for '{name}': {d} (name match)")
                return d

    logger.info(f"Domain resolution for '{name}': no name-matching domain, returning None")
    return None
