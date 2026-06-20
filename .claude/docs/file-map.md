# Key Source Files Reference

Quick reference for what each major file/module does.

## Entry Points

| File | Purpose |
|---|---|
| `run.py` | Entry point + CLI interface |

## Configuration & Scheduling

| File | Purpose |
|---|---|
| `src/config.py` | Settings (pydantic-settings), workflow tuning, `get_profile_overrides()` |
| `src/scheduler.py` | APScheduler setup, `run_workflow_once()` |

## Workflow (LangGraph DAG)

| File | Purpose |
|---|---|
| `src/graph/workflow.py` | LangGraph DAG definition (7-node orchestration) |
| `src/graph/nodes/discovery.py` | `discover_companies` node (Tavily search + Haiku extraction) |
| `src/graph/nodes/scoring.py` | `score_opportunities` node (pure-Python rule-based scoring) |
| `src/graph/nodes/contacts.py` | `find_contacts` node (Haiku-based contact extraction) |
| `src/graph/nodes/insights.py` | `generate_insights` node (disabled; no-op in current config) |
| `src/graph/nodes/outreach.py` | `generate_outreach` node (Haiku email drafts) |
| `src/graph/nodes/report.py` | `generate_report` node (report assembly) |

## Prompts

| File | Purpose |
|---|---|
| `src/prompts/outreach.py` | Grounded outreach email prompt (`build_outreach_prompt()`) with profile customization |
| `src/prompts/followup.py` | Follow-up email prompt (`build_followup_prompt()`) |

## Database

| File | Purpose |
|---|---|
| `src/database/models.py` | SQLAlchemy ORM models (Profile, DiscoveryRun, Company, Contact, Opportunity, ContactStatus, DailyReport) |
| `src/database/session.py` | DB session management, `init_db()`, `_run_migrations()` |

## Web UI

| File | Purpose |
|---|---|
| `src/web.py` | Flask app + all routes (discovery, enrichment, Zoho, follow-ups, profiles, search) |
| `src/templates/base.html` | Base Jinja2 template (nav, auth, layout) |
| `src/templates/runs.html` | Runs list page |
| `src/templates/run.html` | Run detail page |
| `src/templates/quick_run.html` | Quick Run form + results |
| `src/templates/contacts_report.html` | Contacted companies report (dedup, follow-up tracking) |
| `src/templates/follow_ups.html` | Follow-ups dashboard |
| `src/templates/search.html` | Global search + browse |
| `src/templates/profile_form.html` | Profile create/edit form |
| `src/templates/profiles.html` | Profiles list |

## Tools & Utilities

| File | Purpose |
|---|---|
| `src/tools/db_tools.py` | `persist_run_node`, `_upsert_company()` (dedup), `normalize_company_name()` |
| `src/tools/bounces.py` | Zoho bounce scan + match + mark (shared by routes + CLI) |
| `src/tools/followups.py` | Follow-up agent: detect replies, select cadence-due leads, generate/push drafts, bring-forward |
| `src/tools/recovery.py` | Bounced-email recovery: blocklist + re-enrich |
| `src/dashboard.py` | Rich terminal dashboard (CLI `--report`) |
| `src/export.py` | CSV + Markdown export (companies, runs) |

## Enrichment Pipeline

| File | Purpose |
|---|---|
| `src/enrichment/pipeline.py` | Enrichment orchestrator (Layer 0–3 + attempt counter) |
| `src/enrichment/domain_resolver.py` | Layer 0 — resolve missing company domain (email derive + web search) |
| `src/enrichment/scraper.py` | Layer 1 — site scraper (pages, emails, phone/WhatsApp) |
| `src/enrichment/patterns.py` | Layer 2 — email permutation generation |
| `src/enrichment/providers/__init__.py` | Verifier factory (`get_verifier()`) |
| `src/enrichment/providers/base.py` | Base verifier class |
| `src/enrichment/providers/neverbounce.py` | NeverBounce SMTP verification |
| `src/enrichment/providers/millionverifier.py` | MillionVerifier SMTP verification |
| `src/enrichment/providers/local_filter.py` | Free MX/syntax pre-filter + `ChainVerifier` |
| `src/enrichment/providers/hunter.py` | Hunter.io email finder fallback |

## Integrations

| File | Purpose |
|---|---|
| `src/integrations/zoho_mail.py` | Zoho Mail OAuth2, draft creation, bounce detection, reply scanning |

## Worker (Windows)

| File | Purpose |
|---|---|
| `worker/worker.py` | Windows worker script (phases 0–4: recover → enrich → push → bounces → follow-ups) |
| `worker/run_worker.bat` | Task Scheduler launcher (cd to root, runs `py -3.11`, logs output) |
| `worker/.env.example` | Config template for Windows machine |

## Tests

| Directory | Purpose |
|---|---|
| `tests/` | Unit tests for enrichment module |

## Documentation & Config

| File | Purpose |
|---|---|
| `CLAUDE.md` | Root project documentation (high-level overview, gotchas, subdirectory guide) |
| `src/config/CLAUDE.md` | Profile system + workflow tuning details |
| `src/graph/CLAUDE.md` | DAG nodes + AI usage + scoring |
| `src/enrichment/CLAUDE.md` | Email enrichment pipeline (Layer 0–3) |
| `src/integrations/CLAUDE.md` | Zoho Mail OAuth + bounce/reply detection |
| `src/tools/CLAUDE.md` | Company/contact dedup, bounces, follow-ups |
| `src/database/CLAUDE.md` | Models + migrations |
| `src/prompts/CLAUDE.md` | Outreach + follow-up email generation |
| `src/web/CLAUDE.md` | Flask routes + UI features |
| `worker/CLAUDE.md` | Windows worker setup + phases |
| `.claude/docs/cli-reference.md` | Full CLI command listing |
| `.claude/docs/env-vars.md` | Environment variables (Railway + worker) |
| `.claude/docs/web-routes.md` | Web route reference + UI features |
| `.claude/docs/file-map.md` | This file |
