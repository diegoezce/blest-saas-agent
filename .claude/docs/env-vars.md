# Environment Variables Reference

## Railway (Production)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key |
| `TAVILY_API_KEY` | ✅ | Web search API key |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `WEB_PASSWORD` | — | Login password (default: blest2024) |
| `TRIGGER_PASSWORD` | — | Manual trigger password |
| `SCHEDULE_TIME` | — | Cron time HH:MM (default: 08:00) |
| `SCHEDULE_DAYS` | — | Cron days (default: mon-thu) |
| `SCHEDULER_TIMEZONE` | — | Default: America/Argentina/Buenos_Aires |
| `FAST_MODEL` | — | Fast Claude model (default: claude-haiku-4-5-20251001) |
| `REASONING_MODEL` | — | Reasoning model (default: claude-sonnet-4-6) |
| `OUTREACH_MODEL` | — | Model for outreach + follow-up drafts (default: claude-sonnet-4-6). Set to Haiku ID to cut cost |

## Zoho Mail Integration

| Variable | Required | Description |
|---|---|---|
| `ZOHO_CLIENT_ID` | Zoho | OAuth2 client ID |
| `ZOHO_CLIENT_SECRET` | Zoho | OAuth2 client secret |
| `ZOHO_REFRESH_TOKEN` | Zoho/Railway | Long-lived refresh token (from `--zoho-auth`) |
| `ZOHO_ACCOUNT_ID` | Zoho/Railway | Zoho Mail account ID |
| `ZOHO_FROM_ADDRESS` | Zoho/Railway | Sender email address |

## Email Verification (Enrichment)

| Variable | Required | Description |
|---|---|---|
| `EMAIL_VERIFIER_PROVIDER` | Enrichment | Layer 2 verifier: `neverbounce`, `millionverifier` (default), `local` (free MX/syntax pre-filter), or `smart`/`chain` (local → paid backend) |
| `EMAIL_VERIFIER_BACKEND` | Enrichment | Paid backend for `smart`/`chain` (`neverbounce` or `millionverifier`); auto-selected if unset |
| `EMAIL_VERIFIER_API_KEY` | Enrichment | MillionVerifier API key (~$0.003/check). Needs credit balance — at 0 credits verifier returns `unknown` for all candidates |
| `NEVERBOUNCE_API_KEY` | Enrichment | NeverBounce API key (used when provider=neverbounce). Needs credits — new accounts must claim free credits or top up |
| `HUNTER_API_KEY` | Enrichment | Hunter.io API key (25 free/month) |

## Worker-Only (Windows mini PC — `worker/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Railway public connection string |
| `ANTHROPIC_API_KEY` | ✅ | Claude API key (Haiku for drafts, ~$2–4/month) |
| `ZOHO_CLIENT_ID` | ✅ | OAuth2 client ID (same self-client app) |
| `ZOHO_CLIENT_SECRET` | ✅ | OAuth2 client secret |
| `EMAIL_VERIFIER_PROVIDER` | Enrichment | Layer 2 verifier: `neverbounce`, `millionverifier` (default), `local`, or `smart`/`chain` |
| `EMAIL_VERIFIER_BACKEND` | Enrichment | Paid backend for `smart`/`chain` (auto-selected if unset) |
| `EMAIL_VERIFIER_API_KEY` | Enrichment | MillionVerifier key (provider=millionverifier) |
| `NEVERBOUNCE_API_KEY` | Enrichment | NeverBounce key (provider=neverbounce) |
| `HUNTER_API_KEY` | Enrichment | Hunter.io key |
| `FAST_MODEL` | — | Override model (default: claude-haiku-4-5-20251001) |
| `WORKER_ENRICH_BATCH` | — | Contacts to enrich per run (default: 15) |
| `WORKER_PUSH_BATCH` | — | Drafts to push per run (default: 15) |
| `WORKER_ENRICH_DELAY` | — | Seconds between enrichment calls (default: 3) |
| `WORKER_PUSH_DELAY` | — | Seconds between Zoho API calls (default: 1) |
| `WORKER_RETRY_FAILED` | — | Retry previously-failed named contacts (default: true) |
| `WORKER_MAX_ATTEMPTS` | — | Max enrichment passes per contact incl. first (default: 3) |
| `WORKER_RECOVER_BOUNCED` | — | Phase 1b: retry bounced contacts (default: true) |
| `WORKER_RECOVER_BATCH` | — | Bounced contacts to retry per run (default: 10) |
| `WORKER_RECOVER_DELAY` | — | Seconds between recovery contacts (default: 2) |
| `WORKER_CHECK_BOUNCES` | — | Phase 3: scan + mark bounced contacts (default: true; needs READ scope) |
| `WORKER_FOLLOWUP` | — | Phase 4: detect replies + push follow-ups (default: true; needs READ scope) |
| `WORKER_FOLLOWUP_BATCH` | — | Follow-up drafts to push per run (default: 15) |
| `WORKER_FOLLOWUP_DELAY` | — | Seconds between Zoho API calls in follow-up phase (default: 1) |

## Notes

- **MillionVerifier** at 0 credits returns `unknown` for all candidates → emails degrade to `probable` → bounces. Keep funded.
- **NeverBounce** new accounts must claim free credits or top up; otherwise gets "Insufficient credit balance" error.
- **Zoho tokens** — Local `.zoho_tokens.json` takes priority; Railway env vars are fallback.
- **Access token** auto-refreshes every hour; refresh token long-lived (~90 days inactivity).
