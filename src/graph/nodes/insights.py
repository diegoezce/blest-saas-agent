import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.insights import INSIGHTS_STATIC, INSIGHTS_BATCH_PROMPT
from src.schemas.outputs import CompanyInsightList

logger = logging.getLogger(__name__)

_client = None
_BATCH_SIZE = 3


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

    logger.info(f"Step 4: Generating insights for top {len(top)} companies in batches of {_BATCH_SIZE}...")
    insights: list[dict] = []

    for i in range(0, len(top), _BATCH_SIZE):
        batch = top[i : i + _BATCH_SIZE]
        payload = [
            {
                "company": companies_map.get(s["company_name"], {}),
                "scoring": s,
                "contacts": contacts_map.get(s["company_name"], {}),
            }
            for s in batch
        ]

        try:
            result = _llm().messages.create(
                model=cfg.reasoning_model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": INSIGHTS_STATIC,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": INSIGHTS_BATCH_PROMPT.format(
                                companies_json=json.dumps(payload, ensure_ascii=False, indent=2)
                            ),
                        },
                    ],
                }],
                response_model=CompanyInsightList,
            )
            insights.extend(r.model_dump() for r in result.insights)
            logger.debug(f"Batch {i // _BATCH_SIZE + 1}: got {len(result.insights)} insights")
        except Exception as e:
            logger.error(f"Insights batch {i // _BATCH_SIZE + 1} failed: {e}", exc_info=True)
            state["errors"].append(f"Insights batch error: {e}")

    logger.info(f"Generated insights for {len(insights)} companies")
    return {**state, "insights": insights}
