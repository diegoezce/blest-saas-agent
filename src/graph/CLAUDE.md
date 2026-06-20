# DAG Nodes & AI Usage

## Node Behavior

The 7-node LangGraph DAG is tuned for **lead volume + low AI spend**.

| Node | AI? | Notes |
|---|---|---|
| `discover_companies` | ✅ Haiku ×2 | 1 query-generation call + 1 company-extraction call. Slices top 80 Tavily results. |
| `score_opportunities` | ❌ — | **Pure-Python rule-based scoring** (see Scoring below). No AI call. |
| `find_contacts` | ✅ Haiku | Finds **named** decision-makers per `target_roles`. Nameless entries dropped at persist. |
| `generate_insights` | ⏸ disabled | `max_companies_for_insights=0` → returns `[]` immediately. Kept in DAG but no-op. |
| `generate_outreach` | ✅ Haiku | One call per company (up to `max_companies_for_outreach`). Grounded prompt. |
| `generate_report` | ❌ — | Assembles the report dict. |
| `persist_to_db` | ❌ — | Upserts companies (dedup), opportunities, contacts, daily report. |

## Scoring (Rule-Based, No AI)

`src/graph/nodes/scoring.py` scores each company 0–100 in pure Python:

**Buckets** (cumulative max 100):
- Company size: 0–20 (parsed from "50-100"/"200+" ranges)
- International exposure: 0–25
- Remote workforce: 0–20
- English hiring activity: 0–15
- Industry/tech adoption: 0–10
- English keyword signals: 0–10

**Priority tiers**:
- `quick_win`: score ≥ 70
- `strategic`: score ≥ 40, < 70
- `low_priority`: score < 40

**Helper**: `_parse_size()` converts size strings to approximate headcount.
