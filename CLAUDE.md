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
| `outreach_language` | Language for this profile's outreach emails/LinkedIn: `es` (default, Argentine voseo) or `en`. Set from the profile form. |
| `outreach_instructions` | Free-text pitch/value-prop guidance injected into the outreach prompt (what the company offers, proof points, what to emphasize/avoid). Tunable from the profile form. |
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

### Node behavior & AI usage

The pipeline is tuned for **lead volume + low AI spend**. AI calls are kept to the
strict minimum; text processing without AI wherever possible.

| Node | AI? | Notes |
|---|---|---|
| `discover_companies` | ✅ Haiku ×2 | 1 query-generation call + 1 company-extraction call. Slices top 80 Tavily results, 500 chars each. |
| `score_opportunities` | ❌ none | **Pure-Python rule-based scoring** (`src/graph/nodes/scoring.py`). No AI call. See "Scoring" below. |
| `find_contacts` | ✅ Haiku | Finds **named** decision-makers per `target_roles`. Nameless/role-only entries are dropped at persist time (can't be emailed). |
| `generate_insights` | ⏸ disabled | `max_companies_for_insights=0` → node returns `[]` immediately, no AI call. Kept in the DAG but effectively a no-op. Old runs may still have stored insight data. |
| `generate_outreach` | ✅ Haiku | One call per company (up to `max_companies_for_outreach`). Grounded prompt. See "Outreach" below. |
| `generate_report` | ❌ none | Assembles the report dict. |
| `persist_to_db` | ❌ none | Upserts companies (dedup), opportunities, contacts, daily report. |

### Workflow tuning (`src/config.py` → `Settings`)

| Setting | Default | Purpose |
|---|---|---|
| `discovery_queries_per_run` | 12 | Tavily search queries generated per run |
| `max_companies_to_score` | 50 | Cap on unique companies carried into scoring |
| `max_companies_for_contacts` | 30 | Companies to find contacts for |
| `max_companies_for_insights` | 0 | **0 = insights disabled** (no AI) |
| `max_companies_for_outreach` | 20 | Companies to draft outreach for |
| `exclude_known_companies` | true | Skip companies already seen in prior runs → each run surfaces net-new leads |
| `rediscover_after_days` | 0 | 0 = never re-surface a known company; >0 = re-allow a never-contacted company after N days |

Net effect: ~15-20 concrete leads per run at roughly ~$0.12/run (vs the old AI-scoring
+ insights design at ~$0.48/run).

### Scoring (rule-based, no AI)

`src/graph/nodes/scoring.py` scores each company 0-100 in pure Python from structured
fields — no AI call. Buckets: company size (0-20), international exposure (0-25),
remote workforce (0-20), English hiring activity (0-15), industry/tech adoption (0-10),
English keyword signals (0-10). Priority: `quick_win` ≥70, `strategic` ≥40,
`low_priority` <40. `_parse_size()` turns "50-100"/"200+" into an approximate headcount.

### Outreach (grounded, profile-tunable)

`src/graph/nodes/outreach.py` + `src/prompts/outreach.py`. Uses **Haiku** (`fast_model`),
one lean payload per company (no insights). The prompt enforces hard **grounding rules**
to stop hallucination:
- Reference ONLY facts present in the company payload.
- Never claim the company "doesn't / lacks / hasn't" something (an absence can't be verified).
- If data is thin, open with a truthful industry/role-level observation instead of inventing a specific.

A profile's `outreach_instructions` (pitch, value props, proof points, what to emphasize/
avoid) is injected into the prompt as a `WHAT <AGENT> OFFERS` block — this is the main
lever to improve message quality per product.

The prompt enforces a tight first-touch **shape** (greeting → researched hook → one value
bridge → optional true proof → one low-friction CTA → short sign-off), an "earn the reply,
don't pitch" **approach**, and an expanded banned-phrase list. Message **language** is chosen
per profile via `outreach_language` and applied by `build_outreach_prompt()` in
`src/prompts/outreach.py` (Spanish = Argentine voseo; English = warm professional); both the
workflow outreach node and the worker's draft generator call it, so they stay in sync.

### Company deduplication

`_upsert_company()` in `src/tools/db_tools.py` ensures one `Company` row per real
business so feedback never splits across duplicates:
1. Match by normalized **domain** (`_normalize_domain`).
2. Else exact name (`ILIKE`).
3. Else **normalized name** via `normalize_company_name()` — lowercases, strips
   punctuation and legal suffixes (SA, SRL, Inc, Ltd…), so "Acme S.A." == "Acme".

The `/contacts-report` page also de-dups at display time: rows sharing a domain or
normalized name are merged into one card (contacts pooled), and the record with the
richest feedback becomes canonical so the Feedback / Desmarcar buttons target a single row.

### Cross-run dedup (net-new leads, no repeats)

`_upsert_company` prevents duplicate *rows*, but separate runs would still re-surface and
re-contact the **same** companies. Two guards prevent that:
- **Discovery** (`run_discovery_node`) dedups within a run via `normalize_company_name`,
  then drops any company already in the DB (matched by normalized name or domain).
  Controlled by `exclude_known_companies` / `rediscover_after_days`; companies with a
  `ContactStatus` are always excluded.
- **Worker Zoho push** skips any company already contacted (`ContactStatus`) or already
  pushed in a prior run — so a company never gets duplicate outreach across runs (the
  per-`Opportunity` `zoho_pushed_at` flag alone wouldn't catch this, since each run creates
  a fresh Opportunity).

## Contact Enrichment

After a discovery run, contacts can be enriched to find verified emails. The pipeline runs
**Layer 0** (resolve a missing company domain) followed by three verification layers:

### Layer 0 — Domain resolution (`src/enrichment/domain_resolver.py`)
The pipeline instant-fails if the company has no `domain` (~half of discovered companies).
`enrich_contact` first tries to resolve one: derive from an existing contact email, else
web-search the official site (rejecting social / job-board / directory hosts). The resolved
domain is persisted back to `Company` (unless another company already owns it — `domain` is
unique). Contacts with **no name** are skipped at persist time (they can't be pattern-matched
or looked up), so they no longer dilute the email ratio.

### Layer 1 — Site scraping (`src/enrichment/scraper.py`)
- Downloads up to 6 pages per domain (`/`, `/contacto`, `/contact`, `/nosotros`, `/equipo`, `/about`)
- Fetches `robots.txt` via `requests` with **5s timeout** (cached per domain to avoid 6× refetch); 8s page timeout, no retry
- http fallback only attempted on the root path `/`
- Extracts emails (regex) and Argentine phone/WhatsApp numbers
- All found emails are used to infer the corporate pattern for Layer 2

### Layer 2 — Pattern generation + SMTP verification (`src/enrichment/patterns.py` + `providers/`)
- Generates 6 email permutations: `first.last@`, `flast@`, `first@`, `firstlast@`, `f.last@`, `last@`
- If Layer 1 found domain emails, infers the corporate pattern and prioritizes it
- Verifies candidates via the configured provider — `EMAIL_VERIFIER_PROVIDER`: `millionverifier`
  (default, uses `EMAIL_VERIFIER_API_KEY`) or `neverbounce` (uses `NEVERBOUNCE_API_KEY`). The
  provider is chosen by `get_verifier()` in `src/enrichment/providers/__init__.py`; both map their
  results to the same `valid / catch_all / invalid / unknown` statuses.
- Stops on first `valid` result; `catch_all` → stored as `probable`, never `verified`

### Layer 3 — Hunter.io fallback (`src/enrichment/providers/hunter.py`)
- Calls Hunter.io email finder API (`HUNTER_API_KEY`)
- score ≥ 90 → `verified`; score ≥ 50 → `probable`

### Enrichment result fields on `Contact` model
| Field | Values |
|---|---|
| `email_status` | `verified`, `probable`, `not_found` (final values). `catch_all` is an intermediate verifier result, stored as `probable` |
| `email_source` | `site_scrape`, `pattern_verified`, `pattern_unverified`, `hunter` |
| `phone_whatsapp` | nullable text |
| `enriched_at` | datetime |
| `enrichment_log` | JSONB — full per-layer attempt log |

### Running enrichment
- **Web UI**: "Enrich" button per contact or "⚡ Enrich All" button in Outreach Drafts section
- **CLI**: `python run.py --enrich-run <run_id>`
- Both run asynchronously (background thread, same pattern as manual trigger)

### Bulk enrichment ("⚡ Enrich All")
- Route `POST /run/<id>/enrich-all` queues contacts and processes them **sequentially** in a daemon thread.
- **Skips already-enriched contacts** (`enriched_at IS NOT NULL`) so re-runs only fill gaps.
- **Blocks double-runs**: returns 409 if already active for that run_id.
- **Hard 3-minute cap per contact** via `ThreadPoolExecutor.result(timeout=180)` — a hung contact is marked failed and the queue moves on.
- Inserts a **2s delay between contacts** to avoid rate-limiting MillionVerifier/Hunter.
- Progress dict `_enrich_progress[run_id] = {done, total, failed, running, current_name}`:
  - `current_name` updates before each contact so the UI can show "⟳ Procesando: John Smith"
  - JS polls `/run/<id>/enrich-status` every 2s; **auto-resumes on page reload** (DOMContentLoaded check)
  - Displays `N OK · M error` inline
- Each contact takes ~15-70s (scrape + SMTP checks + Hunter fallback), so a full
  run of 30 contacts can take several minutes — this is expected.

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
| `/run/<id>` | GET | Run detail — quick wins, strategic, contacts, outreach drafts (all sections collapsed by default; insights section removed) |
| `/run/latest` | GET | Redirect to latest run |
| `/run/<id>/delete` | POST | Delete a failed run and its report |
| `/run/<id>/export/<fmt>` | GET | Export as `csv` or `md` |
| `/run/<id>/professional-report` | GET | View the AI professional report |
| `/run/<id>/professional-report/generate` | POST | Generate the AI professional report (async, reasoning model) |
| `/run/<id>/professional-report/download` | GET | Download the professional report as Markdown |
| `/run/<id>/zoho-drafts` | POST | Push outreach drafts to Zoho Mail |
| `/run/<id>/enrich-all` | POST | Bulk enrich all **un-enriched** contacts (async, queued) |
| `/run/<id>/enrich-status` | GET | Enrichment progress `{done, total, failed, running, current_name}` |
| `/contact/<id>/enrich` | POST | Enrich a single contact |
| `/contact/<id>/zoho-draft` | POST | Push a single contact's draft to Zoho Mail |
| `/contacts-report` | GET | Contacted companies grouped by profile (dedup, follow-up tracking) |
| `/search` | GET | Browse/search companies — full paginated listing (25/page); contacts panel when `?q=` set |
| `/search/export/<fmt>` | GET | Export the company listing (respects `?q=` filter) as `csv` or `md` |
| `/quick-run` | GET | Quick Run form + history list (last 15 runs) |
| `/quick-run` | POST | Start a Quick Run (creates DiscoveryRun, spawns background thread) |
| `/quick-run/<run_id>` | GET | Quick Run results page |
| `/quick-run/<run_id>/status` | GET | Polling endpoint `{phase, done, total, error}` |
| `/quick-run/<run_id>/push-all-zoho` | POST | Push all email drafts in a Quick Run to Zoho Mail |
| `/quick-run/<run_id>/push-one-zoho` | POST | Push a single company's draft to Zoho Mail |
| `/trigger` | POST | Manual discovery run (requires TRIGGER_PASSWORD) |
| `/schedule/update` | POST | Update cron schedule + profile |
| `/toggle-scheduler` | POST | Pause/resume scheduler |
| `/profiles` | GET | Profile list |
| `/profiles/new` | GET/POST | Create profile |
| `/profiles/<id>/edit` | GET/POST | Edit profile |
| `/company/<id>/toggle-contact` | POST | Mark company as contacted |
| `/company/<id>/feedback` | GET/POST | Get/save contact feedback |
| `/logs` | GET | SSE log stream (JSON) |

### Navigation (header)
Inline search bar → `⚡ Quick Run` → `Runs` → `Contactados` → `Perfiles` → `Salir`.
Visual separators between search/actions and the logout link.

### Global Search (`/search`)
Browse or search companies. With **no query** it lists **all companies** (25/page, prev/next
pagination); with a query it filters companies (name, domain, industry, location) and shows
matching contacts (name, email, role) in a second column. Cards have score pills, email status
badges, a link to the run where each company was found, and a "✓ Contactado" badge if the
company has a `ContactStatus`. **⬇ CSV / ⬇ MD** buttons export the company listing (respecting
the active `?q=` filter) via `/search/export/<fmt>` (`export_companies_csv` /
`export_companies_markdown` in `src/export.py`). Template: `src/templates/search.html`.

### Run detail UI features
- All sections (`Opportunities`, `Outreach`, `Follow-ups`) are **collapsed by default**.
- Email status badges per lead: ✅ verified / 🟡 probable / 🔵 LinkedIn only / 🔴 not found
- Per-contact "Enrich" button (inline result update)
- "⚡ Enrich All" bulk button with live progress counter (`N OK · M error`)
- "📧 Zoho Drafts" button (visible only if Zoho configured)
- Responsive: table → stacked cards on mobile (`data-label` attributes)
- Insights section was removed (insights are no longer generated).

### Quick Run (`/quick-run`)

Fast email-hunting workflow designed to maximize contact coverage in a single pass.

**What it does:**
1. Runs the full discovery pipeline (same LangGraph DAG as a regular run) for the chosen profile.
2. Immediately auto-enriches all contacts from that run (Layer 0 domain resolution → scrape → pattern + SMTP → Hunter).
3. Results page shows a flat table: Empresa | Contacto | Email badge | Descripción | Draft | Zoho | Seguimiento.

**Implementation (`src/web.py` — `_do_quick_run`):**
- Creates a `DiscoveryRun` row before spawning the thread (so the redirect to `/quick-run/<run_id>` is immediate).
- Invokes `graph.invoke(initial_state)` directly; does NOT call `run_workflow_once` (avoids scheduler coupling).
- After graph completes, queries all contacts for the run and enriches them sequentially with a 180s hard cap and 2s delay between contacts.
- Progress state stored in module-level `_quick_run_state[run_id]`: `{phase, done, total, error}`.
  - Phases: `running` (graph) → `enriching` (contacts) → `done` / `error`.

**Results page (`src/templates/quick_run.html`):**
- JS polls `/quick-run/<run_id>/status` every 3s during active phases; reloads when `phase == "done"`.
- "Push all to Zoho" button → `POST /quick-run/<run_id>/push-all-zoho` (bulk, returns count).
- Per-row "Zoho" button → `POST /quick-run/<run_id>/push-one-zoho` (single company).
- "Seguimiento" column: one toggle-contact button per company (using Jinja2 `namespace` to track `last_co` across rows).
- Draft preview modal with copy-to-clipboard.
- History list on the form page (`GET /quick-run`) shows last 15 DiscoveryRuns for navigation.

### Contacted Companies Report (`/contacts-report`)
Cross-run view of every company with a `ContactStatus` record, for follow-up tracking.
- Grouped by profile; each profile section is a **collapsible `<details>`, collapsed by default**, with an overdue badge.
- **De-duplicated**: rows for the same business (by domain or normalized name) collapse into one card.
- Each card: name, location, website, score, ≤40-word description, 1 notable fact, pooled
  contact rows (name · role · email + status badge), and a status strip
  (contacted date, method, response, follow-up date, comment).
- Follow-up highlighting: ⚠ overdue (red border), 📅 Hoy (amber), upcoming (accent).
- Card actions: **💬 Feedback** (opens the feedback modal) and **✕ Desmarcar** (removes
  the `ContactStatus`) — both target the canonical (richest-feedback) record.
- Stats bar: total contacted, follow-ups scheduled, overdue.

## Schedule

- Daily discovery at configured time (default 08:00 ART)
- `_schedule_profile_name` runtime variable (settable from UI)
- Falls back to `SCHEDULE_PROFILE_NAME` env var (default: empty = Default profile)
- Scheduler pauses/resumes via toggle button
- Time and days are ephemeral (not persisted across restart unless set in Railway env vars)

## Database

SQLAlchemy models in `src/database/models.py`. Migration runs automatically on startup via
`_run_migrations()` in `src/database/session.py` — uses `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
Current migrations: `discovery_runs.profile_id`, `profiles.outreach_instructions`,
`profiles.outreach_language`, the five `contacts.*` enrichment columns, and
`opportunities.outreach_subject` + `opportunities.zoho_pushed_at`.

Key models: `Profile`, `DiscoveryRun`, `Company`, `Contact` (with enrichment fields), `Opportunity`,
`ContactStatus`, `DailyReport`.

- **`Company`** — deduplicated by domain/normalized name (one row per real business).
- **`Contact`** — deduplicated within a company at insert time in `persist_run_node`:
  match by `linkedin_url` first (most reliable), then by `name` within the same `company_id`.
  On match, missing fields (`role`, `linkedin_url`, `email`) are backfilled from the new run;
  no duplicate row is created. This means the same person found across multiple runs stays as one row.
- **`Opportunity`** — one row per `(run_id, company_id)`. Key fields:
  - `outreach_draft` — email body text (persisted by workflow + worker)
  - `outreach_subject` — subject line (was previously only in `report_json`; now persisted here too)
  - `zoho_pushed_at` — set when the worker or any push action sends the draft to Zoho; used for idempotency
- **`ContactStatus`** — feedback per company (PK = `company_id`, so exactly one per company):
  `contacted_at`, `comment`, `contact_method`, `response_received`, `follow_up_date`,
  `icp_feedback` (JSONB). Drives the `/contacts-report` page.

## Environment Variables

### Railway (production)

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
| `EMAIL_VERIFIER_PROVIDER` | Enrichment | Layer 2 verifier: `millionverifier` (default) or `neverbounce` |
| `EMAIL_VERIFIER_API_KEY` | Enrichment | MillionVerifier API key (~$0.003/check). Needs a credit balance — at 0 credits the API returns `unknown` for every candidate and emails degrade to unverified guesses (`probable`/`pattern_unverified`) |
| `NEVERBOUNCE_API_KEY` | Enrichment | NeverBounce API key (used when provider=neverbounce; 1,000 free/month) |
| `HUNTER_API_KEY` | Enrichment | Hunter.io API key (25 free/month) |

### Worker-only (Windows mini PC — `worker/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Railway public connection string |
| `ANTHROPIC_API_KEY` | ✅ | Claude API key (Haiku for drafts, ~$2-4/month) |
| `ZOHO_CLIENT_ID` | ✅ | OAuth2 client ID (same self-client app) |
| `ZOHO_CLIENT_SECRET` | ✅ | OAuth2 client secret |
| `EMAIL_VERIFIER_PROVIDER` | Enrichment | Layer 2 verifier: `millionverifier` (default) or `neverbounce` |
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

## Windows Worker (`worker/`)

Standalone script that runs on a local Windows mini PC on a schedule (daily or every 2 days)
via Task Scheduler. Connects directly to the Railway PostgreSQL DB — Railway remains the single
source of truth. No data is stored locally; the worker only reads and writes to the shared DB.
Full operational runbook: **`worker/README.md`**.

### What it does (two phases per run)
1. **Enrichment** — picks up to `WORKER_ENRICH_BATCH` contacts where `enriched_at IS NULL`
   and runs the full pipeline (Layer 0 domain resolution → scrape → SMTP verify → Hunter).
   When `WORKER_RETRY_FAILED` is on and the batch isn't full, it also **retries** previously
   failed *named* contacts (still no email) up to `WORKER_MAX_ATTEMPTS` passes (counter in
   `enrichment_log.attempts`), so contacts that failed only for a missing domain succeed once
   Layer 0 resolves it.
2. **Zoho push** — finds the best opportunity per company (highest score) where a contact
   has a verified/probable email and `zoho_pushed_at IS NULL`. **Company-level guard**: skips
   companies already contacted (`ContactStatus`) or pushed in any prior run, so outreach is
   never duplicated across runs. Uses the stored `outreach_draft` + `outreach_subject`;
   generates a fresh draft with Claude Haiku if the opportunity has none. Sets `zoho_pushed_at`
   after a successful push (idempotency).

### Setup on Windows
1. Clone the repo; copy `worker/.env.example` → `worker/.env` and fill in credentials.
2. `pip install -r requirements.txt`
3. Create a Zoho self-client at [api-console.zoho.com](https://api-console.zoho.com),
   scope: `ZohoMail.messages.CREATE,ZohoMail.accounts.READ`.
4. `python run.py --zoho-auth <grant_token>` — stores `.zoho_tokens.json` in project root.
5. Schedule `worker/run_worker.bat` in Task Scheduler. Daily example (run in an admin shell):
   `schtasks /Create /TN "BlestWorker" /TR "C:\Projects\BlestLeadsAgent\worker\run_worker.bat" /SC DAILY /ST 09:00 /F`

`run_worker.bat` cd's to the project root and runs the worker via the `py -3.11` launcher,
appending stdout/stderr to `worker/worker_task.log`. The worker also logs to `worker/worker.log`
(both gitignored). `init_db()` runs at startup, so the worker applies any pending DB migrations
when it first connects. See `worker/README.md` for the full runbook.

### Key files
| File | Purpose |
|---|---|
| `worker/worker.py` | Main worker script (two-phase: enrich + push) |
| `worker/run_worker.bat` | Task Scheduler launcher (cd to root, runs via `py -3.11`, logs to `worker_task.log`) |
| `worker/README.md` | Worker setup + daily scheduling runbook |
| `worker/.env.example` | Config template for the Windows machine |

## Key Source Files

| File | Purpose |
|---|---|
| `run.py` | Entry point + CLI |
| `src/config.py` | Settings (pydantic-settings), workflow tuning, `get_profile_overrides()` |
| `src/database/models.py` | SQLAlchemy ORM models |
| `src/database/session.py` | DB session, `init_db()`, `_run_migrations()` |
| `src/web.py` | Flask app + all routes |
| `src/scheduler.py` | APScheduler setup, `run_workflow_once()` |
| `src/graph/workflow.py` | LangGraph DAG definition |
| `src/graph/nodes/` | discovery, scoring (rule-based), contacts, insights (disabled), outreach (grounded), report nodes |
| `src/prompts/outreach.py` | Grounded outreach prompt with `custom_instructions_block` |
| `src/tools/db_tools.py` | `persist_run_node`, `_upsert_company` (dedup), `normalize_company_name` |
| `src/enrichment/domain_resolver.py` | Layer 0 — resolve a missing company domain (email derive + official-site web search) |
| `src/enrichment/pipeline.py` | Enrichment orchestrator (Layer 0 domain resolution + 3 layers + attempt counter) |
| `src/enrichment/scraper.py` | Site scraper (Layer 1) |
| `src/enrichment/patterns.py` | Email pattern generation (Layer 2) |
| `src/enrichment/providers/` | `base.py`, `million_verifier.py`, `neverbounce.py`, `hunter.py`; `__init__.py` → `get_verifier()` factory |
| `src/integrations/zoho_mail.py` | Zoho Mail OAuth2 + draft creation |
| `src/dashboard.py` | Rich terminal dashboard, `_enrich_drafts_from_db()` |
| `src/export.py` | CSV + Markdown export |
| `src/templates/` | Jinja2 templates (base, runs, run, profile_form, profiles, contacts_report, quick_run, search) |
| `worker/worker.py` | Windows worker — enrichment + Zoho push (scheduled daily / every 2 days) |
| `worker/run_worker.bat` | Task Scheduler launcher for the worker |
| `tests/` | Unit tests for enrichment module |
