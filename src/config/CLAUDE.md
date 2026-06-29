# Profile System & Workflow Tuning

## Profile Fields

Each profile defines targeting, messaging, and scoring for one product/service:

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | string | — | Unique profile name |
| `active` | bool | true | Enable/disable profile |
| `agent_company_name` | string | "Blest" | Company name in AI prompts |
| `agent_description` | string | — | Short description for prompts |
| `target_industries` | string | — | Comma-separated; overrides global config |
| `target_cities` | string | — | Comma-separated; overrides global config |
| `min_employees` | int | — | Overrides global config |
| `max_employees` | int | — | Overrides global config |
| `search_focus_terms` | string | — | Extra context for query generation |
| `scoring_rubric` | JSONB | DEFAULT_SCORING_RUBRIC | Custom scoring rules |
| `outreach_tone` | enum | "warm" | One of: warm, direct, professional, referral |
| `outreach_language` | enum | "es" | `es` (Argentine voseo) or `en` |
| `outreach_instructions` | text | — | Free-text pitch/value-prop guidance (injected into prompt) |
| `target_roles` | text | — | Role priorities (one per line; used in contact search) |

## How Profile Overrides Work

All graph nodes call `get_profile_overrides(profile_dict)` from `src/config.py`.
This merges profile values **on top of** global `Settings` defaults:
- If a profile field is set, it overrides the global value
- If null, the global value is used
- Result: one unified config per run

## Workflow Tuning (`Settings` in `src/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `discovery_queries_per_run` | 6 | Tavily search queries generated per run (= credits) |
| `tavily_max_results` | 20 | Results per query (free — Tavily bills per query, not per result) |
| `web_search_max_queries` | 4 | Cap on Layer 4 web-email queries per contact |
| `max_companies_to_score` | 50 | Cap on unique companies carried into scoring |
| `max_companies_for_contacts` | 30 | Companies to find contacts for |
| `max_companies_for_insights` | 0 | **0 = insights disabled** (no AI call) |
| `max_companies_for_outreach` | 20 | Companies to draft outreach for |
| `exclude_known_companies` | true | Skip companies already in DB (net-new leads only) |
| `rediscover_after_days` | 0 | 0 = never re-surface known company; >0 = re-allow after N days |

**Net effect**: ~15–20 leads/run, ~$0.12 Claude API cost (vs old $0.48 with AI scoring + insights).

## Tavily Credit Cost

**Tavily bills per query, not per result** — so fewer queries × more results each is
strictly cheaper for the same LLM input. The two consumers:

- **Discovery** (`run_discovery_node`): `discovery_queries_per_run` queries (6 credits).
  The LLM only reads the first ~80 deduped results, so 6×20 fills it as well as 12×10 did.
- **Enrichment Layer 4** (`web_email_finder`): up to `web_search_max_queries` per contact
  (each = 1 credit). Early-stops on a named match. The **worker** is the bigger consumer
  here (enriches `WORKER_ENRICH_BATCH` contacts/run + recovery). Companies without a
  domain also cost domain-resolution searches (≤2 each).

**Rule of thumb**: a full cycle (discovery + enriching its leads) ≈ **30–50 credits**.
At ~3 runs/week that's ~450–500/month. ⚠ Railway env vars override these defaults — set
`DISCOVERY_QUERIES_PER_RUN` / `TAVILY_MAX_RESULTS` there too, and the **worker must
`git pull`** to pick up the cap. Track real spend at app.tavily.com → Usage.
