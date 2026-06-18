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
python run.py --check-bounces        # Scan Zoho inbox for bounces, mark matched contacts
python run.py --detect-replies       # Scan Zoho inbox for replies, mark answered contacts
python run.py --follow-ups           # Generate + push follow-up drafts for unanswered leads
python run.py --recover-bounced [N]  # Retry bounced contacts (blocklist + re-enrich); N max (default 50)
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

`src/graph/nodes/outreach.py` + `src/prompts/outreach.py`. Uses the **`outreach_model`**
(`OUTREACH_MODEL`, default Sonnet `claude-sonnet-4-6`) for customer-facing draft quality —
the same model is used by the workflow node, the worker draft generator, and the follow-up
generator. One lean payload per company (no insights). The prompt enforces hard **grounding rules**
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
- A **named-person** email matching the contact (first/last in the local part) is taken
  immediately as `verified` / `site_scrape`.
- **Generic/shared inboxes** on the domain (`info@`, `contacto@`, `ventas@`, …) are captured
  and held as a fallback (`GENERIC_PREFIXES` in `pipeline.py`; system boxes like `noreply@`
  excluded). They are a real, published, deliverable address, so they're used **only if no
  verified named email is found** — see the precedence note below.

### Layer 2 — Pattern generation + SMTP verification (`src/enrichment/patterns.py` + `providers/`)
- Generates 6 email permutations: `first.last@`, `flast@`, `first@`, `firstlast@`, `f.last@`, `last@`
- If Layer 1 found domain emails, infers the corporate pattern and prioritizes it
- Verifies candidates via the configured provider — `EMAIL_VERIFIER_PROVIDER`:
  - `neverbounce` (uses `NEVERBOUNCE_API_KEY`) or `millionverifier` (default, uses `EMAIL_VERIFIER_API_KEY`)
  - `local` — free, no-API pre-filter (`src/enrichment/providers/local_filter.py`): syntax +
    disposable-domain + **MX/A DNS check** (needs `dnspython`). Rejects dead domains / bad syntax
    as `invalid`; **never returns `valid`** (can't confirm a mailbox — real SMTP needs port 25,
    which is blocked here). Use to cheaply drop dead domains.
  - `smart` / `chain` — `ChainVerifier`: runs the `local` pre-filter first and only calls the paid
    backend when it can't decide (saves credits on dead domains). Backend = `EMAIL_VERIFIER_BACKEND`,
    else NeverBounce if its key is set, else MillionVerifier.
  - All map results to the same `valid / catch_all / invalid / unknown` statuses, chosen by
    `get_verifier()` in `src/enrichment/providers/__init__.py`.
  - ⚠ A paid verifier at **0 credits returns errors → `unknown`**, so the pipeline stores
    unverified pattern guesses as `probable` (`pattern_unverified`) and the worker still pushes
    them → **bounces**. Keep a verifier funded; `local`/`smart` only catch dead domains, not
    invalid mailboxes on live domains.
- Stops on first `valid` result; `catch_all` → stored as `probable`, never `verified`

### Layer 3 — Hunter.io fallback (`src/enrichment/providers/hunter.py`)
- Calls Hunter.io email finder API (`HUNTER_API_KEY`)
- score ≥ 90 → `verified`; score ≥ 50 → `probable`

### Email precedence (which address wins)
After all layers run, the contact's email is chosen in this order:
1. **Verified named email** — Layer 1 name-match scrape, Layer 2 SMTP `valid`, or Hunter ≥90.
2. **Real published generic inbox** — a `info@`/`contacto@` scraped off the site
   (`site_scrape_generic`, stored as `verified`). It's real and won't bounce, so it beats
   any invented guess. Picked just before the `not_found` fallback in `enrich_contact()`.
3. **Unverified/uncertain pattern guess** — `pattern_unverified` or `catch_all` (`probable`),
   or Hunter ≥50. Only used when **no** generic inbox exists (these are the bounce-prone path).

This stops the agent from pushing an invented `first.last@` guess (which bounces) when a
real `info@` is sitting on the company's contact page.

### Enrichment result fields on `Contact` model
| Field | Values |
|---|---|
| `email_status` | `verified`, `probable`, `not_found` (final values); `bounced` = set by the Zoho bounce check (`/bounces/apply`). `catch_all` is an intermediate verifier result, stored as `probable` |
| `email_source` | `site_scrape`, `site_scrape_generic` (published role inbox used when no verified named email exists; stored as `verified`), `pattern_verified`, `pattern_unverified`, `hunter` |
| `phone_whatsapp` | nullable text |
| `enriched_at` | datetime |
| `enrichment_log` | JSONB — full per-layer attempt log; also holds `attempts` (retry counter) and `bad_emails` (addresses that bounced / are known-bad — never re-proposed) |

### Bounced-email recovery

`src/tools/recovery.py` salvages contacts marked `email_status="bounced"`. The bounce
tells us the previous pattern guess was wrong, so recovery **blocklists** the bad address
(stored in `enrichment_log["bad_emails"]`), clears the email, and re-runs `enrich_contact`.
The pipeline reads `bad_emails` and skips them in Layer 1 (scrape match), Layer 2 (pattern
candidates) and Layer 3 (Hunter), so a fresh run targets the remaining patterns.
- `select_bounced_contacts`, `recover_contact`, `run_recovery` (shared).
- CLI: `python run.py --recover-bounced [N]`. Worker: **phase 1b** (`WORKER_RECOVER_BOUNCED`,
  default on), runs before enrichment so recovered emails get pushed the same run.
- ⚠ Confirming the alternative needs a **funded verifier** — with 0 credits, recovery only
  produces another unverified guess (still filtered for dead domains by the `local` pre-filter).

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
3. Generate a grant token (scope: `ZohoMail.messages.READ,ZohoMail.folders.READ,ZohoMail.messages.CREATE,ZohoMail.accounts.READ`, 10 min duration). `CREATE`+`accounts.READ` alone is enough to push drafts; the two READ scopes additionally enable bounce detection (below).
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
Key functions: `is_configured()`, `exchange_grant_token()`, `create_draft()`, `_get_access_token()` (auto-refresh), `scan_bounced_addresses()`.

### Bounce detection
`scan_bounced_addresses()` reads the Zoho inbox, finds bounce notifications (from
`mailer-daemon`/`postmaster`; subjects like "Undelivered Mail Returned to Sender" /
"Undeliverable" — "delay" notices are ignored), and extracts the failed recipient addresses
from the bodies. The matching strategy is robust across providers: pull every address out of
the bounce body and intersect with `Contact.email`. `GET /bounces/scan` previews matches
(read-only); `POST /bounces/apply` sets `Contact.email_status = "bounced"` on matches — which
also drops them from the worker's push eligibility (push only selects verified/probable).
UI: **📭 Chequear rebotes** button on `/contacts-report` (preview counts + confirm, then mark).
CLI / standalone (schedulable): `python run.py --check-bounces` (scans + marks in one shot).
Shared logic lives in `src/tools/bounces.py` (`scan_and_match`, `mark_bounced`, `apply_bounces`)
— used by both the routes and the CLI. Requires the `messages.READ` + `folders.READ` scopes —
re-run `--zoho-auth` with the scope in the setup above if reads return `INVALID_OAUTHSCOPE`.

## Follow-up agent

Follows up with already-contacted leads that haven't replied. Shared logic in
`src/tools/followups.py`; runs as worker **phase 4**, exposed via `/follow-ups` and the
`--detect-replies` / `--follow-ups` CLI flags. Mirrors the bounce molds (scan + match + act)
and the worker's draft generator (Haiku + instructor). Reuses Zoho read scopes.

- **Reply detection** — `scan_inbox_senders()` (in `zoho_mail.py`) reads inbox message stubs
  (no body fetch) and returns `{address: latest_received_ms, ooo_senders: set}`. `detect_replies()`
  intersects with `Contact.email` and sets `Contact.replied_at` **only when the message arrived
  after the first-touch push** (`Opportunity.zoho_pushed_at`), so unrelated prior mail isn't
  counted. A detected reply also sets `ContactStatus.response_received="replied"` if no manual
  feedback exists yet, so it surfaces on `/contacts-report`.
- **OOO detection** — `scan_inbox_senders()` also detects out-of-office auto-replies by subject
  (`_OOO_SUBJECTS`: "out of office", "fuera de oficina", "automatic reply", etc.). When an OOO
  arrives from a known contact's address after their company was contacted: upgrades
  `email_status → "verified"` / `email_source → "ooo_confirmed"` (delivery confirmed), logs
  `enrichment_log["ooo_confirmed_at"]`, and resets the follow-up cadence clock by setting
  `Opportunity.last_followup_at = ooo_date` (without incrementing `followup_count`). The cadence
  then fires ~`FOLLOWUP_FIRST_DAYS` after the OOO, not while the person is away. Repeated OOOs
  from the same contact don't further delay the cadence (`ooo_confirmed_at` already set → skip).
- **Cadence** — constants `FOLLOWUP_FIRST_DAYS=4`, `FOLLOWUP_SECOND_DAYS=10`, `FOLLOWUP_MAX=2`.
  Eligibility and cadence timing are split: `_eligible_followup_opps()` returns pushed
  opportunities (one per company, highest score) whose company has no reply and no manual
  `response_received`, with a verified/probable, non-replied contact email — **regardless of
  timing**. `_followup_due_date(opp)` computes when the next touch is due (`count==0` → push +
  4d, or since OOO if later; `count==1` → last follow-up + 6d). `select_followup_candidates()` =
  eligible with `due_date <= now` (used by the worker); `select_upcoming_followups(within_days=7)`
  = eligible with `now < due_date <= now+N` (drives the "Próximos" UI).
- **Drafting** — `generate_followup()` builds the payload + calls Haiku with
  `build_followup_prompt()` (`src/prompts/followup.py`, Spanish voseo by default via the profile's
  `outreach_language`; 50–120 words, references the original, single CTA). Subject = `"Re: " +
  original`. `run_followups()` pushes each draft via `create_draft()` and bumps
  `followup_count` / `last_followup_at` / `followup_subject` / `followup_draft`.
- **Threading caveat (v1)** — the follow-up is a standalone `"Re:"` draft (no `In-Reply-To`
  header), and the cadence clock runs from `zoho_pushed_at` assuming the first-touch draft is
  **sent the same day it's pushed**.
- **Bring-forward ("Hacer hoy")** — `push_followup_now(session, company_id)` generates + pushes
  a follow-up draft for one company **immediately, bypassing the cadence wait** (the company must
  still be eligible), then bumps the same counters as `run_followups`. Exposed via
  `POST /follow-ups/push-now` (form field `company_id`).
- **`/follow-ups` page** — weekly summary: pending/overdue (cadence due), **upcoming** (eligible
  but not yet due, within `?within=N` days — default 7, clamp 1–30), drafted this week, and who
  replied; plus a stats bar. Pending cards and the Próximos table each have a **"⏩ Hacer hoy"**
  button (→ `/follow-ups/push-now`) to draft a follow-up early. Template `src/templates/follow_ups.html`.

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
| `/follow-ups` | GET | Follow-up dashboard — pending/overdue (cadence due), upcoming (`?within=N` days), drafted this week, replied (weekly summary) |
| `/follow-ups/push-now` | POST | Bring-forward: draft + push a follow-up for one company now, bypassing cadence (`company_id`) |
| `/bounces/scan` | GET | Preview Zoho bounces matched to contacts (read-only) |
| `/bounces/apply` | POST | Mark matched bounced contacts (`email_status="bounced"`) |
| `/search` | GET | Browse/search companies — full paginated listing (25/page); contacts panel when `?q=` set |
| `/search/export/<fmt>` | GET | Export the company listing (respects `?q=` filter) as `csv` or `md` |
| `/quick-run` | GET | Quick Run form + history list (last 15 runs) |
| `/quick-run` | POST | Start a Quick Run (creates DiscoveryRun, spawns background thread) |
| `/quick-run/<run_id>` | GET | Quick Run results page |
| `/quick-run/<run_id>/status` | GET | Polling endpoint `{phase, done, total, error}` |
| `/quick-run/<run_id>/push-all-zoho` | POST | Push all **eligible** drafts (verified/probable, not already contacted/pushed) to Zoho |
| `/quick-run/<run_id>/push-selected-zoho` | POST | Push only the selected contacts (still eligibility-filtered) |
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
Inline search bar → `⚡ Quick Run` → `Runs` → `Contactados` → `Follow-ups` → `Perfiles` → `Salir`.
Visual separators between search/actions and the logout link.

### Global Search (`/search`)
Browse or search companies. With **no query** it lists **all companies** (25/page, prev/next
pagination); with a query it filters companies (name, domain, industry, location) and shows
matching contacts (name, email, role) in a second column. Cards have score pills, email status
badges, a link to the run where each company was found, and per-card actions: **💬 Feedback**
(same modal/route as `/contacts-report`) and a **Marcar contactado / ✓ Contactado** toggle
(`/company/<id>/toggle-contact`) — both redirect back to the current search via referrer, so you
can triage without opening the Run. **⬇ CSV / ⬇ MD** buttons export the company listing (respecting
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
- Push to Zoho is **eligibility-gated** (same guards as the worker): only `verified`/`probable`
  emails with a draft, skipping companies already contacted (`ContactStatus`) or pushed
  (`zoho_pushed_at`), one contact per company per batch. Shared helper `_quick_push_eligible()`.
  - Per-row **checkbox** (pre-checked for eligibles only; ineligible rows greyed with the reason).
  - **"Push seleccionados (N)"** → `POST /quick-run/<run_id>/push-selected-zoho` ({contact_ids}).
  - **"Push todos los elegibles"** → `POST /quick-run/<run_id>/push-all-zoho` (all eligible).
  - Both set `zoho_pushed_at` + mark the company contacted, so re-pushes are idempotent.
- Per-row "📧" button (eligible rows only) → `POST /quick-run/<run_id>/push-one-zoho` (single).
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
- Stats bar: total contacted, respondieron, rebotaron, follow-ups scheduled, overdue.
- **Filter bar** (client-side pills): Todas / 📭 Rebotadas / ⏰ Seguimiento / ✅ Exitosas.
  Pills only appear when their count > 0. Selecting a filter hides non-matching cards,
  collapses empty profile sections, and auto-opens matching ones. Each card carries
  `data-bounced`, `data-followup`, `data-success` attributes for JS filtering.

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
`profiles.outreach_language`, the five `contacts.*` enrichment columns, `contacts.replied_at`,
`opportunities.outreach_subject` + `opportunities.zoho_pushed_at`, and the four follow-up columns
`opportunities.followup_count` / `last_followup_at` / `followup_subject` / `followup_draft`.

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
  - `followup_count` (0-2) / `last_followup_at` / `followup_subject` / `followup_draft` — follow-up
    cadence tracking + last generated follow-up (drives the `/follow-ups` page)
- **`Contact`** also has `replied_at` — set when a reply from that email is seen in the Zoho inbox
  (drives reply detection; replied contacts/companies are excluded from follow-ups).
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
| `OUTREACH_MODEL` | — | Model for customer-facing outreach + follow-up drafts (default: claude-sonnet-4-6). Set to the Haiku id to cut cost at the expense of Spanish quality |
| `ZOHO_CLIENT_ID` | Zoho | OAuth2 client ID |
| `ZOHO_CLIENT_SECRET` | Zoho | OAuth2 client secret |
| `ZOHO_REFRESH_TOKEN` | Zoho/Railway | Long-lived refresh token (from `--zoho-auth`) |
| `ZOHO_ACCOUNT_ID` | Zoho/Railway | Zoho Mail account ID |
| `ZOHO_FROM_ADDRESS` | Zoho/Railway | Sender email address |
| `EMAIL_VERIFIER_PROVIDER` | Enrichment | Layer 2 verifier: `neverbounce`, `millionverifier` (default), `local` (free MX/syntax pre-filter), or `smart`/`chain` (local → paid backend) |
| `EMAIL_VERIFIER_BACKEND` | Enrichment | Paid backend for `smart`/`chain` (`neverbounce` or `millionverifier`); auto-selected if unset |
| `EMAIL_VERIFIER_API_KEY` | Enrichment | MillionVerifier API key (~$0.003/check). Needs a credit balance — at 0 credits the API returns `unknown` for every candidate and emails degrade to unverified guesses (`probable`/`pattern_unverified`) |
| `NEVERBOUNCE_API_KEY` | Enrichment | NeverBounce API key (used when provider=neverbounce). Needs credits — new accounts must claim free credits / top up, else checks fail with "Insufficient credit balance" (same `unknown` degradation as MillionVerifier) |
| `HUNTER_API_KEY` | Enrichment | Hunter.io API key (25 free/month) |

### Worker-only (Windows mini PC — `worker/.env`)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Railway public connection string |
| `ANTHROPIC_API_KEY` | ✅ | Claude API key (Haiku for drafts, ~$2-4/month) |
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
| `WORKER_RECOVER_BOUNCED` | — | Phase 1b: retry bounced contacts (blocklist + re-enrich) (default: true) |
| `WORKER_RECOVER_BATCH` | — | Bounced contacts to retry per run (default: 10) |
| `WORKER_RECOVER_DELAY` | — | Seconds between recovery contacts (default: 2) |
| `WORKER_CHECK_BOUNCES` | — | Phase 3: scan Zoho inbox + mark bounced contacts (default: true; needs READ scope) |
| `WORKER_FOLLOWUP` | — | Phase 4: detect replies + push follow-up drafts (default: true; needs READ scope) |
| `WORKER_FOLLOWUP_BATCH` | — | Follow-up drafts to push per run (default: 15) |
| `WORKER_FOLLOWUP_DELAY` | — | Seconds between Zoho API calls in the follow-up phase (default: 1) |

## Windows Worker (`worker/`)

Standalone script that runs on a local Windows mini PC on a schedule (daily or every 2 days)
via Task Scheduler. Connects directly to the Railway PostgreSQL DB — Railway remains the single
source of truth. No data is stored locally; the worker only reads and writes to the shared DB.
Full operational runbook: **`worker/README.md`**.

### What it does (per run)
0. **Recovery (phase 1b)** — retries up to `WORKER_RECOVER_BATCH` bounced contacts: blocklists
   the bounced address and re-enriches to find a different working email (see "Bounced-email
   recovery"). Runs before enrichment so recovered emails get pushed the same run. Toggle with
   `WORKER_RECOVER_BOUNCED` (default on).
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
3. **Bounce check** — scans the Zoho inbox for bounce notifications and marks matched contacts
   `email_status="bounced"` (see "Bounce detection"). Toggle with `WORKER_CHECK_BOUNCES`
   (default on); non-fatal if the token lacks the READ scope.
4. **Follow-ups** — detects replies (marks `Contact.replied_at`) then generates + pushes
   follow-up drafts for contacted leads that haven't answered (see "Follow-up agent").
   Toggle with `WORKER_FOLLOWUP` (default on); non-fatal if the token lacks the READ scope.

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
| `src/tools/bounces.py` | Zoho bounce scan + match + mark (shared by `/bounces/*` routes and `--check-bounces`) |
| `src/tools/followups.py` | Follow-up agent: detect replies + select due/upcoming leads + generate/push follow-up drafts + bring-forward (`push_followup_now`) (shared by worker phase 4, `/follow-ups`, `--detect-replies`/`--follow-ups`) |
| `src/prompts/followup.py` | Follow-up email prompt (`build_followup_prompt`); reuses outreach language directives |
| `src/enrichment/domain_resolver.py` | Layer 0 — resolve a missing company domain (email derive + official-site web search) |
| `src/enrichment/pipeline.py` | Enrichment orchestrator (Layer 0 domain resolution + 3 layers + attempt counter) |
| `src/enrichment/scraper.py` | Site scraper (Layer 1) |
| `src/enrichment/patterns.py` | Email pattern generation (Layer 2) |
| `src/enrichment/providers/` | `base.py`, `million_verifier.py`, `neverbounce.py`, `local_filter.py` (free MX/syntax pre-filter + `ChainVerifier`), `hunter.py`; `__init__.py` → `get_verifier()` factory |
| `src/tools/recovery.py` | Bounced-email recovery: blocklist bad address + re-enrich (worker phase 1b, `--recover-bounced`) |
| `src/integrations/zoho_mail.py` | Zoho Mail OAuth2 + draft creation |
| `src/dashboard.py` | Rich terminal dashboard, `_enrich_drafts_from_db()` |
| `src/export.py` | CSV + Markdown export |
| `src/templates/` | Jinja2 templates (base, runs, run, profile_form, profiles, contacts_report, quick_run, search) |
| `worker/worker.py` | Windows worker — enrichment + Zoho push (scheduled daily / every 2 days) |
| `worker/run_worker.bat` | Task Scheduler launcher for the worker |
| `tests/` | Unit tests for enrichment module |
