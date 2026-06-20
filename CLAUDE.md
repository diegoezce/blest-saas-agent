# Blest Lead Discovery Agent

Multi-profile B2B lead discovery agent. Discovers, scores, and enriches leads for 
multiple products/services, each with its own targeting criteria, AI prompts, 
scoring rubric, and outreach tone. Generates email drafts and pushes them to Zoho Mail.

## Stack

- Python 3.11+, LangGraph, Anthropic Claude API, Tavily Search
- PostgreSQL (SQLAlchemy 2.0), Flask, APScheduler, Railway
- Contact enrichment: `requests`, `beautifulsoup4`, DNS/SMTP verification
- Windows worker: standalone daily enrichment + Zoho push (on local mini PC)

## Workflow

LangGraph 7-node DAG:
```
discover_companies → score_opportunities → find_contacts → 
generate_insights → generate_outreach → generate_report → persist_to_db
```

**Design**: Tuned for lead volume + low AI spend. Pure-Python rule-based scoring 
(no AI call). Discovery + outreach use Haiku. Follow-ups + bounces run in background 
worker. Net: ~15–20 leads/run at ~$0.12/run.

## Multi-Profile System

App supports multiple profiles (e.g., Blest Learning, Blest App), each with:
- Custom targeting (industries, cities, company size, role priorities)
- Custom outreach tone + language (Spanish voseo or English)
- Custom scoring rubric (or default)

Profile fields override global config via `get_profile_overrides()` in `src/config.py`.

## Non-obvious Gotchas

1. **Company deduplication** — Critical. Runs by domain, then normalized name, 
   then exact name. Cross-run guards prevent re-contacting the same company.
   See `src/tools/db_tools.py:_upsert_company()`.

2. **Contact deduplication** — Within a company, matched by LinkedIn URL first, 
   then name. Missing fields backfilled across runs → same person = one row.

3. **Email precedence** — Verified named email > published generic inbox > 
   unverified pattern guess. Generic inboxes beat guesses to avoid bounces.

4. **Verifier funding** — At 0 credits, SMTP verifier returns `unknown` for all 
   candidates → emails degrade to unverified (`probable`). Keep funded.

5. **Zoho token storage** — Local `.zoho_tokens.json` takes priority; Railway 
   env vars are fallback. Access token auto-refreshes hourly.

## Subdirectory Guides

Claude Code loads these automatically when working in each directory:

| Directory | Coverage |
|---|---|
| `src/config/` | Profile system, workflow tuning, overrides |
| `src/graph/` | DAG nodes, AI usage, rule-based scoring |
| `src/enrichment/` | Layer 0–3 email verification pipeline |
| `src/integrations/` | Zoho OAuth, draft creation, bounce detection |
| `src/tools/` | Company/contact dedup, bounces, follow-ups |
| `src/database/` | SQLAlchemy models, migrations |
| `src/prompts/` | Outreach + follow-up email generation |
| `src/web/` | Flask routes, UI features, templates |
| `worker/` | Windows worker phases: enrich + push |

## Reference Docs

Use `@` to import on demand:
- **CLI commands**: `@.claude/docs/cli-reference.md`
- **Environment variables**: `@.claude/docs/env-vars.md`
- **Web routes**: `@.claude/docs/web-routes.md`
- **File map**: `@.claude/docs/file-map.md`

## Quick Start

```bash
python run.py                    # Run discovery once (default profile)
python run.py --web              # Start Flask + scheduler
python run.py --enrich-run <ID>   # Enrich contacts for a run
python run.py --zoho-auth TOKEN   # Store Zoho Mail OAuth
```

Full CLI reference: `@.claude/docs/cli-reference.md`
