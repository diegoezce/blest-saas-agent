# Database Models & Migrations

SQLAlchemy 2.0 ORM models in `src/database/models.py`. Migrations run automatically 
on startup via `_run_migrations()` in `src/database/session.py` — uses 
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. No downtime migrations.

## Key Models

**`Profile`**
- One per product/service (e.g., Blest Learning, Blest App)
- Stores targeting, tone, language, outreach instructions, custom scoring rubric
- See `src/config/CLAUDE.md` for fields

**`DiscoveryRun`**
- One row per graph invocation
- `profile_id` — which profile this run used
- Tracks: created_at, duration, status, error messages, report JSON
- `enriched_contact_ids` (JSONB) — persists contact IDs enriched during this run; 
  allows recovery of enrichment state after page reload

**`Company`**
- Deduplicated by domain/normalized name (one row per real business)
- Fields: name, domain, location, industry, size, score, description, notables
- Feedback never splits across duplicates

**`Contact`**
- Deduplicated within a company by LinkedIn URL, then name
- Fields: name, role, linkedin_url, company_id
- Enrichment fields: `email`, `email_status` (verified/probable/not_found/bounced), 
  `email_source`, `phone_whatsapp`, `enriched_at`, `enrichment_log` (JSONB — 
  per-layer attempt log + `attempts` counter + `bad_emails` blocklist)
- `replied_at` — set when reply from this email detected in Zoho inbox

**`Opportunity`**
- One row per `(run_id, company_id)` pair
- Fields: company_id, run_id, score, priority, company_description, notables
- Outreach: `outreach_draft` (email body), `outreach_subject` (subject line)
- Zoho: `zoho_pushed_at` (set after push; used for idempotency)
- Follow-up: `followup_count` (0–2), `last_followup_at`, `followup_subject`, `followup_draft`

**`ContactStatus`**
- PK = `company_id` (exactly one per company, for feedback tracking)
- Fields: contacted_at, comment, contact_method, response_received, follow_up_date, icp_feedback (JSONB)
- Drives `/contacts-report` page

**`DailyReport`**
- Aggregates a run's results for the report page
- Stores all report data as JSONB `report_json`

**`IntakeSubmission`**
- One row per client-intake link (token-protected public form at `/intake/<token>`)
- Fields: `token` (unique), `label`, `language`, `status` (pending → submitted → generating → generated | error),
  `answers` (JSONB keyed by question key from `src/prompts/intake.py`), `error_message`,
  `profile_id` (FK — the AI-drafted inactive Profile), `submitted_at`, `generated_at`
- Operator UI: `/intake-admin` (create links, view answers, trigger AI profile draft)

**`EmailOpenEvent`**
- One row per email open event (triggered by tracking pixel)
- Fields: `email_id` (VARCHAR 100 — contact ID as string), `opened_at`, `ip_address`, `user_agent`
- Indexed on `email_id` for fast aggregation
- Queried via `GET /track/stats`, which classifies each hit with `_classify_open()`
  (`src/web.py`) using **IP + UA**: Zoho proxy (`136.143.x` / `ZohoMailImageProxy`) =
  sender's own view; Google proxy (`72.14.x` / `Chrome/42.0.23`) = real Gmail open. The
  page surfaces real recipient opens separately from sender self-opens.

## Current Migrations

- `discovery_runs.profile_id`
- `discovery_runs.enriched_contact_ids` (JSONB, default `{}`)
- `profiles.outreach_instructions`, `profiles.outreach_language`
- Enrichment columns: `contacts.email`, `email_status`, `email_source`, 
  `phone_whatsapp`, `enriched_at`, `enrichment_log`
- `contacts.replied_at`
- `profiles.discovery_strategy` (TEXT — free-text discovery strategy injected into query-gen + extraction prompts)
- `opportunities.outreach_subject`, `opportunities.zoho_pushed_at`
- Follow-up columns: `opportunities.followup_count`, `last_followup_at`, 
  `followup_subject`, `followup_draft`
- `email_open_events` table (CREATE TABLE IF NOT EXISTS — new table, not ALTER)
- `intake_submissions` table (CREATE TABLE IF NOT EXISTS — client intake links/answers; see `IntakeSubmission`)

**Module**: `src/database/session.py:_run_migrations()`
