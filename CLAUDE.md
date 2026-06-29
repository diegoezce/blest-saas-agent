# Blest Lead Discovery Agent

Multi-profile B2B lead discovery agent. Discovers, scores, and enriches leads for multiple products/services, each with its own targeting criteria, AI prompts, scoring rubric, and outreach tone. Generates email drafts and pushes them directly to Zoho Mail.

## Quick Overview

- **Python 3.11+** | LangGraph (workflow) | Claude API | Tavily (search) | PostgreSQL | Flask (web) | Railway (deploy)
- **Daily discovery runs** → company scoring → contact enrichment → Zoho email drafts
- **Multi-profile system**: each profile has custom targeting, scoring rubric, outreach tone, language (ES/EN)
- **Follow-up automation**: reply detection + cadence-based follow-ups (Haiku + instructor)
- **Windows worker**: standalone enrichment + Zoho push daemon (scheduled daily/bi-daily)

## CLI Commands

```bash
python run.py                        # Run discovery once (default profile)
python run.py --profile <ID>         # Run discovery for specific profile
python run.py --web                  # Start web UI + embedded scheduler
python run.py --schedule             # Scheduler daemon only
python run.py --enrich-run <ID>      # Enrich all contacts for a run
python run.py --check-bounces        # Scan Zoho inbox, mark bounced emails
python run.py --follow-ups           # Generate + push follow-up drafts
python run.py --recover-bounced [N]  # Retry bounced contacts (blocklist + re-enrich)
python run.py --setup                # Initialize/migrate database
```

See `run.py --help` for full list.

## Documentation by Module

| Module | Location | Purpose |
|---|---|---|
| **Configuration** | [`src/config/CLAUDE.md`](src/config/CLAUDE.md) | Settings, profile overrides, workflow tuning |
| **Database** | [`src/database/CLAUDE.md`](src/database/CLAUDE.md) | SQLAlchemy models, migrations, schema |
| **Workflow Graph** | [`src/graph/CLAUDE.md`](src/graph/CLAUDE.md) | LangGraph DAG, discovery/scoring/outreach nodes |
| **Web UI** | [`src/web/CLAUDE.md`](src/web/CLAUDE.md) | Flask routes, Quick Run, Contacts Report, Follow-ups |
| **Contact Enrichment** | [`src/enrichment/CLAUDE.md`](src/enrichment/CLAUDE.md) | Layer 0–4 email verification, scraping, SMTP, Hunter, Tavily |
| **Prompts** | [`src/prompts/CLAUDE.md`](src/prompts/CLAUDE.md) | Outreach + follow-up prompt engineering, grounding rules |
| **Tools & Helpers** | [`src/tools/CLAUDE.md`](src/tools/CLAUDE.md) | DB persistence, company dedup, bounce/reply detection, recovery |
| **Integrations** | [`src/integrations/CLAUDE.md`](src/integrations/CLAUDE.md) | Zoho Mail OAuth2, draft creation, bounce/reply scanning |
| **Windows Worker** | [`worker/CLAUDE.md`](worker/CLAUDE.md) | Standalone daemon (enrich + Zoho push + bounces + follow-ups) |

## Key Architecture

**LangGraph DAG** (7 nodes):
```
discover_companies → score_opportunities → find_contacts → generate_insights (disabled)
  → generate_outreach → generate_report → persist_to_db
```

**Lead volume + low cost**: ~15–20 concrete leads/run at ~$0.12/run.
- Discovery: Haiku ×2 (query gen + extraction)
- Scoring: pure Python (no AI)
- Contacts: Haiku (named decision-makers)
- Outreach: Sonnet/Haiku (grounded, profile-tuned)
- Enrichment: SMTP verify + Hunter + Tavily (4 layers, off-path)

**Multi-profile**: each profile overrides global settings via `get_profile_overrides()` in config.

**Deduplication**: companies matched by domain/normalized name → one row per real business.
Cross-run guards prevent re-contacting the same company.

## Deployment

- **Web**: Railway (Flask + scheduler embedded)
- **Worker**: Windows mini PC (Task Scheduler, daily/bi-daily)
- **Database**: Railway PostgreSQL (single source of truth)
- **Tokens**: `.zoho_tokens.json` (local) or Railway env vars fallback

See [`worker/README.md`](worker/README.md) for Windows setup.

## Environment Variables

**Core** (Railway):
- `ANTHROPIC_API_KEY` — Claude API
- `TAVILY_API_KEY` — Web search
- `DATABASE_URL` — PostgreSQL

**Zoho** (optional):
- `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET` — OAuth2 self-client
- `ZOHO_REFRESH_TOKEN`, `ZOHO_ACCOUNT_ID`, `ZOHO_FROM_ADDRESS` — token storage (Railway fallback)

**Enrichment** (optional):
- `EMAIL_VERIFIER_PROVIDER` — `neverbounce` / `millionverifier` / `local` / `smart`
- `EMAIL_VERIFIER_API_KEY` / `NEVERBOUNCE_API_KEY` — verifier credits
- `HUNTER_API_KEY` — Hunter.io (25 free/month)

**Tracking** (optional):
- `TRACKING_BASE_URL` — public base URL of the app (e.g. `https://myapp.up.railway.app`); enables email open tracking pixel in Zoho drafts; view results at `/track/stats`

**Tuning** (defaults in config):
- `SCHEDULE_TIME`, `SCHEDULE_DAYS` — cron timing
- `FAST_MODEL`, `REASONING_MODEL`, `OUTREACH_MODEL` — Claude models
- `DISCOVERY_QUERIES_PER_RUN`, `TAVILY_MAX_RESULTS`, `WEB_SEARCH_MAX_QUERIES` — Tavily credit control (bills per query; see `src/config/CLAUDE.md` → Tavily Credit Cost)
- `WORKER_*` — batch sizes, delays, toggles (worker-only)

Full reference: [`src/config/CLAUDE.md`](src/config/CLAUDE.md) + each module's docs.

## Quick Links

- **Start web**: `python run.py --web`
- **Setup Zoho**: `python run.py --zoho-auth <token>`
- **Check status**: Visit `http://localhost:5000` (password: `blest2024` default)
- **Worker setup**: [`worker/README.md`](worker/README.md)
- **Local dev**: `pytest tests/` (enrichment unit tests)
