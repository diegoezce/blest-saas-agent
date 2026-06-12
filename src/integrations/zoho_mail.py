import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_TOKENS_FILE = Path(".zoho_tokens.json")
_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
_ACCOUNTS_URL = "https://mail.zoho.com/api/accounts"


def is_configured() -> bool:
    """True if a refresh token is stored on disk."""
    try:
        tokens = _load_tokens()
        return bool(tokens.get("refresh_token"))
    except Exception:
        return False


def _load_tokens() -> dict:
    if _TOKENS_FILE.exists():
        return json.loads(_TOKENS_FILE.read_text())
    # Fall back to env vars (Railway / production)
    from src.config import get_settings
    cfg = get_settings()
    if cfg.zoho_refresh_token:
        return {
            "refresh_token": cfg.zoho_refresh_token,
            "account_id": cfg.zoho_account_id,
            "from_address": cfg.zoho_from_address,
        }
    return {}


def _save_tokens(data: dict) -> None:
    _TOKENS_FILE.write_text(json.dumps(data, indent=2))


def _get_credentials() -> tuple[str, str]:
    from src.config import get_settings
    cfg = get_settings()
    client_id = cfg.zoho_client_id
    client_secret = cfg.zoho_client_secret
    if not client_id or not client_secret:
        raise RuntimeError("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET must be set in .env")
    return client_id, client_secret


def _get_access_token() -> str:
    tokens = _load_tokens()
    if not tokens.get("refresh_token"):
        raise RuntimeError("Zoho Mail not configured. Run: python run.py --zoho-auth <grant_token>")

    # Return cached token if still valid (with 60s buffer)
    if tokens.get("access_token") and tokens.get("expires_at", 0) > time.time() + 60:
        return tokens["access_token"]

    # Refresh
    client_id, client_secret = _get_credentials()

    resp = requests.post(_TOKEN_URL, params={
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"Token refresh failed: {data}")

    tokens["access_token"] = access_token
    tokens["expires_at"] = time.time() + data.get("expires_in", 3600)
    _save_tokens(tokens)
    return access_token


def _fetch_account_info(access_token: str) -> dict:
    """Returns dict with accountId and fromAddress (primary email)."""
    resp = requests.get(
        _ACCOUNTS_URL,
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    accounts = data.get("data", [])
    if not accounts:
        raise RuntimeError("No Zoho Mail accounts found for this OAuth token")
    account = accounts[0]
    # Primary send-from address — try multiple fields Zoho may use
    from_address = account.get("primaryEmailAddress") or account.get("mailboxAddress", "")
    if not from_address:
        emails = account.get("emailAddress", [])
        primary = next((e["mailId"] for e in emails if e.get("isPrimary")), None)
        from_address = primary or (emails[0]["mailId"] if emails else "")
    return {"account_id": str(account["accountId"]), "from_address": from_address}


def exchange_grant_token(grant_token: str) -> None:
    """
    Exchange a self-client grant token for access + refresh tokens.
    Stores everything (including account_id) in .zoho_tokens.json.
    """
    client_id, client_secret = _get_credentials()

    resp = requests.post(_TOKEN_URL, params={
        "code": grant_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    refresh_token = data.get("refresh_token")
    access_token = data.get("access_token")
    if not refresh_token or not access_token:
        raise RuntimeError(f"Token exchange failed: {data}")

    info = _fetch_account_info(access_token)

    _save_tokens({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": info["account_id"],
        "from_address": info["from_address"],
        "expires_at": time.time() + data.get("expires_in", 3600),
    })
    logger.info(f"Zoho Mail configured — account_id={info['account_id']} from={info['from_address']}")


def create_draft(to_address: str, subject: str, content: str) -> dict:
    """
    Create a draft email in the authenticated Zoho Mail account.
    Returns the API response dict.
    """
    access_token = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    from_address = tokens.get("from_address", "")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run --zoho-auth.")

    # Wrap plain text in minimal HTML to preserve line breaks
    html_content = "<pre style='font-family:sans-serif;white-space:pre-wrap'>" + content + "</pre>"

    payload = {
        "toAddress": to_address,
        "subject": subject or "(sin asunto)",
        "content": html_content,
        "mailFormat": "html",
        "mode": "draft",
    }
    if from_address:
        payload["fromAddress"] = from_address

    resp = requests.post(
        f"{_ACCOUNTS_URL}/{account_id}/messages",
        headers={
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
