"""Email-verification providers + a factory to pick one via env var.

Set `EMAIL_VERIFIER_PROVIDER` to choose:
  - "neverbounce"      → needs NEVERBOUNCE_API_KEY
  - "millionverifier"  → needs EMAIL_VERIFIER_API_KEY
  - "local"            → free MX/syntax/disposable pre-filter (never confirms a mailbox)
  - "smart" / "chain"  → local pre-filter first, then a paid backend (saves credits).
                         Backend chosen by EMAIL_VERIFIER_BACKEND, else NeverBounce if its
                         key is set, else MillionVerifier.
Default: "millionverifier".
"""
import logging
import os

from .base import EmailVerifier, VerifyResult
from .million_verifier import MillionVerifierProvider
from .neverbounce import NeverBounceProvider
from .local_filter import LocalFilterVerifier, ChainVerifier

logger = logging.getLogger(__name__)

_NEVERBOUNCE_ALIASES = {"neverbounce", "never_bounce", "never-bounce", "nb"}
_MILLIONVERIFIER_ALIASES = {"millionverifier", "million_verifier", "mv", ""}
_LOCAL_ALIASES = {"local", "mx", "heuristic", "filter"}
_CHAIN_ALIASES = {"smart", "chain", "composite"}


def _paid_verifier(name: str) -> EmailVerifier:
    """Return a credit-based verifier by name (defaults to MillionVerifier)."""
    if name in _NEVERBOUNCE_ALIASES:
        return NeverBounceProvider()
    if name and name not in _MILLIONVERIFIER_ALIASES:
        logger.warning(f"Unknown paid verifier {name!r}; falling back to MillionVerifier")
    return MillionVerifierProvider()


def get_verifier() -> EmailVerifier:
    """Return the configured email verifier (defaults to MillionVerifier)."""
    name = os.environ.get("EMAIL_VERIFIER_PROVIDER", "millionverifier").strip().lower()

    if name in _LOCAL_ALIASES:
        return LocalFilterVerifier()

    if name in _CHAIN_ALIASES:
        backend = os.environ.get("EMAIL_VERIFIER_BACKEND", "").strip().lower()
        if not backend:
            backend = "neverbounce" if os.environ.get("NEVERBOUNCE_API_KEY") else "millionverifier"
        return ChainVerifier(LocalFilterVerifier(), _paid_verifier(backend))

    return _paid_verifier(name)


__all__ = [
    "EmailVerifier",
    "VerifyResult",
    "MillionVerifierProvider",
    "NeverBounceProvider",
    "LocalFilterVerifier",
    "ChainVerifier",
    "get_verifier",
]
