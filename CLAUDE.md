# Blest Lead Discovery Agent

Daily B2B lead discovery agent for Blest, a corporate English training company in Argentina.

## Stack
- Python 3.11+
- LangGraph (workflow orchestration)
- Anthropic Claude API (via `instructor` for structured outputs)
- Tavily Search API (web discovery)
- PostgreSQL via SQLAlchemy 2.0 (`psycopg2-binary`)
- Rich (terminal dashboard)
- APScheduler (daily runs)

## Quick Start
```bash
docker compose up -d                  # start PostgreSQL
cp .env.example .env                  # fill in API keys
pip install -r requirements.txt
python run.py --setup                 # create DB tables
python run.py                         # run once now
python run.py --schedule              # start daily daemon
python run.py --report                # show last report
```

## Project Structure
```
src/
  config.py          # pydantic-settings, all env vars
  database/
    models.py        # SQLAlchemy ORM (5 tables)
    session.py       # engine, session factory, init_db()
  schemas/
    outputs.py       # Pydantic models for all LLM outputs
  tools/
    search.py        # Tavily wrapper with batching + dedup
    db_tools.py      # DB helpers + persist_run_node
  prompts/           # One file per workflow step
  graph/
    state.py         # AgentState TypedDict
    workflow.py      # LangGraph StateGraph assembly
    nodes/           # One file per step (discovery→scoring→contacts→insights→outreach)
  dashboard.py       # Rich terminal output
  scheduler.py       # APScheduler daemon
run.py               # Entry point (--setup, --report, --schedule, or run once)
```

## Models Used
- `claude-haiku-4-5-20251001` — discovery, scoring, contacts (high volume)
- `claude-sonnet-4-6` — insights, outreach (nuanced reasoning)

## Database Tables
- `discovery_runs` — each daily run
- `companies` — discovered companies (UNIQUE on domain)
- `opportunities` — scored opportunities per run
- `contacts` — decision makers per company
- `daily_reports` — daily report snapshots

## Adding New ICP Signals
Edit `src/prompts/discovery.py` to add new search patterns or signals.
Edit scoring weights in `src/prompts/scoring.py`.
