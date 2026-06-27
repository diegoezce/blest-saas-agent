# Zoho Mail Integration

Pushes outreach drafts directly into Zoho Mail drafts folder. Also scans inbox for 
bounces and replies to auto-mark contacts and trigger follow-ups.

## One-Time Setup

1. Go to [api-console.zoho.com](https://api-console.zoho.com) → create **Self-Client** app
2. Add `ZOHO_CLIENT_ID` and `ZOHO_CLIENT_SECRET` to `.env`
3. Generate grant token (10 min; scope: `ZohoMail.messages.CREATE,ZohoMail.accounts.READ` 
   minimum; add `messages.READ,folders.READ` for bounce/reply detection)
4. Run `python run.py --zoho-auth <grant_token>` → stores tokens in `.zoho_tokens.json`

## Token Storage & Refresh

- **Local**: `.zoho_tokens.json` (gitignored) — takes priority
- **Railway/production**: env vars `ZOHO_REFRESH_TOKEN`, `ZOHO_ACCOUNT_ID`, `ZOHO_FROM_ADDRESS` — fallback when file absent
- Access token auto-refreshes every hour; refresh token long-lived (~90 days inactivity)

## Draft Creation

"📧 Zoho Drafts" button in run report header (visible only when Zoho configured):
- Creates one draft per company
- Prefers `channel=email` draft, falls back to first available
- Skips companies with no `contact_email`
- Shows result: `✓ N drafts creados · M sin email`

**Key functions**: `is_configured()`, `exchange_grant_token()`, `create_draft()`, 
`_get_access_token()` (auto-refresh)

### Draft formatting (`create_draft()` and `send_email()`)

- Body wrapped in `<div style="font-family:Arial,sans-serif;font-size:11px">` with `white-space:pre-wrap`
- **HTML signature** appended automatically after the body (Mariela Minetti / Directora / Blest Learning, with clickable LinkedIn and WhatsApp links)
- **`_strip_ai_signoff(text)`** — runs before HTML wrapping; removes trailing lines the AI appended after the CTA (URLs, "Más info en", names, phone numbers, social links). Uses `_SIGNOFF_RE` regex.
- **`_fix_spanish_punctuation(text)`** — runs after strip; adds missing `¿` before Spanish questions that lack the opening mark. Applied via regex on sentence boundaries.
- **Tracking pixel** — both functions accept optional `email_id: str`. When set and `TRACKING_BASE_URL` is configured, a 1×1 transparent PNG `<img>` is appended after the signature:
  `<img src="{TRACKING_BASE_URL}/track/open/{email_id}" width="1" height="1" style="display:none;" />`
  Call sites pass the contact's DB integer ID as string. Pixel is omitted if either value is absent.

## Bounce Detection

Scans Zoho inbox for bounce notifications (from `mailer-daemon`/`postmaster`; 
subjects like "Undelivered Mail", "Undeliverable"). Ignores "delay" notices.

Fetches message bodies to inspect for bounce keywords (e.g., "permanent error", "user unknown") 
to improve bounce detection accuracy. Extracts failed recipient addresses from bounce bodies 
and intersects with `Contact.email`.

**Workflow**: `GET /bounces/scan` (preview, read-only) → `POST /bounces/apply` 
(mark matched contacts `email_status="bounced"`; also drops them from worker's push).

Re-enrichment: Contacts with `email_status=not_found` or `None` are automatically re-enriched 
when rediscovered in future runs, allowing second chances for leads initially without email.

**Shared logic**: `src/tools/bounces.py` (`scan_and_match`, `mark_bounced`, `apply_bounces`)
— used by routes + CLI (`python run.py --check-bounces`).

⚠ Requires `messages.READ` + `folders.READ` scopes. Re-run `--zoho-auth` if gets 
`INVALID_OAUTHSCOPE`.

## Reply & OOO Detection

Reads inbox message stubs (no body fetch). `scan_inbox_senders()` returns `{address: 
latest_received_ms, ooo_senders: set}`.

- **Replies**: Set `Contact.replied_at` **only if message arrived after first-touch 
  push** (`Opportunity.zoho_pushed_at`). Also sets `ContactStatus.response_received="replied"` 
  (auto-detects on `/contacts-report`).

- **OOO**: When auto-reply from known contact's address arrives after their company 
  was contacted: upgrades `email_status → "verified"` / `email_source → "ooo_confirmed"`, 
  logs `enrichment_log["ooo_confirmed_at"]`, and resets follow-up cadence clock 
  (fires ~4d after OOO, not while away). Repeated OOOs from same contact don't further delay.

**Module**: `src/integrations/zoho_mail.py`
