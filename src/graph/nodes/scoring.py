import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.scoring import SCORING_PROMPT
from src.schemas.outputs import ScoredCompanyList

logger = logging.getLogger(__name__)

_client = None
_BATCH_SIZE = 5

_SCORING_STATIC = SCORING_PROMPT.split("COMPANIES TO SCORE:")[0].rstrip()
_SCORING_DYNAMIC = "COMPANIES TO SCORE:\n{companies_json}"


def _llm():
    global _client
    if _client is None:
        from src.config import get_settings
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def run_scoring_node(state: AgentState) -> AgentState:
    companies = state.get("companies", [])
    if not companies:
        logger.warning("No companies to score")
        return {**state, "scored_opportunities": []}

    logger.info(f"Step 2: Scoring {len(companies)} companies...")
    from src.config import get_settings
    cfg = get_settings()
    scored: list[dict] = []

    for i in range(0, len(companies), _BATCH_SIZE):
        batch = companies[i : i + _BATCH_SIZE]
        companies_json = json.dumps(batch, ensure_ascii=False, indent=2)

        try:
            result = _llm().messages.create(
                model=cfg.fast_model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _SCORING_STATIC,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": _SCORING_DYNAMIC.format(companies_json=companies_json),
                        },
                    ],
                }],
                response_model=ScoredCompanyList,
            )
            scored.extend(c.model_dump() for c in result.companies)
        except Exception as e:
            logger.error(f"Scoring batch {i//5 + 1} failed: {e}", exc_info=True)
            state["errors"].append(f"Scoring batch error: {e}")

    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        f"Scored {len(scored)} companies — "
        f"{sum(1 for s in scored if s['priority'] == 'quick_win')} quick wins, "
        f"{sum(1 for s in scored if s['priority'] == 'strategic')} strategic"
    )

    return {**state, "scored_opportunities": scored}
