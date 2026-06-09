import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.scoring import SCORING_PROMPT, DEFAULT_SCORING_RUBRIC
from src.schemas.outputs import ScoredCompanyList
from src.config import get_settings, get_profile_overrides

logger = logging.getLogger(__name__)

_client = None
_BATCH_SIZE = 5


def _build_scoring_prompt(state: AgentState) -> tuple[str, str]:
    """Build the static and dynamic parts of the scoring prompt."""
    po = get_profile_overrides(state.get("profile"))
    agent_name = po["agent_company_name"]
    agent_desc = po["agent_description"]

    # Use profile-specific rubric or fall back to default
    rubric_text = DEFAULT_SCORING_RUBRIC
    if po.get("scoring_rubric") and isinstance(po["scoring_rubric"], dict):
        # Convert structured rubric to text
        lines = []
        for key, val in po["scoring_rubric"].items():
            if isinstance(val, dict):
                title = val.get("name", key)
                max_pts = val.get("max", 0)
                lines.append(f"{key} (0–{max_pts} pts):")
                for desc in val.get("criteria", []):
                    lines.append(f"  {desc}")
            elif isinstance(val, str):
                lines.append(f"{key}: {val}")
        if lines:
            rubric_text = "\n".join(lines)

    # Format the parts manually to avoid KeyError from {companies_json} placeholder
    lines = SCORING_PROMPT.split("COMPANIES TO SCORE:")
    static_template = lines[0]
    dynamic_part = "COMPANIES TO SCORE:" + lines[1] if len(lines) > 1 else "COMPANIES TO SCORE:\n{companies_json}"

    static_part = static_template.format(
        agent_name=agent_name,
        agent_description=agent_desc,
        scoring_rubric=rubric_text,
    ).rstrip()

    return static_part, dynamic_part


def _llm():
    global _client
    if _client is None:
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def run_scoring_node(state: AgentState) -> AgentState:
    companies = state.get("companies", [])
    if not companies:
        logger.warning("No companies to score")
        return {**state, "scored_opportunities": []}

    logger.info(f"Step 2: Scoring {len(companies)} companies...")
    cfg = get_settings()
    scored: list[dict] = []

    scoring_static, scoring_dynamic_template = _build_scoring_prompt(state)

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
                            "text": scoring_static,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": scoring_dynamic_template.format(companies_json=companies_json),
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
