import logging
import os
import requests

from .base import EmailVerifier, VerifyResult

logger = logging.getLogger(__name__)

# NeverBounce v4 single-check endpoint.
# Docs: https://developers.neverbounce.com/reference/single-check
_API_URL = "https://api.neverbounce.com/v4/single/check"


class NeverBounceProvider(EmailVerifier):
    """Email verifier backed by NeverBounce (alternative to MillionVerifier).

    Maps NeverBounce's `result` field to the shared VerifyResult statuses:
      valid     -> valid
      catchall  -> catch_all
      invalid   -> invalid
      disposable-> invalid
      unknown   -> unknown
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("NEVERBOUNCE_API_KEY", "")

    def verify(self, email: str) -> VerifyResult:
        if not self._api_key:
            logger.warning("NEVERBOUNCE_API_KEY not set — skipping NeverBounce")
            return VerifyResult(status="unknown")
        try:
            resp = requests.get(
                _API_URL,
                params={"key": self._api_key, "email": email},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # The HTTP call can succeed while the API reports an error
            # (auth_failure, temp_unavail, throttle_triggered, ...).
            api_status = (data.get("status") or "").lower()
            if api_status != "success":
                logger.warning(
                    f"NeverBounce non-success for {email}: "
                    f"{api_status or 'no status'} {data.get('message', '')}"
                )
                return VerifyResult(status="unknown", raw=data)

            result = (data.get("result") or "unknown").lower()
            if result == "valid":
                return VerifyResult(status="valid", confidence=1.0, raw=data)
            if result == "catchall":
                return VerifyResult(status="catch_all", confidence=0.5, raw=data)
            if result in {"invalid", "disposable"}:
                return VerifyResult(status="invalid", confidence=0.0, raw=data)
            return VerifyResult(status="unknown", raw=data)
        except Exception as e:
            logger.warning(f"NeverBounce error for {email}: {e}")
            return VerifyResult(status="unknown")
