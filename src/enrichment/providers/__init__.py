"""Email-verification providers + a factory to pick one via env var.

Set `EMAIL_VERIFIER_PROVIDER` to choose:
  - "millionverifier" (default) → needs EMAIL_VERIFIER_API_KEY
  - "neverbounce"               → needs NEVERBOUNCE_API_KEY
"""
import logging
import os

from .base import EmailVerifier, VerifyResult
from .million_verifier import MillionVerifierProvider
from .neverbounce import NeverBounceProvider

logger = logging.getLogger(__name__)

_NEVERBOUNCE_ALIASES = {"neverbounce", "never_bounce", "never-bounce", "nb"}


def get_verifier() -> EmailVerifier:
    """Return the configured email verifier (defaults to MillionVerifier)."""
    name = os.environ.get("EMAIL_VERIFIER_PROVIDER", "millionverifier").strip().lower()
    if name in _NEVERBOUNCE_ALIASES:
        return NeverBounceProvider()
    if name and name not in {"millionverifier", "million_verifier", "mv", ""}:
        logger.warning(f"Unknown EMAIL_VERIFIER_PROVIDER={name!r}; falling back to MillionVerifier")
    return MillionVerifierProvider()


__all__ = [
    "EmailVerifier",
    "VerifyResult",
    "MillionVerifierProvider",
    "NeverBounceProvider",
    "get_verifier",
]
