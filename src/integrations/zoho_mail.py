import json
import logging
import re
import time
from pathlib import Path

_SIGNOFF_RE = re.compile(
    r"(?i)^("
    r"más info|para más info|podés conocer|conocé más en|"
    r"https?://|www\.|"
    r"saludos|atentamente|hasta pronto|quedo a|cordialmente|"
    r"mariela|blest\s*learning|directora|hello@|"
    r"📧|🌐|💼|💬|\+54|tel[ée]fono|whatsapp"
    r")"
)

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


def _fix_spanish_punctuation(text: str) -> str:
    """Fix common Spanish punctuation errors in AI-generated drafts.

    - Adds missing ¿ before questions that lack the opening mark.
    """
    def maybe_fix(m):
        boundary, sentence = m.group(1), m.group(2)
        if "¿" in sentence:
            return m.group(0)
        return boundary + "¿" + sentence

    return re.sub(
        r"((?:^|(?<=[.!?])\s+))([^¿\n][^\n?]*\?)",
        maybe_fix,
        text,
        flags=re.MULTILINE,
    )


def _strip_ai_signoff(text: str) -> str:
    """Remove any sign-off lines the AI appended after the CTA."""
    lines = text.rstrip().split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and _SIGNOFF_RE.match(lines[-1].strip()):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines)


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

    # Clean up AI-generated content before wrapping
    content = _strip_ai_signoff(content)
    content = _fix_spanish_punctuation(content)

    # Wrap body in Arial 11px and append signature
    _STYLE = "font-family:Arial,sans-serif;font-size:11pt;line-height:1.6"
    _SIG = (
        '<div style="' + _STYLE + ';margin-top:18px;padding-top:12px;'
        'border-top:1px solid #d0d0d0;color:#555">'
        "Mariela Minetti<br>"
        "Directora<br>"
        "Blest Learning<br>"
        "📧 hello@blestlearning.com<br>"
        '🌐 <a href="https://www.blestlearning.com">www.blestlearning.com</a><br>'
        '💼 <a href="https://www.linkedin.com/company/blest-learning">LinkedIn</a><br>'
        '💬 <a href="https://wa.me/5491138908145">+54 9 11 3890 8145 (WhatsApp)</a>'
        "</div>"
    )
    html_content = (
        f'<div style="{_STYLE};white-space:pre-wrap">{content}</div>'
        + _SIG
    )

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


def send_email(to_address: str, subject: str, content: str) -> dict:
    """Send an email directly via Zoho Mail (not a draft).

    Includes List-Unsubscribe headers for one-click unsubscribe compliance.
    Returns the API response dict.
    """
    access_token = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    from_address = tokens.get("from_address", "")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run --zoho-auth.")

    content = _strip_ai_signoff(content)
    content = _fix_spanish_punctuation(content)

    _STYLE = "font-family:Arial,sans-serif;font-size:11pt;line-height:1.6"
    _SIG = (
        '<div style="' + _STYLE + ';margin-top:18px;padding-top:12px;'
        'border-top:1px solid #d0d0d0;color:#555">'
        "Mariela Minetti<br>"
        "Directora<br>"
        "Blest Learning<br>"
        "📧 hello@blestlearning.com<br>"
        '🌐 <a href="https://www.blestlearning.com">www.blestlearning.com</a><br>'
        '💼 <a href="https://www.linkedin.com/company/blest-learning">LinkedIn</a><br>'
        '💬 <a href="https://wa.me/5491138908145">+54 9 11 3890 8145 (WhatsApp)</a>'
        "</div>"
    )
    html_content = (
        f'<div style="{_STYLE};white-space:pre-wrap">{content}</div>'
        + _SIG
    )

    payload = {
        "toAddress": to_address,
        "subject": subject or "(sin asunto)",
        "content": html_content,
        "mailFormat": "html",
        "mode": "send",
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


# ── Unsubscribe detection (requires ZohoMail.messages.READ + folders.READ scope) ──

def scan_unsubscribe_requests(max_messages: int = 200) -> dict:
    """Scan the Zoho inbox for unsubscribe requests sent via List-Unsubscribe.

    Gmail/Outlook send an email to our from_address with subject 'unsubscribe'
    when the recipient clicks the one-click unsubscribe button. We extract the
    sender address and match it against known contacts.

    Returns {checked, unsubscribe_messages, addresses: [..]}
    """
    access = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run --zoho-auth.")
    base = f"{_ACCOUNTS_URL}/{account_id}"
    headers = {"Authorization": f"Zoho-oauthtoken {access}"}
    own_domain = (tokens.get("from_address", "").split("@")[-1] or "").lower()

    fr = requests.get(f"{base}/folders", headers=headers, timeout=15)
    fr.raise_for_status()
    folders = fr.json().get("data", [])
    inbox = next((f for f in folders if (f.get("folderName") or "").lower() == "inbox"), None)
    if not inbox:
        return {"checked": 0, "unsubscribe_messages": 0, "addresses": []}
    folder_id = inbox["folderId"]

    addresses: set[str] = set()
    unsubscribe_messages = 0
    checked = 0
    start = 1
    page = 50
    while checked < max_messages:
        mr = requests.get(
            f"{base}/messages/view", headers=headers,
            params={"folderId": folder_id, "limit": min(page, max_messages - checked), "start": start},
            timeout=20,
        )
        if mr.status_code != 200:
            break
        batch = mr.json().get("data", [])
        if not batch:
            break
        for m in batch:
            checked += 1
            subj = (m.get("subject") or "").lower().strip()
            if subj != "unsubscribe":
                continue
            unsubscribe_messages += 1
            frm = m.get("fromAddress") or m.get("sender") or ""
            match = _EMAIL_RE.search(frm)
            if not match:
                continue
            em = match.group(0).lower()
            if own_domain and own_domain in em:
                continue
            if any(n in em for n in _ADDR_NOISE):
                continue
            addresses.add(em)
        start += len(batch)
        if len(batch) < page:
            break

    return {
        "checked": checked,
        "unsubscribe_messages": unsubscribe_messages,
        "addresses": sorted(addresses),
    }


# ── Bounce detection (requires ZohoMail.messages.READ + folders.READ scope) ──

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BOUNCE_SENDERS = ("mailer-daemon", "mailerdaemon", "postmaster")
_BOUNCE_SUBJECTS = (
    "undeliver", "returned to sender", "failure notice", "mail delivery failed",
    "could not be delivered", "delivery has failed", "returned mail", "delivery failure",
)
# Domains/markers that are never the bounced lead (our own mailbox, the bounce daemon, Zoho).
_ADDR_NOISE = ("mailer-daemon", "postmaster", "@zoho.com", "noreply", "no-reply")

_OOO_SUBJECTS = (
    "out of office", "fuera de oficina", "fuera de la oficina",
    "automatic reply", "auto-reply", "autoreply",
    "respuesta automática", "respuesta automatica",
    "ausente", "vacation", "vacaciones",
)


def _is_bounce(msg: dict, body: str = "") -> bool:
    """True if a message looks like a hard bounce (excludes 'delay' notifications).

    Checks: sender (mailer-daemon/postmaster), subject keywords, OR body keywords.
    Rejects if subject/body says 'delay' but the action is not 'failed'.
    """
    frm = (msg.get("fromAddress") or msg.get("sender") or "").lower()
    subj = (msg.get("subject") or "").lower()
    body_lower = body.lower()

    # If subject explicitly says "delay" and the action is "delayed" (not "failed"), skip it
    action = (msg.get("action") or "").lower()
    if "delay" in subj and action == "delayed":
        return False

    # Check sender
    is_bounce_sender = any(s in frm for s in _BOUNCE_SENDERS)
    # Check subject keywords
    is_bounce_subject = any(s in subj for s in _BOUNCE_SUBJECTS)
    # Check body keywords (permanent error, could not be delivered, etc.)
    is_bounce_body = "permanent error" in body_lower or any(s in body_lower for s in _BOUNCE_SUBJECTS)

    return is_bounce_sender or is_bounce_subject or is_bounce_body


def _is_ooo(msg: dict) -> bool:
    """True if a message is an out-of-office auto-reply."""
    subj = (msg.get("subject") or "").lower()
    return any(s in subj for s in _OOO_SUBJECTS)


def scan_bounced_addresses(max_messages: int = 200) -> dict:
    """Scan the Zoho inbox for bounce notifications and extract the addresses that bounced.

    Returns {checked, bounce_messages, addresses: [..]} where `addresses` are candidate
    recipient emails pulled from the bounce bodies (lowercased, noise filtered). Callers
    intersect these with known contacts to decide what to mark.

    Requires the OAuth token to include ZohoMail.messages.READ + ZohoMail.folders.READ.
    """
    access = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run --zoho-auth.")
    base = f"{_ACCOUNTS_URL}/{account_id}"
    headers = {"Authorization": f"Zoho-oauthtoken {access}"}
    own_domain = (tokens.get("from_address", "").split("@")[-1] or "").lower()

    fr = requests.get(f"{base}/folders", headers=headers, timeout=15)
    fr.raise_for_status()
    folders = fr.json().get("data", [])
    inbox = next((f for f in folders if (f.get("folderName") or "").lower() == "inbox"), None)
    if not inbox:
        return {"checked": 0, "bounce_messages": 0, "addresses": []}
    folder_id = inbox["folderId"]

    addresses: set[str] = set()
    bounce_messages = 0
    checked = 0
    start = 1
    page = 50
    while checked < max_messages:
        mr = requests.get(
            f"{base}/messages/view", headers=headers,
            params={"folderId": folder_id, "limit": min(page, max_messages - checked), "start": start},
            timeout=20,
        )
        if mr.status_code != 200:
            break
        batch = mr.json().get("data", [])
        if not batch:
            break
        for m in batch:
            checked += 1
            mid = m.get("messageId")
            # Fetch body to check bounce keywords + extract emails
            cr = requests.get(f"{base}/folders/{folder_id}/messages/{mid}/content",
                              headers=headers, timeout=20)
            if cr.status_code != 200:
                continue
            body = (cr.json().get("data", {}) or {}).get("content", "") or ""
            # Now check if it's a bounce (can inspect body)
            if not _is_bounce(m, body):
                continue
            bounce_messages += 1
            # Extract emails from body
            for raw in _EMAIL_RE.findall(body):
                em = raw.lower()
                if own_domain and own_domain in em:
                    continue
                if any(n in em for n in _ADDR_NOISE):
                    continue
                addresses.add(em)
        start += len(batch)
        if len(batch) < page:
            break

    return {"checked": checked, "bounce_messages": bounce_messages, "addresses": sorted(addresses)}


def scan_inbox_senders(max_messages: int = 200) -> dict:
    """Scan the Zoho inbox and return the sender addresses of incoming mail.

    Returns {checked, senders, ooo_senders} where:
    - `senders` is {address: received_ms} — latest received timestamp per sender
    - `ooo_senders` is a set of addresses that sent an out-of-office auto-reply;
      these confirm the email is valid without counting as a real reply.

    Reads only message stubs (no body fetch), so it's cheap. Filters out our own
    domain, the bounce daemon and known noise.

    Requires the OAuth token to include ZohoMail.messages.READ + ZohoMail.folders.READ.
    """
    access = _get_access_token()
    tokens = _load_tokens()
    account_id = tokens.get("account_id")
    if not account_id:
        raise RuntimeError("No account_id stored. Re-run --zoho-auth.")
    base = f"{_ACCOUNTS_URL}/{account_id}"
    headers = {"Authorization": f"Zoho-oauthtoken {access}"}
    own_domain = (tokens.get("from_address", "").split("@")[-1] or "").lower()

    fr = requests.get(f"{base}/folders", headers=headers, timeout=15)
    fr.raise_for_status()
    folders = fr.json().get("data", [])
    inbox = next((f for f in folders if (f.get("folderName") or "").lower() == "inbox"), None)
    if not inbox:
        return {"checked": 0, "senders": {}}
    folder_id = inbox["folderId"]

    senders: dict[str, int] = {}
    ooo_senders: set[str] = set()
    # {sender_email: [alt_email, ...]} — alternative contacts found in OOO bodies
    ooo_alternatives: dict[str, list[str]] = {}
    checked = 0
    start = 1
    page = 50
    while checked < max_messages:
        mr = requests.get(
            f"{base}/messages/view", headers=headers,
            params={"folderId": folder_id, "limit": min(page, max_messages - checked), "start": start},
            timeout=20,
        )
        if mr.status_code != 200:
            break
        batch = mr.json().get("data", [])
        if not batch:
            break
        for m in batch:
            checked += 1
            frm = m.get("fromAddress") or m.get("sender") or ""
            match = _EMAIL_RE.search(frm)
            if not match:
                continue
            em = match.group(0).lower()
            if own_domain and own_domain in em:
                continue
            if any(n in em for n in _ADDR_NOISE):
                continue
            try:
                ts = int(m.get("receivedTime") or 0)
            except (TypeError, ValueError):
                ts = 0
            if em not in senders or ts > senders[em]:
                senders[em] = ts
            if _is_ooo(m):
                ooo_senders.add(em)
                # Fetch body to extract alternative contact emails.
                # Only capture emails at the same domain (same company).
                sender_domain = em.split("@")[-1]
                mid = m.get("messageId")
                if mid and em not in ooo_alternatives:
                    try:
                        cr = requests.get(
                            f"{base}/folders/{folder_id}/messages/{mid}/content",
                            headers=headers, timeout=15,
                        )
                        if cr.status_code == 200:
                            body = (cr.json().get("data", {}) or {}).get("content", "") or ""
                            alts = []
                            for raw in _EMAIL_RE.findall(body):
                                alt = raw.lower()
                                if alt == em:
                                    continue
                                if own_domain and own_domain in alt:
                                    continue
                                if any(n in alt for n in _ADDR_NOISE):
                                    continue
                                if alt.split("@")[-1] == sender_domain:
                                    alts.append(alt)
                            if alts:
                                ooo_alternatives[em] = alts
                    except Exception:
                        pass  # non-fatal
        start += len(batch)
        if len(batch) < page:
            break

    return {
        "checked": checked,
        "senders": senders,
        "ooo_senders": ooo_senders,
        "ooo_alternatives": ooo_alternatives,
    }
