import logging
import os
import requests

from .base import EmailVerifier, VerifyResult

logger = logging.getLogger(__name__)

_API_URL = "https://api.millionverifier.com/api/v3/"

# MillionVerifier result quality values that map to "valid"
_VALID_RESULTS = {"ok"}
_CATCH_ALL_RESULTS = {"catch_all"}


class MillionVerifierProvider(EmailVerifier):
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("EMAIL_VERIFIER_API_KEY", "")

    def verify(self, email: str) -> VerifyResult:
        if not self._api_key:
            logger.warning("EMAIL_VERIFIER_API_KEY not set — skipping MillionVerifier")
            return VerifyResult(status="unknown")
        try:
            resp = requests.get(
                _API_URL,
                params={"api": self._api_key, "email": email},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            quality = data.get("result", "unknown").lower()
            if quality in _VALID_RESULTS:
                return VerifyResult(status="valid", confidence=1.0, raw=data)
            if quality in _CATCH_ALL_RESULTS:
                return VerifyResult(status="catch_all", confidence=0.5, raw=data)
            if quality in {"invalid", "disposable", "spamtrap"}:
                return VerifyResult(status="invalid", confidence=0.0, raw=data)
            return VerifyResult(status="unknown", raw=data)
        except Exception as e:
            logger.warning(f"MillionVerifier error for {email}: {e}")
            return VerifyResult(status="unknown")
