import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.outreach import OUTREACH_PROMPT
from src.schemas.outputs import CompanyOutreach
from src.config import get_settings, get_profile_overrides

logger = logging.getLogger(__name__)

_client = None


def _llm():
    global _client
    if _client is None:
        _client = instructor.from_anthropic(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    return _client


def run_outreach_node(state: AgentState) -> AgentState:
    scored = state.get("scored_opportunities", [])
    if not scored:
        logger.warning("No scored companies — skipping outreach")
        return {**state, "outreach_drafts": []}

    cfg = get_settings()
    po = get_profile_overrides(state.get("profile"))

    top = scored[: cfg.max_companies_for_outreach]
    companies_map = {c["name"]: c for c in state.get("companies", [])}
    insights_map = {i["company_name"]: i for i in state.get("insights", [])}
    contacts_map = {c["company_name"]: c for c in state.get("contacts", [])}

    logger.info(f"Step 5: Generating outreach drafts for top {len(top)} companies...")
    all_drafts: list[dict] = []

    outreach_service_desc = "improve their business communication skills"
    if po.get("search_focus_terms"):
        outreach_service_desc = po["search_focus_terms"]

    for scored_company in top:
        company_name = scored_company["company_name"]
        company = companies_map.get(company_name, {})
        insight = insights_map.get(company_name, {})
        contacts = contacts_map.get(company_name, {})

        primary_contact = None
        if contacts and contacts.get("contacts"):
            primary_contact = contacts["contacts"][0]

        payload = {
            "company": company,
            "scored_opportunity": scored_company,
            "insight": insight,
            "primary_contact": primary_contact,
        }

        try:
            result = _llm().messages.create(
                model=cfg.reasoning_model,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": OUTREACH_PROMPT.format(
                        agent_name=po["agent_company_name"],
                        agent_description=po["agent_description"],
                        outreach_service_description=outreach_service_desc,
                        outreach_tone=po.get("outreach_tone", "warm"),
                        company_and_insight_json=json.dumps(payload, ensure_ascii=False, indent=2),
                    ),
                }],
                response_model=CompanyOutreach,
            )
            for draft in result.drafts:
                d = draft.model_dump()
                d["company_name"] = company_name
                if primary_contact:
                    d["contact_name"]         = primary_contact.get("name")
                    d["contact_email"]        = primary_contact.get("email")
                    d["contact_linkedin_url"] = primary_contact.get("linkedin_url")
                    d["contact_role"]         = primary_contact.get("role")
                all_drafts.append(d)
            logger.debug(f"Generated {len(result.drafts)} drafts for {company_name}")
        except Exception as e:
            logger.error(f"Outreach failed for {company_name}: {e}", exc_info=True)
            state["errors"].append(f"Outreach error ({company_name}): {e}")

    logger.info(f"Generated {len(all_drafts)} outreach drafts total")
    return {**state, "outreach_drafts": all_drafts}
