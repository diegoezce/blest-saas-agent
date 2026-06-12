# Blest Lead Discovery Agent

Multi-profile B2B lead discovery agent. Discovers, scores, and enriches leads for multiple
products/services, each with its own targeting criteria, AI prompts, scoring rubric, and outreach tone.
Generates email drafts and pushes them directly to Zoho Mail.

## Stack

- Python 3.11+
- LangGraph (workflow orchestration)
- Anthropic Claude API (via `instructor` for structured outputs)
- Tavily Search API (web discovery)
- PostgreSQL via SQLAlchemy 2.0 (`psycopg2-binary`)
- Rich (terminal dashboard)
- APScheduler (daily runs)
- Flask (web UI)
- Railway (deployment)
- `requests` + `beautifulsoup4` (contact enrichment scraping)

## CLI Commands

```
python run.py                        # Run discovery once (default profile)
python run.py --profile <ID>         # Run discovery for a specific profile
python run.py --web                  # Start web UI + embedded daily scheduler
python run.py --schedule             # Start scheduler daemon only
python run.py --report               # Show last run's dashboard
python run.py --report --date DATE   # Show report for DATE (YYYY-MM-DD)
python run.py --setup                # Initialize/migrate database tables
python run.py --enrich-run <ID>      # Enrich all contacts for a run
python run.py --zoho-auth <TOKEN>    # Store Zoho Mail OAuth credentials
```

## Multi-Profile System

The app supports multiple profiles, each representing a different product/service:

- **Blest Learning** (id=1) — Corporate English training for mid-large Argentine companies.
  Sells to L&D Managers, HR Managers at companies with 20-500 employees.

- **Blest App** (id=2) — SaaS platform for English academies and language institutes.
  Sells to Directors, Academic Coordinators at institutes with 2-30 employees.

### Profile Fields

| Field | Description |
|---|---|
| `name` | Unique profile name |
| `active` | Whether profile is enabled |
| `agent_company_name` | Company name for AI prompts (e.g. "Blest") |
| `agent_description` | Short description for prompts |
| `target_industries` | Comma-separated; overrides global config |
| `target_cities` | Comma-separated; overrides global config |
| `min_employees` | Overrides global config |
| `max_employees` | Overrides global config |
| `search_focus_terms` | Extra context for search query generation |
| `scoring_rubric` | JSONB - custom scoring rubric; falls back to DEFAULT_SCORING_RUBRIC |
| `outreach_tone` | One of: warm, direct, professional, referral |
| `target_roles` | One per line, priority order — internal personnel to find at each company (e.g. HR Manager, L&D Director). Shown in profile form as "Target Internal Personnel" under "Search Criteria — Who to Find" |

### How Profile Overrides Work

All graph nodes use `get_profile_overrides(profile_dict)` from `src/config.py`.
This merges profile values on top of global `Settings` defaults.
If a profile field is set it overrides the global config; if null the global value is used.

## Workflow Pipeline

LangGraph 7-node DAG:
```
discover_companies → score_opportunities → find_contacts → generate_insights
  → generate_outreach → generate_report → persist_to_db
```

## Contact Enrichment

After a discovery run, contacts can be enriched to find verified emails via a 3-layer pipeline:

### Layer 1 — Site scraping (`src/enrichment/scraper.py`)
- Downloads up to 6 pages per domain (`/`, `/contacto`, `/contact`, `/nosotros`, `/equipo`, `/about`)
- Respects `robots.txt`, 10s timeout, 1 req/s rate limit, `User-Agent: BlestLeadAgent/1.0`
- Extracts emails (regex) and Argentine phone/WhatsApp numbers
- All found emails are used to infer the corporate pattern for Layer 2

### Layer 2 — Pattern generation + SMTP verification (`src/enrichment/patterns.py` + `providers/million_verifier.py`)
- Generates 6 email permutations: `first.last@`, `flast@`, `first@`, `firstlast@`, `f.last@`, `last@`
- If Layer 1 found domain emails, infers the corporate pattern and prioritizes it
- Verifies candidates via MillionVerifier API (`EMAIL_VERIFIER_API_KEY`)
- Stops on first `valid` result; `catch_all` → stored as `probable`, never `verified`

### Layer 3 — Hunter.io fallback (`src/enrichment/providers/hunter.py`)
- Calls Hunter.io email finder API (`HUNTER_API_KEY`)
- score ≥ 90 → `verified`; score ≥ 50 → `probable`

### Enrichment result fields on `Contact` model
| Field | Values |
|---|---|
| `email_status` | `verified`, `probable`, `catch_all`, `not_found` |
| `email_source` | `site_scrape`, `pattern_verified`, `hunter` |
| `phone_whatsapp` | nullable text |
| `enriched_at` | datetime |
| `enrichment_log` | JSONB — full per-layer attempt log |

### Running enrichment
- **Web UI**: "Enrich" button per contact or "⚡ Enrich All" button in Outreach Drafts section
- **CLI**: `python run.py --enrich-run <run_id>`
- Both run asynchronously (background thread, same pattern as manual trigger)

## Zoho Mail Integration

Pushes outreach drafts directly into the Zoho Mail drafts folder.

### One-time setup
1. Go to [api-console.zoho.com](https://api-console.zoho.com) → create a **Self-Client** app
2. Add `ZOHO_CLIENT_ID` and `ZOHO_CLIENT_SECRET` to `.env`
3. Generate a grant token (scope: `ZohoMail.messages.CREATE,ZohoMail.accounts.READ`, 10 min duration)
4. Run `python run.py --zoho-auth <grant_token>` — stores tokens in `.zoho_tokens.json`

### Token storage
- **Local**: `.zoho_tokens.json` (gitignored) — takes priority
- **Railway/production**: env vars `ZOHO_REFRESH_TOKEN`, `ZOHO_ACCOUNT_ID`, `ZOHO_FROM_ADDRESS` — used as fallback when file is absent
- Access token auto-refreshes every hour; refresh token is long-lived (~90 days inactivity before Zoho revokes)

### Behavior
- "📧 Zoho Drafts" button appears in the run report header (only when Zoho is configured)
- Creates one draft per company: prefers `channel=email` draft, falls back to first available
- Skips companies with no `contact_email`
- Shows inline result: `✓ N drafts creados · M sin email`

### Module: `src/integrations/zoho_mail.py`
Key functions: `is_configured()`, `exchange_grant_token()`, `create_draft()`, `_get_access_token()` (auto-refresh)

## Web UI Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | All runs list (profile filter, hide failed) |
| `/run/<id>` | GET | Run detail — quick wins, strategic, contacts, insights, outreach drafts |
| `/run/latest` | GET | Redirect to latest run |
| `/run/<id>/delete` | POST | Delete a failed run and its report |
| `/run/<id>/export/<fmt>` | GET | Export as `csv` or `md` |
| `/run/<id>/professional-report` | GET/POST | Generate/view AI professional report |
| `/run/<id>/zoho-drafts` | POST | Push outreach drafts to Zoho Mail |
| `/run/<id>/enrich-all` | POST | Bulk enrich all contacts (async) |
| `/run/<id>/enrich-status` | GET | Enrichment progress `{done, total}` |
| `/contact/<id>/enrich` | POST | Enrich a single contact |
| `/trigger` | POST | Manual discovery run (requires TRIGGER_PASSWORD) |
| `/schedule/update` | POST | Update cron schedule + profile |
| `/toggle-scheduler` | POST | Pause/resume scheduler |
| `/profiles` | GET | Profile list |
| `/profiles/new` | GET/POST | Create profile |
| `/profiles/<id>/edit` | GET/POST | Edit profile |
| `/company/<id>/toggle-contact` | POST | Mark company as contacted |
| `/company/<id>/feedback` | GET/POST | Get/save contact feedback |
| `/logs` | GET | SSE log stream (JSON) |

### Run detail UI features
- Email status badges per lead: ✅ verified / 🟡 probable / 🔵 LinkedIn only / 🔴 not found
- Per-contact "Enrich" button (inline result update)
- "⚡ Enrich All" bulk button with live progress counter
- "📧 Zoho Drafts" button (visible only if Zoho configured)
- Responsive: table → stacked cards on mobile (`data-label` attributes)

## Schedule

- Daily discovery at configured time (default 08:00 ART)
- `_schedule_profile_name` runtime variable (settable from UI)
- Falls back to `SCHEDULE_PROFILE_NAME` env var (default: empty = Default profile)
- Scheduler pauses/resumes via toggle button
- Time and days are ephemeral (not persisted across restart unless set in Railway env vars)

## Database

SQLAlchemy models in `src/database/models.py`. Migration runs automatically on startup via
`_run_migrations()` in `src/database/session.py` — uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

Key models: `Profile`, `DiscoveryRun`, `Company`, `Contact` (with enrichment fields), `Opportunity`,
`ContactStatus`, `DailyReport`.

## Environment Variables

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
| `ZOHO_CLIENT_ID` | Zoho | OAuth2 client ID |
| `ZOHO_CLIENT_SECRET` | Zoho | OAuth2 client secret |
| `ZOHO_REFRESH_TOKEN` | Zoho/Railway | Long-lived refresh token (from `--zoho-auth`) |
| `ZOHO_ACCOUNT_ID` | Zoho/Railway | Zoho Mail account ID |
| `ZOHO_FROM_ADDRESS` | Zoho/Railway | Sender email address |
| `EMAIL_VERIFIER_API_KEY` | Enrichment | MillionVerifier API key (~$0.003/check) |
| `HUNTER_API_KEY` | Enrichment | Hunter.io API key (25 free/month) |

## Key Source Files

| File | Purpose |
|---|---|
| `run.py` | Entry point + CLI |
| `src/config.py` | Settings (pydantic-settings), `get_profile_overrides()` |
| `src/database/models.py` | SQLAlchemy ORM models |
| `src/database/session.py` | DB session, `init_db()`, `_run_migrations()` |
| `src/web.py` | Flask app + all routes |
| `src/scheduler.py` | APScheduler setup, `run_workflow_once()` |
| `src/graph/workflow.py` | LangGraph DAG definition |
| `src/graph/nodes/` | discovery, scoring, contacts, insights, outreach, report nodes |
| `src/enrichment/pipeline.py` | 3-layer enrichment orchestrator |
| `src/enrichment/scraper.py` | Site scraper (Layer 1) |
| `src/enrichment/patterns.py` | Email pattern generation (Layer 2) |
| `src/enrichment/providers/` | `base.py`, `million_verifier.py`, `hunter.py` |
| `src/integrations/zoho_mail.py` | Zoho Mail OAuth2 + draft creation |
| `src/dashboard.py` | Rich terminal dashboard, `_enrich_drafts_from_db()` |
| `src/export.py` | CSV + Markdown export |
| `src/templates/` | Jinja2 templates (base, runs, run, profile_form, profiles) |
| `tests/` | Unit tests for enrichment module (41 tests) |
