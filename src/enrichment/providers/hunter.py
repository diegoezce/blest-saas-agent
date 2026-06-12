import logging
import os
import requests

logger = logging.getLogger(__name__)

_API_URL = "https://api.hunter.io/v2/email-finder"


class HunterProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("HUNTER_API_KEY", "")

    def find_email(self, domain: str, first_name: str, last_name: str) -> dict | None:
        """
        Returns dict with keys: email, score, sources — or None on failure.
        score is Hunter's confidence 0-100.
        """
        if not self._api_key:
            logger.warning("HUNTER_API_KEY not set — skipping Hunter.io")
            return None
        try:
            resp = requests.get(
                _API_URL,
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": self._api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            d = data.get("data", {})
            email = d.get("email")
            if not email:
                return None
            return {
                "email": email,
                "score": d.get("score", 0),
                "sources": d.get("sources", []),
            }
        except Exception as e:
            logger.warning(f"Hunter.io error for {first_name} {last_name} @ {domain}: {e}")
            return None
