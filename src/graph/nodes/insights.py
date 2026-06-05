import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.insights import INSIGHTS_PROMPT
from src.schemas.outputs import CompanyInsight

logger = logging.getLogger(__name__)

_client = None


def _llm():
    global _client
    if _client is None:
        from src.config import get_settings
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def run_insights_node(state: AgentState) -> AgentState:
    scored = state.get("scored_opportunities", [])
    if not scored:
        logger.warning("No scored companies — skipping insights")
        return {**state, "insights": []}

    from src.config import get_settings
    cfg = get_settings()
    top = scored[: cfg.max_companies_for_insights]
    companies_map = {c["name"]: c for c in state.get("companies", [])}
    contacts_map = {c["company_name"]: c for c in state.get("contacts", [])}

    logger.info(f"Step 4: Generating insights for top {len(top)} companies...")
    insights: list[dict] = []

    for scored_company in top:
        company_name = scored_company["company_name"]
        company = companies_map.get(company_name, {})
        contacts = contacts_map.get(company_name, {})

        try:
            result = _llm().messages.create(
                model=cfg.reasoning_model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": INSIGHTS_PROMPT.format(
                        company_json=json.dumps(company, ensure_ascii=False, indent=2),
                        scoring_json=json.dumps(scored_company, ensure_ascii=False, indent=2),
                        contacts_json=json.dumps(contacts, ensure_ascii=False, indent=2),
                    ),
                }],
                response_model=CompanyInsight,
            )
            insights.append(result.model_dump())
            logger.debug(f"Insight generated for {company_name}")
        except Exception as e:
            logger.error(f"Insights failed for {company_name}: {e}", exc_info=True)
            state["errors"].append(f"Insights error ({company_name}): {e}")

    logger.info(f"Generated insights for {len(insights)} companies")
    return {**state, "insights": insights}
