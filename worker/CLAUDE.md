# Windows Worker

Standalone script running on a local Windows mini PC on a schedule (daily or every 2 days) 
via Task Scheduler. Connects directly to Railway PostgreSQL DB (single source of truth). 
No local data storage; worker only reads/writes shared DB. Full runbook: `worker/README.md`.

## What It Does (Per Run)

**Phase 1b — Recovery** (optional, `WORKER_RECOVER_BOUNCED` default on):
- Retries up to `WORKER_RECOVER_BATCH` bounced contacts
- Blocklists bad addresses + re-enriches to find alternatives
- Runs before enrichment so recovered emails pushed same run

**Phase 1 — Enrichment** (`WORKER_ENRICH_BATCH`, default 15):
- Picks contacts where `enriched_at IS NULL`
- Runs full Layer 0–4 pipeline (domain resolve → scrape → SMTP → Hunter → web search if needed)
- If `WORKER_RETRY_FAILED` on: also retries previously-failed *named* contacts 
  up to `WORKER_MAX_ATTEMPTS` (stored in `enrichment_log.attempts`)
- 2s delay between contacts (avoid rate-limiting)

**Phase 2 — Zoho Push** (`WORKER_PUSH_BATCH`, default 15):
- Finds best opportunity per company (highest score) with verified/probable email + no `zoho_pushed_at`
- **Company-level guard**: skips already-contacted (`ContactStatus`) or already-pushed 
  in any prior run → outreach never duplicated
- Uses stored `outreach_draft` + `outreach_subject`; generates fresh Haiku draft if missing
- Sets `zoho_pushed_at` after push (idempotency)
- 1s delay between Zoho API calls

**Phase 3 — Bounce Check** (optional, `WORKER_CHECK_BOUNCES` default on):
- Scans Zoho inbox for bounce notifications
- Marks matched contacts `email_status="bounced"` (see `src/tools/bounces.py`)
- Non-fatal if token lacks READ scope

**Phase 4 — Follow-ups** (optional, `WORKER_FOLLOWUP` default on):
- Detects replies (marks `Contact.replied_at`)
- Generates + pushes follow-up drafts for contacted leads without replies
- Respects cadence: first follow-up 4d after push, second 6d after first
- Non-fatal if token lacks READ scope
- 1s delay between Zoho API calls in this phase

## Windows Setup

1. Clone repo; copy `worker/.env.example` → `worker/.env`, fill in credentials
2. `pip install -r requirements.txt`
3. Create Zoho self-client at [api-console.zoho.com](https://api-console.zoho.com)
   - Scope: `ZohoMail.messages.CREATE,ZohoMail.accounts.READ` minimum
   - Add `messages.READ,folders.READ` for bounce/reply detection
4. `python run.py --zoho-auth <grant_token>` → stores `.zoho_tokens.json` in project root
5. Schedule `worker/run_worker.bat` in Task Scheduler. Example (admin shell):
   ```
   schtasks /Create /TN "BlestWorker" /TR "C:\Projects\...\worker\run_worker.bat" /SC DAILY /ST 09:00 /F
   ```

## Logging

- `run_worker.bat` appends stdout/stderr to `worker/worker_task.log` (Task Scheduler output)
- Worker also logs to `worker/worker.log` (both gitignored)
- `init_db()` runs at startup, applies pending migrations

## Configuration (`.env` variables)

See `@.claude/docs/env-vars.md` for full list. Key worker-specific:
- `WORKER_ENRICH_BATCH`, `WORKER_PUSH_BATCH` — contacts/drafts per run
- `WORKER_RECOVER_BATCH` — bounced contacts to retry
- `WORKER_ENRICH_DELAY`, `WORKER_PUSH_DELAY` — seconds between API calls
- `WORKER_CHECK_BOUNCES`, `WORKER_FOLLOWUP` — toggle phases 3–4

**Module**: `worker/worker.py`
