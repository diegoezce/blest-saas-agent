# Blest Lead Discovery Agent

Multi-profile B2B lead discovery agent. Can discover leads for multiple products/services,
each with its own targeting criteria, AI prompts, scoring rubric, and outreach tone.
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

## Multi-Profile System

The app supports multiple profiles, each representing a different product/service:

- **Blest Learning** (id=1) — Corporate English training for mid-large Argentine companies.
  Sells to L&D Managers, HR Managers at companies with 20-500 employees.

- **Blest App** (id=2) — SaaS platform for English academies and language institutes.
  Sells to Directors, Academic Coordinators at institutes with 2-30 employees.

### Profile Fields

Each profile stores:

| Field | Description |
|---|---|
| `name` | Unique profile name |
| `active` | Whether profile is enabled |
| `agent_company_name` | Company name for AI prompts (e.g. "Blest") |
| `agent_description` | Short description (e.g. "a SaaS platform for English academies") |
| `target_industries` | Comma-separated; overrides global config |
| `target_cities` | Comma-separated; overrides global config |
| `min_employees` | Overrides global config |
| `max_employees` | Overrides global config |
| `search_focus_terms` | Extra context for search query generation |
| `scoring_rubric` | JSONB - custom scoring rubric; falls back to DEFAULT_SCORING_RUBRIC |
| `outreach_tone` | One of: warm, direct, professional, referral |
| `target_roles` | Comma-separated priority role list for contact discovery |

### How Profile Overrides Work

All graph nodes use `get_profile_overrides(profile_dict)` from `src/config.py`.
This merges profile values on top of global `Settings` defaults:
- If a profile field is set: it overrides the global config
- If it's null: the global config value is used

## Web UI

- `/` - All Runs list (shows profile badge per run)
- `/profiles` - Profile management (list, create, edit)
- `/profiles/new` - Create new profile
- `/profiles/<id>/edit` - Edit existing profile
- `/run/<id>` - Run detail with quick wins, strategic, contacts, insights, outreach drafts
- `/run/latest` - Redirect to latest run
- Trigger modal - Profile dropdown to select which profile to run for
- Schedule modal - Configure time and days of week
- Log panel - Real-time log viewer at bottom of page

## Run Discovery

