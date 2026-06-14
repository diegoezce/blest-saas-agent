import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = "BlestLeadAgent/1.0 (contact enrichment; +https://blest.app)"
_TIMEOUT = 8
_MAX_PAGES = 6
_PATHS_TO_CHECK = ["/", "/contacto", "/contact", "/nosotros", "/equipo", "/about"]

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[a-z]{2,})+", re.IGNORECASE)

# Argentine phone / WhatsApp: +54 9 11 1234-5678, 011-1234-5678, etc.
_PHONE_RE = re.compile(
    r"(?:\+54[\s\-]?9?[\s\-]?|0)(?:11|[2-9]\d{1,3})[\s\-]?\d{4}[\s\-]?\d{4}"
)

# Cache robots.txt per domain to avoid re-fetching for every path
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _get_robots(domain: str) -> urllib.robotparser.RobotFileParser:
    if domain in _robots_cache:
        return _robots_cache[domain]
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = requests.get(
            f"https://{domain}/robots.txt",
            headers={"User-Agent": _USER_AGENT},
            timeout=5,
        )
        rp.parse(resp.text.splitlines())
    except Exception:
        pass  # assume all paths allowed if robots.txt unreachable/slow
    _robots_cache[domain] = rp
    return rp


def _can_fetch(domain: str, path: str) -> bool:
    try:
        rp = _get_robots(domain)
        return rp.can_fetch(_USER_AGENT, f"https://{domain}{path}")
    except Exception:
        return True


@dataclass
class ScrapeResult:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    pages_checked: int = 0
    blocked_by_robots: bool = False
    error: str | None = None


def _get_page(url: str) -> str | None:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.debug(f"Failed {url}: {e}")
    return None


def scrape_domain(domain: str) -> ScrapeResult:
    result = ScrapeResult()
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    # Normalise domain (strip scheme/path if present)
    if "://" in domain:
        domain = urlparse(domain).netloc
    domain = domain.lstrip("www.").strip("/")
    if not domain:
        result.error = "empty domain"
        return result

    checked = 0
    for path in _PATHS_TO_CHECK:
        if checked >= _MAX_PAGES:
            break
        if not _can_fetch(domain, path):
            logger.debug(f"robots.txt blocked {domain}{path}")
            result.blocked_by_robots = True
            continue

        url = f"https://{domain}{path}"
        html = _get_page(url)
        if html is None:
            # try http fallback only for the root path
            if path == "/":
                html = _get_page(f"http://{domain}{path}")
        if html is None:
            continue

        checked += 1
        # Extract from raw text (catches obfuscated mailto etc.)
        text = BeautifulSoup(html, "html.parser").get_text(" ")
        for email in _EMAIL_RE.findall(text):
            email = email.lower()
            if email not in seen_emails:
                seen_emails.add(email)
                result.emails.append(email)
        for phone in _PHONE_RE.findall(text):
            phone = phone.strip()
            if phone not in seen_phones:
                seen_phones.add(phone)
                result.phones.append(phone)

        time.sleep(1)  # respect rate limit

    result.pages_checked = checked
    return result
