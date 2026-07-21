import json
import logging
import anthropic
import instructor

from src.graph.state import AgentState
from src.prompts.outreach import build_outreach_prompt
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

    # Only draft for companies the worker would actually push (score >= 40,
    # i.e. quick_win/strategic). low_priority opps are skipped by the Zoho push
    # floor (worker.py), so drafting them wastes Haiku calls and makes the
    # Outreach section show empresas that never appear in Top Opportunities.
    eligible = [s for s in scored if s.get("priority") != "low_priority"]
    if not eligible:
        logger.info("No score >= 40 companies — skipping outreach")
        return {**state, "outreach_drafts": []}

    top = eligible[: cfg.max_companies_for_outreach]
    companies_map = {c["name"]: c for c in state.get("companies", [])}
    contacts_map  = {c["company_name"]: c for c in state.get("contacts", [])}

    logger.info(f"Step 5: Generating outreach for {len(top)} companies (fast model)...")
    all_drafts: list[dict] = []

    outreach_service_desc = po.get("search_focus_terms") or "improve their business communication skills"

    custom = (po.get("outreach_instructions") or "").strip()
    custom_block = (
        f"\nWHAT {po['agent_company_name'].upper()} OFFERS & HOW TO PITCH "
        f"(use only what is relevant; never contradict COMPANY DATA):\n{custom}\n"
        if custom else ""
    )

    for scored_company in top:
        company_name = scored_company["company_name"]
        company  = companies_map.get(company_name, {})
        contacts = contacts_map.get(company_name, {})

        primary_contact = None
        if contacts and contacts.get("contacts"):
            primary_contact = contacts["contacts"][0]

        # Lean payload — no insights (skipped), just what's needed for personalization
        payload = {
            "company_name":   company_name,
            "website":        company.get("website_url"),
            "industry":       company.get("industry"),
            "size":           company.get("size_estimate"),
            "location":       company.get("location"),
            "description":    company.get("description"),
            "signals":        company.get("signals", []),
            "intl_clients":   company.get("has_international_clients"),
            "english_jobs":   company.get("has_english_job_postings"),
            "remote":         company.get("remote_friendly"),
            "score":          scored_company.get("score"),
            "priority":       scored_company.get("priority"),
            "contact_name":   primary_contact.get("name") if primary_contact else None,
            "contact_role":   primary_contact.get("role") if primary_contact else None,
            "contact_email":  primary_contact.get("email") if primary_contact else None,
        }

        try:
            result = _llm().messages.create(
                model=cfg.outreach_model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": build_outreach_prompt(
                        agent_name=po["agent_company_name"],
                        agent_description=po["agent_description"],
                        outreach_service_description=outreach_service_desc,
                        outreach_tone=po.get("outreach_tone", "warm"),
                        company_and_insight_json=json.dumps(payload, ensure_ascii=False, indent=2),
                        custom_instructions_block=custom_block,
                        outreach_language=po.get("outreach_language", "es"),
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

    logger.info(f"Generated {len(all_drafts)} outreach drafts for {len(top)} companies")
    return {**state, "outreach_drafts": all_drafts}
