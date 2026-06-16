"""Free, no-API e-mail pre-filter.

It can only *reject* obviously-bad addresses (bad syntax, disposable domain, or a
domain with no MX/A record) → `invalid`. It can NOT confirm that a mailbox exists
(that needs SMTP/port 25, which is blocked here, or a paid API), so a deliverable-
looking address returns `unknown` — never `valid`.

Used standalone (`EMAIL_VERIFIER_PROVIDER=local`) or as the cheap first step of
`ChainVerifier` (`EMAIL_VERIFIER_PROVIDER=smart`) to avoid spending paid credits on
dead domains.
"""
import logging
import re

from .base import EmailVerifier, VerifyResult

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Role/shared mailboxes — deliverable but low value; flagged, not rejected.
_ROLE_PREFIXES = {
    "info", "hola", "hello", "contact", "contacto", "ventas", "sales", "admin",
    "support", "soporte", "ayuda", "noreply", "no-reply", "postmaster", "webmaster",
    "marketing", "rrhh", "hr", "billing", "facturacion", "cobranzas", "administracion",
}

_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "yopmail.com", "trashmail.com", "getnada.com", "throwawaymail.com", "maildrop.cc",
    "temp-mail.org", "fakeinbox.com", "sharklasers.com", "dispostable.com", "mintemail.com",
}

# Cache MX results per domain (True=has mail records, False=none) for the process.
_mx_cache: dict[str, bool] = {}


def _has_mail_records(domain: str) -> bool | None:
    """True if domain has MX (or A fallback), False if definitely none, None if the
    lookup failed transiently (so the caller treats it as 'unknown', not invalid)."""
    d = domain.lower().strip()
    if d in _mx_cache:
        return _mx_cache[d]
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        logger.warning("dnspython not installed — skipping MX check (pip install dnspython)")
        return None
    try:
        answers = dns.resolver.resolve(d, "MX", lifetime=5)
        ok = len(answers) > 0
        _mx_cache[d] = ok
        return ok
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        # No MX → some domains still accept mail via their A record.
        try:
            dns.resolver.resolve(d, "A", lifetime=5)
            _mx_cache[d] = True
            return True
        except Exception:
            _mx_cache[d] = False
            return False
    except Exception as e:  # timeouts, other DNS errors — transient, don't cache
        logger.debug(f"MX lookup failed for {d}: {e}")
        return None


class LocalFilterVerifier(EmailVerifier):
    def verify(self, email: str) -> VerifyResult:
        e = (email or "").strip().lower()
        if not _EMAIL_RE.match(e):
            return VerifyResult(status="invalid", confidence=0.0, raw={"reason": "bad_syntax"})
        local, _, domain = e.partition("@")
        if domain in _DISPOSABLE_DOMAINS:
            return VerifyResult(status="invalid", confidence=0.0, raw={"reason": "disposable"})
        mx = _has_mail_records(domain)
        if mx is False:
            return VerifyResult(status="invalid", confidence=0.0, raw={"reason": "no_mx"})
        # Deliverable-looking but unconfirmed (mailbox existence needs a paid API / SMTP).
        return VerifyResult(
            status="unknown", confidence=0.0,
            raw={"reason": "deliverable_unconfirmed", "role": local in _ROLE_PREFIXES,
                 "mx": mx},
        )


class ChainVerifier(EmailVerifier):
    """Run a cheap pre-filter first; only call the paid verifier when the pre-filter
    can't decide. Saves paid credits on dead domains / malformed addresses."""

    def __init__(self, pre: EmailVerifier, paid: EmailVerifier):
        self._pre = pre
        self._paid = paid

    def verify(self, email: str) -> VerifyResult:
        pre = self._pre.verify(email)
        if pre.status == "invalid":
            return pre
        return self._paid.verify(email)
